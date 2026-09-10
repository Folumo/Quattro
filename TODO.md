# Quattro — task list

Add new tasks here as `[TASK] ...`. The machine's ISA reference and architecture
notes live in `quattro/__init__.py`'s docstring
(`python -c "import quattro; help(quattro)"`).

**Run anything with `python main.py`** (a menu), or `python main.py tictactoe`
to go straight to one. `python main.py --list` shows them all.

**Test with `python tests/run.py`** (fast, ~2s — run it on every change) or
`python tests/run.py --slow` (~65s, adds programs executed on the real machine).
`python main.py check` is the slow suite.

Layout:

    main.py         THE entry point (menu + every program)
    quattro/        the machine: gates -> words -> storage -> bus -> cpu -> machine
    machine/        THE DRIVE: a real host folder the machine reads and writes
    compiler.py     assembler      cpp.py        C preprocessor
    ccompiler.py    C/C++ compiler lib/          the C standard library
    qbin.py         the linker: .bin executables that live on the drive
    emulator.py     console/asm front-end (debug panels)
    gui_run.py      GPU front-end (graphics window)
    asm/  c/        programs       tools/        the ALU generator
    tests/          the regression suite (run.py + test_*.py, no pytest)
    purity_check.py proves the core is still only gates

## Done

- [DONE] RAM6: 4096 code cells, 14-slot frame, up to 292 instructions.
- [DONE] Disk device — block storage at ports 240-242, seedable image.
- [DONE] C compiler (`python ccompiler.py c/prog.c`): int/char, +-*/%,
  comparisons, && || !, if/else, while, for, do/while, break/continue,
  ++/-- , functions, pointers, arrays, string literals. No recursion/bitwise.
- [DONE] Preemptive scheduler (`python sched_run.py`): timer-driven round-robin;
  hardware snapshots a task's context on the timer interrupt.
- [DONE] OS layer (`python os_run.py`): kernel with syscalls (trap port 232).
  Nums: 1=yield 2=exit 3=spawn.
- [DONE] PURITY RULE (standing, enforced by `python purity_check.py`): the
  machine core uses NO Python helpers — no for/while, if-elif-else, and/or,
  lists/sets/dicts, nested functions, or arithmetic. Only the primitives
  (MIN MAX NOT COM MOD EQ), functions composed from them, and storage classes.
  Exempt (outside world): devices, the storage latches (ST/Latch/Reg),
  Machine/run_machine, the edge converters (to_word/from_word/_addr6), dump/PC.
- [DONE] The BUS is pure too: one-hot EQ/MIN port decode, WGE RAM/device split,
  WSEL/WOR read mux, enable-strobed device/latch writes.
- [DONE] Project overhaul: split `main.py` into the `quattro/` package
  (gates, words, storage, devices, bus, cpu, machine); grouped `asm/` and `c/`;
  removed the dead single-digit-ALU cluster (Counter, ROM_INSTR, RG16,
  HF_DIVIDE, M_ALU).
- [DONE] Terminal (`python term.py`): interactive shell (`asm/shell.asm`) with a
  filesystem on the disk. Commands: ls, cat F, write F text, rm F, clr, help,
  shutdown. **Filenames up to 4 chars, files up to 63 chars** (8 files; the
  directory is 8x4-word names cached from sectors 0-1; file i lives at sector
  2+i*4, up to 4 sectors). Fits in 291 instructions (incl. BIOS), under 292.

- [DONE] Speed optimization (~30 → ~1400 instr/s, ~55x, purity preserved; needs
  `numpy`). **A** VecMem: memory is a numpy "macro" running the one-hot MIN/MAX/EQ
  mux in parallel over all cells (RAM1-5/REG deleted). **B** wide instruction
  memory: one wide cell per instruction, PC/labels are instruction indices →
  capacity 292 → 4096 instructions. **C** `@ROM` (lru_cache) on the pure gates /
  word-ALU = ROM synthesis. Verified: ALU bit-exact over 256×256, purity_check
  passes, shell/OS/scheduler/C-compiler all pass.

- [DONE] 32-bit rebuild: word widened to 16 quarters (0..4.29 billion); one
  register = one int = one pointer. Generated ALU (`tools/gen_words.py`), bit-
  exact; 16-bit `LOAD` immediates; `BigRAM` demand-paged data memory.
- [DONE] Phase 2 C toolchain: preprocessor (`cpp.py`; #include/#define/#if),
  software-stack calling convention (RECURSION), stdlib in `lib/` (stdio/string/
  stdlib + malloc/free heap), multi-file linking. `python ccompiler.py a.c b.c`.
- [DONE] C++ compatibility: classes/methods/this/ctors/new/delete/references/
  bool/`.`/`->`/namespaces (see `c/stack.cpp`). Object model = mangled free
  functions + `this`.

- [DONE] GPU + GUI. `GPU` device = a command-driven blitter (256x192, 16
  colours) with registers at 256..287; the CPU writes a few registers and the
  device paints (at ~1400 instr/s it could never paint pixels itself). TEXT and
  BLIT DMA straight out of RAM. C libs `lib/gpu.h` (primitives) and `lib/gui.h`
  (an immediate-mode toolkit: panel/label/button/checkbox/progress). Run a GUI
  program with `python gui_run.py c/gui_demo.cpp`. NOTE: this moved the C
  compiler's DATA_BASE 256 -> 1024, clear of the GPU window.

- [DONE] Game: `python gui_run.py c/tictactoe.cpp` — Tic-Tac-Toe vs an AI
  (win/block/centre/corner heuristic), written in C++ with a Board class.
  Turn-based by necessity: a full repaint is ~10k instructions (~7s at 1400
  instr/s), so the loop polls the GPU's **click latch** cheaply and repaints only
  on change. Added: GPU click-latch registers (CLICK/CLICKX/CLICKY, a consuming
  read like the keyboard) so a fast click is never missed; compiler **constant
  folding** (recursive, matches machine semantics incl. unsigned wrap + div-by-0).

- [DONE] **Code ceiling raised 4096 -> 65536 instructions.** The instruction
  frame is now 16 slots (was 14): jump targets use 8 quarters (B0,B1,C2..C7) and
  the PC is an 8-digit counter (COUNTER8). Free bonus: a LOAD immediate now
  spans 10 quarters, so constants/addresses reach 0..1048575 (was 65535).
  RSTACK was rebuilt on the VecMem storage macro (8-quarter entries, no wall of
  hand-unrolled cells). Verified with a generated 21,966-instruction program.
- [DONE] **Dead-code elimination** at link time: only functions reachable from
  main are emitted. Including <gui.h> for one helper now costs ~250 instructions
  instead of ~1200. (tictactoe 3138 -> 2861, gui_demo 2576 -> 2270.)

- [DONE] **A real drive, and a real boot.** `python main.py boot`. The machine
  image contains a ROM and nothing else; the OS is a file on the disk that the
  machine goes and fetches for itself.
  - `Drive` device (window 288..303) backed by the `machine/` host folder,
    **read and write**: SIZE/READ/WRITE/READW/LIST/DELETE/MKDIR. File-level, not
    sector-level, because the host folder already *is* the filesystem. Paths are
    confined to the drive root (no `..`, no absolutes).
  - `Loader` port (CODE_ADDR 246 / CODE_DATA 247) — the only way code gets into
    code memory at run time. Needed because this machine is Harvard: a running
    program cannot STORE into code memory, so without a load port a ROM could
    never bring in an OS. Real hardware has the same problem and the same answer.
  - `qbin.py`: the .bin executable format (magic/base/entry/ncode/ndata, then
    the image) + `code_base` relocatable linking in the assembler. One 32-bit
    word IS one 16-quarter instruction frame, so loading is a straight copy —
    one word per instruction, no unpacking.
  - `asm/boot.asm` (146 instrs): reads the header, checks the magic, streams the
    code through the load port, pokes the data image, and jumps to the entry —
    a runtime value off the disk, so a register-pair jump. Draws to the GPU, so
    the boot is visible; says so in red if the drive has no OS or a bad one.
  - `c/os.cpp` (1890 instrs): lists the real drive, reads files through the
    drive's POS register, tells folders from files, and writes `boot.log` to
    your actual disk on every boot. `python main.py check` verifies the whole
    chain (it reaches the OS entry and code memory matches the file bit for bit).

- [DONE] Speed, round 2 (~1000 -> ~1800 instr/s, and much flatter as memory
  grows: tictactoe at 16k code cells went 575 -> 1307). Two changes, both
  semantics-preserving and verified bit-exact against the longhand mux:
  `@ROM_BOUNDED` on `to_word` (the bus re-derived the same constant port numbers
  ~39x per instruction), and VecMem's one-hot decode as a single pass over the
  address-plane stack with preallocated scratch instead of a per-digit Python
  loop that reallocated on every access. Also fixed: `tools/gen_words.py` had
  drifted from the `quattro/words.py` it generates (stale FRAME=14, and a broken
  `__main__`); it now reproduces that file exactly and rewrites it in place.

- [DONE] **A REGRESSION SUITE — `tests/`** (68 tests: ~2s fast tier, ~65s with
  `--slow`). Until now ~6800 lines of Python — a CPU, an assembler, a C++
  compiler, a preprocessor — were guarded by one smoke check, and every session
  re-wrote the same throwaway verification scripts. Now: `tests/run.py` (a
  60-line runner; **no pytest — the project depends on numpy + pygame and that
  stays true**). `test_purity` (the checker itself, against planted violations),
  `test_hardware` (ALU vs Python over every boundary + randoms; VecMem vs the
  longhand one-hot mux), `test_contracts` (the pairs of files that must agree),
  `test_devices`, `test_programs` (C **differential** tests — expected output is
  computed from the machine's real semantics, not a golden string), `test_boot`.
  `main.py check` is now this suite. **Findings it locked in are below.**

- [DONE] **purity_check was unsound — the rule the project rests on was barely
  enforced.** Two independent holes, both now closed and pinned by tests:
  - It banned 16 AST *node types* and missed 14 violations, including **`x += 1`**
    (arithmetic!), `match`, `try`/`assert`/`raise`/`with`, the walrus, `async def`,
    and module-level `for`/`while`. The likely-accidental ones were the worst.
  - Worse, it banned **syntax, not semantics**: `from operator import add` makes
    `add(a, b)` a plain Call node and `+` walks straight past. Fixed with two
    layers: an **import allowlist** (the core may import only itself, plus
    functools/numpy/os for the exempt macros) and a **call whitelist** — a call
    is pure only if it lands on a primitive, on something the core itself defines
    (and which the checker has therefore already verified), or out through
    `self` to a storage cell/device. That rule needs no maintenance as the core
    grows. Verified: real core still passes, zero false alarms.

- [DONE] **Drive path confinement was escapable** (security). `_path` tested
  `p.startswith(self.root)` — a *string* prefix — so a drive rooted at
  `.../machine` could read `.../machine2/secret.txt`, because that genuinely does
  start with `.../machine`. Confirmed by reading a real file outside the drive.
  Now compares path components (`root + os.sep`). This was the one place a bug in
  this project reaches outside the simulation.

- [DONE] **The emulator's disassembler was lying.** It never got updated when the
  instruction frame went 14 -> 16 slots, so it unpacked immediates at 4 quarters
  and jump targets at 6: `LOAD R0, 1000` rendered as `LOAD R0, #232`, `JMP 5000`
  as `JMP 904`. Plausible-looking wrong numbers in the one panel you consult when
  asm misbehaves — it would have cost hours chasing a phantom bug in correct code.
  Fixed, and `test_contracts` now round-trips every instruction form through
  assembler -> frame -> disassembler so it can never drift again.

- [DONE] **Solo bug hunt (no agents): 9 real bugs found by running the machine,
  not reading it.** Each was a hypothesis with a concrete trigger. All fixed and
  pinned; the suite grew 68 -> 92 tests. Two of the leads I chased turned out to
  be **wrong** and were left alone: `cpp.py`'s `#if` evaluator is correct (all 11
  cases pass) and `printf`'s vararg marshalling is correct.
  - **The drive leaked the host directory** (security, the worst of these).
    `_path` correctly *rejected* a bad name by returning None — and `_exec`
    never checked. Every command survived only by accident, because None
    happened to raise inside a bare `except`. `C_LIST` was where the accident
    did not happen: `os.listdir(None)` does not raise, it lists the host's
    **current directory**. With INDEX past the end nothing raised at all, so the
    machine got a clean STATUS=0 and a count of the files in your project
    folder. Now rejected explicitly, up front, for every command.
  - **C calls had no arity check.** A wrong-count call still assembled: the
    caller pushes N values, the callee reads its frame at `nargs`, so the frame
    — *including the return address* — is misaligned. `f(1)` on a 2-arg function
    returned garbage; `f(1,2,3)` on a 1-arg function returned 3. Silent stack
    corruption. Checked now in `_emit_call`, the one funnel every call goes
    through (discounting the implicit `this` for methods).
  - **`sizeof` returned 1 for everything** — it was resolved in the PARSER,
    which has no symbol table and cannot tell `int a[10]` from `int a`. So the
    standard `sizeof(a)/sizeof(a[0])` idiom equalled 1 and every loop written
    that way silently ran once. `sizeof(struct X)` did not even parse. Now
    resolved in the codegen against real symbols: arrays give their length,
    structs their field count, and the operand is not evaluated (as C requires).
    Also fixed on the way: `struct P p;` (the elaborated form) now parses.
  - **`.string` did no escape processing.** `.string "hello\n"` stored a
    backslash and an 'n' and printed literally as `hello\n`. The C compiler had
    always decoded escapes; the assembler never did. (Nothing shipped used one,
    which is why nobody noticed.)
  - **Duplicate labels were silently accepted**, last one wins — a typo'd label
    quietly retargeted every jump to it.
  - **An oversized GPU blit walked the whole request**: a 2000x2000 blit spent
    **1.4s** in Python to paint at most 256x192, and nothing validates what a C
    program writes to W/H — so a C program could freeze the emulator. Clips the
    rectangle before walking it now: **1.393s -> 0.016s (87x)**.
  - **`code_size` was unvalidated.** Machine checked the program length against
    the 65536 the 8-digit PC can address, but not the memory it reserved, so
    index 65536 truncated to 0 and aliased onto the reset vector.
  - **`WRAM` was dead, exported, and broken.** A leftover from the 4-quarter era
    (BigRAM replaced it): it passed a 16-quarter address to a 4-digit decoder.
    That only ever "worked" because the old decode did `zip(planes, addr)` and
    **zip truncates silently** — a 256-word memory quietly answering a 32-bit
    address. My VecMem rewrite turned that into a raise, which is correct and is
    how the dead code surfaced. Removed; VecMem now rejects a wrong-width
    address by design, and says so in its docstring.
  - **Known limits found and pinned rather than changed** (each is a design call
    for the owner, not a bug to sneak in): a scheduler-configured machine can
    never service an ordinary keyboard/timer interrupt, because that path is an
    `elif` on `contexts is None`; `INT_VECTOR_HI` (port 238) is a dead port —
    latched on write, never read, since `int_vec` became a full word.

## Open

- [TASK] **Signed arithmetic — much closer than "no signed arithmetic" suggests.**
  The hardware is ALREADY two's-complement correct: `3 - 10` produces exactly the
  right bit pattern for -7 (pinned in `test_arithmetic_is_twos_complement`), so
  `+ - *` need NO hardware change. Only three things are missing, all in the
  compiler: (1) signed compare — `signed_lt(a,b) == unsigned_lt(a+2^31, b+2^31)`,
  since adding 2^31 wraps and flips the sign bit; verified over 3013 cases incl.
  every edge, 0 mismatches, using only existing gates. (2) signed `/` and `%`
  (negate-if-negative, unsigned divide, fix signs — a runtime helper). (3)
  `print_int` handling the sign. Blocker: the 2^31 bias constant exceeds the
  1048575 LOAD immediate, so this wants the `.word` constant pool first.
- [TASK] `.word` constant pool for literals >1048575 (also unblocks the above).
- [TASK] **RSTACK overflows silently.** `sp` is a single quaternary digit, so the
  4th push wraps it to 0 — the stack cannot tell full from empty, and nesting
  CALLs more than 3 deep silently overwrites the oldest return address. Verified:
  5-deep recursion in asm HANGS the machine. The C compiler sidesteps it with its
  software stack, and asm/shell.asm keeps to <=2, so nothing shipped hits it — but
  it is a trap for anyone writing asm. Fix: widen sp to 2 digits (16 entries) and
  expose an overflow flag. Pinned as a known limit in `test_rstack_overflow_is_documented`.
- [TASK] Assignment-as-expression (`if (0 && (c = 1))`) is unsupported — valid C,
  rejected by the parser. Minor, but it is the only thing the differential suite
  could not express directly.
- [TASK] Macro arity is unchecked: a 2-parameter macro called with one argument
  expands to `(1+)` and a 1-parameter macro called with two silently drops the
  extra. Produces garbage C that fails later, somewhere else, confusingly.
- [TASK] Decide the two pinned design calls: (a) should a scheduler-configured
  machine be able to take a keyboard interrupt? Today it cannot — the ordinary
  IRQ path is an `elif` on `contexts is None`. Nothing shipped needs it, and
  changing it risks the scheduler. (b) `INT_VECTOR_HI` (port 238) is dead —
  remove the port, or wire it up?
- [TASK] `dump()` scans only data 0..228, so it never shows the C toolchain's
  globals (1024+), the stack (20000+) or the heap (40000+) — i.e. nothing a C
  program actually uses.
- [TASK] **This is not a git repository.** ~6800 lines of hand-built work with no
  version control and no way to see or undo a bad change. `git init` would be the
  single cheapest risk reduction available.
- [TASK] GPU polish (optional): double buffering / vsync, sprite transparency,
  a proper built-in font in the device (today the front-end uploads one), clipping
  rectangles, a blitter "copy region" op.
- [TASK] C toolchain polish (optional): function overloading (arg-type
  mangling), single inheritance + virtual (vtables), signed arithmetic, a
  `.word` constant pool for >1048575 literals, `switch`.
- [TASK] OS polish (optional): open subfolders in the file browser (the drive
  already lists any path — the OS just never asks for one), scroll past 8 files,
  a text editor writing back through DRV_WRITE, launch a second .bin from the
  desktop (the load port can do it; it needs somewhere to put a second image).
- [TASK] Boot takes ~11s: 1890 words x 5 instructions through the load port at
  ~1000 instr/s. Options if it ever matters: a DMA mode on the Loader (drive
  streams straight to code memory, the way the GPU already DMAs strings), or
  keep it — a machine that loads its OS one instruction at a time and shows you
  a boot screen while it does is arguably the honest version.
