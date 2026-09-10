"""
Quattro executables: compile C/C++/asm into a loadable .bin on the drive.

    python qbin.py c/hello.cpp machine/bin/hello.bin --base 512
    python qbin.py asm/foo.asm  machine/bin/foo.bin

A .bin is a flat little-endian 32-bit-word file:

    word 0   magic 'QUAT' (0x54415551)
    word 1   base    -- the instruction index the image must be loaded at
    word 2   entry   -- the instruction index to jump to (absolute)
    word 3   ncode   -- how many instruction words follow
    word 4   ndata   -- how many (address, value) data pairs follow
    ncode words       -- the program; ONE WORD IS ONE INSTRUCTION, because a
                        32-bit word is exactly the machine's 16-quarter frame
    ndata*2 words     -- the data image, as address/value pairs

That last point is what makes booting cheap: the loader streams a word straight
into CODE_DATA per instruction, no unpacking.
"""

import os
import struct
import sys

MAGIC = 0x54415551          # 'QUAT' little-endian


def frame_to_word(frame):
    """One 16-quarter instruction frame -> one 32-bit word."""
    w = 0
    for k, q in enumerate(frame):
        w += q * (4 ** k)
    return w


def word_to_frame(w):
    return tuple((w // (4 ** k)) % 4 for k in range(16))


def make_image(code, data, base, entry):
    words = [MAGIC, base, entry, len(code), len(data)]
    words += [frame_to_word(f) for f in code]
    for addr, val in sorted(data.items()):
        words += [addr, val]
    return b''.join(struct.pack('<I', w & 0xFFFFFFFF) for w in words)


def read_image(blob):
    n = len(blob) // 4
    w = list(struct.unpack('<%dI' % n, blob[:n * 4]))
    if not w or w[0] != MAGIC:
        raise ValueError('not a Quattro executable (bad magic)')
    base, entry, ncode, ndata = w[1], w[2], w[3], w[4]
    code = [word_to_frame(x) for x in w[5:5 + ncode]]
    rest = w[5 + ncode:5 + ncode + 2 * ndata]
    data = {rest[i]: rest[i + 1] for i in range(0, len(rest), 2)}
    return base, entry, code, data


def build_bin(sources, base=0, entry_label='main'):
    """Compile sources (C/C++ or .asm) linked to load at instruction `base`."""
    from compiler import compile_asm
    if sources[0].endswith(('.c', '.cpp', '.cc')):
        from ccompiler import compile_program, DATA_BASE
        here = os.path.dirname(os.path.abspath(__file__))
        # same link line as ccompiler.build: C code calls BIOS routines by name
        asm = open(os.path.join(here, 'asm', 'bios.asm')).read() + '\n' + \
            compile_program(sources)
        data_base = DATA_BASE
    else:
        asm = '\n'.join(open(s).read() for s in sources)
        data_base = 0
    code, data, labels = compile_asm(asm, return_labels=True,
                                     data_base=data_base, code_base=base)
    if entry_label not in labels:
        raise ValueError(f'no {entry_label!r} label to use as the entry point')
    return make_image(code, data, base, labels[entry_label]), len(code)


def main():
    argv = sys.argv[1:]
    base = 0
    if '--base' in argv:
        i = argv.index('--base')
        base = int(argv[i + 1])
        del argv[i:i + 2]              # the value is not a source file
    args = [a for a in argv if not a.startswith('--')]
    if len(args) < 2:
        print(__doc__.strip())
        return
    *sources, out = args
    blob, ncode = build_bin(sources, base=base)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'wb') as f:
        f.write(blob)
    print(f'{out}: {ncode} instructions, {len(blob)} bytes, loads at {base}')


if __name__ == '__main__':
    main()
