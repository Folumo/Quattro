"""Single-digit gate primitives and the parts built directly from them.

MIN/MAX/NOT/COM/MOD/EQ are the six premade primitives; Adr4/Adr16
are the address decoders and HF_ADDER/HF_SUBTRACT/HF_MULTIPLY are
one-digit arithmetic. Everything else is built on top of this file."""

from functools import lru_cache

# A pure combinational block memoized is exactly a lookup ROM -- a legitimate
# hardware primitive (microcode/PLA tables are built this way). @ROM caches a
# gate function's truth table so repeated inputs are a dict lookup, not a
# re-evaluation of the whole gate tree. Only ever applied to pure, state-free
# functions of small hashable inputs.
ROM = lru_cache(maxsize=None)

# The same trade where the input space is too wide to tabulate exhaustively:
# keep the hot entries, let the cold ones fall out, so the table stays bounded.
ROM_BOUNDED = lru_cache(maxsize=8192)


MIN = min


MAX = max


NOT = lambda inA: 3 - inA


COM = lambda inA, inB: inA - inB if inA > inB else 0


MOD = lambda inA, inB: (inA + inB) % 4


EQ = lambda inA, inB: 3 if inA == inB else 0


@ROM
def Adr4(Adr, Set):
    A = MIN(EQ(0, Adr), Set)
    B = MIN(EQ(1, Adr), Set)
    C = MIN(EQ(2, Adr), Set)
    D = MIN(EQ(3, Adr), Set)

    return A, B, C, D


@ROM
def Adr16(Adr0, Adr1, Set):
    A, B, C, D = Adr4(Adr0, Set)

    A1, B1, C1, D1 = Adr4(Adr1, A)
    A2, B2, C2, D2 = Adr4(Adr1, B)
    A3, B3, C3, D3 = Adr4(Adr1, C)
    A4, B4, C4, D4 = Adr4(Adr1, D)

    return A1, B1, C1, D1, A2, B2, C2, D2, A3, B3, C3, D3, A4, B4, C4, D4


@ROM
def HF_ADDER(A, B):
    C = MIN(1, MAX(COM(A, NOT(B)), COM(B, NOT(A))))

    Y = MOD(A, B)

    return C, Y


@ROM
def HF_SUBTRACT(A, B):
    result = MOD(MOD(A, NOT(B)), 1)
    return MIN(1, COM(B, A)), result


@ROM
def HF_MULTIPLY(A, B):
    # Low digit = (A*B) mod 4. Partial products k*A mod 4, selected by B.
    # EQ(B, k) is a full-strength (3) selector, so MIN(EQ, kA) passes kA
    # unchanged -- clamping the selector to 1 would truncate digits > 1.
    A1 = A
    A2 = MOD(A, A)   # 2A mod 4
    A3 = MOD(A2, A)  # 3A mod 4

    P1 = MIN(EQ(B, 1), A1)
    P2 = MIN(EQ(B, 2), A2)
    P3 = MIN(EQ(B, 3), A3)

    result = MAX(P1, MAX(P2, P3))

    # High digit / carry = (A*B) // 4, in {0, 1, 2}. Only B >= 2 can carry.
    #   B == 2 -> (2A)//4 = 1 iff A >= 2
    #   B == 3 -> (3A)//4 = COM(A, 1)  (A=2 -> 1, A=3 -> 2)
    C2 = MIN(1, COM(A, 1))
    C3 = COM(A, 1)
    carry = MAX(MIN(EQ(B, 2), C2), MIN(EQ(B, 3), C3))

    return carry, result
