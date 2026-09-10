"""The whole computer wired together (Machine), plus run_machine/dump.

Note this module deliberately does NOT import the assembler: the machine is the
hardware, and knows nothing about how programs are produced. `main.py` is the
entry point that ties compiler + machine + front-ends together."""

from .words import ZERO_WORD, from_word, to_word
from .storage import RAM6, RSTACK, BigRAM, WREG16
from .devices import GPU, Console, Disk, Drive, Keyboard, Loader, Mouse, Timer
from .bus import Bus
from .cpu import CPU


def _addr8(a):
    """An instruction index as 8 quaternary digits (0..65535)."""
    return tuple((a // (4 ** k)) % 4 for k in range(8))


class Machine:
    """The whole computer, steppable one instruction at a time -- so a debugger
    or emulator front-end can drive it and inspect state between steps.

    `keys` seeds the keyboard with key codes; `data` is a {address: value} image
    preloaded into data memory (e.g. a string table).

    `sched` enables preemptive multitasking: a dict {'tasks': [entry_addr, ...],
    'handler': addr, 'period': ticks}. The timer snapshots the running task's
    context and vectors to `handler`, which picks the next task (via the SCHED
    ports) and writes SCHED_RESUME; the machine then restores that task."""

    def __init__(self, machine_code, keys=None, data=None, disk=None, sched=None,
                 drive_root='machine', code_size=None):
        if len(machine_code) > 65536:
            raise ValueError(
                f"program too big: {len(machine_code)} instructions, but the "
                f"8-digit program counter addresses only 65536")
        if code_size and code_size > 65536:
            # Cells past the PC's reach are not just wasted -- instruction index
            # 65536 truncates to 0 and quietly aliases onto the reset vector.
            raise ValueError(
                f"code_size {code_size} exceeds the 65536 instructions the "
                f"8-digit program counter can address")

        # Code memory is one wide cell per instruction (Harvard); the program
        # counter is an instruction index, so instruction i lives at index i.
        # `code_size` reserves room beyond the loaded image for programs the
        # machine loads itself at run time (a boot ROM pulling in an OS).
        self.ram = RAM6(max(1, len(machine_code), code_size or 0))
        for i, instr in enumerate(machine_code):
            self.ram.load(*_addr8(i), *instr)

        self.var_reg = WREG16()
        self.flag_reg = WREG16()
        self.stack = RSTACK()
        self.bus = Bus(BigRAM(), Console(), Keyboard(keys), Timer(),
                       Disk(image=disk), Mouse(), GPU(),
                       Drive(drive_root), Loader())
        self.bus.gpu.mem = self.bus.ram      # let the GPU DMA strings/sprites
        self.bus.drive.mem = self.bus.ram    # the drive DMAs file data too
        self.bus.loader.code = self.ram      # and the load port writes code memory

        # Preload data memory (string tables, constants).
        if data:
            for addr, val in data.items():
                self.bus.ram.run(to_word(addr), 3, to_word(val))

        self.cpu = CPU(self.var_reg, self.flag_reg, self.ram, self.stack,
                       self.bus)

        self.contexts = None
        self.handler_pc = None
        if sched:
            nslots = sched.get('nslots', len(sched['tasks']))
            self.contexts = [{'regs': [ZERO_WORD] * 16, 'pc': _addr8(0)}
                             for _ in range(nslots)]
            for i, a in enumerate(sched['tasks']):  # pre-load the initial tasks
                self.contexts[i]['pc'] = _addr8(a)
            self.handler_pc = _addr8(sched['handler'])
            self.bus.sched_n = nslots
            self.bus.sched_cur = 0
            self.bus.timer.set_period(sched['period'])
            self.bus.int_en.set(1, 3)
            self._load_ctx(self.contexts[0])    # start running task 0

        self.masked_until = None
        self.steps = 0
        self.last_instr = None   # the most recently executed instruction frame

    # A task context is all 16 registers plus the program counter. The hardware
    # snapshots it on a scheduling interrupt and restores it on resume, so the
    # software scheduler never has to touch the register file or the PC directly.
    def _save_ctx(self):
        regs = [self.var_reg.run(n % 4, n // 4, 0) for n in range(16)]
        return {'regs': regs, 'pc': self.ram.get_pc()}

    def _load_ctx(self, ctx):
        for n, w in enumerate(ctx['regs']):
            self.var_reg.run(n % 4, n // 4, 3, w)
        self.ram.set_pc(3, *ctx['pc'])

    @property
    def halted(self):
        return self.flag_reg.run(3, 3, 0)[0] == 3

    def step(self):
        """Execute one instruction (servicing interrupts around it)."""
        bus, ram, stack = self.bus, self.ram, self.stack

        # Service a pending interrupt between instructions.
        if self.contexts is not None:
            # timer preemption: snapshot the running task and enter the kernel
            if bus.int_en.get() and not bus.os_masked and bus.timer.fired:
                self.contexts[bus.sched_cur] = self._save_ctx()
                bus.irq_cause = 0            # 0 = timer
                bus.os_masked = True
                ram.set_pc(3, *self.handler_pc)
        elif bus.int_en.get() and bus.irq_pending():
            # ordinary interrupt: push PC and vector (a hardware CALL)
            self.masked_until = stack.depth()
            stack.push(3, *ram.get_pc())
            bus.int_en.set(0, 3)
            iv = bus.int_vec.get()   # the whole vector fits in one wide word now
            ram.set_pc(3, iv[0], iv[1], iv[2], iv[3], iv[4], iv[5], iv[6], iv[7])

        RET = ram.fetch()
        self.last_instr = RET
        self.cpu.run(*RET)
        bus.timer.tick()  # one clock tick per executed instruction

        if self.contexts is not None:
            # A task made a syscall: snapshot it and enter the kernel.
            if bus.syscall.pending:
                num = bus.syscall.get()
                bus.syscall.clear()
                if not bus.os_masked:
                    self.contexts[bus.sched_cur] = self._save_ctx()
                    bus.irq_cause = num
                    bus.os_masked = True
                    ram.set_pc(3, *self.handler_pc)
            # Kernel asked to create a fresh context (spawn).
            if bus.ctx_req.pending:
                slot = bus.ctx_sel.get()
                entry = bus.ctx_req.get() + 256 * bus.ctx_pc_hi.get()
                bus.ctx_req.clear()
                if 0 <= slot < len(self.contexts):
                    self.contexts[slot] = {'regs': [ZERO_WORD] * 16,
                                           'pc': _addr8(entry)}
            # Kernel asked to resume a task: restore its full context.
            if bus.resume.pending:
                bus.sched_cur = bus.resume.get()
                bus.resume.clear()
                self._load_ctx(self.contexts[bus.sched_cur])
                bus.os_masked = False
                # Give the resumed task a fresh time slice, so the kernel's own
                # run time never eats into it (which would livelock the switch).
                bus.timer.count = 0
                bus.timer.fired = False

        if self.masked_until is not None and stack.depth() == self.masked_until:
            bus.int_en.set(1, 3)   # handler returned: unmask
            self.masked_until = None

        self.steps += 1


def run_machine(machine_code, keys=None, data=None, disk=None, sched=None,
                max_steps=100000):
    """Run a compiled program to halt; return (var_reg, flag_reg, bus)."""
    m = Machine(machine_code, keys=keys, data=data, disk=disk, sched=sched)
    while not m.halted:
        m.step()
        if m.steps >= max_steps:
            print(f"[halted: exceeded {max_steps} steps without HLT]")
            break
    return m.var_reg, m.flag_reg, m.bus


def dump(var_reg, flag_reg, bus=None):
    # Register R_n lives at (Adr0 = n%4, Adr1 = n//4).
    print("VAR_REG:")
    for n in range(16):
        print(f"  R{n:<2} = {from_word(var_reg.run(n % 4, n // 4, 0))}")

    print("FLAG_REG:")
    for n in range(16):
        print(f"  F{n:<2} = {from_word(flag_reg.run(n % 4, n // 4, 0))}")

    if bus is not None:
        print("SCREEN:")
        print("  +" + "-" * bus.console.W + "+")
        for line in bus.console.render().split('\n'):
            print(f"  |{line:<{bus.console.W}}|")
        print("  +" + "-" * bus.console.W + "+")

        nonzero = []
        for addr in range(bus.RAM_TOP + 1):
            w = bus.ram.run(to_word(addr), 0)
            if from_word(w):
                nonzero.append((addr, from_word(w)))
        if nonzero:
            print("DATA MEM (non-zero cells):")
            for addr, val in nonzero:
                print(f"  MEM[{addr}] = {val}")
