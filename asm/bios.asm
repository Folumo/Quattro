-- Quattro BIOS ROM.
-- Reset starts at instruction 0 (_boot), which hands control to the loaded
-- program at label 'main'. The BIOS also provides callable routines at fixed
-- entry points, so programs never need to know the device addresses.
--
-- Calling convention: argument / return value in R0; R13-R15 are BIOS scratch
-- (a program must not expect them to survive a BIOS call).

_boot:
    JMP main            -- hand off to the loaded program

-- print_char: print the character code in R0
print_char:
    LOAD R15, 252       -- CON_OUT
    STORE [R15], R0
    RET

-- read_key: block until a key is available, return its code in R0
read_key:
    LOAD R15, 251       -- KBD_STATUS
rk_wait:
    LOAD R0, [R15]
    JZ R0, rk_wait      -- spin until a key is ready
    LOAD R15, 250       -- KBD_DATA
    LOAD R0, [R15]      -- read (and pop) the key
    RET
