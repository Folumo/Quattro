"""The purity rule is the project's paramount invariant, and purity_check.py is
its only proof. So the checker itself needs checking: these plant known
violations and assert it catches every one.

Every case here was a real hole once. Banning `if` but not `match`, or `+` but
not `+=`, or `+` but not `operator.add`, is not a rule -- it is a suggestion.
"""
import glob
import os
import tempfile

from purity_check import check, core_vocabulary

VOCAB = core_vocabulary(sorted(glob.glob('quattro/*.py')))


def _check_src(src, vocab=VOCAB):
    d = tempfile.mkdtemp()
    p = os.path.join(d, 'm.py')
    with open(p, 'w') as f:
        f.write(src)
    return check(p, vocab)


# --- the real thing must pass -------------------------------------------

def test_core_is_pure():
    """The actual machine core. If this fails, a real violation landed."""
    files = sorted(glob.glob('quattro/*.py'))
    assert files, 'no core modules found'
    problems = []
    for f in files:
        problems += check(f, VOCAB)
    assert not problems, 'quattro/ is impure:\n  ' + '\n  '.join(problems)


# --- banned syntax ------------------------------------------------------

BANNED_SRC = {
    'if': 'def f(a):\n    if a:\n        return 1\n    return 0\n',
    'ternary': 'def f(a):\n    return 1 if a else 0\n',
    'for': 'def f(a):\n    for i in a:\n        pass\n',
    'while': 'def f(a):\n    while a:\n        pass\n',
    'arithmetic': 'def f(a):\n    return a + 1\n',
    'aug_assign': 'def f(a):\n    a += 1\n    return a\n',
    'comparison': 'def f(a):\n    return a > 1\n',
    'bool_op': 'def f(a, b):\n    return a and b\n',
    'unary': 'def f(a):\n    return -a\n',
    'list': 'def f():\n    return [1]\n',
    'dict': 'def f():\n    return {1: 2}\n',
    'set': 'def f():\n    return {1}\n',
    'listcomp': 'def f(a):\n    return [x for x in a]\n',
    'genexp': 'def f(a):\n    return tuple(x for x in a)\n',
    'subscript': 'def f(a):\n    return a[0]\n',
    'lambda': 'def f():\n    return lambda x: x\n',
    'nested_def': 'def f():\n    def g():\n        pass\n    return g\n',
    'match': ('def f(a):\n    match a:\n        case 0:\n            return 1\n'
              '        case _:\n            return 2\n'),
    'try': 'def f(a):\n    try:\n        return a\n    except Exception:\n        return 0\n',
    'assert': 'def f(a):\n    assert a\n    return a\n',
    'raise': 'def f(a):\n    raise ValueError(a)\n',
    'with': 'def f(a):\n    with open("x") as h:\n        return h\n',
    'walrus': 'def f(a):\n    b = (c := a)\n    return b\n',
    'async_def': 'async def f(a):\n    return a\n',
    'nested_async': 'def f():\n    async def g():\n        pass\n    return g\n',
    'module_for': 'for i in range(4):\n    X = i\n',
    'module_while': 'X = 0\nwhile X:\n    X = 1\n',
    'method_aug_assign': 'class C:\n    def m(self, y):\n        y += 1\n        return y\n',
    'method_match': ('class C:\n    def m(self, y):\n        match y:\n'
                     '            case 0:\n                return 1\n        return y\n'),
}


def test_banned_syntax_is_caught():
    missed = [k for k, src in BANNED_SRC.items() if not _check_src(src)]
    assert not missed, f'these violations slip through purity_check: {missed}'


# --- banned semantics: impurity that never spells itself as an operator --

LAUNDERED_SRC = {
    'operator.add is +': 'from operator import add\ndef f(a, b):\n    return add(a, b)\n',
    'operator.getitem is []': 'from operator import getitem\ndef f(a):\n    return getitem(a, 0)\n',
    'np.where is an if': ('import numpy as np\nclass C:\n    def run(self, a, b):\n'
                          '        return np.where(a, b, 0)\n'),
    'outside helper': 'from tools.helper import decode\ndef f(a):\n    return decode(a)\n',
    'builtin sum': 'def f(w):\n    return sum(w)\n',
    'stdlib import': 'import math\ndef f(a):\n    return math.floor(a)\n',
}


def test_laundered_impurity_is_caught():
    missed = [k for k, src in LAUNDERED_SRC.items() if not _check_src(src)]
    assert not missed, f'impurity launders through a call: {missed}'


# --- and legitimate core code must NOT trip it --------------------------

LEGIT_SRC = {
    'gate composition': 'from .gates import MIN, MAX\ndef f(a, b):\n    return MIN(a, MAX(b, a))\n',
    'wire out through self': 'class C:\n    def run(self, a):\n        return self.mem.access(a, 0)\n',
    'word fn + converter': ('from .words import WEQ, to_word\ndef f(addr):\n'
                            '    return WEQ(addr, to_word(229))\n'),
    'tuple return': 'def f(a, b):\n    return (a, b)\n',
    'starred unpack': 'def f(w):\n    a, b, *_ = w\n    return a\n',
}


def test_no_false_alarms():
    vocab = VOCAB | {'MIN', 'MAX', 'WEQ', 'to_word', 'C', 'f'}
    flagged = {k: _check_src(src, vocab) for k, src in LEGIT_SRC.items()}
    flagged = {k: v for k, v in flagged.items() if v}
    assert not flagged, f'purity_check rejects legitimate gate code: {flagged}'
