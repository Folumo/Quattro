#include <stdlib.h>

/* First-fit heap over the high data region. A block stores its usable size in
   the word before the returned pointer; a freed block also chains through the
   word after that header (block[0]=size, block[1]=next-free). No coalescing or
   splitting -- simple, but real malloc/free. Values are unsigned addresses. */
int __heap;
int __freelist;

int malloc(int n) {
    int prev;
    int cur;
    if (__heap == 0) __heap = HEAP_BASE;
    prev = 0;
    cur = __freelist;
    while (cur != 0) {                 /* first fit on the free list */
        if (*cur >= n) {
            if (prev == 0) __freelist = *(cur + 1);
            else *(prev + 1) = *(cur + 1);
            return cur + 1;
        }
        prev = cur;
        cur = *(cur + 1);
    }
    cur = __heap;                      /* else bump the frontier */
    __heap = __heap + n + 1;
    *cur = n;
    return cur + 1;
}

void free(int p) {
    int b;
    b = p - 1;
    *(b + 1) = __freelist;
    __freelist = b;
}

int abs(int n) {
    /* machine arithmetic is unsigned; this is identity for in-range values */
    return n;
}
