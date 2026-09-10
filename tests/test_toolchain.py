"""The toolchain's error handling: things it used to accept and get wrong.

Every case here compiled silently once and produced a program that did the
wrong thing. A compiler that accepts nonsense and emits plausible code is worse
than one that refuses, because the machine runs at 1800 instructions/second and
you will not enjoy single-stepping to find out why.
"""
import os
import tempfile

from ccompiler import build
from compiler import compile_asm, unescape
from cpp import Preprocessor
from quattro import run_machine


def _c(src):
    d = tempfile.mkdtemp()
    p = os.path.join(d, 't.c')
    with open(p, 'w') as f:
        f.write(src)
    return build([p])


def _run(src):
    code, data = _c(src)
    _, _, bus = run_machine(code, data=data, max_steps=3000000)
    return bus.console.render().replace('\n', '').strip()


def _rejects(src, exc=Exception):
    try:
        _c(src)
    except exc:
        return True
    return False


# --- the assembler ------------------------------------------------------

def test_string_escapes_are_decoded():
    """`.string "a\\nb"` stored a backslash and an 'n': three characters where
    two were meant, and a newline that printed literally as \\n. The C compiler
    always decoded escapes; the assembler never did."""
    code, data = compile_asm('.data\ns:\n    .string "a\\nb"\n.text\nHLT\n')
    assert [data[k] for k in sorted(data)] == [97, 10, 98, 0]


def test_string_escape_table():
    assert unescape('a\\nb') == [97, 10, 98]
    assert unescape('\\t') == [9]
    assert unescape('\\\\') == [92]
    assert unescape('\\"') == [34]
    assert unescape('plain') == [112, 108, 97, 105, 110]


def test_unknown_escape_is_rejected():
    try:
        compile_asm('.data\ns:\n    .string "bad \\q"\n.text\nHLT\n')
    except ValueError:
        return
    raise AssertionError('the assembler accepted an unknown escape')


def test_escaped_newline_reaches_the_console():
    """End to end on the real machine, because the whole point is what prints."""
    bios = open('asm/bios.asm').read()
    code, data = compile_asm(bios + '''
main:
    LOAD R1, msg
ploop:
    LOAD R0, [R1]
    JZ R0, pdone
    CALL print_char
    LOAD R2, 1
    ADD R1, R2
    JMP ploop
pdone:
    HLT
.data
msg:
    .string "one\\ntwo"
''')
    _, _, bus = run_machine(code, data=data, max_steps=100000)
    lines = [l for l in bus.console.render().split('\n') if l.strip()]
    assert lines[:2] == ['one', 'two'], f'got {lines[:2]}'
test_escaped_newline_reaches_the_console.slow = True


def test_duplicate_labels_are_rejected():
    """Last-one-wins silently retargeted every jump to the first label."""
    for src in ('a:\n    HLT\na:\n    RET\n',
                '.data\nx:\n    .byte 1\n.text\nx:\n    HLT\n'):
        try:
            compile_asm(src)
        except ValueError:
            continue
        raise AssertionError(f'accepted a duplicate label: {src!r}')


def test_assembler_range_checks():
    for src in ('LOAD R16, 1', 'LOAD R0, 1048576', 'JMP 65536'):
        try:
            compile_asm(src + '\n')
        except ValueError:
            continue
        raise AssertionError(f'accepted out-of-range: {src}')


def test_shipped_asm_still_assembles():
    bios = open('asm/bios.asm').read()
    for f in ('asm/boot.asm', 'asm/code.asm', 'asm/demo.asm', 'asm/os.asm',
              'asm/sched.asm', 'asm/shell.asm', 'test/t1.asm'):
        src = open(f).read()
        if 'main:' in src and '_boot:' not in src:
            src = bios + '\n' + src
        code, _ = compile_asm(src)
        assert len(code) > 0, f


# --- the C compiler -----------------------------------------------------

def test_call_arity_is_checked():
    """A wrong-count call still assembled: the caller pushed N values and the
    callee read its frame at nargs, so the frame -- including the return address
    -- was misaligned. f(1) on a 2-arg function returned garbage; f(1,2,3) on a
    1-arg function returned 3."""
    assert _rejects('int f(int a, int b) { return a + b; }\nint main() { return f(1); }',
                    TypeError)
    assert _rejects('int f(int a) { return a; }\nint main() { return f(1, 2, 3); }',
                    TypeError)
    assert _rejects('int f() { return 1; }\nint main() { return f(9); }', TypeError)


def test_method_call_arity_is_checked():
    """`this` is param 0, so the check has to discount it or every method call
    would look off by one."""
    assert _rejects('class C { public: int m(int q) { return q; } };\n'
                    'int main() { C c; return c.m(1, 2); }', TypeError)


def test_correct_arity_still_compiles():
    assert _run('#include <stdio.h>\nint f(int a, int b) { return a+b; }\n'
                'int main() { print_int(f(2,3)); return 0; }') == '5'
test_correct_arity_still_compiles.slow = True


def test_undeclared_function_is_rejected():
    assert _rejects('int main() { return nosuchfn(1); }', NameError)


SIZEOF_SRC = '''#include <stdio.h>
struct Big { int a; int b; int c; int d; };
int main() {
    int a[10]; int s; int *p; struct Big g;
    print_int(sizeof(int));        putchar(32);
    print_int(sizeof(a));          putchar(32);
    print_int(sizeof(s));          putchar(32);
    print_int(sizeof(p));          putchar(32);
    print_int(sizeof(int*));       putchar(32);
    print_int(sizeof(struct Big)); putchar(32);
    print_int(sizeof(g));          putchar(32);
    print_int(sizeof(a) / sizeof(a[0]));
    return 0;
}'''


def test_sizeof_measures_words():
    """sizeof returned 1 for EVERYTHING, because it was resolved in the parser,
    which has no symbol table and cannot tell `int a[10]` from `int a`. That
    made the standard sizeof(a)/sizeof(a[0]) idiom equal 1, so every loop
    written that way silently ran once. sizeof(struct X) did not even parse."""
    assert _run(SIZEOF_SRC) == '1 10 1 1 1 4 4 10'
test_sizeof_measures_words.slow = True


def test_sizeof_does_not_evaluate_its_operand():
    """C never runs the operand of sizeof."""
    assert _run('''#include <stdio.h>
int hits;
int f() { hits = hits + 1; return 0; }
int main() { hits = 0; print_int(sizeof(f())); print_int(hits); return 0; }''') == '10'
test_sizeof_does_not_evaluate_its_operand.slow = True


def test_elaborated_struct_type_parses():
    """`struct P p;` -- the elaborated form -- used to be a syntax error."""
    assert _run('''#include <stdio.h>
struct P { int x; int y; };
int main() { struct P p; p.x = 7; print_int(p.x); return 0; }''') == '7'
test_elaborated_struct_type_parses.slow = True


# --- the preprocessor ---------------------------------------------------

def _pp(src):
    d = tempfile.mkdtemp()
    p = os.path.join(d, 't.c')
    with open(p, 'w') as f:
        f.write(src)
    return Preprocessor([os.path.join(os.getcwd(), 'lib')]).preprocess(p)


def test_conditional_expressions():
    for expr, want in (('1', 'yes'), ('0', 'no'), ('1 + 1 == 2', 'yes'),
                       ('2 > 1', 'yes'), ('1 && 0', 'no'), ('1 || 0', 'yes'),
                       ('!0', 'yes'), ('(1)', 'yes'), ('defined(FOO)', 'no'),
                       ('3 - 4', 'yes'), ('1 == 1', 'yes')):
        got = _pp(f'#if {expr}\nyes\n#else\nno\n#endif\n').strip()
        assert got == want, f'#if {expr} -> {got!r}, want {want!r}'


def test_macro_expansion():
    for src, want in (('#define ID(x) x\nID(5)\n', '5'),
                      ('#define A 1\n#define B A\nB\n', '1'),
                      ('#define TWICE(x) ((x) + (x))\nTWICE(3)\n', '((3) + (3))'),
                      ('#define A 2\n#define F(x) ((x)*A)\nF(3)\n', '((3)*2)'),
                      ('#define F(a,b) (a+b)\n#define G 7\nF(G,1)\n', '(7+1)')):
        got = _pp(src).strip().split('\n')[-1]
        assert got == want, f'{src!r} -> {got!r}, want {want!r}'
