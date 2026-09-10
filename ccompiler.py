"""
A C / C++ compiler for the Quattro machine.

Pipeline:  cpp.py (preprocess) -> ccompiler (parse + codegen) -> .asm ->
compiler.py (assemble) -> machine code.  Drive it with `build([files...])` or
`python ccompiler.py a.c b.c` (see compile_program / build at the bottom).

Supported:
  - types int / char / void / bool / unsigned|long|short (all one 32-bit word),
    pointers, arrays, string literals, sizeof
  - functions with parameters, prototypes, RECURSION (a software call stack, so
    depth is bounded only by memory, not by the depth-4 hardware stack)
  - all the operators, if/else/while/for/do-while/break/continue, ++/--, +=...
  - PREPROCESSOR: #include "" / <>, object- and function-like #define, #undef,
    #ifdef/#ifndef/#if/#elif/#else/#endif, #pragma once (see cpp.py)
  - MULTI-FILE linking + a small STANDARD LIBRARY (lib/): <stdio.h> (printf,
    puts, print_int, putchar/getchar), <string.h>, <stdlib.h> (malloc/free heap)
  - C++: struct/class with data members and member functions (mangled to free
    functions taking an implicit `this`), constructors, new / delete
    (-> malloc/free), references (pointers), the `.`/`->` operators,
    bool/true/false, `//` comments, namespaces (flattened)

Not supported: bitwise ops (the quaternary ALU has no AND/OR/XOR/shift),
function overloading / templates / inheritance+virtual, signed arithmetic
(comparisons are unsigned), switch. Programs must fit 65536 instructions.

Codegen: values in R0; R1-R5 temporaries; R9 = frame pointer, R10 = software
stack pointer (also the expression-spill stack), R11 = constant 1. Globals and
string literals are data labels; locals/params/args live in the R10 call frame.
"""

import re

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r'''
    (?P<WS>\s+)
  | (?P<LC>//[^\n]*)
  | (?P<BC>/\*.*?\*/)
  | (?P<NUM>\d+)
  | (?P<CH>'(?:\\.|[^'])')
  | (?P<STR>"(?:\\.|[^"])*")
  | (?P<ID>[A-Za-z_]\w*)
  | (?P<OP>->|\+\+|--|\+=|-=|\*=|/=|%=|==|!=|<=|>=|&&|\|\||[-+*/%<>=(){}\[\],;&!.:])
''', re.VERBOSE | re.DOTALL)

_KEYWORDS = {'int', 'char', 'void', 'unsigned', 'long', 'short', 'if', 'else',
             'while', 'for', 'do', 'return', 'break', 'continue', 'extern',
             'sizeof',
             # C++
             'struct', 'class', 'new', 'delete', 'bool', 'true', 'false',
             'this', 'namespace', 'public', 'private', 'protected'}
_TYPES = ('int', 'char', 'void', 'unsigned', 'long', 'short', 'bool')
_ESCAPES = {'n': 10, 't': 9, 'r': 13, '0': 0, '\\': 92, "'": 39, '"': 34}


def _decode(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == '\\':
            out.append(_ESCAPES[s[i + 1]])
            i += 2
        else:
            out.append(ord(s[i]))
            i += 1
    return out


def tokenize(src):
    toks, i = [], 0
    while i < len(src):
        m = _TOKEN.match(src, i)
        if not m:
            raise SyntaxError(f"bad character {src[i]!r} at offset {i}")
        i = m.end()
        kind, val = m.lastgroup, m.group()
        if kind in ('WS', 'LC', 'BC'):
            continue
        if kind == 'NUM':
            toks.append(('num', int(val)))
        elif kind == 'CH':
            toks.append(('num', _decode(val[1:-1])[0]))
        elif kind == 'STR':
            toks.append(('str', _decode(val[1:-1])))
        elif kind == 'ID':
            toks.append(('kw' if val in _KEYWORDS else 'id', val))
        else:
            toks.append(('op', val))
    toks.append(('eof', None))
    return toks


# ---------------------------------------------------------------------------
# Parser -> AST
# ---------------------------------------------------------------------------

class Parser:
    def __init__(self, toks):
        self.toks, self.pos = toks, 0
        self.typenames = set()      # known struct/class names (for is_type)

    def peek(self, k=0):
        return self.toks[self.pos + k]

    def next(self):
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def accept(self, kind, val=None):
        t = self.peek()
        if t[0] == kind and (val is None or t[1] == val):
            return self.next()
        return None

    def expect(self, kind, val=None):
        t = self.accept(kind, val)
        if t is None:
            raise SyntaxError(f"expected {val or kind}, got {self.peek()}")
        return t

    def is_type(self):
        t = self.peek()
        # `struct X` / `class X` in a type position (as in sizeof(struct P) or a
        # `struct P p;` declaration) -- the elaborated form, where the tag is a
        # keyword followed by the name.
        if t == ('kw', 'struct') or t == ('kw', 'class'):
            return self.peek(1)[0] == 'id'
        return ((t[0] == 'kw' and t[1] in _TYPES) or
                (t[0] == 'id' and t[1] in self.typenames))

    def parse_type(self):
        # consume a type specifier; return the base type name. All integer-ish
        # types are one 32-bit word; a struct/class name names an object type.
        if not self.is_type():
            raise SyntaxError(f"expected a type, got {self.peek()}")
        base = 'int'
        while self.is_type():
            t = self.next()
            if t == ('kw', 'struct') or t == ('kw', 'class'):
                base = self.expect('id')[1]             # `struct P` -> P
                continue
            if t[0] == 'id':
                base = t[1]                             # class/struct name
            elif t[1] not in ('unsigned', 'long', 'short'):
                base = t[1]
        return base

    def consume_type(self):
        return self.parse_type()

    # -- top level --
    def parse_program(self):
        items = []
        while self.peek()[0] != 'eof':
            items.extend(self._toplevel())
        return items

    def _toplevel(self):
        t = self.peek()
        if t in (('kw', 'struct'), ('kw', 'class')):
            return [self.parse_class()]
        if t == ('kw', 'namespace'):
            self.next()
            self.expect('id')
            self.expect('op', '{')
            out = []
            while not self.accept('op', '}'):        # flattened (no :: scoping)
                out.extend(self._toplevel())
            return out
        is_extern = bool(self.accept('kw', 'extern'))
        base = self.parse_type()
        ptr = 0
        while self.accept('op', '*'):
            ptr += 1
        name = self.expect('id')[1]
        if self.accept('op', '('):
            params = self.parse_params()
            self.expect('op', ')')
            if self.accept('op', ';'):
                return [('proto', name, params)]
            return [('func', name, params, self.parse_block())]
        kind = 'scalar'
        if self.accept('op', '['):
            kind = ('array', self.expect('num')[1])
            self.expect('op', ']')
        elif base in self.typenames and ptr == 0:
            kind = ('object', base)
        init = self.parse_expr() if self.accept('op', '=') else None
        self.expect('op', ';')
        if is_extern:
            return [('proto', name, ())]
        return [('global', name, kind, init, (base, ptr > 0))]

    def parse_class(self):
        self.next()                                  # 'struct' or 'class'
        name = self.expect('id')[1]
        self.typenames.add(name)
        self.expect('op', '{')
        members = []
        while not self.accept('op', '}'):
            tt = self.peek()
            if tt[0] == 'kw' and tt[1] in ('public', 'private', 'protected'):
                self.next()
                self.expect('op', ':')
                continue
            if tt == ('id', name) and self.peek(1) == ('op', '('):   # constructor
                self.next()
                self.expect('op', '(')
                params = self.parse_params()
                self.expect('op', ')')
                members.append(('ctor', params, self.parse_block()))
                continue
            base = self.parse_type()
            ptr = 0
            while self.accept('op', '*'):
                ptr += 1
            mname = self.expect('id')[1]
            if self.accept('op', '('):               # method
                params = self.parse_params()
                self.expect('op', ')')
                members.append(('method', mname, params, self.parse_block()))
            else:                                    # data field
                kind = 'scalar'
                if self.accept('op', '['):
                    kind = ('array', self.expect('num')[1])
                    self.expect('op', ']')
                elif base in self.typenames and ptr == 0:
                    kind = ('object', base)
                self.expect('op', ';')
                members.append(('field', mname, kind, (base, ptr > 0)))
        self.expect('op', ';')
        return ('class', name, members)

    def parse_params(self):
        # returns a list of (name, base_type, is_pointer) tuples
        params = []
        if self.peek() == ('op', ')'):
            return params
        if self.peek() == ('kw', 'void') and self.peek(1) == ('op', ')'):
            self.next()                              # f(void)
            return params
        while True:
            base = self.parse_type()
            ptr = 0
            while self.accept('op', '*'):
                ptr += 1
            name = self.expect('id')[1]
            if self.accept('op', '['):               # array param decays to ptr
                ptr += 1
                if not self.accept('op', ']'):
                    self.expect('num')
                    self.expect('op', ']')
            params.append((name, base, ptr > 0))
            if not self.accept('op', ','):
                break
        return params

    def parse_block(self):
        self.expect('op', '{')
        stmts = []
        while not self.accept('op', '}'):
            stmts.append(self.parse_stmt())
        return stmts

    def parse_body(self):
        if self.peek() == ('op', '{'):
            return self.parse_block()
        return [self.parse_stmt()]

    def parse_decl(self):
        # a type is at the cursor; parse "type [*] name [ [N] ] [= e] ;"
        base = self.parse_type()
        ptr = 0
        while self.accept('op', '*'):
            ptr += 1
        name = self.expect('id')[1]
        kind = 'scalar'
        if self.accept('op', '['):
            kind = ('array', self.expect('num')[1])
            self.expect('op', ']')
        elif base in self.typenames and ptr == 0:
            kind = ('object', base)
        init = None
        if isinstance(kind, tuple) and kind[0] == 'object' and \
                self.peek() == ('op', '('):          # Point p(args); direct-init
            self.next()
            init = ('ctorinit', self._arglist())
        elif self.accept('op', '='):
            init = self.parse_expr()
        return ('decl', name, kind, init, (base, ptr > 0))

    def parse_stmt(self):
        t = self.peek()
        if self.is_type():
            d = self.parse_decl()
            self.expect('op', ';')
            return d
        if t == ('kw', 'if'):
            self.next()
            self.expect('op', '(')
            cond = self.parse_expr()
            self.expect('op', ')')
            then = self.parse_body()
            els = self.parse_body() if self.accept('kw', 'else') else []
            return ('if', cond, then, els)
        if t == ('kw', 'while'):
            self.next()
            self.expect('op', '(')
            cond = self.parse_expr()
            self.expect('op', ')')
            return ('while', cond, self.parse_body())
        if t == ('kw', 'do'):
            self.next()
            body = self.parse_body()
            self.expect('kw', 'while')
            self.expect('op', '(')
            cond = self.parse_expr()
            self.expect('op', ')')
            self.expect('op', ';')
            return ('dowhile', body, cond)
        if t == ('kw', 'for'):
            self.next()
            self.expect('op', '(')
            init = self.parse_for_init()
            cond = None if self.peek() == ('op', ';') else self.parse_expr()
            self.expect('op', ';')
            update = None if self.peek() == ('op', ')') else self.parse_simple()
            self.expect('op', ')')
            return ('for', init, cond, update, self.parse_body())
        if t == ('kw', 'return'):
            self.next()
            expr = None if self.peek() == ('op', ';') else self.parse_expr()
            self.expect('op', ';')
            return ('return', expr)
        if t == ('kw', 'break'):
            self.next()
            self.expect('op', ';')
            return ('break',)
        if t == ('kw', 'continue'):
            self.next()
            self.expect('op', ';')
            return ('continue',)
        if t == ('op', '{'):
            return ('block', self.parse_block())
        s = self.parse_simple()
        self.expect('op', ';')
        return s

    def parse_for_init(self):
        if self.accept('op', ';'):
            return None
        if self.is_type():
            d = self.parse_decl()
            self.expect('op', ';')
            return d
        s = self.parse_simple()
        self.expect('op', ';')
        return s

    def parse_simple(self):
        # an assignment or expression statement, no trailing ';' consumed
        expr = self.parse_expr()
        t = self.peek()
        if t == ('op', '='):
            self.next()
            return ('assign', expr, self.parse_expr())
        if t[0] == 'op' and t[1] in ('+=', '-=', '*=', '/=', '%='):
            self.next()
            return ('assign', expr, ('bin', t[1][0], expr, self.parse_expr()))
        return ('expr', expr)

    # -- expressions --
    def parse_expr(self):
        return self._logic_or()

    def _logic_or(self):
        node = self._logic_and()
        while self.peek() == ('op', '||'):
            self.next()
            node = ('or', node, self._logic_and())
        return node

    def _logic_and(self):
        node = self._equality()
        while self.peek() == ('op', '&&'):
            self.next()
            node = ('and', node, self._equality())
        return node

    def _equality(self):
        return self._binary(('==', '!='), self._relational)

    def _relational(self):
        return self._binary(('<', '>', '<=', '>='), self._additive)

    def _additive(self):
        return self._binary(('+', '-'), self._term)

    def _term(self):
        return self._binary(('*', '/', '%'), self._unary)

    def _binary(self, ops, sub):
        node = sub()
        while self.peek()[0] == 'op' and self.peek()[1] in ops:
            op = self.next()[1]
            node = ('bin', op, node, sub())
        return node

    def _unary(self):
        t = self.peek()
        if t == ('kw', 'new'):
            self.next()
            cls = self.expect('id')[1]
            args = self._arglist() if self.accept('op', '(') else []
            return ('new', cls, args)
        if t == ('kw', 'delete'):
            self.next()
            self.accept('op', '[')                   # tolerate delete[]
            self.accept('op', ']')
            return ('delete', self._unary())
        if t == ('kw', 'sizeof'):
            # Size is measured in machine words, since every scalar and pointer
            # is exactly one. The PARSER cannot answer this: it has no symbol
            # table, so it cannot tell `int a[10]` from `int a`. It used to just
            # return 1 for everything, which quietly made the standard
            # sizeof(a)/sizeof(a[0]) idiom equal 1 and every such loop run once.
            # So hand it to the codegen, which knows what things are.
            self.next()
            self.expect('op', '(')
            if self.is_type():
                base = self.consume_type()
                ptr = 0
                while self.accept('op', '*'):
                    ptr += 1
                node = ('sizeoftype', base, ptr)
            else:
                node = ('sizeofexpr', self.parse_expr())
            self.expect('op', ')')
            return node
        if t == ('op', '-'):
            self.next()
            return ('bin', '-', ('num', 0), self._unary())      # unary minus
        if t == ('op', '!'):
            self.next()
            return ('bin', '==', self._unary(), ('num', 0))      # logical not
        if t == ('op', '*'):
            self.next()
            return ('deref', self._unary())
        if t == ('op', '&'):
            self.next()
            return ('addr', self._unary())
        if t == ('op', '++'):
            self.next()
            return ('incdec', 'pre', 1, self._unary())
        if t == ('op', '--'):
            self.next()
            return ('incdec', 'pre', -1, self._unary())
        return self._postfix()

    def _arglist(self):
        args = []
        if self.peek() != ('op', ')'):
            while True:
                args.append(self.parse_expr())
                if not self.accept('op', ','):
                    break
        self.expect('op', ')')
        return args

    def _postfix(self):
        node = self._primary()
        while True:
            if self.accept('op', '['):
                idx = self.parse_expr()
                self.expect('op', ']')
                node = ('index', node, idx)
            elif self.peek() in (('op', '.'), ('op', '->')):
                arrow = self.next()[1] == '->'
                mname = self.expect('id')[1]
                if self.accept('op', '('):
                    node = ('mcall', node, mname, self._arglist(), arrow)
                else:
                    node = ('member', node, mname, arrow)
            elif self.accept('op', '++'):
                node = ('incdec', 'post', 1, node)
            elif self.accept('op', '--'):
                node = ('incdec', 'post', -1, node)
            else:
                return node

    def _primary(self):
        t = self.next()
        if t[0] == 'num':
            return ('num', t[1])
        if t == ('kw', 'true'):
            return ('num', 1)
        if t == ('kw', 'false'):
            return ('num', 0)
        if t == ('kw', 'this'):
            return ('this',)
        if t[0] == 'str':
            return ('str', t[1])
        if t == ('op', '('):
            e = self.parse_expr()
            self.expect('op', ')')
            return e
        if t[0] == 'id':
            if self.accept('op', '('):
                args = []
                if self.peek() != ('op', ')'):
                    while True:
                        args.append(self.parse_expr())
                        if not self.accept('op', ','):
                            break
                self.expect('op', ')')
                return ('call', t[1], args)
            return ('var', t[1])
        raise SyntaxError(f"unexpected token {t}")


# ---------------------------------------------------------------------------
# Code generator
#
# Calling convention -- a SOFTWARE stack in data memory (the hardware return
# stack is only depth 4, so it can't hold recursion). R10 = SP (grows up), the
# very same pointer the expression evaluator spills through, so temporaries,
# argument pushes and call frames share ONE stack and compose. R9 = FP (frame
# pointer), R11 = constant 1. Locals/params live at [FP + offset]; a call pushes
# args + a 2-word return address (label low byte / high part) and JMPs; the
# callee returns with a register-pair indirect JMP Rlo,Rhi. Recursion depth is
# bounded only by the stack size. Frame layout, from FP:
#     [FP+0 .. +nargs-1]  arguments (param i at FP+i)
#     [FP+nargs]          return address, low byte
#     [FP+nargs+1]        return address, high part
#     [FP+nargs+2]        saved caller FP
#     [FP+nargs+3 ..]     locals
# ---------------------------------------------------------------------------

FP, SP, ONE = 'R9', 'R10', 'R11'
# Memory map (all clear of the 229..287 device window -- which now includes the
# GPU's registers at 256..287 -- and all <=65535 so a 16-bit LOAD immediate can
# name any of it):
#   1024 .. STACK_BASE  globals + string literals (.data, data_base=1024)
#   STACK_BASE ..       software call stack (grows up)
#   HEAP_BASE ..        malloc/free heap (see lib/stdlib.c)
DATA_BASE = 1024
STACK_BASE = 20000
HEAP_BASE = 40000      # referenced by lib/stdlib.c's malloc


class Codegen:
    def __init__(self):
        self.out, self.data = [], []
        self.n = self.dn = 0
        self.globals, self.funcs = {}, {}
        self.classes = {}        # class name -> {fields{n:(off,ctype,kind)}, size, has_ctor}
        self.func_order = []
        self.local = None        # current function's symbol table
        self.curfunc = None
        self.cur_class = None    # class being compiled (for `this` / bare fields)
        self.epilogue = None
        self.loops = []          # (break_label, continue_label) stack

    def emit(self, line):
        self.out.append(line if line.endswith(':') else '    ' + line)

    def label(self, prefix):
        self.n += 1
        return f'{prefix}{self.n}'

    @staticmethod
    def _fold(op, a, b):
        """One constant operation, matching the machine exactly: unsigned 32-bit
        wrap, and divide-by-zero yields quotient 0 (so a % 0 == a)."""
        M = 1 << 32
        if op == '+':
            return (a + b) % M
        if op == '-':
            return (a - b) % M
        if op == '*':
            return (a * b) % M
        if op == '/':
            return (a // b) if b else 0
        if op == '%':
            return (a % b) if b else a
        if op == '==':
            return 1 if a == b else 0
        if op == '!=':
            return 1 if a != b else 0
        if op == '<':
            return 1 if a < b else 0
        if op == '>':
            return 1 if a > b else 0
        if op == '<=':
            return 1 if a <= b else 0
        if op == '>=':
            return 1 if a >= b else 0
        return None

    def _const(self, e):
        """Value of a wholly-constant expression tree, else None. Folds
        recursively, so `BX + 3 * CELL - 1` collapses to a single LOAD."""
        if e[0] == 'num':
            return e[1]
        if e[0] == 'bin':
            a = self._const(e[2])
            if a is None:
                return None
            b = self._const(e[3])
            if b is None:
                return None
            return self._fold(e[1], a, b)
        return None

    def _sizeof_kind(self, kind):
        if isinstance(kind, tuple):
            if kind[0] == 'array':
                return kind[1]
            if kind[0] == 'object':
                return self.classes[kind[1]]['size']
        return 1

    def _sizeof_type(self, base, ptr):
        """sizeof(T) in machine words. A pointer is one word like everything
        else; a struct/class is the sum of its fields."""
        if ptr:
            return 1
        if base in self.classes:
            return self.classes[base]['size']
        return 1

    def _sizeof_expr(self, e):
        """sizeof(expr) without evaluating it -- C never runs the operand.
        The point is that `int a[10]` must give 10, not 1, or the standard
        sizeof(a)/sizeof(a[0]) idiom silently reports a one-element array."""
        if e[0] == 'var':
            try:
                d = self.info(e[1])
            except NameError:
                if self._is_field(e[1]):
                    off, ctype, kind = self.classes[self.cur_class]['fields'][e[1]]
                    return self._sizeof_kind(kind)
                raise
            return self._sizeof_kind(d[2])
        if e[0] == 'member':
            cls = self._expr_class(e[1])
            if cls and e[2] in self.classes[cls]['fields']:
                off, ctype, kind = self.classes[cls]['fields'][e[2]]
                return self._sizeof_kind(kind)
        if e[0] == 'str':
            return len(e[1]) + 1                 # including the null terminator
        return 1                                 # any scalar / pointer / index

    def declare_global(self, kind, ctype):
        self.dn += 1
        lab = f'_d{self.dn}'
        self.data.append(f'{lab}:')
        n = self._sizeof_kind(kind)
        self.data.append('.byte ' + ', '.join('0' for _ in range(n)))
        return ('global', lab, kind, ctype)

    def info(self, name):
        if self.local is not None and name in self.local:
            return self.local[name]
        if name in self.globals:
            return self.globals[name]
        raise NameError(f"undefined variable: {name}")

    # -- classes / functions --
    def _register_class(self, it):
        _, cname, members = it
        fields, off = {}, 0
        self.classes[cname] = {'fields': fields, 'size': 1, 'has_ctor': False}
        for m in members:
            if m[0] == 'field':
                _, fn, fk, fct = m
                fields[fn] = (off, fct, fk)
                off += self._sizeof_kind(fk)
        self.classes[cname]['size'] = max(off, 1)
        for m in members:              # methods -> mangled free funcs w/ `this`
            if m[0] == 'method':
                self._register_func(cname + '__' + m[1], m[2], m[3], cls=cname)
            elif m[0] == 'ctor':
                self._register_func(cname + '__ctor', m[1], m[2], cls=cname)
                self.classes[cname]['has_ctor'] = True

    def _register_func(self, name, params, body, cls=None):
        plist = list(params)
        if cls is not None:
            plist = [('this', cls, True)] + plist        # implicit this pointer
        syms, off = {}, 0
        for pn, pbase, pptr in plist:
            syms[pn] = ('local', off, 'scalar', (pbase, pptr))
            off += 1
        nargs = len(plist)
        off = nargs + 3                                  # skip retaddr(2) + oldFP
        for dn, dk, dct in self._collect_decls(body):
            if dn not in syms:
                syms[dn] = ('local', off, dk, dct)
                off += self._sizeof_kind(dk)
        self.funcs[name] = {'params': plist, 'symbols': syms, 'body': body,
                            'nargs': nargs, 'framesize': off, 'class': cls}
        self.func_order.append(name)

    # -- dead-code elimination --
    def _callees(self, node, out):
        """Every function name this AST fragment might call. Conservative: a
        method name marks that method on every class, since we don't track the
        static type of every base expression."""
        if isinstance(node, list):
            for x in node:
                self._callees(x, out)
            return
        if not isinstance(node, tuple) or not node:
            return
        k = node[0]
        if k == 'call':
            out.add(node[1])
            if node[1] == 'printf':
                out.add('_printf')          # the intrinsic calls it
            for c in self.classes:          # may be an unqualified this->m()
                out.add(c + '__' + node[1])
        elif k == 'mcall':
            for c in self.classes:
                out.add(c + '__' + node[2])
        elif k == 'new':
            out.add('malloc')
            out.add(node[1] + '__ctor')
        elif k == 'delete':
            out.add('free')
            for c in self.classes:
                out.add(c + '__dtor')
        for x in node:
            self._callees(x, out)

    def _reachable(self, global_inits):
        """Functions main can actually reach. Everything else is dead: including
        <gui.h> for one helper should not cost you the whole widget library."""
        graph = {}
        for name, info in self.funcs.items():
            s = set()
            self._callees(info['body'], s)
            graph[name] = s
        seed = set()
        for _, init in global_inits:
            if init is not None:
                self._callees(init, seed)
        seen, stack = set(), ['main'] + list(seed)
        while stack:
            n = stack.pop()
            if n in seen or n not in self.funcs:
                continue
            seen.add(n)
            stack.extend(graph.get(n, ()))
        return seen

    # -- program --
    def compile(self, items):
        global_inits = []
        for it in items:
            if it[0] == 'class':
                self._register_class(it)
        for it in items:
            if it[0] in ('proto', 'class'):
                continue
            if it[0] == 'global':
                _, name, kind, init, ctype = it
                self.globals[name] = self.declare_global(kind, ctype)
                global_inits.append((name, init))
            else:
                _, name, params, body = it
                self._register_func(name, params, body, cls=None)
        if 'main' not in self.funcs:
            raise ValueError("no main() function")
        live = self._reachable(global_inits)
        self.gen_func('main', global_inits)
        for name in self.func_order:
            if name != 'main' and name in live:
                self.gen_func(name, None)
        head = (['.data'] + self.data if self.data else []) + ['.text']
        return '\n'.join(head + self.out) + '\n'

    def _collect_decls(self, stmts):
        found = []
        for s in stmts:
            if s[0] == 'decl':
                found.append((s[1], s[2], s[4]))
            elif s[0] == 'if':
                found += self._collect_decls(s[2]) + self._collect_decls(s[3])
            elif s[0] in ('while',):
                found += self._collect_decls(s[2])
            elif s[0] == 'dowhile':
                found += self._collect_decls(s[1])
            elif s[0] == 'for':
                init = [s[1]] if s[1] else []
                found += self._collect_decls(init + s[4])
            elif s[0] == 'block':
                found += self._collect_decls(s[1])
        return found

    def _addr_off(self, reg, offset):
        # put FP + offset into `reg` (a frame slot address)
        self.emit(f'COPY {reg}, {FP}')
        if offset:
            self.emit(f'LOAD R3, {offset}')
            self.emit(f'ADD {reg}, R3')

    def gen_func(self, name, global_inits):
        info = self.funcs[name]
        self.local = info['symbols']
        self.curfunc = info
        self.cur_class = info.get('class')
        nargs, framesize = info['nargs'], info['framesize']
        nlocals = framesize - nargs - 3
        self.epilogue = self.label('ret_' + name + '_')
        self.emit(f'{name}:')
        if name == 'main':
            self.emit(f'LOAD {SP}, {STACK_BASE}')
            self.emit(f'LOAD {ONE}, 1')
            self.emit(f'LOAD {FP}, {STACK_BASE}')
            if framesize:
                self.emit(f'LOAD R0, {framesize}')
                self.emit(f'ADD {SP}, R0')
            for gname, ginit in global_inits:
                if ginit is not None:
                    self.gen_expr(ginit)
                    self.gen_store(('var', gname))
        else:
            # prologue: push saved FP, set FP to this frame's arg0, alloc locals
            self.emit(f'STORE [{SP}], {FP}')
            self.emit(f'ADD {SP}, {ONE}')
            self.emit(f'COPY {FP}, {SP}')
            self.emit(f'LOAD R0, {nargs + 3}')
            self.emit(f'SUB {FP}, R0')            # FP = SP - (nargs+3) = arg0 base
            if nlocals:
                self.emit(f'LOAD R0, {nlocals}')
                self.emit(f'ADD {SP}, R0')
        for s in info['body']:
            self.gen_stmt(s)
        self.emit(f'{self.epilogue}:')            # return value already in R0
        if name == 'main':
            self.emit('HLT')
        else:
            self._addr_off('R2', nargs)           # &retaddr_lo
            self.emit('LOAD R1, [R2]')            # R1 = return address low byte
            self._addr_off('R2', nargs + 1)
            self.emit('LOAD R4, [R2]')            # R4 = return address high part
            self._addr_off('R2', nargs + 2)
            self.emit('LOAD R5, [R2]')            # R5 = saved caller FP
            self.emit(f'COPY {SP}, {FP}')         # pop the whole frame (incl args)
            self.emit(f'COPY {FP}, R5')           # restore caller FP
            self.emit('JMP R1, R4')               # return (register-pair indirect)

    # -- statements --
    def gen_stmt(self, s):
        k = s[0]
        if k == 'decl':
            if isinstance(s[3], tuple) and s[3][0] == 'ctorinit':
                cls = s[4][0]
                self._emit_call(cls + '__ctor',
                                lambda: self.gen_addr(('var', s[1])), s[3][1])
            elif s[3] is not None:
                self.gen_expr(s[3])
                self.gen_store(('var', s[1]))
        elif k == 'assign':
            self.gen_expr(s[2])
            self.gen_store(s[1])
        elif k == 'expr':
            if s[1][0] == 'incdec':
                self.gen_incdec(s[1], False)     # value unused
            else:
                self.gen_expr(s[1])
        elif k == 'return':
            if s[1] is not None:
                self.gen_expr(s[1])
            self.emit(f'JMP {self.epilogue}')
        elif k == 'break':
            self.emit(f'JMP {self.loops[-1][0]}')
        elif k == 'continue':
            self.emit(f'JMP {self.loops[-1][1]}')
        elif k == 'block':
            for st in s[1]:
                self.gen_stmt(st)
        elif k == 'if':
            _, cond, then, els = s
            Lelse, Lend = self.label('else'), self.label('endif')
            self.gen_expr(cond)
            self.emit(f'JZ R0, {Lelse}')
            for st in then:
                self.gen_stmt(st)
            self.emit(f'JMP {Lend}')
            self.emit(f'{Lelse}:')
            for st in els:
                self.gen_stmt(st)
            self.emit(f'{Lend}:')
        elif k == 'while':
            _, cond, body = s
            Ltop, Lend = self.label('while'), self.label('endw')
            self.emit(f'{Ltop}:')
            self.gen_expr(cond)
            self.emit(f'JZ R0, {Lend}')
            self.loops.append((Lend, Ltop))
            for st in body:
                self.gen_stmt(st)
            self.loops.pop()
            self.emit(f'JMP {Ltop}')
            self.emit(f'{Lend}:')
        elif k == 'dowhile':
            _, body, cond = s
            Ltop, Lcond, Lend = (self.label('do'), self.label('docond'),
                                 self.label('enddo'))
            self.emit(f'{Ltop}:')
            self.loops.append((Lend, Lcond))
            for st in body:
                self.gen_stmt(st)
            self.loops.pop()
            self.emit(f'{Lcond}:')
            self.gen_expr(cond)
            self.emit(f'JZ R0, {Lend}')
            self.emit(f'JMP {Ltop}')
            self.emit(f'{Lend}:')
        elif k == 'for':
            _, init, cond, update, body = s
            if init:
                self.gen_stmt(init)
            Ltop, Lupd, Lend = (self.label('for'), self.label('forupd'),
                                self.label('endfor'))
            self.emit(f'{Ltop}:')
            if cond:
                self.gen_expr(cond)
                self.emit(f'JZ R0, {Lend}')
            self.loops.append((Lend, Lupd))
            for st in body:
                self.gen_stmt(st)
            self.loops.pop()
            self.emit(f'{Lupd}:')
            if update:
                self.gen_stmt(update)
            self.emit(f'JMP {Ltop}')
            self.emit(f'{Lend}:')
        else:
            raise ValueError(f"bad statement {s}")

    # -- expressions: value into R0 --
    def gen_expr(self, e):
        k = e[0]
        if k == 'sizeoftype':
            self.emit(f'LOAD R0, {self._sizeof_type(e[1], e[2])}')
        elif k == 'sizeofexpr':
            self.emit(f'LOAD R0, {self._sizeof_expr(e[1])}')
        elif k == 'num':
            self.emit(f'LOAD R0, {e[1]}')
        elif k == 'str':
            self.dn += 1
            lab = f'_d{self.dn}'
            self.data.append(f'{lab}:')
            self.data.append('.byte ' + ', '.join(str(b) for b in e[1] + [0]))
            self.emit(f'LOAD R0, {lab}')
        elif k == 'var':
            if self._is_field(e[1]):                    # unqualified member -> this->x
                self.gen_expr(('member', ('this',), e[1], True))
                return
            d = self.info(e[1])
            if isinstance(d[2], tuple):                 # array/object decays to addr
                self._var_addr('R0', d)
            elif d[0] == 'global':
                self.emit(f'LOAD R2, {d[1]}')
                self.emit('LOAD R0, [R2]')
            else:
                self._addr_off('R2', d[1])
                self.emit('LOAD R0, [R2]')
        elif k == 'this':
            self._addr_off('R2', 0)
            self.emit('LOAD R0, [R2]')                  # this = param 0 (a pointer)
        elif k == 'member':
            cls = self._expr_class(e[1])
            _, fct, fkind = self.classes[cls]['fields'][e[2]]
            self.gen_addr(e)                            # R0 = field address
            if isinstance(fkind, tuple):                # array/object field -> addr
                return
            self.emit('COPY R2, R0')
            self.emit('LOAD R0, [R2]')
        elif k == 'mcall':
            self._gen_mcall(e)
        elif k == 'new':
            self._gen_new(e)
        elif k == 'delete':
            self._gen_delete(e)
        elif k == 'addr':
            self.gen_addr(e[1])
        elif k in ('deref', 'index'):
            self.gen_addr(e)
            self.emit('COPY R2, R0')
            self.emit('LOAD R0, [R2]')
        elif k == 'call':
            self.gen_call(e[1], e[2])
        elif k == 'and':
            self.gen_and(e[1], e[2])
        elif k == 'or':
            self.gen_or(e[1], e[2])
        elif k == 'incdec':
            self.gen_incdec(e, True)
        elif k == 'bin':
            v = self._const(e)
            if v is not None and 0 <= v <= 65535:   # fold to a single LOAD
                self.emit(f'LOAD R0, {v}')
                return
            _, op, left, right = e
            self.gen_expr(left)
            if right[0] in ('num', 'var', 'str'):
                self.emit('COPY R1, R0')
                self.gen_expr(right)
            else:
                self.emit('STORE [R10], R0')
                self.emit('ADD R10, R11')
                self.gen_expr(right)
                self.emit('SUB R10, R11')
                self.emit('LOAD R1, [R10]')
            self.gen_binop(op)
        else:
            raise ValueError(f"bad expr {e}")

    def _var_addr(self, reg, d):
        # address of a variable (global label or FP-relative local) into `reg`
        if d[0] == 'global':
            self.emit(f'LOAD {reg}, {d[1]}')
        else:
            self._addr_off(reg, d[1])

    # -- lvalues: address into R0 --
    def gen_addr(self, e):
        if e[0] == 'var':
            if self._is_field(e[1]):
                self.gen_addr(('member', ('this',), e[1], True))
            else:
                self._var_addr('R0', self.info(e[1]))
        elif e[0] == 'this':
            self.gen_expr(('this',))
        elif e[0] == 'member':
            cls = self._expr_class(e[1])
            off = self.classes[cls]['fields'][e[2]][0]
            if e[3]:                              # -> : base is a pointer (value)
                self.gen_expr(e[1])
            else:                                 # .  : base is an object (addr)
                self.gen_addr(e[1])
            if off:
                self.emit(f'LOAD R2, {off}')
                self.emit('ADD R0, R2')
        elif e[0] == 'deref':
            self.gen_expr(e[1])
        elif e[0] == 'index':
            self.gen_expr(('bin', '+', e[1], e[2]))
        else:
            raise ValueError(f"not an lvalue: {e}")

    # -- C++ helpers --
    def _is_field(self, name):
        if self.local and name in self.local:
            return False
        if name in self.globals:
            return False
        return bool(self.cur_class) and name in self.classes[self.cur_class]['fields']

    def _expr_class(self, e):
        if e[0] == 'this':
            return self.cur_class
        if e[0] == 'var':
            if self._is_field(e[1]):
                return self.classes[self.cur_class]['fields'][e[1]][1][0]
            return self.info(e[1])[3][0]
        if e[0] == 'member':
            return self.classes[self._expr_class(e[1])]['fields'][e[2]][1][0]
        raise ValueError(f"cannot determine the class of {e}")

    def _emit_call(self, mangled, this_thunk, args):
        # Every call funnels through here, so this is where arity is checked.
        # Without it a wrong-count call still assembles: the caller pushes N
        # values and the callee reads its frame at nargs, so the frame is
        # misaligned and even the return address is read from the wrong slot.
        # f(1) on a two-parameter function returned a garbage `b`; f(1,2,3) on a
        # one-parameter function returned 3. Silent, and it corrupts the stack.
        info = self.funcs.get(mangled)
        if info is not None:
            want = info['nargs'] - (1 if this_thunk is not None else 0)
            if len(args) != want:
                raise TypeError(
                    f"{mangled}() takes {want} argument{'' if want == 1 else 's'}, "
                    f"but {len(args)} were given")
        ret = self.label('ret')
        if this_thunk is not None:                    # push `this` first
            this_thunk()
            self.emit(f'STORE [{SP}], R0')
            self.emit(f'ADD {SP}, {ONE}')
        for arg in args:
            self.gen_expr(arg)
            self.emit(f'STORE [{SP}], R0')
            self.emit(f'ADD {SP}, {ONE}')
        self.emit(f'LOAD R0, <{ret}')
        self.emit(f'STORE [{SP}], R0')
        self.emit(f'ADD {SP}, {ONE}')
        self.emit(f'LOAD R0, >{ret}')
        self.emit(f'STORE [{SP}], R0')
        self.emit(f'ADD {SP}, {ONE}')
        self.emit(f'JMP {mangled}')
        self.emit(f'{ret}:')

    def _reload_stashed(self):
        self.emit(f'COPY R2, {SP}')
        self.emit(f'SUB R2, {ONE}')
        self.emit('LOAD R0, [R2]')                    # reload the value at [SP-1]

    def _gen_mcall(self, e):
        _, base, mname, args, arrow = e
        cls = self._expr_class(base)
        mangled = cls + '__' + mname
        if mangled not in self.funcs:
            raise NameError(f"no method {cls}::{mname}")
        thunk = (lambda: self.gen_expr(base)) if arrow else (lambda: self.gen_addr(base))
        self._emit_call(mangled, thunk, args)

    def _gen_new(self, e):
        _, cls, args = e
        if cls not in self.classes:
            raise NameError(f"new of unknown type {cls}")
        self.gen_call('malloc', [('num', self.classes[cls]['size'])])   # R0 = ptr
        ctor = cls + '__ctor'
        if ctor in self.funcs:
            self.emit(f'STORE [{SP}], R0')            # stash the new pointer
            self.emit(f'ADD {SP}, {ONE}')
            self._emit_call(ctor, self._reload_stashed, args)
            self.emit(f'SUB {SP}, {ONE}')
            self.emit(f'LOAD R0, [{SP}]')             # pop it back as the result

    def _gen_delete(self, e):
        ptr = e[1]
        try:
            cls = self._expr_class(ptr)
        except ValueError:
            cls = None
        if cls and (cls + '__dtor') in self.funcs:
            self._emit_call(cls + '__dtor', lambda: self.gen_expr(ptr), [])
        self.gen_call('free', [ptr])

    def gen_store(self, lval):
        if lval[0] == 'var':
            if self._is_field(lval[1]):            # unqualified member -> this->x
                self.gen_store(('member', ('this',), lval[1], True))
                return
            d = self.info(lval[1])
            if not isinstance(d[2], tuple):        # scalar variable
                self._var_addr('R2', d)
                self.emit('STORE [R2], R0')
                return
        self.emit(f'STORE [{SP}], R0')
        self.emit(f'ADD {SP}, {ONE}')
        self.gen_addr(lval)
        self.emit('COPY R2, R0')
        self.emit(f'SUB {SP}, {ONE}')
        self.emit(f'LOAD R0, [{SP}]')
        self.emit('STORE [R2], R0')

    def gen_incdec(self, node, want):
        _, when, delta, lval = node
        opc = 'ADD' if delta > 0 else 'SUB'
        if not want or when == 'pre':
            self.gen_expr(lval)
            self.emit(f'{opc} R0, R11')
            self.gen_store(lval)          # R0 = new value
        else:                             # post: result is the old value
            self.gen_expr(lval)
            self.emit('STORE [R10], R0')  # save old
            self.emit('ADD R10, R11')
            self.emit(f'{opc} R0, R11')
            self.gen_store(lval)
            self.emit('SUB R10, R11')
            self.emit('LOAD R0, [R10]')    # restore old -> R0

    def gen_binop(self, op):
        if op == '+':
            self.emit('ADD R1, R0'); self.emit('COPY R0, R1')
        elif op == '-':
            self.emit('SUB R1, R0'); self.emit('COPY R0, R1')
        elif op == '*':
            self.emit('MUL R1, R0'); self.emit('COPY R0, R1')
        elif op == '/':
            self.emit('DIV R1, R0'); self.emit('COPY R0, R1')
        elif op == '%':
            self.emit('COPY R2, R1'); self.emit('COPY R3, R0')
            self.emit('DIV R1, R0'); self.emit('MUL R1, R3')
            self.emit('SUB R2, R1'); self.emit('COPY R0, R2')
        else:
            self.gen_cmp(op)

    def gen_cmp(self, op):
        L, E = self.label('cmp'), self.label('cmpend')
        jump_true = op in ('==', '<', '>')
        if op in ('==', '!='):
            self.emit(f'JEQ R1, R0, {L}')
        elif op in ('<', '>='):
            self.emit(f'JLT R1, R0, {L}')
        else:
            self.emit(f'JLT R0, R1, {L}')
        if jump_true:
            self.emit('LOAD R0, 0'); self.emit(f'JMP {E}')
            self.emit(f'{L}:'); self.emit('LOAD R0, 1'); self.emit(f'{E}:')
        else:
            self.emit('LOAD R0, 1'); self.emit(f'JMP {E}')
            self.emit(f'{L}:'); self.emit('LOAD R0, 0'); self.emit(f'{E}:')

    def gen_and(self, l, r):
        F, E = self.label('and'), self.label('andend')
        self.gen_expr(l)
        self.emit(f'JZ R0, {F}')
        self.gen_expr(r)
        self.emit(f'JZ R0, {F}')
        self.emit('LOAD R0, 1'); self.emit(f'JMP {E}')
        self.emit(f'{F}:'); self.emit('LOAD R0, 0'); self.emit(f'{E}:')

    def gen_or(self, l, r):
        B, F, E = self.label('or'), self.label('orf'), self.label('orend')
        self.gen_expr(l)
        self.emit(f'JZ R0, {B}')
        self.emit('LOAD R0, 1'); self.emit(f'JMP {E}')
        self.emit(f'{B}:')
        self.gen_expr(r)
        self.emit(f'JZ R0, {F}')
        self.emit('LOAD R0, 1'); self.emit(f'JMP {E}')
        self.emit(f'{F}:'); self.emit('LOAD R0, 0'); self.emit(f'{E}:')

    def gen_call(self, name, args):
        if name == 'putchar':
            self.gen_expr(args[0])
            self.emit('CALL print_char')
            return
        if name == 'getchar':
            self.emit('CALL read_key')
            return
        if name == 'printf':
            # variadic intrinsic: marshal the value args into the library's
            # global __va[], then call _printf(fmt) which pulls from it.
            va = self.globals.get('__va')
            if va is None:
                raise NameError("printf requires <stdio.h>")
            for i, arg in enumerate(args[1:]):
                self.gen_expr(arg)
                self._var_addr('R2', va)
                if i:
                    self.emit(f'LOAD R3, {i}')
                    self.emit('ADD R2, R3')
                self.emit('STORE [R2], R0')
            self.gen_call('_printf', [args[0]])
            return
        if name not in self.funcs:
            # an unqualified call inside a method means this->name(args)
            if self.cur_class and (self.cur_class + '__' + name) in self.funcs:
                self._gen_mcall(('mcall', ('this',), name, args, True))
                return
            raise NameError(f"call to undefined function: {name}")
        self._emit_call(name, None, args)


def compile_c(src):
    """Compile ONE preprocessed translation unit's source text to Quattro asm."""
    return Codegen().compile(Parser(tokenize(src)).parse_program())


# --- toolchain driver: preprocess -> link units + stdlib -> compile -> asm ----

_LIB_IMPL = {'stdio.h': 'stdio.c', 'string.h': 'string.c', 'stdlib.h': 'stdlib.c',
             'gpu.h': 'gpu.c', 'gui.h': 'gui.c'}


def compile_program(files, include_dirs=None):
    """Preprocess each source file (pulling in headers), link in the stdlib
    implementations for whichever <system> headers were used, and compile the
    whole lot to one asm program. Multi-file 'linking' is concatenation in a
    single global namespace (prototypes/externs declare; definitions define)."""
    from cpp import Preprocessor
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    incdirs = list(include_dirs or []) + [os.path.join(here, 'lib')]
    units, sys_used = [], set()
    for f in files:
        pp = Preprocessor(incdirs)
        units.append(pp.preprocess(f))
        sys_used |= pp.system_includes
    for h in sorted(sys_used):
        impl = _LIB_IMPL.get(h)
        if impl:
            path = os.path.join(here, 'lib', impl)
            if os.path.exists(path):
                units.append(Preprocessor(incdirs).preprocess(path))
    return compile_c('\n'.join(units))


def build(files, include_dirs=None):
    """Compile + assemble a C/C++ program; returns (machine_code, data_image)."""
    from compiler import compile_asm
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    asm = compile_program(files, include_dirs)
    bios = open(os.path.join(here, 'asm', 'bios.asm')).read()
    return compile_asm(bios + '\n' + asm, data_base=DATA_BASE)


if __name__ == '__main__':
    import sys
    files = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not files:
        files = ['c/prog.c']
    if '--asm' in sys.argv:
        print(compile_program(files))
    else:
        from quattro import run_machine, dump
        code, data = build(files)
        print(f"[compiled {', '.join(files)}: {len(code)} instructions]")
        v, f, bus = run_machine(code, data=data, max_steps=5000000)
        dump(v, f, bus)
