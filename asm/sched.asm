-- Preemptive multitasking demo for the Quattro machine.
--
-- Three tasks each print their own character in a loop. The timer interrupt
-- preempts the running task; the hardware snapshots its full context (all 16
-- registers + PC), and this round-robin scheduler picks the next task and
-- resumes it via the SCHED_RESUME port. Run with:  python sched_run.py
--
-- Any label starting with "task" is registered as a task (in address order);
-- "sched" is the interrupt handler. The runner sets the timer + interrupts up.

taskA:
    LOAD R5, 252        -- CON_OUT
    LOAD R4, 65         -- 'A'
la:
    STORE [R5], R4
    JMP la

taskB:
    LOAD R5, 252
    LOAD R4, 66         -- 'B'
lb:
    STORE [R5], R4
    JMP lb

taskC:
    LOAD R5, 252
    LOAD R4, 67         -- 'C'
lc:
    STORE [R5], R4
    JMP lc

-- Round-robin scheduler: the timer interrupt handler.
sched:
    LOAD R2, 249        -- acknowledge the timer
    LOAD R0, 0
    STORE [R2], R0

    LOAD R2, 0          -- count switches in MEM[0]; stop after 12
    LOAD R0, [R2]
    LOAD R3, 1
    ADD R0, R3
    STORE [R2], R0
    LOAD R3, 12
    JLT R0, R3, go
    HLT

go:
    LOAD R2, 243        -- SCHED_CUR: id of the running task
    LOAD R0, [R2]
    LOAD R3, 1
    ADD R0, R3          -- next = current + 1
    LOAD R2, 244        -- SCHED_N: number of tasks
    LOAD R1, [R2]
    JLT R0, R1, ok      -- wrap round to 0 at the end
    LOAD R0, 0
ok:
    LOAD R2, 245        -- SCHED_RESUME: switch to task R0
    STORE [R2], R0
    RET
