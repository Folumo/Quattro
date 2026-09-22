# Q4 — the 4-quarter (byte-wide) Quattro CPU

A second Quattro CPU whose word is **4 quarters = 8 bits = one byte** (0–255),
built from the same six gate primitives (MIN / MAX / NOT / COM / MOD / EQ) as the
32-bit machine. The word ALU is generated at width 4 by the shared
`tools/gen_words.py`, so the arithmetic is the same design, a quarter of the
width.

Why a byte-wide variant? Because **a Q4 word is exactly one byte on the wire**
(two wires per quarter × four quarters), so it connects to real RAM, real
displays, and USB keyboard/mouse bytes with no conversion — see
[`HARDWARE.md`](HARDWARE.md). This is the version you would actually build first.

## Run it

```
python -m q4.cpu4      # run the demo programs (sum=55, mul=42, mem=99)
python -m q4.test4     # the self-test suite (arith, logic, memory, control)
python -m q4.count4    # the full component census
```

## The machine

- **Word:** 4 quarters = 8 bits = 1 byte (0–255).
- **Registers:** R0–R3 (four bytes).
- **Data RAM:** 256 bytes, byte-addressed.
- **Program:** Harvard, up to 256 instructions; each instruction is 8 quarters
  (2 bytes): `(OP, SUB, DA, SA, I0, I1, I2, I3)`.
- **I/O:** an output port (`OUT`); input ports for a keyboard/mouse are the small
  extension described in `HARDWARE.md §5–6`.

### Instruction set

| class | ops | form |
|---|---|---|
| arith (0) | ADD SUB MUL DIV | `Rd = Rd op Rs` |
| logic (1) | MIN MAX MOD NOT | `Rd = Rd op Rs` (NOT is unary) |
| memory (2) | LOADI, LOAD, STORE, MOV | `Rd=imm` · `Rd=RAM[Rs]` · `RAM[Rs]=Rd` · `Rd=Rs` |
| control (3) | JMP, JZ, OUT, HALT | `pc=a` · `if Rd==0 pc=a` · `port=Rd` · stop |

Arithmetic is byte-wide and wraps mod 256; `MIN`/`MAX` are numeric; `MOD` is
add-mod-256; `NOT` is per-quarter `3−q`; divide-by-zero gives 0. (All verified in
`test4.py`.)

Programs are written with a tiny assembler:

```python
from q4 import Machine4, asm
from q4.words4 import from_word
prog = [('LOADI', 0, 6), ('LOADI', 1, 7), ('MUL', 0, 1), ('OUT', 0), ('HALT',)]
m = Machine4(asm(prog)).run()
print([from_word(w) for w in m.out.log])   # [42]
```

## Component census

`python -m q4.count4` — the whole logic core is **1,852 primitive gates**:

| block | gates |
|---|--:|
| ALU (W_ALU, W=4) | 1,645 |
| Register file (4 regs) | 84 |
| CPU glue (decode + sequencer) | 68 |
| Program counter | 55 |
| **total logic** | **1,852** |

MIN 515 · MAX 337 · NOT 261 · COM 262 · MOD 357 · EQ 120. Plus storage arrays
(256-byte data RAM, 512-byte program ROM, 4 register bytes) — an SRAM/ROM chip,
not gates. That is ~12× smaller than the 32-bit machine's 22,441-gate logic,
mostly because the multiplier and divider shrink with the square of the width.

## Files

```
gates.py     the six primitives (shared, unchanged)
words4.py    the word ALU, generated at width 4 (tools/gen_words.py 4)
storage4.py  ST / VecMem / counters, and the register file, RAM, PC, port
cpu4.py      the ISA, the decode/execute datapath, the assembler, demos
test4.py     the self-test suite
count4.py    the component census
HARDWARE.md  how to wire it to RAM, a clock, a display, and USB kbd/mouse
```
