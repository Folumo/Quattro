-- A tiny multitasking OS for the Quattro machine.  Run with:  python os_run.py
--
-- 'init' spawns three worker tasks, then exits. Each worker prints its letter a
-- few times, yielding between prints, then exits. The kernel (entered by a timer
-- interrupt or a syscall) keeps a task-state table and round-robin schedules the
-- ready tasks; when none are left it halts.
--
-- Syscalls: write a number to SYSCALL (232) to trap into the kernel. Args go in
-- SYSARG (234) / SYSARG_HI (239). Nums: 1=yield, 2=exit, 3=spawn.
-- State table: MEM[10 + task_id], 0 = free, 1 = ready.
--
-- Thanks to two-word code pointers, the worker tasks can live anywhere in code
-- (here, after the kernel, well past address 255): init passes each entry as a
-- (low, high) pair with < and >, and the kernel forwards it to CTX_SETPC.

init:
    LOAD R2, 10         -- state[0] = ready (init is task 0)
    LOAD R0, 1
    STORE [R2], R0

    LOAD R2, 234        -- spawn taskA
    LOAD R0, <taskA
    STORE [R2], R0
    LOAD R2, 239
    LOAD R0, >taskA
    STORE [R2], R0
    LOAD R2, 232
    LOAD R0, 3
    STORE [R2], R0

    LOAD R2, 234        -- spawn taskB
    LOAD R0, <taskB
    STORE [R2], R0
    LOAD R2, 239
    LOAD R0, >taskB
    STORE [R2], R0
    LOAD R2, 232
    LOAD R0, 3
    STORE [R2], R0

    LOAD R2, 234        -- spawn taskC
    LOAD R0, <taskC
    STORE [R2], R0
    LOAD R2, 239
    LOAD R0, >taskC
    STORE [R2], R0
    LOAD R2, 232
    LOAD R0, 3
    STORE [R2], R0

    LOAD R2, 248        -- turn on the timer (preemption)
    LOAD R0, 40
    STORE [R2], R0

    LOAD R2, 232        -- init exits
    LOAD R0, 2
    STORE [R2], R0
    JMP init

-- The kernel: entered on a timer interrupt (cause 0) or a syscall (cause = num).
kernel:
    LOAD R2, 233        -- IRQ_CAUSE
    LOAD R1, [R2]
    JZ R1, ksched       -- timer -> reschedule
    LOAD R3, 3
    JEQ R1, R3, kspawn
    LOAD R3, 2
    JEQ R1, R3, kexit
    JMP ksched          -- yield -> reschedule

kexit:
    LOAD R2, 243        -- state[current] = free
    LOAD R0, [R2]
    LOAD R3, 10
    ADD R0, R3
    LOAD R4, 0
    STORE [R0], R4
    JMP ksched

kspawn:
    LOAD R2, 244        -- N = number of task slots
    LOAD R5, [R2]
    LOAD R6, 0          -- slot = 0
kscan:
    LOAD R3, 10
    ADD R3, R6          -- &state[slot]
    LOAD R0, [R3]
    JZ R0, kfound       -- a free slot
    LOAD R7, 1
    ADD R6, R7
    JLT R6, R5, kscan
    JMP kret            -- table full: spawn silently fails
kfound:
    LOAD R2, 235        -- CTX_SEL = slot
    STORE [R2], R6
    LOAD R2, 239        -- forward the entry's high part
    LOAD R0, [R2]
    LOAD R2, 237        -- CTX_SETPC_HI
    STORE [R2], R0
    LOAD R2, 234        -- forward the entry's low word
    LOAD R0, [R2]
    LOAD R2, 236        -- CTX_SETPC (combines low+high into the full address)
    STORE [R2], R0
    LOAD R3, 10         -- state[slot] = ready
    ADD R3, R6
    LOAD R0, 1
    STORE [R3], R0
kret:
    LOAD R2, 243        -- spawn returns to the caller
    LOAD R0, [R2]
    LOAD R2, 245        -- SCHED_RESUME = current
    STORE [R2], R0
    JMP kret

ksched:
    LOAD R2, 249        -- ack the timer
    LOAD R0, 0
    STORE [R2], R0
    LOAD R2, 243        -- start scanning from current + 1
    LOAD R4, [R2]
    LOAD R2, 244
    LOAD R5, [R2]       -- N
    LOAD R6, 0          -- tries
knext:
    LOAD R7, 1
    ADD R4, R7          -- candidate++
    JLT R4, R5, knowrap
    LOAD R4, 0          -- wrap around
knowrap:
    LOAD R3, 10
    ADD R3, R4
    LOAD R0, [R3]       -- state[candidate]
    LOAD R7, 1
    JEQ R0, R7, krun    -- ready -> run it
    LOAD R7, 1
    ADD R6, R7          -- another try
    JLT R6, R5, knext
    HLT                 -- nothing ready: the OS shuts down
krun:
    LOAD R2, 245        -- SCHED_RESUME = candidate
    STORE [R2], R4
    JMP krun

-- Worker tasks -- they sit well past address 255, reachable only because init
-- spawns them via two-word (low, high) pointers.
taskA:
    LOAD R8, 65         -- 'A'
    JMP work
taskB:
    LOAD R8, 66         -- 'B'
    JMP work
taskC:
    LOAD R8, 67         -- 'C'
    JMP work
work:
    LOAD R9, 3          -- print R8 three times, yielding between each
wloop:
    LOAD R10, 252       -- CON_OUT
    STORE [R10], R8
    LOAD R2, 232        -- yield (syscall 1)
    LOAD R0, 1
    STORE [R2], R0
    LOAD R11, 1
    SUB R9, R11
    JZ R9, wexit
    JMP wloop
wexit:
    LOAD R2, 232        -- exit (syscall 2)
    LOAD R0, 2
    STORE [R2], R0
    JMP wexit
