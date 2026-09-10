// A real C++ program for the Quattro machine: a linked-list stack with a
// constructor, member functions, new/delete, and this.  Build + run with:
//     python ccompiler.py c/stack.cpp
#include <stdio.h>
#include <stdlib.h>

class Node {
public:
    int val;
    Node *next;
};

class Stack {
public:
    Node *head;
    int size;

    Stack() { head = 0; size = 0; }

    void push(int v) {
        Node *n;
        n = new Node();
        n->val = v;
        n->next = head;
        head = n;
        size = size + 1;
    }

    int pop() {
        Node *n;
        int v;
        n = head;
        v = n->val;
        head = n->next;
        size = size - 1;
        delete n;
        return v;
    }

    int count() { return size; }
};

int main() {
    Stack s;
    int i;
    for (i = 1; i <= 5; i = i + 1) s.push(i * i);
    printf("pushed %d items\n", s.count());
    while (s.count() > 0) {
        printf("%d ", s.pop());
    }
    putchar(10);
    return 0;
}
