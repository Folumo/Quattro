#ifndef _STDLIB_H
#define _STDLIB_H
#define HEAP_BASE 40000
int malloc(int n);
void free(int p);
int abs(int n);
extern int __heap;
extern int __freelist;
#endif
