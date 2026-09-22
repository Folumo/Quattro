"""Count every component of the Q4 (4-quarter / byte-wide) CPU.

Same method as the 32-bit machine's census: the core is branch/loop-free gate
calls, so one AST expansion of the netlist is the exact static gate count.
Primitives (MIN/MAX/NOT/COM/MOD/EQ) are leaves; memory macros are counted from
the one-hot mux formula; large arrays (data RAM, instruction memory) are storage
reported by capacity, not gates.

    python -m q4.count4
"""
import ast
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
PRIMS = {'MIN', 'MAX', 'NOT', 'COM', 'MOD', 'EQ'}
MODULES = ['gates.py', 'words4.py', 'storage4.py', 'cpu4.py']
IGNORE = {'to_word', 'from_word', 'tuple', 'int', 'range', 'len', 'sum', 'zip',
          'enumerate', 'min', 'max', 'abs', 'divmod', 'list', 'print'}

calls = {}
for m in MODULES:
    tree = ast.parse(open(os.path.join(HERE, m), encoding='utf-8').read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            c = Counter()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                    c[sub.func.id] += 1
            calls[node.name] = c


def expand(name, external, seen=None):
    seen = seen or set()
    if name in PRIMS:
        return Counter({name: 1})
    if name in external or name in IGNORE or name not in calls or name in seen:
        return Counter()
    seen = seen | {name}
    total = Counter()
    for callee, n in calls[name].items():
        total += Counter({k: v * n for k, v in expand(callee, external, seen).items()})
    return total


def method_calls(module, classname, method):
    tree = ast.parse(open(os.path.join(HERE, module), encoding='utf-8').read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == classname:
            for m in node.body:
                if isinstance(m, ast.FunctionDef) and m.name == method:
                    c = Counter()
                    for sub in ast.walk(m):
                        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                            c[sub.func.id] += 1
                    return c
    return Counter()


def expand_counts(cc, external):
    total = Counter()
    for callee, n in cc.items():
        total += Counter({k: v * n for k, v in expand(callee, external).items()})
    return total


def vecmem(n, width, ndig):
    return Counter(
        EQ=n * ndig,
        MIN=n * max(ndig - 1, 0) + 2 * n * width + n * width,
        NOT=n,
        MAX=n * width + max(n - 1, 0) * width,
    )


def show(label, ctr, inst=1):
    ctr = Counter({k: v * inst for k, v in ctr.items()})
    tot = sum(ctr.values())
    line = '  '.join(f'{p}:{ctr.get(p, 0):>5}' for p in
                     ['MIN', 'MAX', 'NOT', 'COM', 'MOD', 'EQ'])
    print(f'{label:24s} x{inst:<2} | {line} | total {tot:>6}')
    return ctr


def main():
    print('=== Q4 combinational logic (built from the six primitives) ===\n')
    grand = Counter()

    grand += show('ALU  (W_ALU, W=4)', expand('W_ALU', external=set()))
    grand += show('CPU glue (step)', expand('step', external={'W_ALU'}))
    grand += show('Register file (4 regs)', vecmem(4, 4, 1))

    pc = Counter({k: v * 4 for k, v in
                  expand_counts(method_calls('storage4.py', 'COUNTER', 'run'),
                                external=set()).items()})
    pc['MAX'] = pc.get('MAX', 0) + 3          # carry-merge MAX in COUNTER4.run
    grand += show('Program counter (0..255)', pc)

    print('\n' + '=' * 78)
    show('WHOLE-CPU LOGIC TOTAL', grand)
    print('=' * 78)

    print('\n=== storage arrays (memory bits + decoder -- SRAM/ROM, not gates) ===')
    print('  Data RAM       : 256 words x 4 quarters = 256 bytes (one 8-bit SRAM chip)')
    print('  Register bits  : 4 registers x 1 byte   = 4 bytes')
    print('  Instruction mem: Harvard, up to 256 instructions x 2 bytes = 512 bytes ROM')

    print('\n=== physical scale, at 2 wires per quarter ===')
    print('  1 word = 4 quarters = 8 wires = ONE BYTE')
    print(f'  logic gates total = {sum(grand.values())}')
    return grand


if __name__ == '__main__':
    main()
