"""
Purity checker for the quattro/ package: proves the machine core is built ONLY
from gate primitives -- no Python loops, branches, boolean logic, arithmetic,
container types, comparisons, subscripts, or nested functions.

Allowed zones (the "outside world", not machine hardware):
  - the premade primitives (MIN/MAX/NOT/COM/MOD/EQ)
  - the storage cells / latches (ST, Latch, Reg)
  - devices (Console, Keyboard, Timer, Disk, Mouse)
  - the testbench/clock (Machine, run_machine) and edge converters
    (to_word, from_word, _addr8)
  - dump / PC / main (explicitly exempted)

Run:  python purity_check.py     -> lists violations, exits 1 if any
"""

import ast
import glob
import os
import sys

EXEMPT = {
    # storage cells / latches / memory macros (data-holding primitives). VecMem
    # is a memory macro: its read/write is the one-hot MIN/MAX/EQ gate mux, but
    # evaluated in parallel with numpy rather than a Python cell-by-cell walk.
    'ST', 'Latch', 'Reg', 'VecMem', 'BigRAM',
    # devices -- the "outside world", not built from our gates
    'Console', 'Keyboard', 'Timer', 'Disk', 'Mouse', 'GPU', 'Drive', 'Loader',
    # testbench / clock and edge converters
    'Machine', 'run_machine', 'to_word', 'from_word', '_addr8',
    'dump', 'PC', 'main',
}

BANNED = {
    # branching
    ast.If: "if statement",
    ast.IfExp: "conditional expression",
    ast.Match: "match statement",
    ast.Assert: "assert (a branch)",
    # looping
    ast.For: "for loop",
    ast.AsyncFor: "async for loop",
    ast.While: "while loop",
    # non-local control flow
    ast.Try: "try/except",
    ast.Raise: "raise",
    ast.With: "with statement",
    ast.AsyncWith: "async with statement",
    ast.Await: "await",
    # logic and arithmetic the gates are supposed to be doing
    ast.BoolOp: "and/or",
    ast.BinOp: "arithmetic operator",
    ast.AugAssign: "augmented assignment (+= is still arithmetic)",
    ast.UnaryOp: "unary operator",
    ast.Compare: "comparison",
    ast.NamedExpr: "walrus operator",
    # containers and indexing
    ast.List: "list literal",
    ast.Dict: "dict literal",
    ast.Set: "set literal",
    ast.ListComp: "list comprehension",
    ast.SetComp: "set comprehension",
    ast.DictComp: "dict comprehension",
    ast.GeneratorExp: "generator expression",
    ast.Subscript: "subscript/indexing",
    ast.Lambda: "lambda",
}
# except* (3.11+); harmless to skip on older interpreters that lack the node
if hasattr(ast, 'TryStar'):
    BANNED[ast.TryStar] = "try/except*"

FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)

# Banning syntax is not enough: `from operator import add` makes `add(a, b)` a
# plain Call node, and `+` walks straight past a checker that only looks for
# ast.BinOp. So the core may only import from itself, plus the few host modules
# the EXEMPT outside-world classes are built from.
ALLOWED_IMPORTS = {
    'functools',   # lru_cache, i.e. @ROM -- memoizing a pure block is a ROM
    'numpy',       # the VecMem / BigRAM memory macros
    'os',          # the Drive device: the drive IS a host folder
}

# The six premade primitives. Everything else callable must be something the
# core itself defines -- and therefore something this checker has already
# verified is pure. That rule needs no maintenance as the core grows.
PRIMITIVES = {'MIN', 'MAX', 'NOT', 'COM', 'MOD', 'EQ'}


def core_vocabulary(files):
    """Every name the core defines or imports from itself: the only names a
    pure function is allowed to call."""
    names = set(PRIMITIVES)
    for path in files:
        tree = ast.parse(open(path, encoding='utf-8').read())
        for top in tree.body:
            if isinstance(top, (ast.ClassDef,) + FUNCS):
                names.add(top.name)
            elif isinstance(top, ast.ImportFrom) and top.level:
                names.update(a.asname or a.name for a in top.names)
            elif isinstance(top, ast.Assign):
                names.update(t.id for t in top.targets
                             if isinstance(t, ast.Name))
    return names


def _describe(node):
    for kind, label in BANNED.items():
        if isinstance(node, kind):
            return label
    return type(node).__name__


def _check_imports(path, tree):
    problems = []
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            # a relative import is the core importing itself: always fine
            mods = [] if node.level else [node.module or '']
        for m in mods:
            if m.split('.')[0] not in ALLOWED_IMPORTS:
                problems.append(
                    f"{path}:{node.lineno}: imports {m!r} -- the core may only "
                    f"import itself or {sorted(ALLOWED_IMPORTS)}")
    return problems


def check(path, vocab=None):
    tree = ast.parse(open(path, encoding='utf-8').read())
    problems = _check_imports(path, tree)

    for top in tree.body:
        if isinstance(top, (ast.Import, ast.ImportFrom, ast.Expr, ast.Assign)):
            continue  # module docstrings, constants, primitive lambdas, imports
        if not isinstance(top, (ast.ClassDef,) + FUNCS):
            # Anything else at module level is executable code -- a for loop
            # building a table, an if picking an implementation. The core is
            # definitions only, so this is a violation rather than a skip.
            problems.append(
                f"{path}:{top.lineno}: {_describe(top)} at module level")
            continue
        if top.name in EXEMPT:
            continue

        # every node inside a core class/function must be pure
        methods = set()
        if isinstance(top, ast.ClassDef):
            methods = {n for n in top.body if isinstance(n, FUNCS)}
        for node in ast.walk(top):
            if isinstance(node, FUNCS):
                if isinstance(node, ast.AsyncFunctionDef):
                    problems.append(
                        f"{path}:{node.lineno}: async function in {top.name}")
                if node is not top and node not in methods:
                    problems.append(
                        f"{path}:{node.lineno}: nested function in {top.name}")
                continue
            if isinstance(node, ast.Call):
                problems += _check_call(path, node, top.name, vocab)
                continue
            for kind, label in BANNED.items():
                if isinstance(node, kind):
                    problems.append(
                        f"{path}:{node.lineno}: {label} in {top.name}")
                    break

    return problems


def _check_call(path, node, where, vocab):
    """A call is pure only if it lands on a gate primitive, on something the
    core defines (already checked), or on a wire out of this object (self.x.y()
    -- a storage cell or device, which are the exempt outside world)."""
    fn = node.func
    if isinstance(fn, ast.Name):
        if vocab is not None and fn.id not in vocab:
            return [f"{path}:{node.lineno}: calls {fn.id!r} in {where} -- not a "
                    f"primitive and not defined in the core"]
        return []
    if isinstance(fn, ast.Attribute):
        root = fn
        while isinstance(root, ast.Attribute):
            root = root.value
        if isinstance(root, ast.Name) and root.id == 'self':
            return []
        got = getattr(root, 'id', type(root).__name__)
        return [f"{path}:{node.lineno}: calls {got}.{fn.attr}() in {where} -- a "
                f"pure function may only call out through self"]
    return [f"{path}:{node.lineno}: computed call in {where}"]


if __name__ == '__main__':
    files = sorted(glob.glob(os.path.join('quattro', '*.py')))
    vocab = core_vocabulary(files)
    probs = []
    for f in files:
        probs += check(f, vocab)
    if probs:
        print(f"{len(probs)} violation(s):")
        for p in probs:
            print(" ", p)
        sys.exit(1)
    print(f"quattro/ core is PURE ({len(files)} modules): gates, gate-built "
          "functions, and storage only.")
