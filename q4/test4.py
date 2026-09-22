"""Self-test for the Q4 CPU: run small programs on the gate machine and check
the output against byte (mod 256) semantics. Run: python -m q4.test4"""

from .cpu4 import Machine4, asm
from .words4 import from_word, to_word, WMIN, WMAX, WNOT, WMOD

M = 256


def out(prog):
    m = Machine4(asm(prog)).run(max_steps=200000)
    return [from_word(w) for w in m.out.log]


def one(op, a, b, want):
    r = out([('LOADI', 0, a), ('LOADI', 1, b), (op, 0, 1),
             ('OUT', 0), ('HALT',)])
    assert r == [want], f'{op} {a},{b}: got {r}, want {want}'


def test_arith():
    one('ADD', 200, 100, (200 + 100) % M)     # wraps: 44
    one('SUB', 5, 9, (5 - 9) % M)             # wraps: 252
    one('MUL', 20, 13, (20 * 13) % M)         # wraps: 260 -> 4
    one('DIV', 200, 7, 200 // 7)              # 28
    one('DIV', 5, 0, 0)                       # divide-by-zero -> 0


def test_logic():
    for a, b in [(0, 0), (200, 55), (17, 240), (255, 1)]:
        one('MIN', a, b, from_word(WMIN(to_word(a), to_word(b))))
        one('MAX', a, b, from_word(WMAX(to_word(a), to_word(b))))
        one('MOD', a, b, from_word(WMOD(to_word(a), to_word(b))))   # add-mod-256
    # NOT is unary on Rd
    for a in (0, 1, 85, 255):
        r = out([('LOADI', 0, a), ('NOT', 0), ('OUT', 0), ('HALT',)])
        assert r == [from_word(WNOT(to_word(a)))], (a, r)


def test_memory():
    # store then load across all four registers as data/address
    r = out([('LOADI', 0, 99), ('LOADI', 1, 5), ('STORE', 0, 1),
             ('LOADI', 0, 0), ('LOAD', 0, 1), ('OUT', 0), ('HALT',)])
    assert r == [99], r
    # MOV
    r = out([('LOADI', 2, 123), ('MOV', 0, 2), ('OUT', 0), ('HALT',)])
    assert r == [123], r
    # RAM survives many addresses
    r = out([('LOADI', 0, 200), ('LOADI', 1, 250), ('STORE', 0, 1),
             ('LOADI', 0, 7), ('LOADI', 1, 3), ('STORE', 0, 1),
             ('LOADI', 1, 250), ('LOAD', 2, 1), ('OUT', 2), ('HALT',)])
    assert r == [200], r


def test_control():
    # JZ taken vs not, and JMP forming a countdown loop
    r = out([('LOADI', 0, 3),          # R0 = 3
             ('LOADI', 3, 1),          # R3 = 1
             ('OUT', 0),               # 2: emit R0   <-- loop
             ('SUB', 0, 3),            # 3: R0 -= 1
             ('JZ', 0, 6),             # 4: if R0==0 goto 6
             ('JMP', 2),               # 5: goto 2
             ('HALT',)])               # 6
    assert r == [3, 2, 1], r


def test_demos():
    from .cpu4 import DEMOS
    assert out(DEMOS['sum']) == [55]
    assert out(DEMOS['mul']) == [42]
    assert out(DEMOS['mem']) == [99]


if __name__ == '__main__':
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f'FAIL {t.__name__}: {e}')
            traceback.print_exc()
        else:
            passed += 1
            print(f'ok   {t.__name__}')
    print(f'\n{passed}/{len(tests)} passed')
