"""The boot chain: the machine finding its own OS on the drive and loading it.

The point of this test is that NOTHING about the OS is in the machine image. The
image is a ROM. So arriving at the OS's entry point at all is only possible if
the ROM really read bin/os.bin off the drive, streamed it through the load port
into code memory, and jumped to an address it read off a disk.
"""
import os
import shutil
import tempfile

from main import OS_BASE, build_os, build_rom
from qbin import build_bin, make_image, read_image, frame_to_word, word_to_frame
from quattro import Machine


def _pc(m):
    return sum(q * 4 ** k for k, q in enumerate(m.ram.get_pc()))


def _boot(drive_root='machine', max_steps=40000):
    _, entry, image, _ = read_image(open('machine/bin/os.bin', 'rb').read())
    rom, romdata = build_rom()
    m = Machine(rom, data=romdata, code_size=OS_BASE + len(image) + 16,
                drive_root=drive_root)
    while _pc(m) < OS_BASE and m.steps < max_steps and not m.halted:
        m.step()
    return m, entry, image


# --- the executable format ----------------------------------------------

def test_frame_word_round_trip():
    """One 32-bit word IS one 16-quarter instruction frame. That identity is the
    whole reason loading a program is a straight copy."""
    for w in (0, 1, 2**31, 2**32 - 1, 0x54415551):
        assert frame_to_word(word_to_frame(w)) == w


def test_image_round_trip():
    code = [tuple((i + k) % 4 for k in range(16)) for i in range(20)]
    data = {1024: 65, 1025: 66, 40000: 999}
    blob = make_image(code, data, base=512, entry=522)
    base, entry, got_code, got_data = read_image(blob)
    assert (base, entry) == (512, 522)
    assert got_code == code
    assert got_data == data


def test_bad_magic_is_rejected():
    try:
        read_image(b'not a quattro executable at all!')
    except ValueError:
        return
    raise AssertionError('read_image accepted a non-executable')


def test_build_bin_links_at_base():
    blob, ncode = build_bin(['c/os.cpp'], base=OS_BASE)
    base, entry, code, _ = read_image(blob)
    assert base == OS_BASE and len(code) == ncode
    assert OS_BASE <= entry < OS_BASE + ncode, 'entry point is outside the image'
test_build_bin_links_at_base.slow = True


# --- the ROM ------------------------------------------------------------

def test_code_size_beyond_the_pc_is_rejected():
    """Cells past the PC's reach are not merely wasted: instruction index 65536
    truncates to 0 and aliases onto the reset vector."""
    rom, romdata = build_rom()
    try:
        Machine(rom, data=romdata, code_size=70000)
    except ValueError:
        pass
    else:
        raise AssertionError('Machine accepted more code memory than the PC can address')
    Machine(rom, data=romdata, code_size=65536)      # the exact limit is fine


def test_rom_fits_below_the_os():
    rom, _ = build_rom()
    assert len(rom) <= OS_BASE, (
        f'the ROM is {len(rom)} instructions and would overflow into the OS '
        f'load area at {OS_BASE}')


def test_machine_image_contains_no_os():
    """If this ever fails, the OS got linked into the ROM and the boot is a lie."""
    rom, _ = build_rom()
    _, _, image, _ = read_image(open('machine/bin/os.bin', 'rb').read())
    assert len(rom) < len(image), 'the ROM is as big as the OS -- is it in there?'
test_machine_image_contains_no_os.slow = True


# --- the whole chain ----------------------------------------------------

def test_rom_boots_the_os_off_the_drive():
    build_os()
    m, entry, image = _boot()
    assert _pc(m) == entry, (
        f'the ROM did not reach the OS entry point: stopped at {_pc(m)}, '
        f'wanted {entry}, halted={m.halted} after {m.steps} steps')
test_rom_boots_the_os_off_the_drive.slow = True


def test_loaded_code_matches_the_file_exactly():
    """Every instruction the ROM wrote into code memory must be the one on disk.
    A single wrong quarter is a program that runs and does the wrong thing."""
    build_os()
    m, _, image = _boot()
    for i, frame in enumerate(image):
        addr = tuple(((OS_BASE + i) // 4 ** k) % 4 for k in range(8))
        assert m.ram.mem.access(addr, 0) == frame, f'code memory differs at +{i}'
test_loaded_code_matches_the_file_exactly.slow = True


def test_machine_reports_a_drive_with_no_os():
    """Delete the OS and the machine must say so, not hang or run garbage."""
    build_os()
    tmp = tempfile.mkdtemp()
    empty = os.path.join(tmp, 'empty')
    os.makedirs(empty)
    with open(os.path.join(empty, 'nothing.txt'), 'w') as f:
        f.write('no OS here')
    m, _, _ = _boot(drive_root=empty, max_steps=8000)
    assert m.halted, 'a driveless machine should stop, not run off into nothing'
    assert m.bus.gpu.frames > 0, 'it should have said something on screen'
    shutil.rmtree(tmp, ignore_errors=True)
test_machine_reports_a_drive_with_no_os.slow = True


def test_machine_rejects_a_corrupt_os():
    build_os()
    tmp = tempfile.mkdtemp()
    bad = os.path.join(tmp, 'bad')
    os.makedirs(os.path.join(bad, 'bin'))
    with open(os.path.join(bad, 'bin', 'os.bin'), 'wb') as f:
        f.write(b'this is not a QUAT image' * 8)
    m, _, _ = _boot(drive_root=bad, max_steps=8000)
    assert m.halted, 'a corrupt OS should be caught by the ROM magic check'
    shutil.rmtree(tmp, ignore_errors=True)
test_machine_rejects_a_corrupt_os.slow = True


def test_os_writes_its_boot_log_to_the_real_disk():
    """The drive is read/write and the OS proves it every boot."""
    build_os()
    log = os.path.join('machine', 'boot.log')
    if os.path.exists(log):
        os.remove(log)
    _, entry, image = read_image(open('machine/bin/os.bin', 'rb').read()), None, None
    rom, romdata = build_rom()
    _, _, img, _ = read_image(open('machine/bin/os.bin', 'rb').read())
    m = Machine(rom, data=romdata, code_size=OS_BASE + len(img) + 16)
    for _ in range(60000):
        if m.halted or os.path.exists(log):
            break
        m.step()
    assert os.path.exists(log), 'the OS never wrote boot.log to the host disk'
    with open(log) as f:
        assert 'QuattroOS' in f.read()
test_os_writes_its_boot_log_to_the_real_disk.slow = True
