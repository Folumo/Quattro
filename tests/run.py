"""
Quattro's test suite. No pytest -- the project depends on numpy and pygame and
nothing else, and the runner is 60 lines, so it stays that way.

    python tests/run.py            the fast tests (a few seconds)
    python tests/run.py --slow     everything, including programs run on the
                                   real gate machine at ~1800 instructions/second
    python tests/run.py alu bus    only modules matching these names

A test is any `test_*` function in a `tests/test_*.py` module. It passes if it
returns without raising; use plain `assert`. Mark a test that has to run code on
the machine with `slow = True` on the function -- those cost seconds each, so
they are opt-in and everything else stays fast enough to run on every change.
"""

import glob
import importlib.util
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)


def load(path):
    spec = importlib.util.spec_from_file_location(
        os.path.basename(path)[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    slow = '--slow' in sys.argv
    paths = sorted(glob.glob(os.path.join(ROOT, 'tests', 'test_*.py')))
    if args:
        paths = [p for p in paths if any(a in os.path.basename(p) for a in args)]

    passed = failed = skipped = 0
    failures = []
    t0 = time.time()
    for path in paths:
        mod = load(path)
        name = os.path.basename(path)[:-3]
        tests = [(n, getattr(mod, n)) for n in sorted(dir(mod))
                 if n.startswith('test_') and callable(getattr(mod, n))]
        print(f'\n{name}')
        for tname, fn in tests:
            if getattr(fn, 'slow', False) and not slow:
                print(f'  skip {tname}  (slow -- use --slow)')
                skipped += 1
                continue
            t = time.time()
            try:
                fn()
            except Exception as e:
                failed += 1
                failures.append((name, tname, traceback.format_exc()))
                print(f'  FAIL {tname}  {type(e).__name__}: {e}')
            else:
                passed += 1
                print(f'  ok   {tname}  ({time.time() - t:.2f}s)')

    print('\n' + '=' * 62)
    for name, tname, tb in failures:
        print(f'\n--- {name}.{tname} ---\n{tb}')
    print(f'{passed} passed, {failed} failed, {skipped} skipped '
          f'in {time.time() - t0:.1f}s')
    if not slow and skipped:
        print('(run with --slow to include the tests that execute code on the machine)')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
