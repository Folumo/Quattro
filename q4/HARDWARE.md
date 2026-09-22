# Building Q4 in real hardware

How to take the 4-quarter CPU off the simulator and wire it to real RAM, a real
clock, a display, and a USB keyboard and mouse.

There is one fact that makes all of this easy, and it is worth stating first.

---

## 0. The one fact: a Q4 word IS a byte

The CPU is defined in base 4 (each digit, a *quarter*, is 0-3). Real chips are
binary, so **encode each quarter as 2 wires** (0→`00`, 1→`01`, 2→`10`, 3→`11`).

A word is 4 quarters, so it is **4 × 2 = 8 wires = one byte**. And the encoding
lines up exactly: a quarter at place *k* is worth 4ᵏ, and two bits are worth
2ᵏ⁺¹ and 2ᵏ — so the 8 wires read as a plain binary byte equal to the word's
value. `q0 + 4·q1 + 16·q2 + 64·q3` **is** the 8-bit number on those wires.

> **A Q4 word on the bus is a standard 8-bit byte, bit for bit. No conversion.**

That is the whole reason this variant (rather than the 32-bit one) is the one to
build first: every register, the data bus, the RAM, the I/O ports, the character
codes going to a display, and the bytes coming from a USB keyboard are all just
bytes. You build the *inside* of the CPU from 2-bit-per-quarter logic (a handful
of 74HC gates per primitive, or one small EEPROM per gate block — see the 32-bit
project's TODO), but the *outside* connects like any 8-bit machine.

The whole logic core is **1,852 primitive gates** (`python -m q4.count4`): ALU
1,645, register file 84, sequencer 68, program counter 55. Everything below
hangs off its buses.

---

## 1. The pins the CPU exposes

Bring these signals out of the core (all TTL/CMOS logic levels):

| bus / signal | width | direction | meaning |
|---|---|---|---|
| `D0..D7`  | 8 | in/out | **data bus** — one word/byte |
| `A0..A7`  | 8 | out | **data-memory address** (256 bytes) |
| `PA0..PA7`| 8 | out | **program address** (Harvard, 256 instructions) |
| `PD0..PD15`| 16 | in | **program data** — the 2-byte instruction fetched |
| `CLK`     | 1 | in | the clock — one instruction per rising edge |
| `/RST`    | 1 | in | reset: PC→0, clear halt |
| `/WE`     | 1 | out | data-memory write strobe (STORE) |
| `/OE`     | 1 | out | data-memory read enable (LOAD) |
| `IO`      | 1 | out | I/O access (address in device window — see §6) |
| `HALT`    | 1 | out | the machine has stopped |

Data and program memory are **separate buses** (Harvard) — the CPU cannot write
its own program, exactly like the simulator. That is a feature: the program ROM
can be a plain ROM.

---

## 2. Clock

The CPU does exactly one instruction per clock edge, so the clock is just a
free-running oscillator into `CLK`. Everything edge-triggered (the program
counter, the register write, the RAM write strobe) fires on that edge.

- **Bring-up / debugging:** a **555 timer** wired astable at **1-10 Hz**, or a
  debounced push-button, so you can single-step and watch the buses on LEDs.
- **Running:** a **canned crystal oscillator** (a 4-pin half-can, e.g. 1-10 MHz)
  straight into `CLK`, or a crystal + `74HC04` inverter, or an MCU pin.
- Add a **RUN/STEP switch** that selects between the button and the oscillator —
  invaluable while building.
- `/RST`: a power-on reset (RC + Schmitt `74HC14`) and a reset button, both
  pulling `/RST` low to force PC = 0.

The one timing rule: the clock period must be longer than the slowest
combinational path (the ALU ripple through multiply/divide) **plus** the RAM
access time in §4. On a slow breadboard clock this is never a problem; it only
matters when you push the crystal fast.

---

## 3. RAM — the important one

Data memory is **256 bytes**: 256 words × 1 byte. Use a single asynchronous
**8-bit SRAM** — a `6116` (2K×8), `62256` (32K×8), or any byte-wide static RAM;
you only use the low 256 bytes.

Wiring is direct because the word is a byte and the address is a byte:

```
   CPU D0..D7  <---->  SRAM  I/O0..I/O7      (bidirectional data)
   CPU A0..A7   ---->  SRAM  A0..A7          (byte address)
   SRAM A8..    ---->  tie LOW (unused)
   CPU /WE      ---->  SRAM  /WE             (STORE strobe)
   CPU /OE      ---->  SRAM  /OE             (LOAD enable)
   GND          ---->  SRAM  /CE             (always selected)
```

- **Bidirectional bus:** on a LOAD the SRAM drives `D0..D7`; on a STORE the CPU
  drives them. `/OE` and `/WE` keep exactly one driver active at a time — never
  assert both. If your CPU's data-bus output is not tri-state, put a
  **`74HC245` transceiver** between CPU and RAM and steer its direction from
  `/WE` (write = CPU→RAM, else RAM→CPU).
- **Timing:** async SRAM returns data an access-time (≈55 ns) after the address
  is stable. Keep the clock period above that. On a LOAD, the address (`A0..A7`
  = the register `Rs`) is valid for the whole cycle, so the byte is back well
  before the edge that latches it into the register.
- The program ROM is the same idea on the *program* bus: a byte-wide ROM/EEPROM
  (e.g. `28C256`), `PA0..PA7`→ROM address, ROM data→`PD` — but 2 bytes per
  instruction, so either a 16-bit-wide ROM or two 8-bit ROMs side by side
  (one for the low byte `OP,SUB,DA,SA`, one for the high byte of the immediate).

---

## 4. A display

From simplest to richest:

**(a) HD44780 character LCD — recommended first display.**
A 16×2 or 20×4 text LCD speaks a simple 8-bit parallel protocol. Wire it to the
CPU's **output port** (the `OUT` instruction / the device window in §6):

```
   CPU D0..D7  ---->  LCD  DB0..DB7      (character or command byte)
   IO-strobe   ---->  LCD  E             (latch on the strobe)
   A0 (or a    ---->  LCD  RS            (0 = command, 1 = data/char)
     control bit)
   GND         ---->  LCD  R/W           (write only)
```

`OUT`-ing an ASCII byte makes that character appear. Two device addresses (one
with RS=0 for commands like "clear/home", one with RS=1 for characters) give you
a full text console the CPU drives directly, at whatever speed it runs. This is
the honest, buildable display for a gate CPU.

**(b) UART → your laptop.** Wire the output port to a `MAX232`/`FTDI`/`CH340`
and `OUT` bytes to a serial terminal. The "display" is your PC. Least wiring;
best for first-light bring-up.

**(c) VGA — a separate video subsystem, not a CPU job.** VGA needs a 25 MHz
pixel clock and continuous scan-out — thousands of times faster than the CPU.
Do it the way the simulator's GPU is a separate device: a **dual-port (or
time-shared) framebuffer RAM** the CPU writes character/pixel bytes into, plus
an **independent video timing generator** (counters + a character-ROM) that
scans that RAM out to R/G/B + HSync/VSync on its own clock. The CPU just writes
bytes; the video hardware runs itself. Build (a) first.

---

## 5. USB keyboard and mouse

**You do not bit-bang USB from a gate CPU.** USB is a 1.5-12 Mbit/s differential
protocol with enumeration, packets, handshakes and HID report parsing — many
orders of magnitude beyond a ~kHz, 1,852-gate byte machine. Every hobby CPU
solves this the same way: a small helper chip is the **USB host**, and it hands
the CPU **plain bytes**.

**Recommended bridge:** a cheap microcontroller running USB-host firmware —
a **Raspberry Pi Pico / RP2040** (TinyUSB host), an **ATmega32U4**, or a
purpose-made **CH9350** ("USB keyboard+mouse → serial/parallel") chip. The
bridge:

1. is the USB host: powers the port, enumerates the keyboard/mouse, polls them;
2. parses the HID reports;
3. presents the CPU with simple byte registers:
   - **keyboard:** the ASCII (or HID usage) code of the last key pressed, in a
     latch/queue, plus a "key ready" bit;
   - **mouse:** `dx`, `dy` (signed step) and a `buttons` byte, each in a latch.

The CPU reads these with a `LOAD` from an **input port** — exactly the model the
simulator already uses (its `Keyboard` is a byte queue at a bus port, its
`Mouse` is x/y/buttons bytes at ports). So the CPU side needs no USB knowledge
at all; it just reads bytes from device addresses.

```
   USB-A socket ── D+ D- ──►  [ RP2040 / CH9350 ]  ──►  8-bit latch ──► CPU D0..D7
   (keyboard/mouse)            USB host + HID parse       (KBD / MOUSE     on an
                                                           input ports)     IN read
```

One wiring note: the bridge and the CPU share the CPU's data bus through a
tri-state latch (`74HC374` + `/OE` from the I/O decoder), so the bridge only
drives the bus when the CPU reads its port.

**Small CPU-side extension needed:** the Q4 as written has an *output* port
(`OUT`). To read input you add symmetric **input ports** — either an `IN Rd,port`
instruction, or (cleaner, and matching the 32-bit machine) memory-map them: a
`LOAD` from a reserved high address returns the device byte. See §6.

---

## 6. Memory-mapped I/O (how devices attach)

The cleanest way to bolt on the display, keyboard and mouse — and exactly what
the 32-bit machine's bus does — is to **reserve the top of the 256-byte address
space for devices**. A small address comparator (a `74HC688` or a couple of
gates on `A4..A7`) raises the `IO` line when the address is in the device
window; then `LOAD`/`STORE` to those addresses hit a device instead of RAM.

A suggested map (mirrors the simulator's device ports):

| address | device | access |
|---|---|---|
| `0x00 – 0xEF` | data RAM (240 bytes) | LOAD / STORE |
| `0xF0` | display / UART out | STORE (byte → screen) |
| `0xF1` | display command (RS=0) | STORE |
| `0xF4` | keyboard data | LOAD (pops a key) |
| `0xF5` | keyboard status | LOAD (1 = key ready) |
| `0xF8` | mouse dx | LOAD |
| `0xF9` | mouse dy | LOAD |
| `0xFA` | mouse buttons | LOAD |

The decoder routes: address < `0xF0` → SRAM `/CE`; address ≥ `0xF0` → the matching
device's chip-select. STORE to `0xF0` strobes the LCD/UART latch; LOAD from
`0xF4` enables the keyboard latch onto the bus; and so on. Now the same `LOAD`
and `STORE` instructions the CPU already has reach every peripheral — no new
opcodes except, optionally, the input read.

---

## 7. Whole system, one picture

```
                         8-bit DATA BUS  (D0..D7 = one word = one byte)
   ┌───────────┬──────────────┬──────────────┬──────────────┬─────────────┐
   │           │              │              │              │             │
 ┌─┴───────┐  ┌┴────────┐   ┌─┴────────┐   ┌─┴───────────┐  │             │
 │ Q4 CORE │  │  SRAM   │   │  PROG ROM│   │  I/O DECODER│  │             │
 │ 1852    │  │ 256 B   │   │  512 B   │   │ (A4..A7 →   │  │             │
 │ gates   │  │ data    │   │ (Harvard)│   │  IO / /CE)  │  │             │
 │         │  └─────────┘   └────┬─────┘   └──┬───┬───┬──┘  │             │
 │  A0..A7 ├───────────────┐     │            │   │   │     │             │
 │  PA0..7 ├───────────────┼─────┘         ┌──┴┐ ┌┴─┐ ┌┴───┐│             │
 │  /WE /OE│               │               │LCD│ │KB│ │MOUSE││            │
 │  CLK /RST                               │/UART│ └┬─┘ └┬──┘│            │
 └──┬────┬─┘                               └───┘   │    │   │             │
    │    │                                      ┌──┴────┴───┴─┐           │
 ┌──┴─┐ ┌┴─────┐                                │ USB-HID     │           │
 │CLK │ │RESET │                                │ bridge MCU  │◄─ USB ────┤
 │osc │ │button│                                │ (RP2040/…)  │  keyboard │
 └────┘ └──────┘                                └─────────────┘  + mouse  │
```

Data RAM, program ROM and every device share the one 8-bit data bus; the I/O
decoder makes sure exactly one thing drives it per cycle. The clock and reset
sequence the core; the USB bridge turns keyboard/mouse into bytes the core reads
like memory.

---

## 8. Suggested bring-up order

1. **Core on a slow clock, LEDs on the buses.** 555 at 1 Hz, LEDs on `D0..D7`
   and `PA0..PA7`. Load the `sum` demo into the program ROM; watch the PC step
   and the accumulator climb to 55. This proves the CPU, clock and ROM.
2. **Add SRAM.** Run the `mem` demo (store 99, read it back). Proves the data
   bus, address bus and `/WE`//`/OE` timing.
3. **Add the LCD** on the output port. `OUT` an ASCII byte; see a character.
   Now you have a display.
4. **Add the USB bridge** last, as an input port. Echo keystrokes to the LCD —
   a one-line program (`LOAD` key, `STORE` to display) — and you have an
   interactive byte computer built from six gates.

Every step is independently testable, and each maps directly onto something the
simulator already does, so you can check the hardware against `python -m q4.test4`.
