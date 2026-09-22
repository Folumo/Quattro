"""Storage for the 4-quarter machine.

A word here is 4 quarters = 8 bits = ONE BYTE (0..255). That identity is the
whole reason this variant is easy to wire to the real world: two wires per
quarter, four quarters, is exactly an 8-wire byte bus -- so standard byte-wide
RAM, USB HID report bytes, and a character display all line up with one word.

ST / VecMem / the counters are the same storage primitives the 32-bit machine
uses (copied here so q4/ stands alone); RegFile4 / RAM4 / PC4 / Port are the
4-quarter register file, data memory, program counter, and an output port.
"""

import numpy as np

from .gates import EQ, HF_ADDER, MAX, MIN
from .words4 import WORD_QUARTERS   # = 4


class ST:
    """A one-quarter storage cell: writes on a strobe, always readable."""
    def __init__(self):
        self.inValue = 0

    def run(self, Val, Set):
        if Set > 0:
            self.inValue = Val
        return self.inValue


class VecMem:
    """Addressable word memory as a storage macro (an SRAM / register-file cell
    array, not synthesized from datapath gates). n words of `width` quarters,
    addressed by `ndig` base-4 digits. Read/write is the one-hot MIN/MAX/EQ mux
    evaluated over every cell at once."""

    def __init__(self, n, width, ndig):
        self.n = n
        self.width = width
        self.cells = np.zeros((n, width), dtype=np.int16)
        rows = np.arange(n, dtype=np.int64)
        self.planes = np.array([((rows // (4 ** k)) % 4) for k in range(ndig)],
                               dtype=np.int16)
        self._addr = np.zeros((ndig, 1), dtype=np.int16)
        self._sel_buf = np.zeros(n, dtype=np.int16)
        self._mux = np.zeros((n, width), dtype=np.int16)

    def _sel(self, addr):
        self._addr[:, 0] = addr
        np.multiply((self.planes == self._addr).all(axis=0), 3,
                    out=self._sel_buf, casting='unsafe')
        return self._sel_buf

    def access(self, addr, write_en, word=None):
        col = self._sel(addr)[:, None]
        if write_en > 0:
            np.minimum(3 - col, self.cells, out=self.cells)
            np.maximum(self.cells,
                       np.minimum(col, np.asarray(word, np.int16)),
                       out=self.cells)
        np.minimum(col, self.cells, out=self._mux)
        return tuple(self._mux.max(axis=0).tolist())


class COUNTER:
    """One base-4 digit with an add-1 step and a load path (for jumps)."""
    def __init__(self):
        self.inValue = ST()

    def run(self, ADD, Load=0, LoadVal=0):
        val = self.inValue.run(0, 0)
        NEXT, NEW = HF_ADDER(val, ADD)
        ld = MIN(1, Load)
        result = MAX(MIN(EQ(ld, 1), LoadVal), MIN(EQ(ld, 0), NEW))
        return NEXT, self.inValue.run(result, 3)


class COUNTER4:
    """Four-digit counter (0..255): the program counter for 256 instructions."""
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


# -- the machine's addressable state --------------------------------------

class RegFile4:
    """Four registers R0..R3, each one 4-quarter word, addressed by one quarter.
    One-hot decode + read/write mux (VecMem)."""
    def __init__(self):
        self.mem = VecMem(4, WORD_QUARTERS, 1)

    def run(self, addr, Set, word=None):
        return self.mem.access((addr,), Set, word)


class RAM4:
    """256 bytes of data memory: 256 words of 4 quarters, addressed by a full
    4-quarter word (a one-byte address). A byte in, a byte out."""
    def __init__(self):
        self.mem = VecMem(256, WORD_QUARTERS, WORD_QUARTERS)

    def run(self, addr_word, Set, word=None):
        return self.mem.access(addr_word, Set, word)


class PC4:
    """Program counter: a 4-quarter counter over instruction indices (0..255).
    step() advances by one; load() jumps to an address; get() reads it."""
    def __init__(self):
        self.c = COUNTER4()

    def get(self):
        return self.c.run(0, 0, 0, 0)

    def update(self, take, a0, a1, a2, a3):
        # one call: load the jump target when `take`, else add 1
        self.c.run(1, 0, 0, 0, take, a0, a1, a2, a3)


class Port:
    """An output port -- the 'outside world'. Writing it on a strobe latches a
    byte and records it (this is where a real build wires a display or a UART)."""
    def __init__(self):
        self.value = None
        self.log = []

    def write(self, word, en):
        if en:
            self.value = word
            self.log.append(word)
