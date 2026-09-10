#include <string.h>

int strlen(char *s) {
    int n;
    n = 0;
    while (s[n] != 0) n = n + 1;
    return n;
}

int strcmp(char *a, char *b) {
    int i;
    i = 0;
    while (a[i] != 0) {
        if (a[i] != b[i]) return a[i] - b[i];
        i = i + 1;
    }
    return 0 - b[i];             /* 0 if equal, else b is longer */
}

void strcpy(char *d, char *s) {
    int i;
    i = 0;
    while (s[i] != 0) {
        d[i] = s[i];
        i = i + 1;
    }
    d[i] = 0;
}

void memcpy(char *d, char *s, int n) {
    int i;
    for (i = 0; i < n; i = i + 1) d[i] = s[i];
}

void memset(char *d, int v, int n) {
    int i;
    for (i = 0; i < n; i = i + 1) d[i] = v;
}
