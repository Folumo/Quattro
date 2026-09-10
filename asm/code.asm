-- User program. Entered by the BIOS at 'main'.
-- Loads a null-terminated string from disk sector 0 and prints it, showing
-- memory-mapped block storage: select a sector, then stream words from the
-- disk data port (241), which auto-advances.

.text
main:
    LOAD R1, 240        -- DISK_SECTOR port
    LOAD R0, 0
    STORE [R1], R0      -- select sector 0 (resets the read position)
    LOAD R5, 241        -- DISK_DATA port
loop:
    LOAD R0, [R5]       -- read next word from disk
    JZ R0, done         -- 0 terminator -> stop
    CALL print_char     -- BIOS: print it
    JMP loop
done:
    HLT
