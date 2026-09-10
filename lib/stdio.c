#include <stdio.h>

/* variadic marshalling area: the printf() intrinsic fills __va before calling
   _printf, which walks the format string pulling values from it. */
int __va[16];
int __vi;

void prints(char *s) {
    int i;
    i = 0;
    while (s[i] != 0) {
        putchar(s[i]);
        i = i + 1;
    }
}

void puts(char *s) {
    prints(s);
    putchar(10);
}

void print_int(int n) {
    char buf[12];
    int i;
    if (n == 0) {
        putchar(48);
        return;
    }
    i = 0;
    while (n > 0) {
        buf[i] = 48 + (n % 10);
        i = i + 1;
        n = n / 10;
    }
    while (i > 0) {
        i = i - 1;
        putchar(buf[i]);
    }
}

void _printf(char *fmt) {
    int i;
    int c;
    __vi = 0;
    i = 0;
    while (fmt[i] != 0) {
        c = fmt[i];
        if (c == 37) {                 /* '%' */
            i = i + 1;
            c = fmt[i];
            if (c == 100) {            /* %d */
                print_int(__va[__vi]);
                __vi = __vi + 1;
            } else if (c == 99) {      /* %c */
                putchar(__va[__vi]);
                __vi = __vi + 1;
            } else if (c == 115) {     /* %s */
                prints(__va[__vi]);
                __vi = __vi + 1;
            } else {
                putchar(c);            /* %% and unknown */
            }
        } else {
            putchar(c);
        }
        i = i + 1;
    }
}
