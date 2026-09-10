"""
Quattro -- a base-4 (quaternary) computer built entirely from single-digit
gate primitives, simulated in Python.

The package is layered bottom-up; each module is built only from the ones above
it, and the machine core is gate-pure (checked by ``python purity_check.py``):

    gates    -- MIN/MAX/NOT/COM/MOD/EQ, the address decoders, the half-gates
    words    -- word encode/decode + the word ALU (WADD..W_ALU)
    storage  -- ST cell, VecMem memory macro, register file, data RAM, code
                memory (RAM6), counters, stack
    devices  -- Console/Keyboard/Timer/Mouse/Disk (the "outside world")
    bus      -- address decode + interconnect + control latches
    cpu      -- branch-free gate-select instruction decode/execute
    machine  -- the whole computer wired together (Machine, run_machine)

--------------------------------------------------------------------------- ISA

Instruction frame (16 quaternary slots):
    [OP][SUB][RNF0][RNF1][D0][D1][A0][A1][B0][B1][C2][C3][C4][C5][C6][C7]

    DEST = (D0,D1)  SRCA = (A0,A1)  SRCB = (B0,B1)   -- registers R0..R15
    IMM  = (A0,A1,B0,B1,C2..C7)   immediate 0..1048575 (a LOAD doesn't use C2+)
    TARGET = (B0,B1,C2..C7)       jump address = an instruction index, 0..65535
                                  (code memory is one 16-slot cell per
                                  instruction; the PC is an 8-digit counter)

RNF operand source:  0 -> var reg (R0..R15)   1 -> flag reg
                     2 -> immediate           3 -> data memory (LOAD only)

OP / SUB:
    0 0 ADD    0 1 SUB     0 2 MUL     0 3 DIV
    1 0 MIN    1 1 MAX     1 2 MOD     1 3 NOT
    2 0 LOAD   2 1 STORE   2 2 COPY    2 3 HLT
    3 0 CALL   3 1 JMP     3 2 JCMP    3 3 RET     (JCMP: JZ/JEQ/JLT via RNF1)

Jumps: JMP/CALL label reach 0..4095 directly. JMP Rn is a single-register
indirect (0..255); JMP Rlo, Rhi is a register-PAIR indirect reaching 0..4095
(target = R(lo) low word + R(hi) high quarters). The assembler's <label /
>label give a label's low byte / high part.

Memory map (data address space, via LOAD/STORE through the bus). Devices occupy
229..287; RAM is 0..228 (zero page) and 288.. upward (BigRAM, demand-paged):
  0..228 data RAM                229 MOUSE_X   230 MOUSE_Y   231 MOUSE_BTN
  232 SYSCALL     233 IRQ_CAUSE  234 SYSARG     235 CTX_SEL   236 CTX_SETPC
  237 CTX_SETPC_HI 238 INT_VECTOR_HI 239 SYSARG_HI 240 DISK_SECTOR
  241 DISK_DATA   242 DISK_STATUS 243 SCHED_CUR 244 SCHED_N   245 SCHED_RESUME
  248 TIMER_PERIOD 249 TIMER_CTRL 250 KBD_DATA  251 KBD_STATUS
  252 CON_OUT     253 CON_CTRL   254 INT_ENABLE 255 INT_VECTOR
  256..287 GPU register window -- a command-driven blitter:
      256 CMD  257 X  258 Y  259 W  260 H  261 COLOR  262 ADDR  263 X2  264 Y2
      265 MOUSE_X  266 MOUSE_Y  267 BUTTONS  268 STATUS
    Write CMD to run it against the current registers: 0 CLEAR, 1 PIXEL,
    2 RECT, 3 FRAME, 4 LINE, 5 CIRCLE, 6 TEXT (DMAs the string at ADDR),
    7 BLIT (DMAs a W*H sprite at ADDR). 256x192 pixels, 16-colour palette.
    The CPU is far too slow to paint pixels itself, so the device does it.

An interrupt pushes the PC and vectors to INT_VECTOR (like a hardware CALL); it
stays masked until the handler's RET returns, then auto-re-enables. Boot: reset
PC = 0 = the BIOS ROM (asm/bios.asm), which jumps to the user program at label
'main' and provides print_char / read_key at fixed entry points.
"""

from .gates import MIN, MAX, NOT, COM, MOD, EQ, Adr4, Adr16
from .words import (to_word, from_word, ZERO_WORD, ONE_WORD, FRAME, WSEL, WOR,
                    WADD, WSUB, WMUL, WDIV, WGE, W_ALU)
from .storage import RAM6, WREG16, BigRAM, RSTACK
from .devices import Console, Keyboard, Timer, Mouse, Disk, GPU
from .bus import Latch, Reg, Bus
from .cpu import CPU
from .machine import Machine, run_machine, dump, _addr8

__all__ = [
    "MIN", "MAX", "NOT", "COM", "MOD", "EQ", "Adr4", "Adr16",
    "to_word", "from_word", "ZERO_WORD", "ONE_WORD", "FRAME", "WSEL", "WOR",
    "WADD", "WSUB", "WMUL", "WDIV", "WGE", "W_ALU",
    "RAM6", "WREG16", "BigRAM", "RSTACK",
    "Console", "Keyboard", "Timer", "Mouse", "Disk", "GPU",
    "Latch", "Reg", "Bus", "CPU",
    "Machine", "run_machine", "dump", "_addr8",
]
