// Quattro C demo: for loop, ++, logical &&, continue.
int main() {
    int i;
    for (i = 0; i < 10; i++) {
        if (i > 2 && i < 6)     // skip 3, 4, 5
            continue;
        putchar(48 + i);        // prints 0 1 2 6 7 8 9
    }
    return 0;
}
