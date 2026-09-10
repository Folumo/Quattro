#ifndef _STDIO_H
#define _STDIO_H
/* putchar/getchar/printf are compiler intrinsics; the rest is C in stdio.c. */
int putchar(int c);
int getchar();
void prints(char *s);
void puts(char *s);
void print_int(int n);
int printf(char *fmt);
void _printf(char *fmt);
extern int __va[16];
extern int __vi;
#endif
