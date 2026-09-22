"""The 4-quarter CPU (Q4): a minimal byte-wide gate machine.

Word = 4 quarters = 8 bits (0..255). Same six primitives, same gate-composed
datapath as the 32-bit machine, at a quarter of the width. The word ALU is
reused verbatim from words4 (generated at W=4); this file is the register-file
datapath, the instruction decode, and the sequencer.

Instruction = 8 quarters (two bytes): (OP, SUB, DA, SA, I0, I1, I2, I3)
  OP  : class    0 arith   1 logic   2 memory   3 control
  SUB : sub-op within the class
  DA  : destination register (0..3)      SA : source register (0..3)
  IMM = (I0,I1,I2,I3) : a 4-quarter immediate / address / jump target

ISA:
  arith  (0): ADD SUB MUL DIV        Rd = Rd op Rs
  logic  (1): MIN MAX MOD NOT        Rd = Rd op Rs
  memory (2): LOADI Rd,imm | LOAD Rd,Rs | STORE Rd,Rs | MOV Rd,Rs
              LOAD/STORE use Rs as the address: LOAD Rd,Rs is Rd = RAM[Rs];
              STORE Rd,Rs is RAM[Rs] = Rd.
  control(3): JMP a | JZ Rd,a | OUT Rd | HALT
"""

from .gates import Adr4, MAX, MIN, NOT
from .words4 import W_ALU, WSEL, WOR, WNZ, to_word, from_word
from .storage4 import RegFile4, RAM4, PC4, Port, ST

_OPS = {
    'ADD': (0, 0), 'SUB': (0, 1), 'MUL': (0, 2), 'DIV': (0, 3),
    'MIN': (1, 0), 'MAX': (1, 1), 'MOD': (1, 2), 'NOT': (1, 3),
    'LOADI': (2, 0), 'LOAD': (2, 1), 'STORE': (2, 2), 'MOV': (2, 3),
    'JMP': (3, 0), 'JZ': (3, 1), 'OUT': (3, 2), 'HALT': (3, 3),
}
_REGREG = {'ADD', 'SUB', 'MUL', 'DIV', 'MIN', 'MAX', 'MOD', 'LOAD', 'STORE', 'MOV'}


def asm(prog):
    """Assemble [(mnemonic, *args), ...] into 8-quarter instruction tuples."""
    code = []
    for line in prog:
        m = line[0]
        op, sub = _OPS[m]
        da = sa = imm = 0
        if m in _REGREG:
            da, sa = line[1], line[2]
        elif m in ('LOADI', 'JZ'):
            da, imm = line[1], line[2]
        elif m == 'NOT':
            da = line[1]
        elif m == 'JMP':
            imm = line[1]
        elif m == 'OUT':
            da = line[1]
        i0, i1, i2, i3 = to_word(imm)
        code.append((op, sub, da, sa, i0, i1, i2, i3))
    return code


class Machine4:
    """One byte-wide machine, steppable one instruction at a time."""

    def __init__(self, code):
        self.reg = RegFile4()
        self.ram = RAM4()
        self.pc = PC4()
        self.out = Port()
        self.halt = ST()
        self.code = list(code)        # Harvard instruction memory (an array)
        self.steps = 0

    @property
    def halted(self):
        return self.halt.run(0, 0) == 3

    def step(self):
        # ---- fetch (Harvard instruction memory) ----
        idx = from_word(self.pc.get())
        if idx >= len(self.code):     # ran off the end: stop (sequencer guard)
            self.halt.run(3, 3)
            return
        OP, SUB, DA, SA, I0, I1, I2, I3 = self.code[idx]
        imm = (I0, I1, I2, I3)

        Rd = self.reg.run(DA, 0)
        Rs = self.reg.run(SA, 0)
        Aa, Bb, Cc, Dd = Adr4(OP, 3)          # class: arith / logic / mem / ctrl

        # ---- arith + logic reuse the word ALU (it returns 0 for OP 2,3) ----
        flag, alu = W_ALU(Rd, Rs, OP, SUB)
        alu_en = MAX(Aa, Bb)

        # ---- memory class: LOADI / LOAD / STORE / MOV ----
        La, Lb, Lc, Ld = Adr4(SUB, Cc)
        memval = self.ram.run(Rs, 0)          # RAM[Rs]
        mem_wb = WOR(WOR(WSEL(La, imm), WSEL(Lb, memval)), WSEL(Ld, Rs))
        self.ram.run(Rs, Lc, Rd)              # STORE: RAM[Rs] = Rd
        mem_en = MAX(La, MAX(Lb, Ld))         # LOADI / LOAD / MOV write Rd

        # ---- writeback to Rd ----
        wb = WOR(WSEL(alu_en, alu), WSEL(mem_en, mem_wb))
        self.reg.run(DA, MAX(alu_en, mem_en), wb)

        # ---- control class: JMP / JZ / OUT / HALT ----
        Fa, Fb, Fc, Fd = Adr4(SUB, Dd)
        rd_zero = NOT(WNZ(Rd))                # 3 if Rd == 0
        take = MAX(Fa, MIN(Fb, rd_zero))      # JMP always, JZ if Rd == 0
        self.out.write(Rd, Fc)                # OUT
        self.halt.run(3, Fd)                  # HALT

        # ---- PC: jump to imm when taken, else advance by one ----
        self.pc.update(take, I0, I1, I2, I3)
        self.steps += 1

    def run(self, max_steps=100000):
        while not self.halted and self.steps < max_steps:
            self.step()
        return self


# --- demo programs ---------------------------------------------------------

DEMOS = {
    # sum 1..10 = 55
    'sum': [
        ('LOADI', 0, 0),      # 0: R0 = 0            accumulator
        ('LOADI', 1, 10),     # 1: R1 = 10           counter
        ('LOADI', 3, 1),      # 2: R3 = 1            constant
        ('ADD', 0, 1),        # 3: R0 += R1     <-- loop
        ('SUB', 1, 3),        # 4: R1 -= 1
        ('JZ', 1, 7),         # 5: if R1 == 0 goto 7
        ('JMP', 3),           # 6: goto 3
        ('OUT', 0),           # 7: output R0 (= 55)
        ('HALT',),            # 8
    ],
    # 6 * 7 = 42, straight through the byte-wide multiplier
    'mul': [
        ('LOADI', 0, 6),
        ('LOADI', 1, 7),
        ('MUL', 0, 1),
        ('OUT', 0),
        ('HALT',),
    ],
    # store 99 to RAM[5], read it back, output it
    'mem': [
        ('LOADI', 0, 99),     # R0 = 99   (data)
        ('LOADI', 1, 5),      # R1 = 5    (address)
        ('STORE', 0, 1),      # RAM[R1=5] = R0=99
        ('LOADI', 0, 0),      # clobber R0
        ('LOAD', 0, 1),       # R0 = RAM[R1=5]
        ('OUT', 0),           # 99
        ('HALT',),
    ],
}


def run_demo(name):
    m = Machine4(asm(DEMOS[name])).run()
    outs = [from_word(w) for w in m.out.log]
    print(f'{name:5s}: output {outs}  ({m.steps} instructions)')
    return outs


if __name__ == '__main__':
    for name in DEMOS:
        run_demo(name)
