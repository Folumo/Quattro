"""The address decoder + interconnect, plus its control latches.

Built from gates: one-hot port decode (EQ/MIN), RAM/device split
(WGE), a WSEL/WOR read mux, and enable-strobed device/latch writes."""

from .gates import EQ, MAX, MIN
from .words import (ONE_WORD, WEQ, WGE, WOR, WSEL, WSUB, ZERO_WORD, from_word,
                    to_word)

class Latch:
    """A value-holding latch (a hardware register): updates on a strobed write.
    A storage class, like ST -- the enable-gate lives inside it."""

    def __init__(self, v=0):
        self.v = v

    def set(self, v, en):
        if en:
            self.v = v

    def get(self):
        return self.v


class Reg:
    """A request latch: a value plus a `pending` strobe, raised on a strobed
    write and lowered by the consumer. Used for the syscall / resume / context
    signals the run loop services. A storage class."""

    def __init__(self):
        self.v = 0
        self.pending = 0

    def set(self, v, en):
        if en:
            self.v = v
            self.pending = 3

    def clear(self):
        self.pending = 0

    def get(self):
        return self.v


class Bus:
    """
    Address decoder + interconnect, built from gates. Every access drives the
    one-hot port decode (EQ/MIN) and the RAM/device split (WGE); reads are a
    WSEL/WOR mux, writes drive each device / control latch through an enable
    strobe (the device gates its own side effect).

    The map: 0..228 is zero-page data RAM, 229..303 is the memory-mapped device
    window (single ports up to 255, then the GPU's 32-register window and the
    drive's 16), and RAM resumes at 304 for high memory.
    """

    RAM_TOP = 228
    DEV_BASE = 229      # first device address
    DEV_TOP = 303       # last device address; RAM resumes at 304 (high memory)
    GPU_BASE = 256      # the GPU's register window, 256..287 (32 registers)
    GPU_TOP = 287
    DRV_BASE = 288      # the drive's register window, 288..303
    DRV_TOP = 303
    MOUSE_X = 229       # read: pointer column (console character cells)
    MOUSE_Y = 230       # read: pointer row
    MOUSE_BTN = 231     # read: button bitmask (1 = left, 2 = right)
    SYSCALL = 232       # write num: software trap into the kernel (a syscall)
    IRQ_CAUSE = 233     # read: why the kernel was entered (0 = timer, else syscall)
    SYSARG = 234        # read/write: the syscall argument (low word)
    CTX_SEL = 235       # write: select a task slot for context setup
    CTX_SETPC = 236     # write low: init selected slot's PC (low+high), regs = 0
    CTX_SETPC_HI = 237  # write high: high part of the next CTX_SETPC address
    INT_VECTOR_HI = 238 # write high: high part of the interrupt vector
    SYSARG_HI = 239     # read/write: high part of the syscall argument
    DISK_SECTOR = 240   # write: select a sector (resets the transfer position)
    DISK_DATA = 241     # read/write: stream a word to/from the current position
    DISK_STATUS = 242   # read: 1 = ready (always, in the sim)
    SCHED_CUR = 243     # read: id of the currently running task
    SCHED_N = 244       # read: number of tasks
    SCHED_RESUME = 245  # write: switch to task id (restores its context)
    CODE_ADDR = 246     # write: select the instruction index to load at
    CODE_DATA = 247     # write: store one instruction word there; index++
    TIMER_PERIOD = 248  # write: interrupt every N ticks (0 = off)
    TIMER_CTRL = 249    # write: acknowledge/clear; read: 1 if fired
    KBD_DATA = 250      # read: next key code (pops it)
    KBD_STATUS = 251    # read: 1 if a key is waiting, else 0
    CON_OUT = 252       # write: print a character to the console
    CON_CTRL = 253      # write: console command (0 = clear screen)
    INT_ENABLE = 254    # write: 0 = mask interrupts, non-zero = enable
    INT_VECTOR = 255    # write: handler address (interrupts jump here)

    def __init__(self, ram, console, keyboard, timer, disk, mouse, gpu=None,
                 drive=None, loader=None):
        self.ram = ram
        self.console = console
        self.keyboard = keyboard
        self.timer = timer
        self.disk = disk
        self.mouse = mouse
        self.gpu = gpu
        self.drive = drive
        self.loader = loader
        # program-writable control registers, as storage latches
        self.int_en = Latch(0)           # interrupts enabled (non-zero)
        self.int_vec = Latch(ZERO_WORD)  # interrupt vector (low word)
        self.int_vec_hi = Latch((0, 0))  # interrupt vector (high quarters)
        self.sysarg = Latch(ZERO_WORD)   # syscall argument (low word)
        self.sysarg_hi = Latch(ZERO_WORD)   # syscall argument (high word)
        self.ctx_sel = Latch(0)          # task slot for context setup
        self.ctx_pc_hi = Latch(0)        # high part of the next CTX_SETPC
        self.syscall = Reg()             # a task trapped into the kernel
        self.resume = Reg()              # kernel asked to switch tasks
        self.ctx_req = Reg()             # kernel asked to init a context (low PC)
        # scheduler state the run loop owns (not program-writable, so plain ints)
        self.sched_n = 0
        self.sched_cur = 0
        self.irq_cause = 0        # 0 = timer, else the syscall number
        self.os_masked = False    # true while the kernel is running (no preempt)

    def _sel(self, addr, port):
        # one-hot decode line: 3 when the FULL address equals `port`, else 0.
        # A device port matches only its exact low address with zero high
        # quarters, so high memory (>=256) never aliases a device.
        return WEQ(addr, to_word(port))

    def _gpu_sel(self, addr, En):
        # the GPU answers to a whole window (256..287) rather than one port
        ge = WGE(addr, to_word(self.GPU_BASE))
        le = WGE(to_word(self.GPU_TOP), addr)
        return MIN(En, MIN(ge, le))

    def _gpu_reg(self, addr):
        borrow, idx = WSUB(addr, to_word(self.GPU_BASE))   # register index
        return from_word(idx)

    def _drv_sel(self, addr, En):
        ge = WGE(addr, to_word(self.DRV_BASE))
        le = WGE(to_word(self.DRV_TOP), addr)
        return MIN(En, MIN(ge, le))

    def _drv_reg(self, addr):
        borrow, idx = WSUB(addr, to_word(self.DRV_BASE))
        return from_word(idx)

    def _ram_enable(self, addr, En):
        # RAM is everything outside the device window (so 0..228 zero-page and
        # 304+ high memory both read/write RAM).
        d_ge = WGE(addr, to_word(self.DEV_BASE))    # addr >= 229
        d_le = WGE(to_word(self.DEV_TOP), addr)     # addr <= 303
        return MIN(En, EQ(MIN(d_ge, d_le), 0))

    def read(self, addr, En=3):
        # `addr` is a full word. En is the CPU's read strobe. The RAM/device
        # split and port decode are gates; the source's word is muxed onto the bus.
        ram_out = WSEL(self._ram_enable(addr, En), self.ram.run(addr, 0))

        s_mx = MIN(En, self._sel(addr, self.MOUSE_X))
        s_my = MIN(En, self._sel(addr, self.MOUSE_Y))
        s_mb = MIN(En, self._sel(addr, self.MOUSE_BTN))
        s_kd = MIN(En, self._sel(addr, self.KBD_DATA))
        s_ks = MIN(En, self._sel(addr, self.KBD_STATUS))
        s_tc = MIN(En, self._sel(addr, self.TIMER_CTRL))
        s_dd = MIN(En, self._sel(addr, self.DISK_DATA))
        s_ds = MIN(En, self._sel(addr, self.DISK_STATUS))
        s_sc = MIN(En, self._sel(addr, self.SCHED_CUR))
        s_sn = MIN(En, self._sel(addr, self.SCHED_N))
        s_ic = MIN(En, self._sel(addr, self.IRQ_CAUSE))
        s_sa = MIN(En, self._sel(addr, self.SYSARG))
        s_sh = MIN(En, self._sel(addr, self.SYSARG_HI))

        out = WOR(ram_out, WSEL(s_mx, to_word(self.mouse.x)))
        out = WOR(out, WSEL(s_my, to_word(self.mouse.y)))
        out = WOR(out, WSEL(s_mb, to_word(self.mouse.buttons)))
        out = WOR(out, WSEL(s_kd, to_word(self.keyboard.pop(s_kd))))
        out = WOR(out, WSEL(s_ks, to_word(self.keyboard.ready())))
        out = WOR(out, WSEL(s_tc, to_word(self.timer.fired)))
        out = WOR(out, WSEL(s_dd, to_word(self.disk.read(s_dd))))
        out = WOR(out, WSEL(s_ds, ONE_WORD))
        out = WOR(out, WSEL(s_sc, to_word(self.sched_cur)))
        out = WOR(out, WSEL(s_sn, to_word(self.sched_n)))
        out = WOR(out, WSEL(s_ic, to_word(self.irq_cause)))
        out = WOR(out, WSEL(s_sa, self.sysarg.get()))
        out = WOR(out, WSEL(s_sh, self.sysarg_hi.get()))
        s_gpu = self._gpu_sel(addr, En)
        out = WOR(out, WSEL(s_gpu,
                            to_word(self.gpu.read(self._gpu_reg(addr), s_gpu))))
        s_drv = self._drv_sel(addr, En)
        out = WOR(out, WSEL(s_drv,
                            to_word(self.drive.read(self._drv_reg(addr), s_drv))))
        return out

    def write(self, addr, word, En=3):
        # Every device and control latch is driven every cycle; its enable
        # strobe (port-select AND the write enable) gates whether it updates.
        val = from_word(word)
        self.ram.run(addr, self._ram_enable(addr, En), word)

        self.console.putc(val, MIN(En, self._sel(addr, self.CON_OUT)))
        self.console.ctrl(val, MIN(En, self._sel(addr, self.CON_CTRL)))
        self.disk.set_sector(val, MIN(En, self._sel(addr, self.DISK_SECTOR)))
        self.disk.write(val, MIN(En, self._sel(addr, self.DISK_DATA)))
        self.timer.set_period(val, MIN(En, self._sel(addr, self.TIMER_PERIOD)))
        self.timer.ack(MIN(En, self._sel(addr, self.TIMER_CTRL)))

        self.int_en.set(val, MIN(En, self._sel(addr, self.INT_ENABLE)))
        self.int_vec.set(word, MIN(En, self._sel(addr, self.INT_VECTOR)))
        self.int_vec_hi.set(word, MIN(En, self._sel(addr, self.INT_VECTOR_HI)))
        self.sysarg.set(word, MIN(En, self._sel(addr, self.SYSARG)))
        self.sysarg_hi.set(word, MIN(En, self._sel(addr, self.SYSARG_HI)))
        self.ctx_sel.set(val, MIN(En, self._sel(addr, self.CTX_SEL)))
        self.ctx_pc_hi.set(val, MIN(En, self._sel(addr, self.CTX_SETPC_HI)))
        self.ctx_req.set(val, MIN(En, self._sel(addr, self.CTX_SETPC)))
        self.syscall.set(val, MIN(En, self._sel(addr, self.SYSCALL)))
        self.resume.set(val, MIN(En, self._sel(addr, self.SCHED_RESUME)))
        self.gpu.write(self._gpu_reg(addr), val, self._gpu_sel(addr, En))
        self.drive.write(self._drv_reg(addr), val, self._drv_sel(addr, En))
        self.loader.write_addr(val, MIN(En, self._sel(addr, self.CODE_ADDR)))
        self.loader.write_data(val, MIN(En, self._sel(addr, self.CODE_DATA)))

    def irq_pending(self):
        return MAX(self.keyboard.ready(), self.timer.fired)
