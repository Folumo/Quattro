-- Interactive demo for the emulator (python emulator.py).
-- Echoes every typed key to the console, and prints '*' on each mouse click
-- (edge-detected -- holding the button prints only once).
-- Runs forever; quit the emulator with Esc.

main:
loop:
    LOAD R1, 251        -- KBD_STATUS: a key waiting?
    LOAD R0, [R1]
    JZ R0, nokey
    LOAD R1, 250        -- KBD_DATA: read (and pop) the key
    LOAD R0, [R1]
    CALL print_char     -- BIOS: echo it
nokey:
    LOAD R1, 231        -- MOUSE_BTN: current button state
    LOAD R2, [R1]
    LOAD R1, 5          -- MEM[5] remembers the previous state
    LOAD R3, [R1]
    STORE [R1], R2
    JZ R2, loop         -- not pressed now -> keep polling
    JZ R3, click        -- was up, now down -> a fresh click
    JMP loop
click:
    LOAD R0, 42         -- '*'
    CALL print_char
    JMP loop
