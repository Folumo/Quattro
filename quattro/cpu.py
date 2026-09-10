"""The CPU: branch-free gate-select instruction decode and execute."""

from .gates import Adr4, EQ, MAX, MIN, NOT
from .words import WOR, WSEL, WSUB, WEQ, WNZ, W_ALU
from .storage import WREG16

class CPU:
    """
    Word-wide CPU. Instruction frame is 14 quaternary slots:
        (OP, SUB, RNF0, RNF1, D0, D1, A0, A1, B0, B1, C2, C3, C4, C5)
      OP, SUB : opcode class and sub-op
      RNF0/1  : operand source (0 = var reg, 1 = flag reg, 2 = immediate)
      DEST = (D0,D1) : destination register (0..15); tested reg for JCMP-family
      SRCA = (A0,A1) : operand-1 register (0..15)
      SRCB = (B0,B1) : operand-2 register (0..15)
      IMM  = (A0,A1,B0,B1)   : immediate word (0..255) when a source is immediate

    For functions (OP == 3):
      JMP / CALL : target = 6-quarter code address (B0,B1,C2,C3,C4,C5), 0..4095;
                   or register R(A0,A1) when RNF0 == 0 (register-indirect, so
                   limited to 0..255); RNF0 == 2 selects the immediate target.
      JCMP-family: RNF1 = condition (0 = Ra!=0, 1 = Ra==0, 2 = Ra==Rb, 3 = Ra<Rb)
                   with Ra = R(D0,D1), Rb = R(A0,A1); target = (B0..C5).
      RET        : no operands.
    """

    def __init__(self, varReg: WREG16, flagReg: WREG16,
                 ram=None, stack=None, bus=None):
        self.var_reg = varReg
        self.flg_reg = flagReg
        self.ram = ram      # RAM6, so we can steer the program counter
        self.stack = stack  # RSTACK, for CALL / RET
        self.bus = bus      # Bus (RAM + memory-mapped devices), for LOAD/STORE

    def _operand(self, mode, a0, a1, imm):
        rv = self.var_reg.run(a0, a1, 0)
        fv = self.flg_reg.run(a0, a1, 0)
        return WOR(WOR(WSEL(EQ(mode, 0), rv),
                       WSEL(EQ(mode, 1), fv)),
                   WSEL(EQ(mode, 2), imm))

    def run(self, OP, SUB, RNF0=0, RNF1=0, D0=0, D1=0, A0=0, A1=0,
            B0=0, B1=0, C2=0, C3=0, C4=0, C5=0, C6=0, C7=0):
        # Pure gate-select execution: every unit computes every cycle, and the
        # class/sub-op decode lines gate which results are actually written --
        # exactly how the parallel hardware behaves. Words are WORD_QUARTERS
        # wide; the immediate occupies the low four quarters, the rest zero.
        Aa, Bb, Cc, Dd = Adr4(OP, 3)  # class lines: arith / logic / code / func
        # Immediate spans the low 10 quarters (A0,A1,B0,B1 + the C2..C7 slots a
        # LOAD doesn't use), so LOAD Rd, N carries 0..1048575 in one instruction.
        imm = (A0, A1, B0, B1, C2, C3, C4, C5, C6, C7, 0, 0, 0, 0, 0, 0)

        V1 = self._operand(RNF0, A0, A1, imm)
        V2 = self._operand(RNF1, B0, B1, imm)

        # arithmetic / logic: R(DEST) = ALU result, and store the arith flag
        flag, VAL0 = W_ALU(V1, V2, OP, SUB)
        self.var_reg.run(D0, D1, MAX(Aa, Bb), VAL0)
        self.flg_reg.run(D0, D1, Aa,
                         (flag, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))

        # code class: LOAD / STORE / COPY / HLT
        La, Lb, Lc, Ld = Adr4(SUB, Cc)
        mem = EQ(RNF1, 3)             # LOAD's source is data memory when RNF1=3

        # LOAD Rd, [Ra]: strobe a bus read at address R(SRCA) (a full word)
        adw = self.var_reg.run(A0, A1, 0)
        rd_en = MIN(La, mem)
        mword = self.bus.read(adw, rd_en)
        self.var_reg.run(D0, D1, rd_en, mword)

        # LOAD Rd, #imm (or reg/flag source): R(DEST) = V2
        self.var_reg.run(D0, D1, MIN(La, NOT(mem)), V2)

        # STORE [Ra], Rs: strobe a bus write of R(SRCB); the same register-file
        # port also carries the high half of a register-pair jump target below.
        rB = self.var_reg.run(B0, B1, 0)
        self.bus.write(adw, rB, Lb)

        # COPY: R(DEST) = V1
        self.var_reg.run(D0, D1, Lc, V1)

        # HLT: raise the halt flag at (3, 3)
        self.flg_reg.run(3, 3, Ld,
                         (3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))

        # functions (OP == 3): control flow. Dd is the func-class line.
        Fa, Fb, Fc, Fd = Adr4(SUB, Dd)  # CALL / JMP / JCMP / RET

        # JCMP-family condition, selected by RNF1: Ra!=0 / Ra==0 / Ra==Rb / Ra<Rb
        ra = self.var_reg.run(D0, D1, 0)   # Ra = R(DEST)
        rb = self.var_reg.run(A0, A1, 0)   # Rb = R(SRCA)
        ranz = WNZ(ra)                     # 3 if Ra != 0
        raz = NOT(ranz)                    # 3 if Ra == 0
        weq = WEQ(ra, rb)                  # 3 if Ra == Rb
        bw, DIF = WSUB(ra, rb)
        wlt = EQ(bw, 1)                    # 3 if Ra < Rb (subtraction borrowed)
        K0, K1, K2, K3 = Adr4(RNF1, 3)
        take = MAX(MAX(MIN(K0, ranz), MIN(K1, raz)),
                   MAX(MIN(K2, weq), MIN(K3, wlt)))

        # CALL/JMP target mux: immediate / single register / register pair.
        # The target is a 6-quarter code address (instruction index); it comes
        # from the low quarters of R(SRCA), with R(SRCB) supplying the pair's top.
        Limm = EQ(RNF0, 2)
        Lreg = NOT(Limm)
        Lpair = MIN(EQ(RNF1, 1), Lreg)
        rb0, rb1, rb2, rb3, *_ = rb
        h0, h1, h2, h3, *_ = rB
        jt0 = MAX(MIN(Limm, B0), MIN(Lreg, rb0))
        jt1 = MAX(MIN(Limm, B1), MIN(Lreg, rb1))
        jt2 = MAX(MIN(Limm, C2), MIN(Lreg, rb2))
        jt3 = MAX(MIN(Limm, C3), MIN(Lreg, rb3))
        jt4 = MAX(MIN(Limm, C4), MIN(Lpair, h0))
        jt5 = MAX(MIN(Limm, C5), MIN(Lpair, h1))
        jt6 = MAX(MIN(Limm, C6), MIN(Lpair, h2))
        jt7 = MAX(MIN(Limm, C7), MIN(Lpair, h3))

        # Where the PC goes: CALL/JMP -> jt, JCMP(taken) -> immediate target,
        # RET -> the popped return address.
        Ljmp = MAX(Fa, Fb)
        Ltake = MIN(Fc, take)
        p0, p1, p2, p3, p4, p5, p6, p7 = self.stack.pop(Fd)
        n0 = MAX(MAX(MIN(Ljmp, jt0), MIN(Ltake, B0)), MIN(Fd, p0))
        n1 = MAX(MAX(MIN(Ljmp, jt1), MIN(Ltake, B1)), MIN(Fd, p1))
        n2 = MAX(MAX(MIN(Ljmp, jt2), MIN(Ltake, C2)), MIN(Fd, p2))
        n3 = MAX(MAX(MIN(Ljmp, jt3), MIN(Ltake, C3)), MIN(Fd, p3))
        n4 = MAX(MAX(MIN(Ljmp, jt4), MIN(Ltake, C4)), MIN(Fd, p4))
        n5 = MAX(MAX(MIN(Ljmp, jt5), MIN(Ltake, C5)), MIN(Fd, p5))
        n6 = MAX(MAX(MIN(Ljmp, jt6), MIN(Ltake, C6)), MIN(Fd, p6))
        n7 = MAX(MAX(MIN(Ljmp, jt7), MIN(Ltake, C7)), MIN(Fd, p7))
        load_en = MAX(MAX(Ljmp, Ltake), Fd)

        # CALL pushes the return address before the PC is loaded.
        g0, g1, g2, g3, g4, g5, g6, g7 = self.ram.get_pc()
        self.stack.push(Fa, g0, g1, g2, g3, g4, g5, g6, g7)
        self.ram.set_pc(load_en, n0, n1, n2, n3, n4, n5, n6, n7)
