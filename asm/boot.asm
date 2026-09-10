-- ===========================================================================
-- Quattro boot ROM.
--
-- This is what the machine wakes up running: reset puts the program counter at
-- instruction 0, the BIOS jumps here, and this is the only code that exists.
-- There is no operating system in the machine image at all -- the ROM has to go
-- and find one:
--
--   1. read the 5-word header of  bin/os.bin  off the drive
--   2. check it is actually one of ours, and that the drive gave us the file
--   3. read the code words into a staging buffer in DATA memory, then stream
--      them through the load port (CODE_ADDR / CODE_DATA) into CODE memory.
--      This machine is Harvard -- code memory is unreachable from a STORE --
--      so the load port is the only door in, exactly as on real hardware.
--      One 32-bit word IS one 16-quarter instruction frame, so it is a
--      straight copy: no unpacking, one word per instruction.
--   4. poke the OS's data image (its string tables) into data memory
--   5. jump to the entry point. It is a runtime value read off the disk, not
--      an assemble-time label, so this has to be a register-pair jump.
--
-- After step 5 the ROM is finished forever and the OS owns the machine.
--
-- The ROM talks to the GPU rather than the console, because the boot sequence
-- should be visible on the machine's own screen.
-- ===========================================================================

.data
ospath:
    .string "bin/os.bin"
msg1:
    .string "Quattro ROM"
msg2:
    .string "drive: loading bin/os.bin"
msg3:
    .string "starting QuattroOS ..."
-- these are drawn at x=8 in an 8px font, so they must stay under 30 characters
msgnofile:
    .string "ERROR: no bin/os.bin on drive"
msgbad:
    .string "ERROR: bin/os.bin is corrupt"
hdr:
    .byte 0, 0, 0, 0, 0

.text
main:
    -- ---- boot screen -----------------------------------------------------
    LOAD R15, 0
    LOAD R14, 261           -- GPU_COLOR = 0 (black)
    STORE [R14], R15
    LOAD R14, 256           -- GPU_CMD = 0 (clear)
    STORE [R14], R15

    LOAD R4, 1              -- the constant 1; every loop below leans on it

    LOAD R6, 10             -- the ROM speaks in green
    LOAD R1, msg1
    LOAD R2, 8
    LOAD R3, 8
    CALL gputext
    LOAD R6, 7
    LOAD R1, msg2
    LOAD R2, 8
    LOAD R3, 24
    CALL gputext

    -- ---- read the header -------------------------------------------------
    LOAD R1, 290            -- DRV_NAME = "bin/os.bin"
    LOAD R0, ospath
    STORE [R1], R0
    LOAD R1, 291            -- DRV_BUF = hdr
    LOAD R0, hdr
    STORE [R1], R0
    LOAD R1, 292            -- DRV_LEN = 5 words
    LOAD R0, 5
    STORE [R1], R0
    LOAD R1, 293            -- DRV_POS = 0
    LOAD R0, 0
    STORE [R1], R0
    LOAD R1, 288            -- DRV_CMD = 3 (READW)
    LOAD R0, 3
    STORE [R1], R0

    LOAD R1, 289            -- DRV_STATUS: non-zero means the drive said no
    LOAD R0, [R1]
    LOAD R1, msgnofile
    JCMP R0, fail

    -- ---- is it ours?  check the low byte of the magic against 'Q' --------
    LOAD R2, hdr
    LOAD R0, [R2]           -- magic
    LOAD R12, 256
    COPY R11, R0
    DIV R11, R12
    MUL R11, R12
    SUB R0, R11             -- R0 = magic % 256   (no modulo op: div, mul, sub)
    LOAD R11, 81            -- 'Q', the first byte of "QUAT"
    SUB R0, R11             -- 0 if it matched
    LOAD R1, msgbad
    JCMP R0, fail

    -- ---- parse the rest:  base, entry, ncode, ndata ----------------------
    ADD R2, R4
    LOAD R7, [R2]           -- base   -- the instruction index it must live at
    ADD R2, R4
    LOAD R8, [R2]           -- entry  -- where to jump when we are done
    ADD R2, R4
    LOAD R9, [R2]           -- ncode  -- how many instruction words
    ADD R2, R4
    LOAD R10, [R2]          -- ndata  -- how many (address, value) data pairs

    -- ---- pull the code words into a staging buffer in data memory --------
    LOAD R1, 291
    LOAD R0, 8192
    STORE [R1], R0          -- DRV_BUF = 8192
    LOAD R1, 292
    COPY R0, R9
    STORE [R1], R0          -- DRV_LEN = ncode
    LOAD R1, 293
    LOAD R0, 20
    STORE [R1], R0          -- DRV_POS = 5 header words * 4 bytes
    LOAD R1, 288
    LOAD R0, 3
    STORE [R1], R0          -- READW

    -- ---- stream them through the load port into code memory --------------
    LOAD R1, 246            -- CODE_ADDR = base; the port auto-advances
    COPY R0, R7
    STORE [R1], R0
    LOAD R2, 8192
    COPY R3, R9
    LOAD R5, 247            -- CODE_DATA
    JZ R3, nocode
cloop:
    LOAD R0, [R2]
    STORE [R5], R0          -- one word == one instruction frame
    ADD R2, R4
    SUB R3, R4
    JCMP R3, cloop
nocode:

    -- ---- and the data image, as (address, value) pairs -------------------
    JZ R10, run
    LOAD R1, 291
    LOAD R0, 8192
    STORE [R1], R0
    LOAD R1, 292
    COPY R0, R10
    LOAD R11, 2
    MUL R0, R11
    STORE [R1], R0          -- DRV_LEN = ndata * 2 words
    LOAD R1, 293
    COPY R0, R9
    LOAD R11, 5
    ADD R0, R11
    LOAD R11, 4
    MUL R0, R11
    STORE [R1], R0          -- DRV_POS = (5 + ncode) * 4 bytes
    LOAD R1, 288
    LOAD R0, 3
    STORE [R1], R0          -- READW

    LOAD R2, 8192
    COPY R3, R10
dloop:
    LOAD R11, [R2]          -- address
    ADD R2, R4
    LOAD R12, [R2]          -- value
    ADD R2, R4
    STORE [R11], R12
    SUB R3, R4
    JCMP R3, dloop
run:

    LOAD R6, 10
    LOAD R1, msg3
    LOAD R2, 8
    LOAD R3, 40
    CALL gputext

    -- ---- hand over ------------------------------------------------------
    -- `entry` came off the disk, so the target is not a label the assembler
    -- could bake in: split it into a low/high register pair and jump through.
    COPY R11, R8
    LOAD R12, 256
    DIV R11, R12            -- R11 = entry / 256   (the high half)
    COPY R2, R11
    MUL R2, R12
    COPY R3, R8
    SUB R3, R2              -- R3 = entry % 256    (the low half)
    JMP R3, R11

-- the drive could not give us an OS: say so in red and stop
fail:
    LOAD R6, 12
    LOAD R2, 8
    LOAD R3, 56
    CALL gputext
    HLT

-- gputext: draw the string at R1 at pixel (R2, R3) in colour R6
gputext:
    LOAD R14, 257           -- GPU_X
    STORE [R14], R2
    LOAD R14, 258           -- GPU_Y
    STORE [R14], R3
    LOAD R14, 262           -- GPU_ADDR: the GPU DMAs the string out of RAM
    STORE [R14], R1
    LOAD R14, 261           -- GPU_COLOR
    STORE [R14], R6
    LOAD R14, 256           -- GPU_CMD
    LOAD R15, 6             -- 6 = TEXT
    STORE [R14], R15
    RET
