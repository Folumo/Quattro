"""
Quattro -- one entry point for everything.

    python main.py              pick a program from the menu
    python main.py tictactoe    run one straight away
    python main.py --list       just list them

Quattro is a base-4 (quaternary) computer built entirely out of single-digit
gate primitives: MIN / MAX / NOT / COM / MOD / EQ. Everything below -- the ALU,
the CPU, the bus, the C/C++ compiler, the GPU -- sits on top of those six.

Layout:
    quattro/        the machine itself (gates -> words -> storage -> bus -> cpu)
    machine/        the drive: a real folder the machine reads and writes
    compiler.py     the assembler          cpp.py       the C preprocessor
    ccompiler.py    the C/C++ compiler     lib/         the C standard library
    qbin.py         the linker: .bin executables that live on the drive
    emulator.py     console/asm front-end  gui_run.py   GPU front-end
    asm/  c/        programs               tools/       the ALU generator
    tests/          the regression suite (python tests/run.py [--slow])
    purity_check.py proves the core is still built only from gates
"""

import subprocess
import sys


# --------------------------------------------------------------- runners

def run_gpu(files):
    """A C/C++ program that draws through the GPU, in a graphics window."""
    from gui_run import GuiRunner
    GuiRunner(files).run()


def run_emulator(path, disk=None):
    """An assembly program in the full debugger/emulator (regs, PC, devices)."""
    from emulator import Emulator
    Emulator(path, disk=disk).run()


def make_fs(files):
    """Build a disk image for the shell's filesystem from {name: text}.
    Directory (sectors 0..1) = up to 8 four-char names; file i's contents live
    at sector 2 + i*4. The Disk loader spills an over-long list into the
    following sectors, so each entry can just be written whole."""
    disk, dirwords = {}, []
    for i, (name, text) in enumerate(files.items()):
        if i >= 8:
            break
        nm = [ord(c) for c in name][:4]
        nm += [0] * (4 - len(nm))
        dirwords += nm
        disk[2 + i * 4] = [ord(c) for c in text][:63] + [0]
    disk[0] = dirwords
    return disk


def run_shell():
    """The terminal: an interactive shell + filesystem, running on the gates."""
    run_emulator('asm/shell.asm', disk=make_fs({
        'read': 'read me!',
        'hi': 'hello there',
        'base': 'base four is neat',
    }))


def _run_console(code, data, sched=None, steps=5000000):
    from quattro import run_machine, dump
    v, f, bus = run_machine(code, data=data, sched=sched, max_steps=steps)
    dump(v, f, bus)


def run_c(files):
    """A C/C++ program whose output is text, printed when it halts."""
    from ccompiler import build
    code, data = build(files)
    print(f"[compiled {', '.join(files)}: {len(code)} instructions]")
    _run_console(code, data)


def run_os():
    """The multitasking OS: syscall traps, a task table, round-robin scheduling.
    'init' spawns workers that print a letter and yield; the kernel halts when
    nothing is ready. Expect ABCABCABC."""
    from compiler import compile_asm
    code, data, labels = compile_asm(open('asm/os.asm').read(), return_labels=True)
    print(f"[asm/os.asm: {len(code)} instructions]")
    _run_console(code, data, sched={'tasks': [labels['init']], 'nslots': 4,
                                    'handler': labels['kernel'], 'period': 0},
                 steps=20000)


def run_sched():
    """Preemptive multitasking: the timer interrupt snapshots a task's whole
    context in hardware; the asm handler picks the next one. Expect AAA..BBB..CCC."""
    from compiler import compile_asm
    code, data, labels = compile_asm(open('asm/sched.asm').read(), return_labels=True)
    tasks = sorted((l for l in labels if l.startswith('task')), key=lambda l: labels[l])
    print(f"[asm/sched.asm: {len(code)} instructions, tasks: {', '.join(tasks)}]")
    _run_console(code, data, sched={'tasks': [labels[t] for t in tasks],
                                    'handler': labels['sched'], 'period': 30},
                 steps=20000)


# Where the two programs live. They are separate images that must not tread on
# each other: the ROM is burned in at instruction 0 and the OS is loaded off the
# drive above it, while in data memory the ROM keeps its strings just above the
# device window and the C toolchain starts its own globals at 1024.
OS_BASE = 512          # the ROM owns instructions 0..511; the OS loads above it
ROM_DATA = 320         # ROM data: above the device window (ends 303), below 1024


def build_rom():
    """Assemble the boot ROM: the BIOS, then boot.asm. This is the whole machine
    image -- there is deliberately no OS in it."""
    from compiler import compile_asm
    rom, romdata = compile_asm(open('asm/bios.asm').read() + '\n' +
                               open('asm/boot.asm').read(), data_base=ROM_DATA)
    if len(rom) > OS_BASE:
        raise SystemExit(f'ROM is {len(rom)} instructions -- it would overflow '
                         f'into the OS load area at {OS_BASE}')
    return rom, romdata


def build_os():
    """Compile the OS to a real file on the drive: machine/bin/os.bin."""
    import os as _os
    from qbin import build_bin
    blob, ncode = build_bin(['c/os.cpp'], base=OS_BASE)
    _os.makedirs('machine/bin', exist_ok=True)
    with open('machine/bin/os.bin', 'wb') as f:
        f.write(blob)
    print(f'machine/bin/os.bin: {ncode} instructions, {len(blob)} bytes, '
          f'loads at {OS_BASE}')
    return ncode


def run_boot():
    """Boot the machine for real. Reset runs the ROM; the ROM finds bin/os.bin
    on the drive, streams it into code memory through the load port, and jumps
    to it. The OS then draws its own GUI. Nothing about the OS is baked into the
    machine image -- it genuinely comes off the disk, and if you delete the file
    the machine tells you it has nothing to boot."""
    from gui_run import GuiRunner
    ncode = build_os()
    rom, romdata = build_rom()
    print(f'ROM: {len(rom)} instructions')
    GuiRunner.boot(rom, romdata, code_size=OS_BASE + ncode + 16).run()


def run_check(slow=True):
    """The regression suite: purity, the gate hardware against reference
    arithmetic, the contracts between components that are written down twice,
    the devices, and programs run on the real machine including the boot chain.

    This is `python tests/run.py --slow`; see tests/run.py to run a subset."""
    cmd = [sys.executable, 'tests/run.py'] + (['--slow'] if slow else [])
    raise SystemExit(subprocess.run(cmd).returncode)


# --------------------------------------------------------------- the menu

PROGRAMS = [
    ('boot', 'Boot QuattroOS off the drive    (ROM + C++, graphics)',
     run_boot),
    ('tictactoe', 'Tic-Tac-Toe against the AI      (C++, graphics)',
     lambda: run_gpu(['c/tictactoe.cpp'])),
    ('gui', 'GUI widget demo                 (C++, graphics)',
     lambda: run_gpu(['c/gui_demo.cpp'])),
    ('shell', 'Terminal + filesystem           (asm, emulator)',
     run_shell),
    ('demo', 'Keyboard + mouse demo           (asm, emulator)',
     lambda: run_emulator('asm/demo.asm')),
    ('disk', 'Boot a message off the disk     (asm, emulator)',
     lambda: run_emulator('asm/code.asm')),
    ('greet', 'Type-a-key greeting demo        (asm, emulator)',
     lambda: run_emulator('test/t1.asm')),
    ('os', 'Multitasking OS with syscalls   (asm, console)',
     run_os),
    ('sched', 'Preemptive scheduler            (asm, console)',
     run_sched),
    ('stack', 'Linked-list Stack class         (C++, console)',
     lambda: run_c(['c/stack.cpp'])),
    ('cdemo', 'Loops / pointers demo           (C, console)',
     lambda: run_c(['c/prog.c'])),
    ('check', 'Run the test suite              (purity + hardware + boot)',
     run_check),
]


def show_menu():
    print(__doc__.strip().split('Layout:')[0].strip())
    print()
    for i, (key, desc, _) in enumerate(PROGRAMS, 1):
        print(f'  {i:2d}. {key:-10s} {desc}')
    print()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    if '--list' in sys.argv or '-l' in sys.argv:
        for key, desc, _ in PROGRAMS:
            print(f'{key:12s} {desc}')
        return
    if args:                                  # run one directly by name
        wanted = args[0]
        for key, _, fn in PROGRAMS:
            if key == wanted:
                fn()
                return
        print(f"unknown program: {wanted!r}\n")
        for key, desc, _ in PROGRAMS:
            print(f'  {key:12s} {desc}')
        return
    show_menu()
    try:
        choice = input('run which? (number or name, blank to quit) ').strip()
    except EOFError:
        return
    if not choice:
        return
    for i, (key, _, fn) in enumerate(PROGRAMS, 1):
        if choice == key or choice == str(i):
            fn()
            return
    print(f'unknown choice: {choice!r}')


if __name__ == '__main__':
    main()
