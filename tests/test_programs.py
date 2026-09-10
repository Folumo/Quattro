"""Programs executed on the real gate machine.

These are the slow tier (the machine runs ~1800 instructions/second, so each is
seconds, not milliseconds) -- run with `python tests/run.py --slow`.

The C cases are DIFFERENTIAL: each one's expected output is computed here in
Python under the machine's actual semantics (unsigned 32-bit, wrapping, x/0 == 0),
so they check the compiler against arithmetic rather than against a golden string
somebody typed. If the compiler emits wrong code for `a - b`, that is a silent
wrong answer in every program on the machine, and nothing else would catch it.
"""
import os
import tempfile

from ccompiler import build
from compiler import compile_asm
from quattro import Machine, run_machine

M = 4294967296


def _run_c(src, max_steps=3000000):
    d = tempfile.mkdtemp()
    path = os.path.join(d, 't.c')
    with open(path, 'w') as f:
        f.write(src)
    code, data = build([path])
    _, _, bus = run_machine(code, data=data, max_steps=max_steps)
    return bus.console.render().replace('\n', '').strip()


def _expr_case(body, want):
    src = '#include <stdio.h>\nint main() {\n' + body + '\nreturn 0; }\n'
    got = _run_c(src)
    assert got == str(want), f'{body!r}: want {want!r} got {got!r}'


# --- arithmetic under the machine's real semantics ----------------------

def test_c_arithmetic_wraps_unsigned():
    _expr_case('print_int(3 - 10);', (3 - 10) % M)
    _expr_case('print_int(100000 * 100000);', (100000 * 100000) % M)
    _expr_case('print_int(-5);', (-5) % M)
test_c_arithmetic_wraps_unsigned.slow = True


def test_c_division():
    _expr_case('print_int(1000000 / 7);', 1000000 // 7)
    _expr_case('print_int(1000000 % 7);', 1000000 % 7)
test_c_division.slow = True


def test_c_division_by_zero_matches_hardware():
    """The hardware defines x/0 == 0, so x%0 == x. The compiler's constant
    folder must agree with the ALU, or a folded expression and a runtime one
    give different answers for the same source."""
    _expr_case('int z; z = 0; print_int(100 / z);', 0)
    _expr_case('int z; z = 0; print_int(100 % z);', 100)
test_c_division_by_zero_matches_hardware.slow = True


def test_c_precedence():
    _expr_case('print_int(2 + 3 * 4 - 6 / 2);', 2 + 3 * 4 - 6 // 2)
    _expr_case('print_int(((1+2)*(3+4)) - ((5-3)*(2+2)));',
               ((1 + 2) * (3 + 4)) - ((5 - 3) * (2 + 2)))
test_c_precedence.slow = True


def test_c_comparisons_are_unsigned():
    """KNOWN LIMIT, pinned: `int` is unsigned, so a negative intermediate is a
    huge positive and `a < 0` is never true. If signed types land, this changes."""
    _expr_case('int a; a = 3 - 10; if (a > 100) print_int(1); else print_int(0);', 1)
    _expr_case('int a; a = 3 - 10; if (a < 0) print_int(1); else print_int(0);', 0)
test_c_comparisons_are_unsigned.slow = True


# --- control flow -------------------------------------------------------

def test_c_loops():
    _expr_case('int i; int s; s=0; i=0; while (i<10) { s+=i; i++; } print_int(s);',
               sum(range(10)))
    _expr_case('int i; int s; s=0; for(i=0;i<10;i++){ if(i%2==0) continue; s+=i; } print_int(s);',
               sum(i for i in range(10) if i % 2))
    _expr_case('int i; for(i=0;i<100;i++){ if(i==7) break; } print_int(i);', 7)
    _expr_case('int i; int j; int s; s=0; for(i=0;i<5;i++) for(j=0;j<5;j++) s+=i*j; print_int(s);',
               sum(i * j for i in range(5) for j in range(5)))
    _expr_case('int i; i=0; do { i++; } while (i<5); print_int(i);', 5)
test_c_loops.slow = True


def test_c_increment_and_compound_assign():
    _expr_case('int i; i = 5; print_int(i++); print_int(i);', 56)
    _expr_case('int i; i = 5; print_int(++i); print_int(i);', 66)
    _expr_case('int i; i = 10; i += 5; i -= 3; i *= 2; i /= 4; print_int(i);',
               ((10 + 5 - 3) * 2) // 4)
test_c_increment_and_compound_assign.slow = True


def test_c_pointers_and_arrays():
    _expr_case('int a[5]; int i; for(i=0;i<5;i++) a[i]=i*i; print_int(a[4]); print_int(a[0]);', 160)
    _expr_case('int x; int *p; x=42; p=&x; *p = *p + 1; print_int(x);', 43)
test_c_pointers_and_arrays.slow = True


def test_c_short_circuit():
    """&& and || must not evaluate the right side when the left decides it."""
    got = _run_c('''#include <stdio.h>
int hits;
int bump() { hits = hits + 1; return 1; }
int zero() { return 0; }
int main() {
    hits = 0; if (zero() && bump()) { } print_int(hits);
    hits = 0; if (bump() || bump()) { } print_int(hits);
    hits = 0; if (bump() && bump()) { } print_int(hits);
    hits = 0; if (zero() || bump()) { } print_int(hits);
    return 0;
}''')
    assert got == '0121', f'short-circuit broken: {got!r}'
test_c_short_circuit.slow = True


# --- the calling convention ---------------------------------------------

def test_c_recursion():
    """The hardware return stack is only depth 4, so recursion works solely
    because the compiler builds its own stack in memory. If the convention
    drifts, these are what break."""
    assert _run_c('''#include <stdio.h>
int fact(int n) { if (n <= 1) return 1; return n * fact(n - 1); }
int main() { print_int(fact(10)); return 0; }''') == str(3628800)
    assert _run_c('''#include <stdio.h>
int fib(int n) { if (n < 2) return n; return fib(n-1) + fib(n-2); }
int main() { print_int(fib(15)); return 0; }''') == '610'
    assert _run_c('''#include <stdio.h>
int down(int n) { if (n == 0) return 0; return 1 + down(n - 1); }
int main() { print_int(down(50)); return 0; }''') == '50'
test_c_recursion.slow = True


def test_c_mutual_recursion():
    assert _run_c('''#include <stdio.h>
int isodd(int n);
int iseven(int n) { if (n == 0) return 1; return isodd(n - 1); }
int isodd(int n) { if (n == 0) return 0; return iseven(n - 1); }
int main() { print_int(iseven(20)); print_int(isodd(20)); return 0; }''') == '10'
test_c_mutual_recursion.slow = True


def test_c_nested_and_multi_arg_calls():
    assert _run_c('''#include <stdio.h>
int f(int a, int b, int c, int d, int e) { return a*10000 + b*1000 + c*100 + d*10 + e; }
int main() { print_int(f(1,2,3,4,5)); return 0; }''') == '12345'
    assert _run_c('''#include <stdio.h>
int add(int a, int b) { return a + b; }
int main() { print_int(add(add(1,2), add(add(3,4), 5))); return 0; }''') == '15'
test_c_nested_and_multi_arg_calls.slow = True


# --- the shipped programs still build and run ---------------------------

def test_shipped_programs_build():
    for f in ('c/stack.cpp', 'c/tictactoe.cpp', 'c/gui_demo.cpp', 'c/os.cpp',
              'c/prog.c'):
        code, _ = build([f])
        assert 0 < len(code) <= 65536, f'{f}: {len(code)} instructions'
test_shipped_programs_build.slow = True


def test_cpp_stack_program_runs():
    code, data = build(['c/stack.cpp'])
    _, _, bus = run_machine(code, data=data, max_steps=5000000)
    assert 'pushed 5 items' in bus.console.render()
test_cpp_stack_program_runs.slow = True


def test_asm_scheduler_round_robins():
    code, data, labels = compile_asm(open('asm/sched.asm').read(),
                                     return_labels=True)
    tasks = sorted((l for l in labels if l.startswith('task')),
                   key=lambda l: labels[l])
    _, _, bus = run_machine(code, data=data, max_steps=20000,
                            sched={'tasks': [labels[t] for t in tasks],
                                   'handler': labels['sched'], 'period': 30})
    screen = bus.console.render()
    assert 'A' in screen and 'B' in screen and 'C' in screen
test_asm_scheduler_round_robins.slow = True


def test_asm_os_syscalls():
    code, data, labels = compile_asm(open('asm/os.asm').read(), return_labels=True)
    _, _, bus = run_machine(code, data=data, max_steps=20000,
                            sched={'tasks': [labels['init']], 'nslots': 4,
                                   'handler': labels['kernel'], 'period': 0})
    assert bus.console.render().startswith('ABCABCABC')
test_asm_os_syscalls.slow = True
