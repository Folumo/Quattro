"""
Quattro emulator front-end: a pygame window showing the machine's console
display plus real-time internals, with keyboard and mouse wired into the
machine's devices.

    python emulator.py [program.asm]     (default: demo.asm)

If the program defines a `main` label it is linked after the BIOS (so
print_char / read_key work); otherwise it is loaded raw at address 0.

Controls:
    F5   pause / resume          F6   single step (while paused)
    F7   reset the machine       Esc  quit
    any other key                goes to the machine's keyboard
    mouse over the display       drives the machine's mouse ports
"""

import sys
import time

import pygame

from compiler import compile_asm
from quattro import Machine, from_word, to_word

# ---------------------------------------------------------------------------
# machine loading
# ---------------------------------------------------------------------------

DISK_IMAGE = {0: [ord(c) for c in "LOADED FROM DISK"] + [0]}


def load_program(path):
    src = open(path).read()
    has_main = any(line.split('--')[0].strip() == 'main:'
                   for line in src.split('\n'))
    if has_main:  # link with the BIOS, which jumps to main
        src = open('asm/bios.asm').read() + '\n' + src
    return compile_asm(src, return_labels=True)


# ---------------------------------------------------------------------------
# instruction decoding (for the live panel)
# ---------------------------------------------------------------------------

_ARITH = {0: 'ADD', 1: 'SUB', 2: 'MUL', 3: 'DIV'}
_LOGIC = {0: 'MIN', 1: 'MAX', 2: 'MOD', 3: 'NOT'}
_CODE = {0: 'LOAD', 1: 'STORE', 2: 'COPY', 3: 'HLT'}
_JCMP = {0: 'JCMP', 1: 'JZ', 2: 'JEQ', 3: 'JLT'}


def _rn(hi, lo):
    return f"R{lo + 4 * hi}"


def _pack(*quarters):
    """Little-endian base-4 quarters -> the number the CPU sees. Both operands
    below are packed this way; the slot COUNTS must match quattro/cpu.py, or the
    panel quietly reports a different number than the one the machine ran."""
    return sum(q * (4 ** i) for i, q in enumerate(quarters))


def decode(instr):
    if instr is None:
        return "--"
    OP, SUB, RNF0, RNF1, D0, D1, A0, A1, B0, B1, C2, C3, C4, C5, C6, C7 = instr
    dest, srca, srcb = _rn(D1, D0), _rn(A1, A0), _rn(B1, B0)
    imm = _pack(A0, A1, B0, B1, C2, C3, C4, C5, C6, C7)   # cpu.py: 10 quarters
    target = _pack(B0, B1, C2, C3, C4, C5, C6, C7)        # cpu.py: 8 quarters

    if OP in (0, 1):
        name = (_ARITH if OP == 0 else _LOGIC)[SUB]
        a = srca if RNF0 == 0 else f"F{A0 + 4 * A1}" if RNF0 == 1 else f"#{imm}"
        b = srcb if RNF1 == 0 else f"F{B0 + 4 * B1}" if RNF1 == 1 else f"#{imm}"
        return f"{name} {dest} <- {a},{b}"
    if OP == 2:
        if SUB == 0:
            if RNF1 == 3:
                return f"LOAD {dest}, [{srca}]"
            return f"LOAD {dest}, #{imm}"
        if SUB == 1:
            return f"STORE [{srca}], {srcb}"
        if SUB == 2:
            return f"COPY {dest}, {srca}"
        return "HLT"
    # OP == 3: functions
    if SUB == 3:
        return "RET"
    if SUB == 2:
        name = _JCMP.get(RNF1, 'JCMP')
        if RNF1 in (2, 3):
            return f"{name} {dest},{srca} -> {target}"
        return f"{name} {dest} -> {target}"
    name = 'CALL' if SUB == 0 else 'JMP'
    if RNF0 == 2:
        return f"{name} {target}"
    if RNF1 == 1:
        return f"{name} {srca},{srcb} (pair)"
    return f"{name} {srca}"


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

BG = (16, 17, 23)
PANEL = (26, 28, 38)
BORDER = (70, 76, 96)
TEXT = (200, 205, 215)
DIM = (110, 118, 138)
GREEN = (95, 235, 125)
SCREEN_BG = (7, 18, 9)
ACCENT = (240, 200, 90)
RED = (235, 95, 95)
BLUE = (110, 170, 250)

DISP_X, DISP_Y = 20, 60
PANEL_W = 440
FRAME_BUDGET = 0.014     # seconds of machine time per video frame


class Emulator:
    def __init__(self, path, disk=None):
        self.path = path
        self.disk_img = DISK_IMAGE if disk is None else disk
        self.code, self.data, self.labels = load_program(path)
        self.m = self.make_machine()

        pygame.init()
        # Adapt the cell size to the console dimensions so any screen (24x6 or
        # 40x16) fits a ~640px-wide display box, with panels to the right.
        cols, rows = self.m.bus.console.W, self.m.bus.console.H
        self.cw = max(10, min(640 // cols, 30))
        self.ch = int(self.cw * 1.4)
        disp_w, disp_h = cols * self.cw, rows * self.ch
        self.disp_rect = pygame.Rect(DISP_X, DISP_Y, disp_w, disp_h)
        self.panel_x = DISP_X + disp_w + 28
        self.mem_y = DISP_Y + disp_h + 30
        win_w = self.panel_x + PANEL_W + 12
        win_h = max(self.mem_y + 200, 648)
        self.win_w, self.win_h = win_w, win_h
        self.win = pygame.display.set_mode((win_w, win_h))
        pygame.display.set_caption(f"Quattro Emulator -- {path}")
        self.font = pygame.font.SysFont('consolas', 16)
        self.small = pygame.font.SysFont('consolas', 13)
        self.big = pygame.font.SysFont('consolas', max(10, self.ch - 6), bold=True)
        self.clock = pygame.time.Clock()

        self.running = True          # machine executing (False = paused)
        self.frames = 0
        self.rate_win = []           # (time, steps) samples for steps/sec
        self.mem_vals = {}           # incrementally scanned data memory
        self.mem_cursor = 0

    def make_machine(self):
        return Machine(self.code, data=self.data,
                       disk={s: list(v) for s, v in self.disk_img.items()})

    # -- input ---------------------------------------------------------------

    def handle_key(self, ev):
        if ev.key == pygame.K_ESCAPE:
            return False
        if ev.key == pygame.K_F5:
            if not self.m.halted:
                self.running = not self.running
        elif ev.key == pygame.K_F6:
            if not self.running and not self.m.halted:
                self.m.step()
        elif ev.key == pygame.K_F7:
            self.m = self.make_machine()
            self.running = True
            self.rate_win.clear()
            self.mem_vals.clear()
            self.mem_cursor = 0
        elif ev.key == pygame.K_RETURN:
            self.m.bus.keyboard.queue.append(10)
        elif ev.key == pygame.K_BACKSPACE:
            self.m.bus.keyboard.queue.append(8)
        elif ev.unicode and 32 <= ord(ev.unicode) < 127:
            self.m.bus.keyboard.queue.append(ord(ev.unicode))
        return True

    def update_mouse(self):
        mouse = self.m.bus.mouse
        mx, my = pygame.mouse.get_pos()
        if self.disp_rect.collidepoint(mx, my):
            mouse.x = (mx - self.disp_rect.x) // self.cw
            mouse.y = (my - self.disp_rect.y) // self.ch
        b = pygame.mouse.get_pressed(3)
        # only count clicks that happen over the machine's screen
        over = self.disp_rect.collidepoint(mx, my)
        mouse.buttons = (1 * b[0] + 2 * b[2]) if over else 0

    # -- machine driving -----------------------------------------------------

    def run_slice(self):
        if not self.running or self.m.halted:
            return
        deadline = time.perf_counter() + FRAME_BUDGET
        while time.perf_counter() < deadline:
            self.m.step()
            if self.m.halted:
                self.running = False
                break
        now = time.perf_counter()
        self.rate_win.append((now, self.m.steps))
        while self.rate_win and now - self.rate_win[0][0] > 2.0:
            self.rate_win.pop(0)

    def steps_per_sec(self):
        if len(self.rate_win) < 2:
            return 0
        (t0, s0), (t1, s1) = self.rate_win[0], self.rate_win[-1]
        return int((s1 - s0) / (t1 - t0)) if t1 > t0 else 0

    # -- reading machine state (debugger peeks, no writes) --------------------

    def reg(self, n):
        return from_word(self.m.var_reg.run(n % 4, n // 4, 0))

    def flag(self, n):
        return from_word(self.m.flag_reg.run(n % 4, n // 4, 0))

    def pc(self):
        d = self.m.ram.get_pc()
        return sum(v * (4 ** i) for i, v in enumerate(d))

    def scan_memory(self):
        # Sweep data memory a few addresses per frame through the real gate
        # read port (the full mux is slow, so scanning all 229 at once would
        # stall the GUI). A complete sweep takes ~2 seconds.
        for _ in range(3):
            a = self.mem_cursor
            v = from_word(self.m.bus.ram.run(to_word(a), 0))
            if v:
                self.mem_vals[a] = v
            else:
                self.mem_vals.pop(a, None)
            self.mem_cursor = (self.mem_cursor + 1) % (self.m.bus.RAM_TOP + 1)
        return sorted(self.mem_vals.items())

    # -- drawing ---------------------------------------------------------------

    def text(self, s, x, y, color=TEXT, font=None):
        self.win.blit((font or self.font).render(s, True, color), (x, y))

    def label(self, s, x, y):
        self.text(s, x, y, DIM, self.small)

    def draw_display(self):
        con = self.m.bus.console
        r = self.disp_rect
        pygame.draw.rect(self.win, SCREEN_BG, r)
        pygame.draw.rect(self.win, BORDER, r.inflate(8, 8), 2, border_radius=4)
        self.label("DISPLAY (console framebuffer)", r.x, r.y - 22)

        cw, ch = self.cw, self.ch
        for row in range(con.H):
            for col in range(con.W):
                c = con.buf[row][col]
                if 32 < c < 127:
                    g = self.big.render(chr(c), True, GREEN)
                    gx = r.x + col * cw + (cw - g.get_width()) // 2
                    gy = r.y + row * ch + (ch - g.get_height()) // 2
                    self.win.blit(g, (gx, gy))

        # blinking cursor at the console's write position
        if (self.frames // 25) % 2 == 0 and con.row < con.H:
            cx = r.x + con.col * cw
            cy = r.y + con.row * ch + ch - 5
            pygame.draw.rect(self.win, GREEN, (cx + 2, cy, cw - 4, 3))

        # pointer cell highlight
        mouse = self.m.bus.mouse
        mx, my = pygame.mouse.get_pos()
        if r.collidepoint(mx, my):
            hl = pygame.Rect(r.x + mouse.x * cw, r.y + mouse.y * ch, cw, ch)
            pygame.draw.rect(self.win, (60, 90, 70), hl, 1)

    def draw_panel(self):
        x = self.panel_x
        panel = pygame.Rect(x - 12, 12, self.win_w - x, self.win_h - 24)
        pygame.draw.rect(self.win, PANEL, panel, border_radius=6)
        pygame.draw.rect(self.win, BORDER, panel, 1, border_radius=6)

        # status line
        if self.m.halted:
            status, col = "HALTED", RED
        elif self.running:
            status, col = "RUNNING", GREEN
        else:
            status, col = "PAUSED", ACCENT
        self.text(status, x, 22, col)
        self.text(f"{self.steps_per_sec():,} instr/s", x + 110, 22, DIM)
        self.text(f"steps {self.m.steps:,}", x + 240, 22, DIM)

        # PC + last instruction
        self.label("PC / LAST INSTRUCTION", x, 52)
        self.text(f"{self.pc():4d}  {decode(self.m.last_instr)}", x, 70, BLUE)

        # registers
        self.label("REGISTERS", x, 102)
        for n in range(16):
            cx = x + (n // 8) * 180
            cy = 122 + (n % 8) * 20
            v = self.reg(n)
            color = TEXT if v else DIM
            self.text(f"R{n:<2}= {v:>3}", cx, cy, color)
            self.text(f"{v:02X}", cx + 105, cy, DIM, self.small)

        # flags (only the interesting ones)
        self.label("FLAGS", x, 292)
        shown = [(n, self.flag(n)) for n in range(16)]
        nz = [f"F{n}={v}" for n, v in shown if v]
        self.text("  ".join(nz) if nz else "(all clear)",
                  x, 310, ACCENT if nz else DIM)

        # devices
        bus = self.m.bus
        self.label("DEVICES", x, 342)
        self.text(f"timer  period={bus.timer.period} count={bus.timer.count}"
                  f" fired={int(bus.timer.fired)}", x, 360)
        q = bus.keyboard.queue
        qs = ' '.join(str(k) for k in q[:8]) + (' ...' if len(q) > 8 else '')
        self.text(f"kbd    queue=[{qs}]", x, 380)
        self.text(f"mouse  x={bus.mouse.x} y={bus.mouse.y}"
                  f" btn={bus.mouse.buttons}", x, 400)
        self.text(f"disk   pos={bus.disk.pos}", x, 420)
        self.text(f"int    enabled={int(bool(bus.int_en.get()))}"
                  f" vector={from_word(bus.int_vec.get())}", x, 440)

        # scheduler / OS
        if self.m.contexts is not None:
            self.label("SCHEDULER", x, 472)
            self.text(f"task {bus.sched_cur}/{bus.sched_n}"
                      f"  in-kernel={int(bus.os_masked)}"
                      f"  cause={bus.irq_cause}", x, 490)

        self.label("CALL STACK", x, 468)
        self.text(f"depth {self.m.stack.depth()}", x, 486)

        # disk filesystem (read the Disk storage directly -- it's plain Python)
        self.label("DISK FILES", x, 514)
        files = self.disk_files()
        if not files:
            self.text("(empty)", x, 532, DIM)
        for i, (name, body) in enumerate(files[:6]):
            self.text(f"{name}  {body}", x, 532 + i * 18, TEXT)

    def disk_files(self):
        # Decode shell.asm's filesystem: sectors 0-1 = 8 slots of 4-word names,
        # sector 2+i*4 = file i's content (chars until a 0).
        st = self.m.bus.disk.storage
        ss = self.m.bus.disk.sector_size
        out = []
        for i in range(8):
            nb = i * 4
            first = st[nb] if nb < len(st) else 0
            if not (32 < first < 127):
                continue
            name = ''
            for j in range(4):
                c = st[nb + j] if nb + j < len(st) else 0
                if c == 0:
                    break
                name += chr(c) if 32 <= c < 127 else '.'
            base = (2 + i * 4) * ss
            body = ''
            for j in range(64):
                if base + j >= len(st):
                    break
                c = st[base + j]
                if c == 0:
                    break
                body += chr(c) if 32 <= c < 127 else '.'
            out.append((name, body))
        return out

    def draw_memory(self):
        y0 = self.mem_y
        ncols = max(1, self.disp_rect.width // 106)
        maxn = ncols * ((self.win_h - y0 - 40) // 20)
        self.label("DATA MEMORY (non-zero cells)", DISP_X, y0)
        cells = self.scan_memory()
        if not cells:
            self.text("(all zero)", DISP_X, y0 + 20, DIM)
        for i, (addr, v) in enumerate(cells[:maxn]):
            cx = DISP_X + (i % ncols) * 106
            cy = y0 + 20 + (i // ncols) * 20
            self.text(f"[{addr:3d}]={v:3d}", cx, cy, TEXT)
        if len(cells) > maxn:
            self.text(f"...+{len(cells) - maxn}", DISP_X, self.win_h - 44, DIM)

    def draw_help(self):
        self.text("F5 pause/resume   F6 step   F7 reset   Esc quit   "
                  "type to send keys - click the display to send clicks",
                  DISP_X, self.win_h - 22, DIM, self.small)

    def draw(self):
        self.win.fill(BG)
        self.draw_display()
        self.draw_memory()
        self.draw_panel()
        self.draw_help()
        pygame.display.flip()

    # -- main loop -------------------------------------------------------------

    def run(self):
        alive = True
        while alive:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    alive = False
                elif ev.type == pygame.KEYDOWN:
                    alive = self.handle_key(ev) and alive
            self.update_mouse()
            self.run_slice()
            self.draw()
            self.frames += 1
            self.clock.tick(60)
        pygame.quit()


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'asm/demo.asm'
    Emulator(path).run()


if __name__ == '__main__':
    main()
