"""The gate-built hardware, checked against independent references.

The ALU is unrolled from single-digit gates and is the thing everything else
stands on: if WADD is wrong at one carry, every program is wrong and no amount
of staring at C code will find it. These compare it against plain Python
arithmetic over random values plus every edge that has ever mattered
(0, 1, the carry boundaries, the top of the range, and division by zero).
"""
import random

import numpy as np

from quattro.storage import RSTACK, VecMem
from quattro.words import (WADD, WSUB, WMUL, WDIV, WGE, WEQ, WNZ, WMIN, WMAX,
                           WORD_QUARTERS, from_word, to_word)

M = 4 ** WORD_QUARTERS          # 2**32

# every boundary that has ever mattered, plus randoms
EDGES = [0, 1, 2, 3, 4, 5, 15, 16, 255, 256, 257, 1023, 1024, 65535, 65536,
         1048575, 1048576, 2**31 - 1, 2**31, 2**31 + 1, M - 2, M - 1]


def _pairs(n=400, seed=0):
    rnd = random.Random(seed)
    for a in EDGES:
        for b in EDGES:
            yield a, b
    for _ in range(n):
        yield rnd.randrange(M), rnd.randrange(M)


def test_add_matches_python():
    for a, b in _pairs():
        carry, s = WADD(to_word(a), to_word(b))
        assert from_word(s) == (a + b) % M, f'{a} + {b}'
        assert (carry == 1) == (a + b >= M), f'{a} + {b} carry'


def test_sub_matches_python():
    for a, b in _pairs():
        borrow, d = WSUB(to_word(a), to_word(b))
        assert from_word(d) == (a - b) % M, f'{a} - {b}'
        assert (borrow == 1) == (a < b), f'{a} - {b} borrow'


def test_mul_matches_python():
    for a, b in _pairs(200, seed=1):
        _, p = WMUL(to_word(a), to_word(b))
        assert from_word(p) == (a * b) % M, f'{a} * {b}'


def test_div_matches_python():
    for a, b in _pairs(200, seed=2):
        if b == 0:
            continue
        _, q = WDIV(to_word(a), to_word(b))
        assert from_word(q) == a // b, f'{a} / {b}'


def test_div_by_zero_is_defined():
    """Real hardware cannot raise. The machine defines x/0 = 0, and the C
    compiler's constant folder has to agree with it -- so this is pinned."""
    for a in EDGES:
        _, q = WDIV(to_word(a), to_word(0))
        assert from_word(q) == 0, f'{a} / 0 should be 0, got {from_word(q)}'


def test_compare_gates():
    for a, b in _pairs(200, seed=3):
        assert (WGE(to_word(a), to_word(b)) == 3) == (a >= b), f'{a} >= {b}'
        assert (WEQ(to_word(a), to_word(b)) == 3) == (a == b), f'{a} == {b}'
    for a in EDGES:
        assert (WNZ(to_word(a)) == 3) == (a != 0), f'{a} != 0'


def test_min_max_are_numeric_not_per_digit():
    """WMIN/WMAX compare the WHOLE WORD and select one of the two operands --
    they are not the single-digit MIN/MAX gate applied per quarter, despite
    sharing its name. WMIN(4, 3) is 3, not the digit-wise 0. Pinned because the
    name invites exactly the wrong assumption (it caught me writing this suite)."""
    for x, y in _pairs(100, seed=4):
        wa, wb = to_word(x), to_word(y)
        assert from_word(WMIN(wa, wb)) == min(x, y), f'WMIN({x}, {y})'
        assert from_word(WMAX(wa, wb)) == max(x, y), f'WMAX({x}, {y})'
    # the case that distinguishes the two readings
    assert from_word(WMIN(to_word(4), to_word(3))) == 3


def test_arithmetic_is_twos_complement():
    """a - b for a < b already produces the correct two's-complement pattern for
    the negative. This is why signed +/-/* need no new hardware."""
    for a, b in ((3, 10), (0, 1), (100, 5000), (0, M - 1)):
        _, d = WSUB(to_word(a), to_word(b))
        assert from_word(d) == (a - b) % M


# --- the memory macro ---------------------------------------------------

def _ref_access(cells, planes, n, addr, we, word):
    """VecMem's docstring longhand: the one-hot gate mux, written out plainly.
    The fast version must be bit-identical to this or the docstring is a lie."""
    sel = np.full(n, 3, dtype=np.int16)
    for plane, d in zip(planes, addr):
        sel = np.minimum(sel, np.where(plane == d, 3, 0))
    if we > 0:
        col = sel[:, None]
        cells[:] = np.maximum(np.minimum(3 - col, cells),
                              np.minimum(col, np.asarray(word, np.int16)))
    return tuple(int(x) for x in np.max(np.minimum(sel[:, None], cells), axis=0))


def test_vecmem_is_the_one_hot_mux():
    rnd = random.Random(7)
    for (n, width, ndig) in ((16, 16, 2), (64, 8, 3), (256, 16, 4), (2418, 16, 8)):
        m = VecMem(n, width, ndig)
        ref = np.zeros((n, width), dtype=np.int16)
        planes = [((np.arange(n) // (4 ** k)) % 4).astype(np.int16)
                  for k in range(ndig)]
        for _ in range(600):
            a = rnd.randrange(0, 4 ** ndig)     # includes out-of-range rows
            addr = tuple((a // (4 ** k)) % 4 for k in range(ndig))
            we = rnd.choice([0, 0, 3])
            word = tuple(rnd.randrange(4) for _ in range(width))
            got = m.access(addr, we, word)
            assert got == _ref_access(ref, planes, n, addr, we, word), (n, addr, we)
        assert np.array_equal(m.cells, ref), f'cell array diverged at n={n}'


def test_vecmem_out_of_range_address_reads_zero():
    """No row matches, so the sense array sees nothing -- it must not alias."""
    m = VecMem(3, 8, 1)
    m.access((0,), 3, (3,) * 8)
    assert m.access((3,), 0) == (0,) * 8


def test_vecmem_rejects_a_wrong_width_address():
    """A macro built for N digits must not quietly answer to a longer address by
    using its low N digits -- that is how a 256-word memory ends up responding to
    a 32-bit address. (It used to: the decode zipped planes against the address,
    and zip truncates.)"""
    m = VecMem(256, 16, 4)
    try:
        m.access(tuple(range(16)), 0)      # a full 16-quarter word into 4 digits
    except Exception:
        return
    raise AssertionError('VecMem silently truncated an over-long address')


# --- the return stack ---------------------------------------------------

def test_rstack_round_trips_within_depth():
    s = RSTACK()
    for v in (5, 300, 65535):
        s.push(3, *tuple((v // (4 ** k)) % 4 for k in range(8)))
    for v in (65535, 300, 5):
        assert sum(q * 4 ** k for k, q in enumerate(s.pop(3))) == v


def test_rstack_push_is_strobed():
    s = RSTACK()
    before = s.depth()
    s.push(0, *((0,) * 8))          # enable low: must not move
    assert s.depth() == before


def test_rstack_overflow_is_documented():
    """KNOWN LIMIT, pinned so a change is deliberate: sp is a single quaternary
    digit, so the 4th push wraps it to 0 and the stack cannot tell full from
    empty. Nesting CALLs more than 3 deep silently corrupts the return address
    (asm/shell.asm keeps to <=2; the C compiler sidesteps it with a software
    stack). If this test starts failing because sp got wider, that is progress
    -- update it."""
    s = RSTACK()
    for i in range(4):
        s.push(3, *((0,) * 8))
    assert s.depth() == 0, 'sp no longer wraps at 4 -- the stack got deeper?'
