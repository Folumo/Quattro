FRAME = 16  # quaternary slots per instruction (must match quattro.words.FRAME)

# `.string "a\n"` used to store a backslash and an 'n' -- three characters where
# the author meant two, and a newline that printed as literal \n. The C compiler
# has always decoded these (ccompiler._ESCAPES); the assembler never did.
_ESCAPES = {'n': 10, 't': 9, 'r': 13, '0': 0, '\\': 92, '"': 34, "'": 39}


def unescape(s):
    """A quoted .string body -> the character codes it denotes."""
    out, i = [], 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            if s[i + 1] not in _ESCAPES:
                raise ValueError(f"unknown escape in string: \\{s[i + 1]}")
            out.append(_ESCAPES[s[i + 1]])
            i += 2
        else:
            out.append(ord(s[i]))
            i += 1
    return out


def compile_asm(asm_code, return_labels=False, data_base=0, code_base=0):
    """
    ASM compiler for the base-4 word machine.

    Instruction frame (12 quaternary slots):
        [OP] [SUB] [RNF0] [RNF1] [D0] [D1] [A0] [A1] [B0] [B1] [C2] [C3]

      OP   : class   0=arith, 1=logic, 2=code, 3=functions
      SUB  : sub-op within the class (see table below)
      RNF0 : operand-1 source   0=var reg, 1=flag reg, 2=immediate
      RNF1 : operand-2 source
      DEST = (D0,D1) : destination register 0..15; tested reg for JCMP family
      SRCA = (A0,A1) : operand-1 register 0..15
      SRCB = (B0,B1) : operand-2 register 0..15
      IMM  = (A0,A1,B0,B1)  : immediate word (0..255), little-endian
      TARGET = (B0,B1,C2,C3): jump target address (0..255), little-endian

    Registers R0..R15 map to (Adr0 = n%4, Adr1 = n//4); R0..R3 keep their
    original (n, 0) addresses.

    Sub-ops:
      arith (0): ADD=0 SUB=1 MUL=2 DIV=3
      logic (1): MIN=0 MAX=1 MOD=2 NOT=3
      code  (2): LOAD=0 STORE=1 COPY=2 HLT=3
      func  (3): CALL=0 JMP=1 JCMP=2 RET=3

    Memory / move (RNF1 selects LOAD's source: 2 = immediate, 3 = memory):
      LOAD  Rd, imm     Rd = imm (0..255)
      LOAD  Rd, [Ra]    Rd = MEM[R(Ra)]        (data memory, register-indirect)
      STORE [Ra], Rs    MEM[R(Ra)] = R(Rs)
      COPY  Rd, Rs      Rd = R(Rs)

    Control flow:
      JMP  target / JMP  Rn          (Rn = register-indirect)
      CALL target / CALL Rn
      JCMP Rc, target      jump if Rc != 0
      JZ   Rc, target      jump if Rc == 0
      JEQ  Ra, Rb, target  jump if Ra == Rb
      JLT  Ra, Rb, target  jump if Ra <  Rb
      RET
    A `target` is a label (`name:` line) or a raw address 0..255.

    Sections and data:
      .text                 code section (default)
      .data                 data section (preloaded into data memory)
      label: .string "..."  null-terminated ASCII string; label = its address
      label: .byte 1, 2, 3  raw byte values
    A data label used as an immediate (e.g. LOAD R0, msg) gives its address.
    """

    REG = 0  # operand from a var register
    IMM = 2  # operand is an immediate word

    instructions = {
        'ADD': (0, 0), 'SUB': (0, 1), 'MUL': (0, 2), 'DIV': (0, 3),
        'MIN': (1, 0), 'MAX': (1, 1), 'MOD': (1, 2), 'NOT': (1, 3),
        'LOAD': (2, 0), 'STORE': (2, 1), 'COPY': (2, 2), 'HLT': (2, 3),
        'CALL': (3, 0), 'JMP': (3, 1), 'RET': (3, 3),
        'JCMP': (3, 2), 'JZ': (3, 2), 'JEQ': (3, 2), 'JLT': (3, 2),
    }
    JCMP_COND = {'JCMP': 0, 'JZ': 1, 'JEQ': 2, 'JLT': 3}

    def reg(tok):
        n = int(tok[1:])  # 'R7' -> 7
        if not 0 <= n <= 15:
            raise ValueError(f"register out of range (R0..R15): {tok}")
        return (n % 4, n // 4)  # (Adr0, Adr1)

    def is_reg(tok):
        return len(tok) >= 2 and tok[0] in 'Rr' and tok[1:].isdigit()

    def is_mem(tok):
        return tok.startswith('[') and tok.endswith(']')

    def mem_reg(tok):
        return reg(tok[1:-1])  # '[R2]' -> reg('R2')

    def word(n):
        n = int(n)
        if not 0 <= n <= 255:
            raise ValueError(f"value out of range (0..255): {n}")
        return (n % 4, (n // 4) % 4, (n // 16) % 4, (n // 64) % 4)

    def word20(n):
        # LOAD's immediate spans 10 quarters (A0,A1,B0,B1 + the C2..C7 slots a
        # LOAD doesn't otherwise use), so one LOAD Rd, N carries 0..1048575.
        n = int(n)
        if not 0 <= n <= 1048575:
            raise ValueError(f"immediate out of range (0..1048575): {n} "
                             "(load a larger value from a .word constant pool)")
        return tuple((n // (4 ** k)) % 4 for k in range(10))

    def addr8(n):  # an 8-quarter code address (instruction index), 0..65535
        n = int(n)
        if not 0 <= n <= 65535:
            raise ValueError(f"code address out of range (0..65535): {n}")
        return tuple((n // (4 ** k)) % 4 for k in range(8))

    def frame(op, sub, rnf0=0, rnf1=0,
              dest=(0, 0), srca=(0, 0), srcb=(0, 0), c=(0, 0, 0, 0, 0, 0)):
        return (op, sub, rnf0, rnf1, dest[0], dest[1], srca[0], srca[1],
                srcb[0], srcb[1], c[0], c[1], c[2], c[3], c[4], c[5])

    def strip_comment(s):
        # drop a '--' comment, but not one inside a quoted string
        q = False
        for i, ch in enumerate(s):
            if ch == '"':
                q = not q
            elif not q and s[i:i + 2] == '--':
                return s[:i]
        return s

    # --- pass 1: collect labels, the data image, and the instruction lines.
    # A label resolves to a final number: a code label to its instruction index
    # (code memory is one wide cell per instruction), a data label to its
    # data-memory address.
    program = []       # token-lists, one per code instruction
    labels = {}        # name -> resolved number
    data_image = {}    # data address -> value (preloaded into data memory)
    section = 'text'
    data_ptr = data_base   # C toolchain sets this >=256 to clear the device window
    for raw in asm_code.split('\n'):
        line = strip_comment(raw).strip()
        if not line:
            continue
        low = line.lower()
        if low == '.text':
            section = 'text'
            continue
        if low == '.data':
            section = 'data'
            continue
        if line.endswith(':'):
            name = line[:-1].strip()
            if name in labels:
                # Last-one-wins would silently retarget every jump to the first
                # one -- a duplicated label is always a mistake, never a intent.
                raise ValueError(f"duplicate label: {name!r}")
            # a code label is an instruction index; `code_base` is the index the
            # program will be LOADED at, so a boot ROM can place it above itself
            labels[name] = data_ptr if section == 'data' else len(program) + code_base
            continue
        if section == 'data':
            if low.startswith('.string'):
                a, b = line.find('"'), line.rfind('"')
                for code in unescape(line[a + 1:b]):
                    data_image[data_ptr] = code
                    data_ptr += 1
                data_image[data_ptr] = 0   # null terminator
                data_ptr += 1
            elif low.startswith('.byte'):
                for tok in line[5:].replace(',', ' ').split():
                    data_image[data_ptr] = int(tok)
                    data_ptr += 1
            else:
                raise ValueError(f"unknown data directive: {line}")
            continue
        program.append(line.replace(',', ' ').split())

    def resolve(tok):
        return labels[tok] if tok in labels else int(tok)

    def imm_value(tok):
        # an immediate is a number, or a label resolved to its address.
        # <x is the low byte (x % 256), >x is the high part (x // 256) -- so a
        # full code address (0..4095) fits in a register pair: LOAD lo, <lbl /
        # LOAD hi, >lbl / JMP lo, hi.
        if tok and tok[0] == '<':
            return resolve(tok[1:]) % 256
        if tok and tok[0] == '>':
            return resolve(tok[1:]) // 256
        return resolve(tok)

    def target(tok):
        d = addr8(imm_value(tok))
        return (d[0], d[1]), (d[2], d[3], d[4], d[5], d[6], d[7])   # B0,B1 + C2..C7

    # --- pass 2: emit frames
    machine_code = []
    for parts in program:
        op = parts[0].upper()
        if op not in instructions:
            raise ValueError(f"Unknown instruction: {op}")
        instr0, instr1 = instructions[op]

        if op in ('HLT', 'RET'):
            f = frame(instr0, instr1)

        elif op == 'LOAD':
            if is_mem(parts[2]):
                # LOAD Rd, [Ra]  -> Rd = MEM[R(Ra)]   (RNF1 = 3 selects memory)
                f = frame(instr0, instr1, rnf1=3,
                          dest=reg(parts[1]), srca=mem_reg(parts[2]))
            else:
                # LOAD Rd, imm  -> Rd = imm (0..1048575); may be a label address
                d = word20(imm_value(parts[2]))
                f = frame(instr0, instr1, rnf1=IMM, dest=reg(parts[1]),
                          srca=(d[0], d[1]), srcb=(d[2], d[3]),
                          c=(d[4], d[5], d[6], d[7], d[8], d[9]))

        elif op in ('ADD', 'SUB', 'MUL', 'DIV', 'MIN', 'MAX', 'MOD'):
            # OP Rd, Rs   -> Rd = Rd OP Rs
            rd = reg(parts[1])
            f = frame(instr0, instr1, rnf0=REG, rnf1=REG,
                      dest=rd, srca=rd, srcb=reg(parts[2]))

        elif op == 'NOT':
            rd = reg(parts[1])
            f = frame(instr0, instr1, rnf0=REG, dest=rd, srca=rd)

        elif op == 'COPY':
            # COPY Rd, Rs   -> Rd = Rs
            f = frame(instr0, instr1, rnf0=REG,
                      dest=reg(parts[1]), srca=reg(parts[2]))

        elif op == 'STORE':
            # STORE [Ra], Rs  -> MEM[R(Ra)] = R(Rs)
            f = frame(instr0, instr1,
                      srca=mem_reg(parts[1]), srcb=reg(parts[2]))

        elif op in ('JMP', 'CALL'):
            if len(parts) >= 3 and is_reg(parts[1]) and is_reg(parts[2]):
                # JMP Rlo, Rhi -- full address from a register pair (0..4095)
                f = frame(instr0, instr1, rnf0=REG, rnf1=1,
                          srca=reg(parts[1]), srcb=reg(parts[2]))
            elif is_reg(parts[1]):          # JMP Rn -- single register (0..255)
                f = frame(instr0, instr1, rnf0=REG, srca=reg(parts[1]))
            else:                           # JMP label / immediate (direct)
                srcb, c = target(parts[1])
                f = frame(instr0, instr1, rnf0=IMM, srcb=srcb, c=c)

        elif op in ('JCMP', 'JZ'):
            # cond Rc, target
            srcb, c = target(parts[2])
            f = frame(instr0, instr1, rnf1=JCMP_COND[op],
                      dest=reg(parts[1]), srcb=srcb, c=c)

        elif op in ('JEQ', 'JLT'):
            # cond Ra, Rb, target
            srcb, c = target(parts[3])
            f = frame(instr0, instr1, rnf1=JCMP_COND[op],
                      dest=reg(parts[1]), srca=reg(parts[2]), srcb=srcb, c=c)

        machine_code.append(f)

    if return_labels:
        return machine_code, data_image, labels
    return machine_code, data_image
