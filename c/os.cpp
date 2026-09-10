// QuattroOS -- the operating system.
//
// This is NOT part of the machine image. It is compiled to a real file on the
// drive, machine/bin/os.bin, which the boot ROM finds, streams into code memory
// through the load port, and jumps to. Build it and boot the machine with:
//
//     python main.py boot
//
// The drive IS the machine/ folder on your host disk, so the files this lists
// are real files on it, and the boot log it writes every startup really does
// land on your disk. Nothing here is baked into the machine.
#include <gui.h>
#include <string.h>

/* the drive's register window (288..303) */
#define DRV_CMD    288
#define DRV_STATUS 289
#define DRV_NAME   290
#define DRV_BUF    291
#define DRV_LEN    292
#define DRV_POS    293
#define DRV_RESULT 294
#define DRV_INDEX  295

#define D_READ  1
#define D_WRITE 2
#define D_LIST  4

/* scratch buffers, high in data memory and clear of the stack (20000) */
#define NAMEBUF 30000
#define RAWBUF  30100       /* file bytes exactly as they came off the drive */
#define VIEWBUF 30300       /* those bytes laid out as display lines */
#define LINELEN 28          /* characters that fit across the viewer panel */
#define VIEWLINES 3

#define MAXROWS 8           /* file rows that fit in the list panel */
#define ROWTOP  36          /* top of row 0 */
#define ROWH    12
#define NOSEL   99          /* sel value meaning "nothing picked yet" */

void drv(int reg, int val) { int *p; p = reg; *p = val; }
int drvget(int reg) { int *p; p = reg; return *p; }

/* put the name of directory entry `i` in NAMEBUF; returns the entry count */
int listEntry(int i) {
    drv(DRV_NAME, 0);                     /* no name = the drive's root */
    drv(DRV_BUF, NAMEBUF);
    drv(DRV_INDEX, i);
    drv(DRV_CMD, D_LIST);
    return drvget(DRV_RESULT);
}

/* Read the top of a file and lay it out as display lines, breaking at newlines
   and wrapping at LINELEN. Returns 0 if the drive refused the read (a folder,
   say) -- the caller must not then trust the buffers.
   The drive gives one byte per word, so a char* indexes it directly. */
int readLines(char *name) {
    char *raw;
    char *out;
    int n;
    int p;
    int line;
    int col;
    int c;

    drv(DRV_NAME, name);
    drv(DRV_BUF, RAWBUF);
    drv(DRV_LEN, LINELEN * VIEWLINES);
    drv(DRV_POS, 0);
    drv(DRV_CMD, D_READ);
    if (drvget(DRV_STATUS)) return 0;
    n = drvget(DRV_RESULT);

    raw = RAWBUF;
    p = 0;
    for (line = 0; line < VIEWLINES; line = line + 1) {
        out = VIEWBUF + line * 32;
        col = 0;
        while (col < LINELEN && p < n) {
            c = raw[p];
            p = p + 1;
            if (c == 10) break;           /* newline ends this display line */
            if (c != 13) {                /* skip CR, so CRLF files read right */
                out[col] = c;
                col = col + 1;
            }
        }
        out[col] = 0;
    }
    return 1;
}

/* The drive is read/write, so say so on it: this file appears on your host
   disk, and in the list below, the moment the machine boots. */
void writeLog() {
    char *s;
    s = "QuattroOS booted from bin/os.bin";
    drv(DRV_NAME, "boot.log");
    drv(DRV_BUF, s);                      /* the drive DMAs it straight out */
    drv(DRV_LEN, strlen(s));
    drv(DRV_POS, 0);
    drv(DRV_CMD, D_WRITE);
}

void desktop(int count, int sel, int ok) {
    int i;
    int y;
    gpu_clear(BLUE);

    gpu_rect(0, 0, GPU_WIDTH, 13, LGRAY);
    gpu_text(4, 3, "QuattroOS", BLACK);
    gpu_text(134, 3, "drive: machine/", DGRAY);

    gui_panel(6, 20, 244, 118, LGRAY);
    gpu_text(12, 24, "Files on the drive:", BLACK);
    y = ROWTOP + 2;
    for (i = 0; i < count && i < MAXROWS; i = i + 1) {
        listEntry(i);
        if (i == sel) gpu_rect(10, y - 2, 236, ROWH, LCYAN);
        gpu_text(14, y, NAMEBUF, BLACK);
        y = y + ROWH;
    }

    gui_panel(6, 142, 244, 48, LGRAY);
    if (sel == NOSEL) {
        gpu_text(12, 147, "click a file to read it", DGRAY);
    } else {
        listEntry(sel);
        gpu_text(12, 146, NAMEBUF, BLUE);
        if (ok) {
            gpu_text(12, 158, VIEWBUF, BLACK);
            gpu_text(12, 168, VIEWBUF + 32, BLACK);
            gpu_text(12, 178, VIEWBUF + 64, BLACK);
        } else {
            gpu_text(12, 162, "(a folder, not a file)", DGRAY);
        }
    }
}

int main() {
    int count;
    int sel;
    int ok;
    int i;
    int y;

    writeLog();
    count = listEntry(0);       /* the entry count comes back with entry 0 */
    sel = NOSEL;
    ok = 0;
    desktop(count, sel, ok);

    /* Nothing on screen changes unless you click, so redraw only then. The
       click latch means a quick click is never missed, however slow we poll. */
    while (1) {
        if (gpu_click()) {
            y = gpu_click_y();
            i = (y - ROWTOP) / ROWH;
            if (y >= ROWTOP && i < count && i < MAXROWS) {
                listEntry(i);
                ok = readLines(NAMEBUF);
                sel = i;
                desktop(count, sel, ok);
            }
        }
    }
    return 0;
}
