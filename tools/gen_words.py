"""Generate the unrolled, gate-pure word ALU for a given width W (quarters).
Emits straight-line code (no loops) composed only of the single-digit gate
primitives, so purity_check still sees pure gate logic. Width is now one knob."""


def generate(W):
    out = []
    ctr = [0]

    def fresh(pfx='t'):
        ctr[0] += 1
        return f'{pfx}{ctr[0]}'

    def line(s=''):
        out.append(s)

    # --- generation-time ripple helpers: emit code, return result var names ---
    def unpack(name, src, w):
        line(f'    ({", ".join(f"{name}{i}" for i in range(w))}) = {src}')
        return [f'{name}{i}' for i in range(w)]

    def ripple_add(a, b, w):
        # a, b: lists of var-name/expr strings (len w). returns (carry, sum-list)
        s = []
        c = '0'
        for i in range(w):
            cv, sv = fresh('c'), fresh('s')
            line(f'    {cv}, {sv} = FULL_ADD({a[i]}, {b[i]}, {c})')
            s.append(sv)
            c = cv
        return c, s

    def ripple_sub(a, b, w):
        # returns (borrow, diff-list)
        d = []
        br = '0'
        for i in range(w):
            bv, dv = fresh('b'), fresh('d')
            line(f'    {bv}, {dv} = FULL_SUB({a[i]}, {b[i]}, {br})')
            d.append(dv)
            br = bv
        return br, d

    def wge(a, b, w):
        br, _ = ripple_sub(a, b, w)
        g = fresh('g')
        line(f'    {g} = EQ({br}, 0)')   # 3 if a >= b else 0
        return g

    # ============================ WSEL / WOR / WNOT =======================
    line('@ROM')
    line('def WSEL(sel, W):')
    a = unpack('w', 'W', W)
    line(f'    return ({", ".join(f"MIN(sel, {a[i]})" for i in range(W))})')
    line('')
    line('')
    line('@ROM')
    line('def WOR(A, B):')
    a = unpack('a', 'A', W)
    b = unpack('b', 'B', W)
    line(f'    return ({", ".join(f"MAX({a[i]}, {b[i]})" for i in range(W))})')
    line('')
    line('')
    line('@ROM')
    line('def WNOT(A):')
    a = unpack('a', 'A', W)
    line(f'    return ({", ".join(f"NOT({a[i]})" for i in range(W))})')
    line('')
    line('')

    # ============================ WADD / WSUB / WGE =======================
    line('@ROM')
    line('def WADD(A, B):')
    a = unpack('a', 'A', W)
    b = unpack('b', 'B', W)
    c, s = ripple_add(a, b, W)
    line(f'    return {c}, ({", ".join(s)})')
    line('')
    line('')
    line('@ROM')
    line('def WSUB(A, B):')
    a = unpack('a', 'A', W)
    b = unpack('b', 'B', W)
    br, d = ripple_sub(a, b, W)
    line(f'    return {br}, ({", ".join(d)})')
    line('')
    line('')
    line('@ROM')
    line('def WGE(A, B):')
    a = unpack('a', 'A', W)
    b = unpack('b', 'B', W)
    g = wge(a, b, W)
    line(f'    return {g}')
    line('')
    line('')

    # ============================ WMUL ===================================
    # Low-word multiply. The product is one word (mod 4**W), so only the lower
    # triangle of partial products is built: digit i of A times digit j of B
    # lands at position i+j, and any digit that would reach position W or beyond
    # is discarded. The old version summed the full 2W-digit product and threw
    # its top half away -- ~56% more gates for nothing. Overflow is no longer
    # reported (that flag was never read by any program); the (flag, low) tuple
    # shape is kept for W_ALU, with a constant-0 flag.
    line('@ROM')
    line('def WMUL(A, B):')
    a = unpack('a', 'A', W)
    b = unpack('b', 'B', W)
    acc = ['0'] * W
    for j in range(W):
        n = W - j                       # partial-product digits that fit: 0..W-1-j
        hi, lo = [], []
        for i in range(n):
            hv, lv = fresh('h'), fresh('l')
            line(f'    {hv}, {lv} = HF_MULTIPLY({a[i]}, {b[j]})')
            hi.append(hv)
            lo.append(lv)
        p = [lo[0]]                     # A * b[j], carry-chained, truncated to n digits
        k = hi[0]
        for i in range(1, n):
            cv, ov = fresh('c'), fresh('o')
            line(f'    {cv}, {ov} = HF_ADDER({lo[i]}, {k})')
            p.append(ov)
            if i < n - 1:
                kv = fresh('k')
                line(f'    _, {kv} = HF_ADDER({hi[i]}, {cv})')
                k = kv
        carry = '0'                     # add the shifted partial into acc[j..W-1]
        for i in range(n):
            pos = j + i
            cv, sv = fresh('mc'), fresh('ms')
            line(f'    {cv}, {sv} = FULL_ADD({acc[pos]}, {p[i]}, {carry})')
            acc[pos] = sv
            carry = cv
    line(f'    low = ({", ".join(acc)})')
    line('    return 0, low')
    line('')
    line('')

    # ============================ WDIV ===================================
    # Base-4 restoring long division, W digit-stages. Comparison IS subtraction,
    # so rather than three "R >= kB" tests (each a throwaway subtract) plus a
    # fourth subtract of q*B, subtract B three times in a chain (Rp-B, -B, -B)
    # and KEEP the differences: the borrows give the quotient digit, and the
    # matching difference is the new remainder -- three subtractions per stage
    # instead of four, and no 2B/3B to precompute. Divide-by-zero gates q to 0
    # (so the remainder stays A). Returns (remainder, quotient); the machine's
    # DIV op uses the quotient, and C's % is a - (a/b)*b, so the remainder feeds
    # only the (never-read) flag -- but it is already computed, so it is free.
    WP = W + 1
    line('@ROM')
    line('def WDIV(A, B):')
    a = unpack('a', 'A', W)
    b = unpack('b', 'B', W)
    B1 = [b[i] for i in range(W)] + ['0']
    ortree = 'MAX(' * (W - 1) + b[0] + ''.join(f', {b[i]})' for i in range(1, W))
    line(f'    bnz = NOT(EQ({ortree}, 0))')   # 3 if B != 0 else 0
    R = ['0'] * WP
    Q = [None] * W
    for i in range(W - 1, -1, -1):
        Rp = [a[i]] + R[:W]                    # R*4 + a_i (a free digit shift)
        br1, D1 = ripple_sub(Rp, B1, WP)
        br2, D2 = ripple_sub(D1, B1, WP)
        br3, D3 = ripple_sub(D2, B1, WP)
        e1, e2, e3 = fresh('e'), fresh('e'), fresh('e')
        line(f'    {e1} = EQ({br1}, 0)')       # 3 if that subtract did NOT borrow
        line(f'    {e2} = EQ({br2}, 0)')
        line(f'    {e3} = EQ({br3}, 0)')
        # q = bnz AND (Rp<B ? 0 : Rp<2B ? 1 : Rp<3B ? 2 : 3)
        q = fresh('q')
        line(f'    {q} = MIN(bnz, MIN({e1}, MAX(MIN({e2}, '
             f'MAX(MIN({e3}, 3), MIN(NOT({e3}), 2))), MIN(NOT({e2}), 1))))')
        q0, q1, q2, q3 = fresh('q'), fresh('q'), fresh('q'), fresh('q')
        line(f'    {q0} = EQ({q}, 0)')
        line(f'    {q1} = EQ({q}, 1)')
        line(f'    {q2} = EQ({q}, 2)')
        line(f'    {q3} = EQ({q}, 3)')
        Rn = []                                # new remainder = the selected difference
        for k in range(WP):
            sv = fresh('r')
            line(f'    {sv} = MAX(MAX(MIN({q0}, {Rp[k]}), MIN({q1}, {D1[k]})), '
                 f'MAX(MIN({q2}, {D2[k]}), MIN({q3}, {D3[k]})))')
            Rn.append(sv)
        R = Rn
        Q[i] = q
    line(f'    Q = ({", ".join(Q)})')
    line(f'    R = ({", ".join(R[:W])})')
    line('    return R, Q')
    line('')
    line('')

    # ============================ WMIN / WMAX / WMOD =====================
    line('@ROM')
    line('def WMIN(A, B):')
    a = unpack('a', 'A', W)
    b = unpack('b', 'B', W)
    g = wge(a, b, W)
    line(f'    gz = EQ({g}, 0)')
    line('    return (' + ', '.join(
        f'MAX(MIN({g}, {b[i]}), MIN(gz, {a[i]}))' for i in range(W)) + ')')
    line('')
    line('')
    line('@ROM')
    line('def WMAX(A, B):')
    a = unpack('a', 'A', W)
    b = unpack('b', 'B', W)
    g = wge(a, b, W)
    line(f'    gz = EQ({g}, 0)')
    line('    return (' + ', '.join(
        f'MAX(MIN({g}, {a[i]}), MIN(gz, {b[i]}))' for i in range(W)) + ')')
    line('')
    line('')
    line('@ROM')
    line('def WMOD(A, B):')
    line('    cw, S = WADD(A, B)')
    line('    return S')
    line('')
    line('')

    # WNZ: 3 if the word is non-zero, else 0.  WEQ: 3 if A == B, else 0.
    line('@ROM')
    line('def WNZ(A):')
    a = unpack('a', 'A', W)
    ortree = 'MAX(' * (W - 1) + a[0] + ''.join(f', {a[i]})' for i in range(1, W))
    line(f'    return NOT(EQ({ortree}, 0))')
    line('')
    line('')
    line('@ROM')
    line('def WEQ(A, B):')
    a = unpack('a', 'A', W)
    b = unpack('b', 'B', W)
    andtree = 'MIN(' * (W - 1) + f'EQ({a[0]}, {b[0]})' + ''.join(
        f', EQ({a[i]}, {b[i]}))' for i in range(1, W))
    line(f'    return {andtree}')
    line('')
    line('')

    # ============================ W_ALU ==================================
    line('@ROM')
    line('def W_ALU(InA, InB, Instr0, Instr1):')
    line('    """Word ALU: returns (flag_digit, result_word). Width-generic:')
    line('    every op runs; the class/sub-op decode lines select the result."""')
    line('    Aa, Bb, Cc, Dd = Adr4(Instr0, 3)')
    line('    A, B, C, D = Adr4(Instr1, Aa)')
    line('    A1, B1, C1, D1 = Adr4(Instr1, Bb)')
    line('    Cout, ADD = WADD(InA, InB)')
    line('    Borrow, SUBr = WSUB(InA, InB)')
    line('    Mov, MULr = WMUL(InA, InB)')
    line('    Rem, QUOT = WDIV(InA, InB)')
    line('    arith = WOR(WOR(WSEL(A, ADD), WSEL(B, SUBr)),')
    line('                WOR(WSEL(C, MULr), WSEL(D, QUOT)))')
    rem = unpack('rm', 'Rem', W)
    ortree = 'MAX(' * (W - 1) + rem[0] + ''.join(f', {rem[i]})' for i in range(1, W))
    line(f'    Xdiv = MIN(1, {ortree})')
    line('    flag = MAX(MAX(MIN(A, Cout), MIN(B, Borrow)), '
         'MAX(MIN(C, Mov), MIN(D, Xdiv)))')
    line('    logic = WOR(WOR(WSEL(A1, WMIN(InA, InB)), WSEL(B1, WMAX(InA, InB))),')
    line('                WOR(WSEL(C1, WMOD(InA, InB)), WSEL(D1, WNOT(InA))))')
    line('    return flag, WOR(arith, logic)')
    line('')

    return '\n'.join(out)


def generate_module(W):
    """Full words.py for width W: edge converters + word gates + ALU."""
    zeros = ', '.join('0' * 1 for _ in range(W))
    header = f'''"""Words: {W} quaternary digits (little-endian), value 0..4**{W}-1.

GENERATED by tools/gen_words.py for WORD_QUARTERS = {W}. Do not edit by hand;
change the width there and regenerate. to_word/from_word convert at the edges
only; WSEL/WOR/WNOT are the word mux gates; WADD..W_ALU are the word ALU, all
unrolled from the single-digit gates in gates.py (so purity_check still sees
pure gate logic). @ROM memoizes each pure block as a lookup ROM."""

from .gates import (ROM, ROM_BOUNDED, Adr4, EQ, MAX, MIN, NOT, HF_ADDER,
                    HF_SUBTRACT, HF_MULTIPLY)

WORD_QUARTERS = {W}

# The instruction frame width (quaternary slots per instruction): one word is
# exactly one frame, which is what makes loading a program a straight copy.
FRAME = {W}


# The bus re-derives the same handful of constant port numbers on every access
# (one per device decode line), so this is by far the hottest converter in the
# machine. Memoizing it is the same lookup-ROM trade @ROM makes for the gate
# blocks -- bounded, because unlike a gate block its input is a full {W}-digit
# value, so an unbounded table would grow without limit.
@ROM_BOUNDED
def to_word(n):
    return tuple((n // (4 ** k)) % 4 for k in range(WORD_QUARTERS))


def from_word(w):
    return sum(v * (4 ** k) for k, v in enumerate(w))


ZERO_WORD = tuple(0 for _ in range(WORD_QUARTERS))
ONE_WORD = (1,) + tuple(0 for _ in range(WORD_QUARTERS - 1))


def FULL_ADD(a, b, cin):
    c1, s1 = HF_ADDER(a, b)
    c2, s = HF_ADDER(s1, cin)
    return MAX(c1, c2), s


def FULL_SUB(a, b, bin):
    br1, d1 = HF_SUBTRACT(a, b)
    br2, d = HF_SUBTRACT(d1, bin)
    return MAX(br1, br2), d


'''
    return header + generate(W)


if __name__ == '__main__':
    # Rewrite quattro/words.py in place. This is the only way that file should
    # ever change: to widen the machine, pass a new width here and rerun.
    #     python tools/gen_words.py 16
    import os
    import sys
    W = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'quattro', 'words.py')
    with open(out, 'w') as f:
        f.write(generate_module(W))
    print(f'{out}: width-{W} words + ALU')
