"""
Run a C/C++ GUI program on the Quattro machine and show its GPU output.

    python gui_run.py c/gui_demo.cpp

The GPU is a device (plain Python, no pygame), so this front-end does three
things the device can't: it rasterizes an 8x8 font and uploads it, it scans the
framebuffer out to a window, and it feeds the pointer back in as GPU-pixel
mouse registers. Esc quits, F7 resets.
"""

import sys

import pygame

from ccompiler import build
from quattro import Machine

SCALE = 3
STEPS_PER_FRAME = 400      # CPU instructions between redraws


def rasterize_font():
    """Render ASCII 32..126 into 8x8 row-bitmasks for the GPU's TEXT command."""
    pygame.font.init()
    for name in ('consolas', 'couriernew', 'dejavusansmono', 'monospace'):
        try:
            f = pygame.font.SysFont(name, 8)
            if f is not None:
                break
        except Exception:
            continue
    table = {}
    for code in range(32, 127):
        surf = f.render(chr(code), False, (255, 255, 255), (0, 0, 0))
        w, h = surf.get_size()
        rows = []
        for j in range(8):
            bits = 0
            for i in range(8):
                if i < w and j < h and surf.get_at((i, j))[0] > 100:
                    bits |= (0x80 >> i)
            rows.append(bits)
        table[code] = tuple(rows)
    return table


class GuiRunner:
    """Two ways in. GuiRunner(files) compiles a C/C++ program and runs it
    directly -- the program IS the machine image. GuiRunner.boot(rom, ...) puts
    only a ROM in code memory and leaves room above it, so the machine has to
    find its own OS on the drive and load it: a real boot."""

    def __init__(self, files=None, code=None, data=None, title=None,
                 code_size=None, drive_root='machine'):
        if files:
            code, data = build(files)
            print(f"[compiled {', '.join(files)}: {len(code)} instructions]")
            title = ', '.join(files)
        self.code, self.data = code, data
        self.code_size, self.drive_root = code_size, drive_root
        self.m = self._new_machine()
        self.gpu = self.m.bus.gpu
        pygame.init()
        self.gpu.load_font(rasterize_font())
        self.win = pygame.display.set_mode(
            (self.gpu.W * SCALE, self.gpu.H * SCALE))
        pygame.display.set_caption('Quattro GPU — ' + (title or ''))
        self.surf = pygame.Surface((self.gpu.W, self.gpu.H))
        self.clock = pygame.time.Clock()
        self.palette = self.gpu.PALETTE
        self.prev_btn = 0

    @classmethod
    def boot(cls, rom, romdata, code_size=None, drive_root='machine'):
        return cls(code=rom, data=romdata, code_size=code_size,
                   drive_root=drive_root, title=f'boot ROM → {drive_root}/')

    def _new_machine(self):
        return Machine(self.code, data=self.data, code_size=self.code_size,
                       drive_root=self.drive_root)

    def reset(self):
        self.m = self._new_machine()
        self.gpu = self.m.bus.gpu
        self.gpu.load_font(rasterize_font())

    def pump(self):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return False
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return False
                if ev.key == pygame.K_F7:
                    self.reset()
                elif ev.unicode:
                    self.m.bus.keyboard.queue.append(ord(ev.unicode))
        mx, my = pygame.mouse.get_pos()
        buttons = pygame.mouse.get_pressed()
        mask = (1 if buttons[0] else 0) + (2 if buttons[2] else 0)
        px, py = mx // SCALE, my // SCALE
        self.gpu.set_mouse(px, py, mask)
        # latch the press->release edge: the machine is far too slow to catch it
        if self.prev_btn and not mask:
            self.gpu.set_click(px, py)
        self.prev_btn = mask
        return True

    def draw(self):
        fb = self.gpu.fb
        # palette -> RGB, then scale up to the window
        import numpy as np
        rgb = np.zeros((self.gpu.H, self.gpu.W, 3), dtype=np.uint8)
        for i, c in enumerate(self.palette):
            rgb[fb == i] = c
        pygame.surfarray.blit_array(self.surf, rgb.swapaxes(0, 1))
        pygame.transform.scale(self.surf, self.win.get_size(), self.win)
        pygame.display.flip()

    def run(self):
        running = True
        while running:
            running = self.pump()
            for _ in range(STEPS_PER_FRAME):
                if self.m.halted:
                    break
                self.m.step()
            self.draw()
            self.clock.tick(60)
        pygame.quit()


def main():
    files = [a for a in sys.argv[1:] if not a.startswith('-')]
    if not files:
        files = ['c/gui_demo.cpp']
    GuiRunner(files).run()


if __name__ == '__main__':
    main()
