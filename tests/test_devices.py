"""The devices, and the boot chain end to end.

The Drive opens a real folder on your host disk, so its containment check is the
one piece of this project where a bug reaches outside the simulation. It gets the
most attention here.
"""
import os
import tempfile

from quattro import Machine
from quattro.bus import Bus
from quattro.devices import Drive, GPU, Loader
from quattro.storage import RAM6


def _drive():
    """A drive rooted at <tmp>/machine, with a sibling <tmp>/machine2 holding a
    secret. The sibling is the point: it shares a string prefix with the root."""
    tmp = tempfile.mkdtemp()
    root = os.path.join(tmp, 'machine')
    os.makedirs(root)
    os.makedirs(os.path.join(tmp, 'machine2'))
    with open(os.path.join(tmp, 'machine2', 'secret.txt'), 'w') as f:
        f.write('SECRET')
    with open(os.path.join(root, 'ok.txt'), 'w') as f:
        f.write('fine')
    return Drive(root)


ESCAPES = [
    '../machine2/secret.txt',   # the prefix attack: a bare startswith() lets
    '../machine2',              # root=/x/machine reach /x/machine2/...
    '../machine2/',
    '../secret.txt',
    '..',
    '..\\..\\x',
    'bin/../../secret.txt',
    'a/../../../secret.txt',
]

LEGIT = ['ok.txt', 'bin/os.bin', 'docs/about.txt', 'a/b/c.txt', '/ok.txt', '']


def test_drive_blocks_escapes():
    d = _drive()
    escaped = [n for n in ESCAPES if d._path(n) is not None]
    assert not escaped, f'the machine can read outside its drive via: {escaped}'


def test_drive_allows_legitimate_paths():
    d = _drive()
    blocked = [n for n in LEGIT if d._path(n) is None]
    assert not blocked, f'wrongly blocked: {blocked}'


def test_drive_confines_every_path_it_returns():
    d = _drive()
    for name in ESCAPES + LEGIT:
        p = d._path(name)
        if p is not None:
            assert p == d.root or p.startswith(d.root + os.sep), f'{name} -> {p}'


def test_drive_read_write_round_trip():
    d = _drive()
    m = Machine([(2, 3) + (0,) * 14])       # a HLT; we only want its memory
    d.mem = m.bus.ram
    text = b'written by the machine'
    for i, b in enumerate(b'out.txt\x00'):
        d._poke(700 + i, b)
    for i, b in enumerate(text):
        d._poke(800 + i, b)
    d.reg[Drive.R_NAME] = 700
    d.reg[Drive.R_BUF] = 800
    d.reg[Drive.R_LEN] = len(text)
    d.reg[Drive.R_POS] = 0
    d.write(Drive.R_CMD, Drive.C_WRITE)
    assert d.reg[Drive.R_STATUS] == 0
    with open(os.path.join(d.root, 'out.txt'), 'rb') as f:
        assert f.read() == text


def test_drive_list_refuses_a_rejected_path():
    """_path returning None is a REJECTION and every command must honour it.
    It used to be passed straight through to os.listdir(None), which does not
    raise -- it lists the host's current directory. The machine got a clean
    STATUS=0 and a count of the files in the project folder."""
    d = _drive()
    m = Machine([(2, 3) + (0,) * 14])
    d.mem = m.bus.ram
    for i, b in enumerate(b'../../../\x00'):
        d._poke(700 + i, b)
    d.reg[Drive.R_NAME] = 700
    d.reg[Drive.R_BUF] = 800
    for index in (0, 1, 9999):          # 9999 skipped the accidental raise
        d.reg[Drive.R_INDEX] = index
        d.write(Drive.R_CMD, Drive.C_LIST)
        assert d.reg[Drive.R_STATUS] != 0, f'INDEX={index}: rejected path listed something'
        assert d.reg[Drive.R_RESULT] == 0, f'INDEX={index}: leaked a host directory count'


def test_drive_list_still_works_for_real_paths():
    d = _drive()
    m = Machine([(2, 3) + (0,) * 14])
    d.mem = m.bus.ram
    d.reg[Drive.R_NAME] = 0            # no name = the drive root
    d.reg[Drive.R_BUF] = 800
    d.reg[Drive.R_INDEX] = 0
    d.write(Drive.R_CMD, Drive.C_LIST)
    assert d.reg[Drive.R_STATUS] == 0 and d.reg[Drive.R_RESULT] >= 1
    name = ''.join(chr(d.mem.peek(800 + i)) for i in range(16)).split('\x00')[0]
    assert name == 'ok.txt', f'listed {name!r}'


def test_drive_rejects_every_command_on_a_bad_path():
    d = _drive()
    m = Machine([(2, 3) + (0,) * 14])
    d.mem = m.bus.ram
    for i, b in enumerate(b'../machine2/secret.txt\x00'):
        d._poke(700 + i, b)
    d.reg[Drive.R_NAME] = 700
    d.reg[Drive.R_BUF] = 800
    d.reg[Drive.R_LEN] = 4
    for cmd in (Drive.C_SIZE, Drive.C_READ, Drive.C_WRITE, Drive.C_READW,
                Drive.C_LIST, Drive.C_DELETE, Drive.C_MKDIR):
        d.write(Drive.R_CMD, cmd)
        assert d.reg[Drive.R_STATUS] != 0, f'command {cmd} accepted a path outside the drive'
    assert os.path.exists(os.path.join(os.path.dirname(d.root), 'machine2', 'secret.txt')), \
        'the drive deleted a file outside itself'


def test_drive_reports_failure_rather_than_raising():
    """A device cannot throw a Python exception at the machine -- it has to
    report status, the way real hardware does."""
    d = _drive()
    m = Machine([(2, 3) + (0,) * 14])
    d.mem = m.bus.ram
    for i, b in enumerate(b'does-not-exist.txt\x00'):
        d._poke(700 + i, b)
    d.reg[Drive.R_NAME] = 700
    d.write(Drive.R_CMD, Drive.C_SIZE)
    assert d.reg[Drive.R_STATUS] != 0


# --- the GPU ------------------------------------------------------------

def test_gpu_clips_instead_of_crashing():
    """Nothing validates what a C program writes to the GPU's registers, so
    every command has to survive nonsense coordinates."""
    g = GPU()
    for cmd in range(8):
        for x, y, w, h in ((-50, -50, 10, 10), (250, 190, 999, 999),
                           (0, 0, 0, 0), (10, 10, 4, 4)):
            g.reg[GPU.R_X], g.reg[GPU.R_Y] = x, y
            g.reg[GPU.R_W], g.reg[GPU.R_H] = w, h
            g.reg[GPU.R_X2], g.reg[GPU.R_Y2] = x + 5, y + 5
            g.reg[GPU.R_COLOR] = 3
            g._exec(cmd)                      # must not raise
    assert g.fb.shape == (GPU.H, GPU.W)


def test_gpu_click_latch_is_consumed_once():
    """The CPU is far too slow to catch a press/release edge by polling, so the
    latch holds a click until read -- and must then clear, or one click reads as
    many."""
    g = GPU()
    g.set_click(10, 20)
    assert g.read(GPU.R_CLICK) == 1
    assert g.read(GPU.R_CLICK) == 0
    assert g.read(GPU.R_CLICKX) == 10 and g.read(GPU.R_CLICKY) == 20


def test_gpu_colour_is_always_in_palette():
    g = GPU()
    g.reg[GPU.R_COLOR] = 999
    g._exec(GPU.C_CLEAR)
    assert 0 <= int(g.fb.max()) < len(GPU.PALETTE)


def _blit_source(value=5, n=64):
    m = Machine([(2, 3) + (0,) * 14])
    for i in range(n):
        m.bus.ram.run(tuple((i // 4 ** k) % 4 for k in range(16)), 3,
                      tuple((value // 4 ** k) % 4 for k in range(16)))
    return m.bus.ram


def test_gpu_blit_draws_correctly():
    g = GPU()
    g.mem = _blit_source()
    g.reg[GPU.R_X], g.reg[GPU.R_Y] = 2, 3
    g.reg[GPU.R_W] = g.reg[GPU.R_H] = 4
    g.reg[GPU.R_ADDR] = 0
    g._exec(GPU.C_BLIT)
    assert int(g.fb[3, 2]) == 5 and int(g.fb[6, 5]) == 5, 'blit did not paint its rectangle'
    assert int(g.fb[2, 2]) == 0 and int(g.fb[3, 1]) == 0, 'blit painted outside itself'


def test_gpu_blit_clips_at_both_edges():
    for x, y in ((-2, -2), (GPU.W - 2, GPU.H - 2), (-100, 50), (50, -100)):
        g = GPU()
        g.mem = _blit_source()
        g.reg[GPU.R_X], g.reg[GPU.R_Y] = x, y
        g.reg[GPU.R_W] = g.reg[GPU.R_H] = 4
        g.reg[GPU.R_ADDR] = 0
        g._exec(GPU.C_BLIT)          # must not raise or wrap around the edges
    g = GPU()
    g.mem = _blit_source()
    g.reg[GPU.R_X], g.reg[GPU.R_Y] = -2, -2
    g.reg[GPU.R_W] = g.reg[GPU.R_H] = 4
    g.reg[GPU.R_ADDR] = 0
    g._exec(GPU.C_BLIT)
    assert int(g.fb[1, 1]) == 5, 'the on-screen part of a clipped blit vanished'
    assert int(g.fb[GPU.H - 1, GPU.W - 1]) == 0, 'a negative origin wrapped to the far edge'


def test_gpu_blit_cost_follows_the_visible_area():
    """Nothing validates W/H, so an absurd blit must cost what it draws, not what
    it was asked for. This used to walk w*h in Python: 1.4s for a 2000x2000 blit
    that can paint at most 256x192, freezing the emulator from a C program."""
    import time
    g = GPU()
    g.mem = _blit_source()
    g.reg[GPU.R_X] = g.reg[GPU.R_Y] = 0
    g.reg[GPU.R_W] = g.reg[GPU.R_H] = 2000
    g.reg[GPU.R_ADDR] = 0
    t = time.time()
    g._exec(GPU.C_BLIT)
    assert time.time() - t < 0.5, 'an oversized blit still walks the whole request'


# --- the load port ------------------------------------------------------

def test_loader_writes_code_memory_and_advances():
    ram = RAM6(8)
    ld = Loader()
    ld.code = ram
    ld.write_addr(2)
    ld.write_data(0)
    ld.write_data(1)
    assert ld.index == 4, 'the load port must auto-advance'


def test_loader_out_of_range_write_does_not_corrupt():
    """KNOWN LIMIT, pinned: the port silently ignores a write past the end of
    code memory rather than reporting it. It must at minimum not scribble on a
    valid cell."""
    ram = RAM6(4)
    ld = Loader()
    ld.code = ram
    before = [ram.mem.access(tuple((i // 4 ** k) % 4 for k in range(8)), 0)
              for i in range(4)]
    ld.write_addr(9)
    ld.write_data(0xFFFF)
    after = [ram.mem.access(tuple((i // 4 ** k) % 4 for k in range(8)), 0)
             for i in range(4)]
    assert before == after, 'a past-the-end load port write corrupted real code'


# --- the bus map --------------------------------------------------------

def test_every_address_routes_to_exactly_one_place():
    """RAM below, devices in a window, RAM again above. An address that both
    reads RAM and strobes a device would be a silent aliasing bug."""
    for addr in (0, 1, 228, Bus.DEV_BASE - 1, Bus.DEV_BASE, 255, 256,
                 Bus.GPU_BASE, Bus.GPU_TOP, Bus.DRV_BASE, Bus.DRV_TOP,
                 Bus.DEV_TOP, Bus.DEV_TOP + 1, 1024, 30000, 65535):
        is_device = Bus.DEV_BASE <= addr <= Bus.DEV_TOP
        assert (addr <= Bus.RAM_TOP or addr > Bus.DEV_TOP) == (not is_device), addr


def test_device_windows_do_not_overlap():
    assert Bus.GPU_TOP < Bus.DRV_BASE, 'the GPU and drive windows overlap'
    assert Bus.DEV_BASE <= Bus.GPU_BASE and Bus.DRV_TOP <= Bus.DEV_TOP
    assert Bus.RAM_TOP < Bus.DEV_BASE
    assert GPU.NREG >= (Bus.GPU_TOP - Bus.GPU_BASE + 1)
    assert Drive.NREG >= Drive.R_INDEX + 1
