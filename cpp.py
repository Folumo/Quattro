"""
C/C++ preprocessor for the Quattro toolchain -- runs as a text pass BEFORE
ccompiler.tokenize, flattening a source file (and everything it #includes) into
one translation unit.

Handles the common cases: comment stripping (quote-aware), backslash-newline
splicing, #include "local" / <system>, object- and function-like #define /
#undef, conditional compilation (#ifdef/#ifndef/#if/#elif/#else/#endif with
defined() and integer constant expressions), #pragma once, and #error. Macro
bodies are re-scanned so macros can use other macros, with a self-reference
guard. Not every C99 corner (no #/## operators, no variadic macros), but enough
to write real multi-file programs and a standard library.
"""

import os
import re

_ID = re.compile(r'[A-Za-z_]\w*')
# expansion-level tokenizer: identifiers, numbers, strings/chars, or one char
_TOK = re.compile(r'''
    "(?:\\.|[^"\\])*"        # string literal
  | '(?:\\.|[^'\\])*'        # char literal
  | [A-Za-z_]\w*             # identifier
  | \d+                      # number
  | \s+                      # whitespace (kept)
  | .                        # any single char
''', re.VERBOSE | re.DOTALL)


class PreprocessorError(Exception):
    pass


class Preprocessor:
    def __init__(self, include_dirs=None):
        self.include_dirs = list(include_dirs or [])
        self.macros = {}      # name -> (params | None, body_str)
        self.once = set()     # abspaths marked #pragma once
        self.system_includes = set()   # <name> headers seen (for lib linking)
        self.out = []

    # ------------------------------------------------------------------ public
    def preprocess(self, path):
        self.out = []
        self._include_file(os.path.abspath(path))
        return '\n'.join(self.out) + '\n'

    def preprocess_text(self, text, name='<input>', base_dir='.'):
        self.out = []
        self._run(text, name, os.path.abspath(base_dir))
        return '\n'.join(self.out) + '\n'

    # -------------------------------------------------------------- text phases
    @staticmethod
    def _strip_and_splice(text):
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        text = re.sub(r'\\\n', '', text)          # splice continued lines
        out, i, n = [], 0, len(text)
        while i < n:
            c = text[i]
            if c in '"\'':                         # copy a literal verbatim
                q = c
                out.append(c)
                i += 1
                while i < n and text[i] != q:
                    if text[i] == '\\':
                        out.append(text[i])
                        i += 1
                    if i < n:
                        out.append(text[i])
                        i += 1
                if i < n:
                    out.append(text[i])
                    i += 1
            elif text[i:i + 2] == '//':
                while i < n and text[i] != '\n':
                    i += 1
            elif text[i:i + 2] == '/*':
                i += 2
                while i < n and text[i:i + 2] != '*/':
                    i += 1
                i += 2
                out.append(' ')
            else:
                out.append(c)
                i += 1
        return ''.join(out)

    # ------------------------------------------------------------- include glue
    def _find(self, name, system, cur_dir):
        dirs = list(self.include_dirs) if system else [cur_dir] + self.include_dirs
        for d in dirs:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return os.path.abspath(p)
        raise PreprocessorError(f"include file not found: {name!r}")

    def _include_file(self, abspath):
        if abspath in self.once:
            return
        with open(abspath, encoding='utf-8') as f:
            text = f.read()
        self._run(text, abspath, os.path.dirname(abspath) or '.')

    # ------------------------------------------------------------- main scanner
    def _run(self, text, path, cur_dir):
        lines = self._strip_and_splice(text).split('\n')
        cond = []           # stack of [active_here, taken_any, parent_active]
        i = 0

        def active():
            return all(c[0] for c in cond)

        while i < len(lines):
            raw = lines[i]
            i += 1
            s = raw.strip()
            if s.startswith('#'):
                d = s[1:].strip()
                word = (d.split() or [''])[0]
                arg = d[len(word):].strip()
                if word in ('ifdef', 'ifndef', 'if'):
                    parent = active()
                    if word == 'ifdef':
                        val = arg in self.macros
                    elif word == 'ifndef':
                        val = arg not in self.macros
                    else:
                        val = parent and self._eval(arg) != 0
                    cond.append([parent and val, val, parent])
                elif word == 'elif':
                    top = cond[-1]
                    top[0] = top[2] and not top[1] and self._eval(arg) != 0
                    top[1] = top[1] or top[0]
                elif word == 'else':
                    top = cond[-1]
                    top[0] = top[2] and not top[1]
                    top[1] = True
                elif word == 'endif':
                    cond.pop()
                elif not active():
                    continue                       # skip directives in dead code
                elif word == 'include':
                    self._do_include(arg, cur_dir)
                elif word == 'define':
                    self._do_define(arg)
                elif word == 'undef':
                    self.macros.pop(arg.split()[0] if arg else '', None)
                elif word == 'pragma':
                    if arg.strip() == 'once':
                        self.once.add(os.path.abspath(path))
                elif word == 'error':
                    raise PreprocessorError(f"#error: {arg}")
                elif word in ('line',):
                    pass
                else:
                    raise PreprocessorError(f"unknown directive: #{d}")
            elif active():
                self.out.append(self._expand(raw))

    def _do_include(self, arg, cur_dir):
        arg = self._expand(arg).strip()
        if arg[:1] == '"':
            name, system = arg[1:arg.index('"', 1)], False
        elif arg[:1] == '<':
            name, system = arg[1:arg.index('>', 1)], True
            self.system_includes.add(name)
        else:
            raise PreprocessorError(f"bad #include: {arg}")
        self._include_file(self._find(name, system, cur_dir))

    def _do_define(self, arg):
        m = _ID.match(arg)
        if not m:
            raise PreprocessorError(f"bad #define: {arg}")
        name = m.group()
        rest = arg[m.end():]
        if rest.startswith('('):                   # function-like macro
            depth, j = 0, 0
            for j, ch in enumerate(rest):
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0:
                        break
            params = [p.strip() for p in rest[1:j].split(',') if p.strip()]
            body = rest[j + 1:].strip()
            self.macros[name] = (params, body)
        else:                                      # object-like macro
            self.macros[name] = (None, rest.strip())

    # ------------------------------------------------------------ macro expand
    def _expand(self, line, hide=()):
        toks = _TOK.findall(line)
        out, i = [], 0
        while i < len(toks):
            t = toks[i]
            if _ID.fullmatch(t) and t in self.macros and t not in hide:
                params, body = self.macros[t]
                if params is None:                 # object-like
                    out.append(self._expand(body, hide + (t,)))
                    i += 1
                else:                              # function-like: need '('
                    j = i + 1
                    while j < len(toks) and toks[j].isspace():
                        j += 1
                    if j < len(toks) and toks[j] == '(':
                        args, j = self._collect_args(toks, j)
                        sub = self._subst(params, body, args)
                        out.append(self._expand(sub, hide + (t,)))
                        i = j
                    else:
                        out.append(t)
                        i += 1
            else:
                out.append(t)
                i += 1
        return ''.join(out)

    @staticmethod
    def _collect_args(toks, j):
        # toks[j] == '(' ; return (list_of_arg_strings, index_after_close)
        depth, k, args, cur = 0, j, [], []
        while k < len(toks):
            t = toks[k]
            if t == '(':
                depth += 1
                if depth > 1:
                    cur.append(t)
            elif t == ')':
                depth -= 1
                if depth == 0:
                    args.append(''.join(cur).strip())
                    return ([a for a in args if a != '' or len(args) > 1], k + 1)
                cur.append(t)
            elif t == ',' and depth == 1:
                args.append(''.join(cur).strip())
                cur = []
            else:
                cur.append(t)
            k += 1
        raise PreprocessorError("unterminated macro argument list")

    def _subst(self, params, body, args):
        table = dict(zip(params, args + [''] * (len(params) - len(args))))
        out = []
        for t in _TOK.findall(body):
            out.append(table[t] if _ID.fullmatch(t) and t in table else t)
        return ''.join(out)

    # ------------------------------------------------- #if constant expressions
    def _eval(self, expr):
        # expand defined(X)/defined X, then macros, then evaluate as Python ints.
        expr = re.sub(r'defined\s*\(\s*(\w+)\s*\)',
                      lambda m: '1' if m.group(1) in self.macros else '0', expr)
        expr = re.sub(r'defined\s+(\w+)',
                      lambda m: '1' if m.group(1) in self.macros else '0', expr)
        expr = self._expand(expr)
        # bare identifiers left over evaluate to 0 (standard rule)
        expr = _ID.sub(lambda m: m.group() if m.group() in
                       ('and', 'or', 'not') else '0', expr)
        expr = expr.replace('&&', ' and ').replace('||', ' or ').replace('!', ' not ')
        try:
            return int(bool(eval(expr, {'__builtins__': {}}, {})))
        except Exception:
            return 0


def preprocess(path, include_dirs=None):
    return Preprocessor(include_dirs).preprocess(path)
