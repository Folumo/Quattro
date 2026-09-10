-- ===========================================================================
-- Quattro Shell + Filesystem  v2  (shell.asm)      run with: python term.py
-- Entry: main  (BIOS jumps here at reset; BIOS provides print_char / read_key)
-- ===========================================================================
--
-- DATA-MEMORY MAP (data RAM is 0..228):
--   0  .. 60   : .data strings (bannerstr, helpstr) - preloaded at load time
--   100..103   : NAMEBUF  (parsed file name, 4 words, null-padded)
--   110..141   : DIR cache (8 slots x 4 words). slot i name = dir[110+i*4..+3];
--                dir[110+i*4] == 0 marks a free slot.
--   150..226   : LINEBUF  (typed line, null-terminated; read_line caps at 76)
-- REGISTER CONVENTION:
--   R0        : BIOS arg/return (char to print / key), general scratch
--   R1        : char / temp
--   R3        : working pointer (line / dir / disk dest)
--   R4        : loop counter
--   R5        : constant scratch
--   R6        : device-port pointer (240 / 241 / 253)
--   R7        : disk sector argument
--   R8        : slot index (0..7, or 8 = none)
--   R9        : dir / name pointer (also the matched slot base after findslot)
--   R10       : compare pointer (findslot)
--   R11       : saved text pointer (write, survives helper calls)
--   R13..R15  : BIOS scratch (clobbered by every print_char / read_key)
-- FILESYSTEM (disk = 64 sectors x 16 words):
--   sectors 0..1     : directory, 8 slots x 4-word names (null-padded)
--   sector 2 + i*4   : contents of file i, chars + a 0 terminator (<=63 chars,
--                      spanning up to 4 sectors).  Blank disk (all 0) = empty.
--   File names are up to 4 characters.
-- COMMANDS (dispatch by first letter; 'c' split by 2nd letter):
--   ls              list file names
--   cat F           print file F
--   write F text    create/overwrite F with text (<=63 chars)
--   rm F            delete F
--   clr             clear the screen
--   help            show the command list
--   shutdown        halt the machine

.text
main:
    LOAD R7, 0          -- read the directory (sectors 0..1) into the cache
    CALL dseek
    LOAD R3, 110
    LOAD R4, 32
mdr:
    LOAD R0, [R6]
    STORE [R3], R0
    LOAD R5, 1
    ADD R3, R5
    SUB R4, R5
    JCMP R4, mdr
    LOAD R1, bannerstr  -- greet
    CALL puts
    LOAD R0, 10
    CALL print_char
    JMP prompt

-- ---- prompt + read a line + dispatch -------------------------------------
prompt:
    LOAD R0, 36         -- '$'
    CALL print_char
    LOAD R0, 32         -- ' '
    CALL print_char
    CALL read_line      -- fills LINEBUF (150..), echoes, handles bs/enter
    LOAD R3, 150
    LOAD R1, [R3]       -- first character of the line
    JZ R1, prompt       -- empty line -> new prompt
    LOAD R5, 108        -- 'l' -> ls
    JEQ R1, R5, do_ls
    LOAD R5, 119        -- 'w' -> write
    JEQ R1, R5, do_write
    LOAD R5, 114        -- 'r' -> rm
    JEQ R1, R5, do_rm
    LOAD R5, 104        -- 'h' -> help
    JEQ R1, R5, do_help
    LOAD R5, 115        -- 's' -> shutdown
    JEQ R1, R5, do_shutdown
    LOAD R5, 99         -- 'c' -> cat / clr
    JEQ R1, R5, cdisp
    JMP err             -- unknown command
cdisp:
    LOAD R3, 151        -- second character distinguishes cat / clr
    LOAD R1, [R3]
    LOAD R5, 108        -- 'l' -> clr
    JEQ R1, R5, do_clr
    JMP do_cat
err:
    LOAD R0, 63         -- '?'
    CALL print_char
    LOAD R0, 10
    CALL print_char
    JMP prompt

-- ---- ls -------------------------------------------------------------------
do_ls:
    LOAD R3, 110        -- dir cache base
    LOAD R8, 0          -- slot index
ls_slot:
    LOAD R0, [R3]       -- first char of this slot's name
    JZ R0, ls_next      -- empty slot
    COPY R9, R3         -- print up to 4 name chars (stop at 0)
    LOAD R4, 4
ls_pc:
    LOAD R0, [R9]
    JZ R0, ls_eol
    CALL print_char
    LOAD R5, 1
    ADD R9, R5
    SUB R4, R5
    JCMP R4, ls_pc
ls_eol:
    LOAD R0, 10
    CALL print_char
ls_next:
    LOAD R5, 4
    ADD R3, R5          -- next slot base
    LOAD R5, 1
    ADD R8, R5
    LOAD R5, 8
    JLT R8, R5, ls_slot
    JMP prompt

-- ---- cat F ----------------------------------------------------------------
do_cat:
    LOAD R3, 150
    CALL argptr         -- R3 -> first argument char
    CALL parsename      -- NAMEBUF = name
    CALL findslot       -- R8 = slot, or 8 if absent
    LOAD R5, 8
    JEQ R8, R5, err
    CALL sectorof       -- R7 = 2 + slot*4
    CALL dseek          -- select the sector, R6 = DISK_DATA
cat_l:
    LOAD R0, [R6]
    JZ R0, cat_end      -- 0 terminator (also stops at blank cells / end of disk)
    CALL print_char
    JMP cat_l
cat_end:
    LOAD R0, 10
    CALL print_char
    JMP prompt

-- ---- rm F -----------------------------------------------------------------
do_rm:
    LOAD R3, 150
    CALL argptr
    CALL parsename
    CALL findslot       -- R8 = slot, R9 = its dir base
    LOAD R5, 8
    JEQ R8, R5, err
    LOAD R4, 4          -- zero the 4-word directory entry
    LOAD R0, 0
rm_z:
    STORE [R9], R0
    LOAD R5, 1
    ADD R9, R5
    SUB R4, R5
    JCMP R4, rm_z
    CALL flushdir       -- persist the directory
    JMP prompt

-- ---- write F text ---------------------------------------------------------
do_write:
    LOAD R3, 150
    CALL argptr         -- R3 -> name
    CALL parsename      -- NAMEBUF = name; R3 past the name
    CALL skipsp         -- R3 -> the text
    LOAD R9, 100        -- reject an empty name
    LOAD R0, [R9]
    JZ R0, err
    COPY R11, R3        -- save the text pointer across the lookups
    CALL findslot       -- existing file?  R8 = slot, R9 = base
    LOAD R5, 8
    JLT R8, R5, w_slot  -- yes: overwrite it
    CALL freeslot       -- else grab a free slot (R8 = slot, R9 = base)
    LOAD R5, 8
    JEQ R8, R5, err     -- directory full
    CALL namecpy        -- write the name into the cache
    CALL flushdir       -- persist the directory
w_slot:
    CALL sectorof       -- R7 = 2 + slot*4
    CALL dseek          -- select it, R6 = DISK_DATA
    COPY R3, R11        -- restore the text pointer
    LOAD R4, 63         -- cap the content
w_wr:
    LOAD R0, [R3]
    JZ R0, w_term
    STORE [R6], R0      -- stream one char to disk
    LOAD R5, 1
    ADD R3, R5
    SUB R4, R5
    JCMP R4, w_wr
w_term:
    LOAD R0, 0
    STORE [R6], R0      -- 0 terminator
    JMP prompt

-- ---- clr ------------------------------------------------------------------
do_clr:
    LOAD R6, 253        -- CON_CTRL
    LOAD R0, 0
    STORE [R6], R0      -- 0 = clear screen
    JMP prompt

-- ---- help -----------------------------------------------------------------
do_help:
    LOAD R1, helpstr
    CALL puts
    LOAD R0, 10
    CALL print_char
    JMP prompt

-- ---- shutdown -------------------------------------------------------------
do_shutdown:
    LOAD R1, byestr
    CALL puts
    HLT                 -- stop the machine

-- ===========================================================================
-- HELPERS (all RET-terminated; nesting never exceeds depth 2)
-- ===========================================================================

-- read_line: read into LINEBUF echoing keys; backspace erases; enter (10/13)
--            ends the line. Caps at 76 chars so long text can't run past the
--            data RAM into the device ports. Uses R0,R3,R4,R5 + BIOS scratch.
read_line:
    LOAD R3, 150
    LOAD R4, 0
rl_loop:
    CALL read_key       -- R0 = key
    LOAD R5, 13
    JEQ R0, R5, rl_done
    LOAD R5, 10
    JEQ R0, R5, rl_done
    LOAD R5, 8
    JEQ R0, R5, rl_bs
    LOAD R5, 76         -- line full?  ignore further chars until enter
    JLT R4, R5, rl_st
    JMP rl_loop
rl_st:
    STORE [R3], R0      -- store + echo the char
    CALL print_char
    LOAD R5, 1
    ADD R3, R5
    ADD R4, R5
    JMP rl_loop
rl_bs:
    JZ R4, rl_loop      -- nothing to erase
    LOAD R5, 1
    SUB R3, R5
    SUB R4, R5
    LOAD R0, 8          -- console backspace erases the cell
    CALL print_char
    JMP rl_loop
rl_done:
    LOAD R5, 0
    STORE [R3], R5      -- null-terminate
    LOAD R0, 10
    CALL print_char     -- echo newline
    RET

-- argptr: R3 = line base -> R3 = first char of the first argument (skips the
--         command word, then spaces). Tail-calls skipsp. Uses R1,R5.
argptr:
ap_word:
    LOAD R1, [R3]
    JZ R1, ap_ret
    LOAD R5, 32
    JEQ R1, R5, skipsp  -- hit a space: skip spaces, then return
    LOAD R5, 1
    ADD R3, R5
    JMP ap_word
ap_ret:
    RET

-- skipsp: advance R3 past spaces -> R3 = first non-space. Uses R1,R5.
skipsp:
    LOAD R1, [R3]
    LOAD R5, 32
    JEQ R1, R5, sk_adv
    RET
sk_adv:
    LOAD R5, 1
    ADD R3, R5
    JMP skipsp

-- parsename: R3 -> name start. Copies up to 4 chars into NAMEBUF (100..103),
--            null-pads the rest, and advances R3 past the name (to the space
--            or terminator). Uses R0,R1,R4,R5,R9.
parsename:
    LOAD R9, 100
    LOAD R4, 4
pn_cp:
    LOAD R1, [R3]
    JZ R1, pn_pad
    LOAD R5, 32
    JEQ R1, R5, pn_pad
    JZ R4, pn_skip      -- buffer full: skip the rest of an over-long name
    STORE [R9], R1
    LOAD R5, 1
    ADD R9, R5
    SUB R4, R5
    ADD R3, R5
    JMP pn_cp
pn_skip:
    LOAD R5, 1
    ADD R3, R5
    JMP pn_cp
pn_pad:
    JZ R4, pn_done
    LOAD R5, 0
    STORE [R9], R5
    LOAD R5, 1
    ADD R9, R5
    SUB R4, R5
    JMP pn_pad
pn_done:
    RET

-- findslot: NAMEBUF vs each dir slot -> R8 = slot (0..7), R9 = its base; or
--           R8 = 8 if not found. Uses R0,R1,R3,R4,R5,R10. Preserves R11.
findslot:
    LOAD R8, 0
    LOAD R9, 110
fs_slot:
    LOAD R3, 100        -- NAMEBUF pointer
    COPY R10, R9        -- this slot's dir pointer
    LOAD R4, 4
fs_cmp:
    LOAD R0, [R3]
    LOAD R1, [R10]
    JEQ R0, R1, fs_ok
    JMP fs_no
fs_ok:
    LOAD R5, 1
    ADD R3, R5
    ADD R10, R5
    SUB R4, R5
    JCMP R4, fs_cmp
    RET                 -- all 4 matched: R8 = slot, R9 = base
fs_no:
    LOAD R5, 4
    ADD R9, R5
    LOAD R5, 1
    ADD R8, R5
    LOAD R5, 8
    JLT R8, R5, fs_slot
    RET                 -- R8 = 8: not found

-- freeslot: -> R8 = a free slot (0..7), R9 = its base; or R8 = 8 if full.
--           Uses R0,R5. Preserves R11.
freeslot:
    LOAD R8, 0
    LOAD R9, 110
free_l:
    LOAD R0, [R9]
    JZ R0, free_hit
    LOAD R5, 4
    ADD R9, R5
    LOAD R5, 1
    ADD R8, R5
    LOAD R5, 8
    JLT R8, R5, free_l
free_hit:
    RET

-- namecpy: copy NAMEBUF (100..103) into the dir slot at R9. Uses R0,R3,R4,R5.
namecpy:
    LOAD R3, 100
    LOAD R4, 4
nc_l:
    LOAD R0, [R3]
    STORE [R9], R0
    LOAD R5, 1
    ADD R3, R5
    ADD R9, R5
    SUB R4, R5
    JCMP R4, nc_l
    RET

-- sectorof: R8 = slot -> R7 = 2 + slot*4 (the file's first sector).
sectorof:
    COPY R7, R8
    LOAD R5, 4
    MUL R7, R5
    LOAD R5, 2
    ADD R7, R5
    RET

-- dseek: R7 = sector -> select it; leaves R6 = 241 (DISK_DATA). Uses R6.
dseek:
    LOAD R6, 240
    STORE [R6], R7
    LOAD R6, 241
    RET

-- flushdir: write the 32-word DIR cache back to sectors 0..1. Tail-calls dwrite.
flushdir:
    LOAD R7, 0
    LOAD R3, 110
    LOAD R4, 32
    JMP dwrite

-- dwrite: R7 = sector, R3 = src, R4 = count. Streams count words out.
dwrite:
    CALL dseek
dw_loop:
    LOAD R0, [R3]
    STORE [R6], R0
    LOAD R5, 1
    ADD R3, R5
    SUB R4, R5
    JCMP R4, dw_loop
    RET

-- puts: print the null-terminated string at MEM[R1..]. Uses R0,R2. Keeps R1.
puts:
    LOAD R0, [R1]
    JZ R0, puts_end
    CALL print_char
    LOAD R2, 1
    ADD R1, R2
    JMP puts
puts_end:
    RET

.data
bannerstr:
    .string "Quattro FS"
helpstr:
    .string "ls  cat F  write F T  rm F  clr  help  shutdown"
byestr:
    .string "bye"
