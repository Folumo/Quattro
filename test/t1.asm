.data
name:
    .string "Fran"
surname:
    .string "Stanic"


.text
main:
    LOAD R0, 70
    CALL print_char
    LOAD R0, 114
    CALL print_char
    LOAD R0, 97
    CALL print_char
    LOAD R0, 110
    CALL print_char

    CALL rk_wait
    JEQ R0, 115, secret
    HLT

secret:
    LOAD R0, 83
    CALL print_char
    LOAD R0, 116
    CALL print_char
    LOAD R0, 97
    CALL print_char
    LOAD R0, 110
    CALL print_char
    LOAD R0, 105
    CALL print_char
    LOAD R0, 99
    CALL print_char
    RET
