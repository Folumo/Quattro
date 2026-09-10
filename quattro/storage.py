"""Storage: the ST cell, the vectorized memory primitive (VecMem), the word
register file (WREG16), data memory (BigRAM), code memory (RAM6), the program
counters (COUNTER*), and the call stack (RSTACK).

Every VecMem address must have exactly as many digits as the macro was built
with. It used to truncate a longer one silently, which is how a 256-word memory
can quietly answer to a 32-bit address -- the aliasing bug you would then spend
a day finding. It raises now."""

import numpy as np

from .gates import Adr4, EQ, HF_ADDER, MAX, MIN, MOD
from .words import WORD_QUARTERS

class ST:
    def __init__(self):
        self.inValue = 0

    def run(self, Val, Set):
        if Set > 0:
            self.inValue = Val

        return self.inValue


class VecMem:
    """Addressable word memory, treated as a storage primitive (like an SRAM or
    register-file macro in a real cell library -- not synthesized from datapath
    gates). Holds `n` words of `width` quarters each, addressed by `ndig` base-4
    digits.

    Read and write are still the one-hot gate mux -- MIN / MAX / EQ / NOT -- but
    evaluated over every cell at once with numpy: exactly the parallel logic a
    hardware memory's address decoder + sense array performs in a single step,
    instead of the Python-serial walk over 4**ndig cells that the old RAM
    hierarchy did. Same gates, same result, ~50x faster per access.

        select   sel[r]  = MIN over digits of EQ(row_digit, addr_digit)   (0 or 3)
        write    cell    = MAX(MIN(NOT sel, cell), MIN(sel, newword))
        read     out[d]  = MAX over rows of MIN(sel[r], cell[r][d])
    """

    def __init__(self, n, width, ndig):
        self.n = n
        self.width = width
        self.cells = np.zeros((n, width), dtype=np.int16)
        rows = np.arange(n, dtype=np.int64)
        # The address-plane stack: planes[k][r] is the k-th base-4 digit of row
        # index r. One (ndig, n) array rather than a list, so comparing an
        # address against every row is a single vectorized op.
        self.planes = np.array([((rows // (4 ** k)) % 4) for k in range(ndig)],
                               dtype=np.int16)
        # Scratch held across accesses: the decoder and sense array are physical
        # things in a real macro, not something reallocated on every read.
        self._addr = np.zeros((ndig, 1), dtype=np.int16)
        self._sel_buf = np.zeros(n, dtype=np.int16)
        self._mux = np.zeros((n, width), dtype=np.int16)

    def _sel(self, addr):
        # sel[r] = MIN over digits of EQ(row_digit, addr_digit), as 3 or 0.
        # MIN-over-digits of a 3/0 EQ is exactly "every digit matched", which is
        # what .all() computes -- one pass over the plane stack, not one per digit.
        self._addr[:, 0] = addr
        np.multiply((self.planes == self._addr).all(axis=0), 3,
                    out=self._sel_buf, casting='unsafe')
        return self._sel_buf

    def access(self, addr, write_en, word=None):
        # write_en is the strobe (write when > 0, like an ST cell); the read mux
        # runs every time, so a write-then-read of the same address (as the
        # register file does in one call) returns the freshly written value.
        col = self._sel(addr)[:, None]
        if write_en > 0:
            # cell = MAX(MIN(NOT sel, cell), MIN(sel, newword)), evaluated in
            # place: sel is one-hot, so this clears the selected row and drops
            # the new word into it, leaving every other row untouched.
            np.minimum(3 - col, self.cells, out=self.cells)
            np.maximum(self.cells,
                       np.minimum(col, np.asarray(word, np.int16)),
                       out=self.cells)
        np.minimum(col, self.cells, out=self._mux)
        return tuple(self._mux.max(axis=0).tolist())



class RAM6:
    """Code memory: one word per instruction, Harvard-split from data RAM. Each
    cell holds a whole 16-slot instruction frame, addressed by the 8-digit
    program counter, so a fetch is ONE wide memory read -- not sixteen
    single-digit reads -- and the counter advances by exactly one instruction
    per fetch (its reliable +1 step). Jump targets and the PC are instruction
    indices, 0..65535."""

    def __init__(self, size):
        self.mem = VecMem(size, 16, 8)
        self.C = COUNTER8()

    def load(self, a0, a1, a2, a3, a4, a5, a6, a7, *instr):
        # load port: write a whole instruction frame at an index (Set wired high)
        self.mem.access((a0, a1, a2, a3, a4, a5, a6, a7), 3, instr)

    def fetch(self):
        p = self.C.run(0, 0, 0, 0, 0, 0, 0, 0)   # current instruction index
        instr = self.mem.access(p, 0)            # one wide read of the frame
        self.C.run(1, 0, 0, 0, 0, 0, 0, 0)       # step to the next instruction
        return instr

    def get_pc(self):
        return self.C.run(0, 0, 0, 0, 0, 0, 0, 0)

    def set_pc(self, En, a0, a1, a2, a3, a4, a5, a6, a7):
        # Load the program counter when En is asserted (JMP/CALL/RET/interrupt).
        self.C.run(0, 0, 0, 0, 0, 0, 0, 0, En, a0, a1, a2, a3, a4, a5, a6, a7)


class COUNTER:
    def __init__(self):
        self.inValue = ST()

    def run(self, ADD, Load=0, LoadVal=0):
        val = self.inValue.run(0, 0)
        NEXT, NEW = HF_ADDER(val, ADD)

        # Load path: when Load is asserted, jam LoadVal in instead of ADDing.
        # This is what lets a JMP/CALL set the program counter to any address.
        ld = MIN(1, Load)
        result = MAX(MIN(EQ(ld, 1), LoadVal), MIN(EQ(ld, 0), NEW))

        return NEXT, self.inValue.run(result, 3)


class COUNTER3:
    def __init__(self):
        self.c1 = COUNTER()
        self.c2 = COUNTER()
        self.c3 = COUNTER()

    def run(self, add0, add1, add2, Load=0, L0=0, L1=0, L2=0):
        carry1, val1 = self.c1.run(add0, Load, L0)
        carry2, val2 = self.c2.run(MAX(carry1, add1), Load, L1)
        carry3, val3 = self.c3.run(MAX(carry2, add2), Load, L2)

        return val1, val2, val3


class COUNTER4:
    """Four-digit counter (0..255): the program counter for the 256-cell RAM4."""

    def __init__(self):
        self.c1 = COUNTER()
        self.c2 = COUNTER()
        self.c3 = COUNTER()
        self.c4 = COUNTER()

    def run(self, a0, a1, a2, a3, Load=0, L0=0, L1=0, L2=0, L3=0):
        carry1, v1 = self.c1.run(a0, Load, L0)
        carry2, v2 = self.c2.run(MAX(carry1, a1), Load, L1)
        carry3, v3 = self.c3.run(MAX(carry2, a2), Load, L2)
        carry4, v4 = self.c4.run(MAX(carry3, a3), Load, L3)

        return v1, v2, v3, v4


class COUNTER5:
    """Five-digit counter (0..1023)."""

    def __init__(self):
        self.c1 = COUNTER()
        self.c2 = COUNTER()
        self.c3 = COUNTER()
        self.c4 = COUNTER()
        self.c5 = COUNTER()

    def run(self, a0, a1, a2, a3, a4, Load=0, L0=0, L1=0, L2=0, L3=0, L4=0):
        carry1, v1 = self.c1.run(a0, Load, L0)
        carry2, v2 = self.c2.run(MAX(carry1, a1), Load, L1)
        carry3, v3 = self.c3.run(MAX(carry2, a2), Load, L2)
        carry4, v4 = self.c4.run(MAX(carry3, a3), Load, L3)
        carry5, v5 = self.c5.run(MAX(carry4, a4), Load, L4)

        return v1, v2, v3, v4, v5


class COUNTER8:
    """Eight-digit counter (0..65535): the program counter. It counts whole
    instructions, so the machine can hold 65536 of them."""

    def __init__(self):
        self.c1 = COUNTER()
        self.c2 = COUNTER()
        self.c3 = COUNTER()
        self.c4 = COUNTER()
        self.c5 = COUNTER()
        self.c6 = COUNTER()
        self.c7 = COUNTER()
        self.c8 = COUNTER()

    def run(self, a0, a1, a2, a3, a4, a5, a6, a7,
            Load=0, L0=0, L1=0, L2=0, L3=0, L4=0, L5=0, L6=0, L7=0):
        carry1, v1 = self.c1.run(a0, Load, L0)
        carry2, v2 = self.c2.run(MAX(carry1, a1), Load, L1)
        carry3, v3 = self.c3.run(MAX(carry2, a2), Load, L2)
        carry4, v4 = self.c4.run(MAX(carry3, a3), Load, L3)
        carry5, v5 = self.c5.run(MAX(carry4, a4), Load, L4)
        carry6, v6 = self.c6.run(MAX(carry5, a5), Load, L5)
        carry7, v7 = self.c7.run(MAX(carry6, a6), Load, L6)
        carry8, v8 = self.c8.run(MAX(carry7, a7), Load, L7)

        return v1, v2, v3, v4, v5, v6, v7, v8


class RSTACK:
    """Return-address stack, depth 4; each entry is an 8-quarter code address
    (0..65535). CALL pushes the address to come back to (push-enable wire En);
    RET pops it. `sp` holds the index of the next free entry.

    Built on the same VecMem storage macro as the register file: the slot is
    picked by the stack pointer and push/pop simply strobe it, so the entry
    width is a parameter rather than a wall of hand-unrolled cells."""

    def __init__(self):
        self.mem = VecMem(4, 8, 1)
        self.sp = ST()

    def depth(self):
        return self.sp.run(0, 0)   # index of the next free entry == item count

    def push(self, En, a0, a1, a2, a3, a4, a5, a6, a7):
        s = self.sp.run(0, 0)
        self.mem.access((s,), En, (a0, a1, a2, a3, a4, a5, a6, a7))
        self.sp.run(MOD(s, 1), En)     # sp = (s + 1) % 4, only when enabled

    def pop(self, En):
        s = MOD(self.sp.run(0, 0), 3)  # sp - 1 (mod 4)
        self.sp.run(s, En)             # commit only when enabled
        return self.mem.access((s,), 0)


class WREG16:
    """16 word registers addressed by (Adr0, Adr1): register n lives at
    (n%4, n//4). A gate-decoded register file -- the one-hot Adr16 decode and the
    read/write mux, evaluated in parallel over all 16 cells (see VecMem)."""

    def __init__(self):
        self.mem = VecMem(16, WORD_QUARTERS, 2)

    def run(self, Adr0, Adr1, Set, word=None):
        return self.mem.access((Adr0, Adr1), Set, word)


class BigRAM:
    """Data memory as a direct-indexed, demand-paged macro. A real memory chip
    is an *addressed array* (an SRAM/DRAM macro from the cell library), not
    something synthesized from datapath gates -- so this indexes straight to the
    addressed cell in O(1) and allocates physical pages only where the program
    actually writes. That gives the whole WORD_QUARTERS-digit (32-bit) address
    space at the cost of just the touched pages -- huge, sparse, modular. A
    storage primitive, like ST / VecMem; the gate-built datapath (ALU, CPU, bus
    decode) is what stays purely gate-composed."""

    PAGE = 4096

    def __init__(self, width=WORD_QUARTERS):
        self.width = width
        self.zero = tuple(0 for _ in range(width))
        self.pages = {}

    def _index(self, addr):
        n, p = 0, 1
        for d in addr:
            n += d * p
            p *= 4
        return n

    def peek(self, a):
        """Plain int-addressed read, for device DMA (the GPU fetching a string
        or sprite). Not part of the CPU datapath."""
        pi, off = divmod(a, self.PAGE)
        page = self.pages.get(pi)
        if page is None:
            return 0
        n, p = 0, 1
        for d in page[off]:
            n += int(d) * p
            p *= 4
        return n

    def run(self, addr, Set, word=None):
        a = self._index(addr)
        pi, off = divmod(a, self.PAGE)
        if Set > 0:
            page = self.pages.get(pi)
            if page is None:
                page = self.pages[pi] = np.zeros((self.PAGE, self.width),
                                                 dtype=np.int16)
            page[off] = word
            return tuple(int(x) for x in word)
        page = self.pages.get(pi)
        if page is None:
            return self.zero
        return tuple(int(x) for x in page[off])
