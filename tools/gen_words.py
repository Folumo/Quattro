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

    # ============================ WORD_x_DIGIT ============================
    # A (W digits) * one digit d -> W+1 digits.
    line('@ROM')
    line('def WORD_x_DIGIT(A, d):')
    a = unpack('a', 'A', W)
    for i in range(W):
        line(f'    h{i}, l{i} = HF_MULTIPLY({a[i]}, d)')
    line('    o0 = l0')
    line('    k = h0')
    for i in range(1, W):
        line(f'    c, o{i} = HF_ADDER(l{i}, k)')
        line(f'    _, k = HF_ADDER(h{i}, c)')
    line(f'    o{W} = k')
    line(f'    return ({", ".join(f"o{i}" for i in range(W + 1))})')
    line('')
    line('')

    # ============================ WMUL ===================================
    # sum of shifted partial products; keep low W digits + overflow flag.
    line('@ROM')
    line('def WMUL(A, B):')
    b = unpack('b', 'B', W)
    for j in range(W):
        pj = ', '.join(f'p{j}_{k}' for k in range(W + 1))
        line(f'    ({pj}) = WORD_x_DIGIT(A, {b[j]})')
    acc = ['0'] * (2 * W)
    for j in range(W):
        carry = '0'
        for k in range(W + 1):
            pos = j + k
            cv, sv = fresh('mc'), fresh('ms')
            line(f'    {cv}, {sv} = FULL_ADD({acc[pos]}, p{j}_{k}, {carry})')
            acc[pos] = sv
            carry = cv
        pos = j + W + 1
        while pos < 2 * W:
            cv, sv = fresh('mc'), fresh('ms')
            line(f'    {cv}, {sv} = FULL_ADD({acc[pos]}, 0, {carry})')
            acc[pos] = sv
            carry = cv
            pos += 1
    low = ', '.join(acc[:W])
    hi_or = 'MAX(' * (2 * W - W - 1) + acc[W]
    for k in range(W + 1, 2 * W):
        hi_or += f', {acc[k]})'
    line(f'    low = ({low})')
    line(f'    overflow = MIN(1, {hi_or})')
    line('    return overflow, low')
    line('')
    line('')

    # ============================ WDIV ===================================
    # Base-4 restoring long division, W digit-stages, W+1-wide intermediates.
    # Divide-by-zero gates every subtraction off -> quotient 0, remainder A.
    WP = W + 1
    line('@ROM')
    line('def WDIV(A, B):')
    a = unpack('a', 'A', W)
    b = unpack('b', 'B', W)
    # B, 2B, 3B as WP-digit values
    B1 = [b[i] for i in range(W)] + ['0']
    line(f'    # B != 0 ?')
    line(f'    bnz = NOT(EQ(MAX(' + 'MAX(' * (W - 2) + ', '.join(b[:2]) + ')' +
         ''.join(f', {b[i]})' for i in range(2, W)) + ', 0))')
    c, B2 = ripple_add(B1, B1, WP)
    _, B3 = ripple_add(B2, B1, WP)
    # remainder R starts at 0 (WP digits)
    R = ['0'] * WP
    Q = [None] * W
    for i in range(W - 1, -1, -1):
        # R' = R*4 + A_i  ==  shift digits up, insert a_i at bottom
        Rp = [a[i]] + R[:W]   # WP digits
        ge1 = wge(Rp, B1, WP)
        ge2 = wge(Rp, B2, WP)
        ge3 = wge(Rp, B3, WP)
        # q = 3 if ge3 else 2 if ge2 else 1 if ge1 else 0, then gate by bnz
        q = fresh('q')
        line(f'    {q} = MIN(bnz, MAX(MIN({ge3}, 3), MIN(EQ({ge3}, 0), '
             f'MAX(MIN({ge2}, 2), MIN(EQ({ge2}, 0), MIN({ge1}, 1))))))')
        # subtrahend = q * B : select among 0/B1/B2/B3
        sub = []
        for k in range(WP):
            sv = fresh('sb')
            line(f'    {sv} = MAX(MAX(MIN(EQ({q}, 1), {B1[k]}), '
                 f'MIN(EQ({q}, 2), {B2[k]})), MIN(EQ({q}, 3), {B3[k]}))')
            sub.append(sv)
        _, R = ripple_sub(Rp, sub, WP)
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
