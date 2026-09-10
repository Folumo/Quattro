// Tic-Tac-Toe, with an AI opponent, for the Quattro machine.
//     python gui_run.py c/tictactoe.cpp
//
// You are X, the machine is O. Click a square to play; click anywhere to start
// a new game once it's over.
//
// Design note: a full repaint costs ~10k CPU instructions, and this CPU runs at
// about 1400 per second -- so we must NOT redraw every loop. Instead the loop
// just polls the GPU's latched click register (a handful of instructions) and
// only repaints when the board actually changes. The click latch is what makes
// that safe: the device remembers a click until we read it, so a quick click is
// never missed no matter how slowly we poll.
//
// Everything is unsigned on this machine, so 9 (not -1) is the "no square"
// sentinel -- a negative would wrap to a huge number.
//
// We include <gpu.h> rather than <gui.h>: this game paints itself and needs no
// widgets.
#include <gpu.h>

#define EMPTY 0
#define XX    1
#define OO    2

#define BX 62          // board origin
#define BY 34
#define CELL 44

class Board {
public:
    int cell[9];

    void reset() {
        int i;
        for (i = 0; i < 9; i = i + 1) cell[i] = EMPTY;
    }
    int at(int i) { return cell[i]; }
    void set(int i, int v) { cell[i] = v; }

    int full() {
        int i;
        for (i = 0; i < 9; i = i + 1) {
            if (cell[i] == EMPTY) return 0;
        }
        return 1;
    }

    int lineOf(int a, int b, int c) {
        if (cell[a] == EMPTY) return 0;
        if (cell[a] == cell[b]) {
            if (cell[b] == cell[c]) return cell[a];
        }
        return 0;
    }

    int winner() {
        int w;
        w = lineOf(0, 1, 2); if (w) return w;
        w = lineOf(3, 4, 5); if (w) return w;
        w = lineOf(6, 7, 8); if (w) return w;
        w = lineOf(0, 3, 6); if (w) return w;
        w = lineOf(1, 4, 7); if (w) return w;
        w = lineOf(2, 5, 8); if (w) return w;
        w = lineOf(0, 4, 8); if (w) return w;
        w = lineOf(2, 4, 6); if (w) return w;
        return 0;
    }

    // a square that would immediately win for `who`, else 9
    int findWin(int who) {
        int i;
        for (i = 0; i < 9; i = i + 1) {
            if (cell[i] == EMPTY) {
                cell[i] = who;
                if (winner() == who) {
                    cell[i] = EMPTY;
                    return i;
                }
                cell[i] = EMPTY;
            }
        }
        return 9;
    }

    // win if we can, else block, else centre, else a corner, else anything
    int aiMove() {
        int m;
        int i;
        m = findWin(OO); if (m < 9) return m;
        m = findWin(XX); if (m < 9) return m;
        if (cell[4] == EMPTY) return 4;
        if (cell[0] == EMPTY) return 0;
        if (cell[2] == EMPTY) return 2;
        if (cell[6] == EMPTY) return 6;
        if (cell[8] == EMPTY) return 8;
        for (i = 0; i < 9; i = i + 1) {
            if (cell[i] == EMPTY) return i;
        }
        return 9;
    }
};

// which square is at this pixel?  9 = none.  (bounds first: unsigned!)
int cellAt(int px, int py) {
    int c;
    int r;
    if (px < BX) return 9;
    if (py < BY) return 9;
    if (px >= BX + 3 * CELL) return 9;
    if (py >= BY + 3 * CELL) return 9;
    c = (px - BX) / CELL;
    r = (py - BY) / CELL;
    return r * 3 + c;
}

void drawBoard(Board *b, int state) {
    int i;
    int r;
    int c;
    int x;
    int y;
    gpu_clear(BLUE);
    gpu_text(74, 8, "TIC TAC TOE", WHITE);

    gpu_rect(BX, BY, 3 * CELL, 3 * CELL, LGRAY);
    gpu_line(BX + CELL, BY, BX + CELL, BY + 3 * CELL - 1, BLACK);
    gpu_line(BX + 2 * CELL, BY, BX + 2 * CELL, BY + 3 * CELL - 1, BLACK);
    gpu_line(BX, BY + CELL, BX + 3 * CELL - 1, BY + CELL, BLACK);
    gpu_line(BX, BY + 2 * CELL, BX + 3 * CELL - 1, BY + 2 * CELL, BLACK);
    gpu_frame(BX, BY, 3 * CELL, 3 * CELL, BLACK);

    for (i = 0; i < 9; i = i + 1) {
        r = i / 3;
        c = i - r * 3;
        x = BX + c * CELL;
        y = BY + r * CELL;
        if (b->at(i) == XX) {
            gpu_line(x + 11, y + 11, x + 33, y + 33, RED);
            gpu_line(x + 33, y + 11, x + 11, y + 33, RED);
        }
        if (b->at(i) == OO) {
            gpu_circle(x + 22, y + 22, 13, WHITE);
            gpu_circle(x + 22, y + 22, 12, WHITE);
        }
    }

    if (state == 0) gpu_text(70, 174, "your move (X)", LCYAN);
    if (state == 1) gpu_text(70, 174, "YOU WIN!", YELLOW);
    if (state == 2) gpu_text(70, 174, "I WIN - click", LRED);
    if (state == 3) gpu_text(70, 174, "DRAW - click", LGREEN);
}

int main() {
    Board b;
    int state;          // 0 playing, 1 you won, 2 machine won, 3 draw
    int redraw;
    int idx;
    int m;
    int w;

    b.reset();
    state = 0;
    redraw = 1;

    while (1) {
        if (redraw) {
            drawBoard(&b, state);
            redraw = 0;
        }
        if (gpu_click()) {                 // cheap poll; latch means no misses
            if (state) {
                b.reset();                 // game over: click starts a new one
                state = 0;
                redraw = 1;
            } else {
                idx = cellAt(gpu_click_x(), gpu_click_y());
                if (idx < 9) {
                    if (b.at(idx) == EMPTY) {
                        b.set(idx, XX);
                        w = b.winner();
                        if (w == XX) state = 1;
                        else {
                            if (b.full()) state = 3;
                            else {
                                m = b.aiMove();
                                if (m < 9) b.set(m, OO);
                                w = b.winner();
                                if (w == OO) state = 2;
                                else {
                                    if (b.full()) state = 3;
                                }
                            }
                        }
                        redraw = 1;
                    }
                }
            }
        }
    }
    return 0;
}
