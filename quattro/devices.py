"""I/O devices -- the "outside world", modelled directly in Python
(not built from our gates). Each answers to a fixed bus address."""

import os

import numpy as np


class Loader:
    """The program-load port -- how code gets INTO code memory at run time.

    This machine is Harvard: code memory is separate from data and a running
    program cannot write it, so without this port a boot ROM could never read an
    OS off the drive and jump to it. Real hardware has the same problem and the
    same answer (a flash-programming port / a bootstrap loader).

    The convenient part: a 32-bit word is exactly 16 quarters, which is exactly
    one instruction frame -- so a program streams in at one word per
    instruction. Write CODE_ADDR to pick the instruction index, then write each
    instruction word to CODE_DATA; the index auto-advances.
    """

    def __init__(self):
        self.code = None      # the RAM6, wired up by Machine
        self.index = 0

    def write_addr(self, val, en=3):
        if en:
            self.index = val

    def write_data(self, val, en=3):
        if not en or self.code is None:
            return
        frame = tuple((val // (4 ** k)) % 4 for k in range(16))   # word == frame
        addr = tuple((self.index // (4 ** k)) % 4 for k in range(8))
        self.code.load(*addr, *frame)
        self.index += 1


class GPU:
    """A command-driven graphics device -- a blitter, in the spirit of the Amiga
    blitter or a TMS9918 VDP.

    The CPU runs about 1400 instructions/second, so it could never paint a
    49k-pixel frame one pixel at a time (that would take a minute). Instead the
    CPU writes a handful of registers and then writes CMD; the *device* does the
    pixel work. TEXT and BLIT go further and DMA their string / sprite straight
    out of data memory, so the CPU only ever hands over an address.

    Registers are memory-mapped at GPU_BASE (see Bus); writing R_CMD executes a
    command against the current register values. Reads of MX/MY/BTN give the
    pointer in framebuffer pixels (the front-end keeps them updated).
    """

    W, H = 256, 192

    # register indices, relative to the GPU's base address
    (R_CMD, R_X, R_Y, R_W, R_H, R_COLOR, R_ADDR, R_X2, R_Y2,
     R_MX, R_MY, R_BTN, R_STATUS, R_CLICK, R_CLICKX, R_CLICKY) = range(16)
    NREG = 32

    # command opcodes written to R_CMD
    (C_CLEAR, C_PIXEL, C_RECT, C_FRAME, C_LINE, C_CIRCLE,
     C_TEXT, C_BLIT) = range(8)

    PALETTE = [
        (0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170),
        (170, 0, 0), (170, 0, 170), (170, 85, 0), (170, 170, 170),
        (85, 85, 85), (85, 85, 255), (85, 255, 85), (85, 255, 255),
        (255, 85, 85), (255, 85, 255), (255, 255, 85), (255, 255, 255),
    ]

    def __init__(self):
        self.fb = np.zeros((self.H, self.W), dtype=np.uint8)
        self.reg = [0] * self.NREG
        self.mem = None      # data memory, for DMA (wired up by Machine)
        self.font = {}       # char code -> 8 row bitmasks (front-end uploads)
        self.frames = 0      # bumped on every command, so the GUI can redraw

    # -- front-end helpers -------------------------------------------------
    def load_font(self, table):
        """table: {char_code: (8 row bitmasks, bit 7 = leftmost pixel)}"""
        self.font = dict(table)

    def set_mouse(self, x, y, buttons):
        self.reg[self.R_MX] = max(0, min(self.W - 1, int(x)))
        self.reg[self.R_MY] = max(0, min(self.H - 1, int(y)))
        self.reg[self.R_BTN] = int(buttons)

    def set_click(self, x, y):
        """Latch a completed click. The CPU is far too slow to catch a
        press/release edge by polling, so the device remembers it until the
        program consumes it -- the same trick as the keyboard queue."""
        self.reg[self.R_CLICK] = 1
        self.reg[self.R_CLICKX] = max(0, min(self.W - 1, int(x)))
        self.reg[self.R_CLICKY] = max(0, min(self.H - 1, int(y)))

    # -- bus interface -----------------------------------------------------
    def read(self, r, en=3):
        if not en or r >= self.NREG:
            return 0
        if r == self.R_STATUS:
            return 1                      # always ready (commands are instant)
        if r == self.R_CLICK:             # consuming read: latch clears
            v = self.reg[r]
            self.reg[r] = 0
            return v
        return self.reg[r]

    def write(self, r, val, en=3):
        if not en or r >= self.NREG:
            return
        self.reg[r] = val
        if r == self.R_CMD:
            self._exec(val)
            self.frames += 1

    # -- command engine ----------------------------------------------------
    def _exec(self, cmd):
        g = self.reg
        x, y, w, h = g[self.R_X], g[self.R_Y], g[self.R_W], g[self.R_H]
        col = g[self.R_COLOR] % 16
        if cmd == self.C_CLEAR:
            self.fb[:, :] = col
        elif cmd == self.C_PIXEL:
            self._px(x, y, col)
        elif cmd == self.C_RECT:
            self._rect(x, y, w, h, col)
        elif cmd == self.C_FRAME:
            self._rect(x, y, w, 1, col)
            self._rect(x, y + h - 1, w, 1, col)
            self._rect(x, y, 1, h, col)
            self._rect(x + w - 1, y, 1, h, col)
        elif cmd == self.C_LINE:
            self._line(x, y, g[self.R_X2], g[self.R_Y2], col)
        elif cmd == self.C_CIRCLE:
            self._circle(x, y, g[self.R_X2], col)
        elif cmd == self.C_TEXT:
            self._text(x, y, g[self.R_ADDR], col)
        elif cmd == self.C_BLIT:
            self._blit(x, y, w, h, g[self.R_ADDR])

    def _px(self, x, y, col):
        if 0 <= x < self.W and 0 <= y < self.H:
            self.fb[y, x] = col

    def _rect(self, x, y, w, h, col):
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.W, x + w), min(self.H, y + h)
        if x1 > x0 and y1 > y0:
            self.fb[y0:y1, x0:x1] = col

    def _line(self, x0, y0, x1, y1, col):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self._px(x0, y0, col)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def _circle(self, cx, cy, r, col):
        x, y, d = r, 0, 1 - r
        while x >= y:
            for px, py in ((x, y), (y, x), (-x, y), (-y, x),
                           (-x, -y), (-y, -x), (x, -y), (y, -x)):
                self._px(cx + px, cy + py, col)
            y += 1
            if d < 0:
                d += 2 * y + 1
            else:
                x -= 1
                d += 2 * (y - x) + 1

    def _glyph(self, x, y, code, col):
        rows = self.font.get(code)
        if not rows:
            return
        for j, bits in enumerate(rows):
            for i in range(8):
                if bits & (0x80 >> i):
                    self._px(x + i, y + j, col)

    def _text(self, x, y, addr, col):
        if self.mem is None:
            return
        for _ in range(256):                       # sanity bound
            c = self.mem.peek(addr)
            if c == 0:
                break
            self._glyph(x, y, c, col)
            x += 8
            addr += 1

    def _blit(self, x, y, w, h, addr):
        # Clip the region BEFORE walking it, not per pixel. Nothing validates
        # what a C program writes to W/H, and the old loop ran w*h times however
        # little of that landed on screen -- a 2000x2000 blit spent 1.4s in
        # Python to paint at most 256x192. A real blitter walks the clipped
        # rectangle; so does this now.
        if self.mem is None:
            return
        for j in range(max(0, -y), min(h, self.H - y)):
            row = addr + j * w
            for i in range(max(0, -x), min(w, self.W - x)):
                self.fb[y + j, x + i] = self.mem.peek(row + i) % 16


class Drive:
    """A real drive: a host folder (default `machine/`) that the machine can
    read AND write. Files and subfolders in it are the machine's filesystem, so
    a compiled program dropped in there is genuinely on the disk, and anything
    the OS writes really lands on your disk.

    File-level rather than sector-level, because the host folder already IS the
    filesystem -- there is nothing to be gained by pretending it is a platter.
    The machine names a file by putting a null-terminated path in RAM and
    pointing NAME at it; data moves through a RAM buffer at BUF.

    Registers (relative to DRV_BASE), commands written to CMD:
        0 CMD     1 STATUS  2 NAME   3 BUF    4 LEN    5 POS   6 RESULT  7 INDEX
      CMD 0 SIZE   -> RESULT = file size in bytes (STATUS 1 if missing)
      CMD 1 READ   -> read LEN bytes from POS into BUF, one byte per word;
                      RESULT = bytes actually read
      CMD 2 WRITE  -> write LEN bytes from BUF at POS (extends/creates the file)
      CMD 3 READW  -> read LEN 32-bit little-endian words from POS into BUF
                      (this is how an executable is loaded)
      CMD 4 LIST   -> name of directory entry INDEX into BUF; RESULT = count
      CMD 5 DELETE -> remove the named file
      CMD 6 MKDIR  -> create the named directory
    """

    (R_CMD, R_STATUS, R_NAME, R_BUF, R_LEN, R_POS, R_RESULT, R_INDEX) = range(8)
    NREG = 16
    (C_SIZE, C_READ, C_WRITE, C_READW, C_LIST, C_DELETE, C_MKDIR) = range(7)

    def __init__(self, root='machine'):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self.reg = [0] * self.NREG
        self.mem = None       # data memory, wired up by Machine

    # -- helpers -----------------------------------------------------------
    def _str_at(self, addr):
        out = []
        for _ in range(256):
            c = self.mem.peek(addr)
            if c == 0:
                break
            out.append(chr(c & 0xFF))
            addr += 1
        return ''.join(out)

    def _path(self, name):
        # Keep the machine inside its own drive: no escaping via .. or absolutes.
        # The containment test compares path COMPONENTS, not string prefixes --
        # a prefix test lets root="/x/machine" reach "/x/machine2/secret",
        # because that really does start with "/x/machine".
        p = os.path.normpath(os.path.join(self.root, name.lstrip('/\\')))
        if p != self.root and not p.startswith(self.root + os.sep):
            return None
        return p

    def _poke(self, addr, val):
        self.mem.run(tuple((addr // (4 ** k)) % 4 for k in range(16)), 3,
                     tuple((val // (4 ** k)) % 4 for k in range(16)))

    # -- bus interface -----------------------------------------------------
    def read(self, r, en=3):
        if not en or r >= self.NREG:
            return 0
        return self.reg[r]

    def write(self, r, val, en=3):
        if not en or r >= self.NREG:
            return
        self.reg[r] = val
        if r == self.R_CMD:
            self._exec(val)

    def _exec(self, cmd):
        if self.mem is None:
            return
        g = self.reg
        g[self.R_STATUS] = 0
        name = self._str_at(g[self.R_NAME]) if g[self.R_NAME] else ''
        path = self._path(name)
        if path is None:
            # _path said no. Refuse HERE, explicitly. Letting a rejected name
            # through as None and trusting it to blow up inside the except below
            # is not a check: os.listdir(None) does not raise, it lists the
            # host's current directory, and the machine learns what is in it.
            g[self.R_STATUS] = 1
            g[self.R_RESULT] = 0
            return
        try:
            if cmd == self.C_SIZE:
                g[self.R_RESULT] = os.path.getsize(path)
            elif cmd == self.C_READ:
                with open(path, 'rb') as f:
                    f.seek(g[self.R_POS])
                    data = f.read(g[self.R_LEN])
                for i, b in enumerate(data):
                    self._poke(g[self.R_BUF] + i, b)
                g[self.R_RESULT] = len(data)
            elif cmd == self.C_READW:
                with open(path, 'rb') as f:
                    f.seek(g[self.R_POS])
                    data = f.read(g[self.R_LEN] * 4)
                n = len(data) // 4
                for i in range(n):
                    self._poke(g[self.R_BUF] + i,
                               int.from_bytes(data[i * 4:i * 4 + 4], 'little'))
                g[self.R_RESULT] = n
            elif cmd == self.C_WRITE:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                if not os.path.exists(path):
                    open(path, 'wb').close()
                with open(path, 'r+b') as f:
                    f.seek(g[self.R_POS])
                    f.write(bytes(self.mem.peek(g[self.R_BUF] + i) & 0xFF
                                  for i in range(g[self.R_LEN])))
                g[self.R_RESULT] = g[self.R_LEN]
            elif cmd == self.C_LIST:
                base = path if name else self.root
                entries = sorted(os.listdir(base))
                g[self.R_RESULT] = len(entries)
                if g[self.R_INDEX] < len(entries):
                    e = entries[g[self.R_INDEX]]
                    if os.path.isdir(os.path.join(base, e)):
                        e = e + '/'
                    for i, ch in enumerate(e):
                        self._poke(g[self.R_BUF] + i, ord(ch))
                    self._poke(g[self.R_BUF] + len(e), 0)
            elif cmd == self.C_DELETE:
                os.remove(path)
            elif cmd == self.C_MKDIR:
                os.makedirs(path, exist_ok=True)
            else:
                g[self.R_STATUS] = 2
        except Exception:
            g[self.R_STATUS] = 1          # any failure: STATUS != 0


class Console:
    """A character screen with an internal framebuffer and an auto cursor.

    Writing a character code to the CON_OUT port prints it at the cursor and
    advances (a teletype-style text display). This is the framebuffer a real
    video circuit would scan out to a monitor.
    """

    def __init__(self, width=40, height=16):
        self.W, self.H = width, height
        self.buf = [[0] * width for _ in range(height)]
        self.row = self.col = 0

    def putc(self, c, en=3):
        if not en:   # chip-select strobe from the bus (a device is exempt)
            return
        if c == 10:  # newline
            self.row, self.col = self.row + 1, 0
        elif c == 8:  # backspace: step back and blank the cell
            if self.col > 0:
                self.col -= 1
            elif self.row > 0:
                self.row, self.col = self.row - 1, self.W - 1
            self.buf[self.row][self.col] = 0
        else:
            if self.row < self.H:
                self.buf[self.row][self.col] = c
            self.col += 1
            if self.col >= self.W:
                self.row, self.col = self.row + 1, 0
        if self.row >= self.H:  # scroll up one line
            self.buf.pop(0)
            self.buf.append([0] * self.W)
            self.row = self.H - 1

    def ctrl(self, cmd, en=3):
        if en and cmd == 0:  # clear screen, home the cursor
            self.buf = [[0] * self.W for _ in range(self.H)]
            self.row = self.col = 0

    def render(self):
        rows = []
        for r in self.buf:
            rows.append(''.join(chr(c) if 32 <= c < 127 else ' ' for c in r).rstrip())
        return '\n'.join(rows)


class Keyboard:
    """A key buffer. Keys queued here arrive as input; reading KBD_DATA pops the
    next one. While the buffer is non-empty the device asserts its interrupt."""

    def __init__(self, keys=None):
        self.queue = list(keys or [])

    def ready(self):
        return len(self.queue) > 0

    def pop(self, en=3):
        # only advance the queue when the bus actually selects KBD_DATA
        return self.queue.pop(0) if (en and self.queue) else 0


class Timer:
    """A programmable interval timer. Set a period (in clock ticks) and it
    raises an interrupt every `period` ticks until acknowledged. A tick here is
    one executed instruction -- the machine's clock."""

    def __init__(self):
        self.period = 0    # 0 = disabled
        self.count = 0
        self.fired = False

    def set_period(self, p, en=3):
        if en:
            self.period, self.count, self.fired = p, 0, False

    def ack(self, en=3):
        if en:
            self.fired = False

    def tick(self):
        if self.period > 0:
            self.count += 1
            if self.count >= self.period:
                self.count = 0
                self.fired = True


class Mouse:
    """A pointing device: current position (in console character cells) and a
    button bitmask (1 = left, 2 = right). The emulator front-end updates these;
    programs poll the MOUSE_X / MOUSE_Y / MOUSE_BTN ports."""

    def __init__(self):
        self.x = 0
        self.y = 0
        self.buttons = 0


class Disk:
    """
    Block-storage device: `sectors` sectors of `sector_size` words each. A
    program selects a sector (DISK_SECTOR), then streams words through DISK_DATA
    -- reading or writing -- with the position auto-advancing, like PIO-mode
    disk access. Contents persist for the run and can be seeded at power-on
    (e.g. a boot sector). `image` is {sector: [words]}.
    """

    def __init__(self, sectors=64, sector_size=16, image=None):
        self.sector_size = sector_size
        self.storage = [0] * (sectors * sector_size)
        self.pos = 0
        for sec, words in (image or {}).items():
            base = sec * sector_size
            for i, w in enumerate(words):
                if base + i < len(self.storage):
                    self.storage[base + i] = w

    def set_sector(self, s, en=3):
        if en:
            self.pos = min(s * self.sector_size, len(self.storage))

    def read(self, en=3):
        if not en:
            return 0
        v = self.storage[self.pos] if self.pos < len(self.storage) else 0
        self.pos = min(self.pos + 1, len(self.storage))
        return v

    def write(self, v, en=3):
        if en and self.pos < len(self.storage):
            self.storage[self.pos] = v
            self.pos += 1
