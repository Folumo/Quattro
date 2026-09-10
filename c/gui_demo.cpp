// A GUI application for the Quattro machine -- running on a CPU built entirely
// from single-digit quaternary gates.  Build + run with:
//     python gui_run.py c/gui_demo.cpp
//
// Everything is drawn by the GPU (a command-driven blitter); the CPU only writes
// a few registers per shape, which is the only way this is affordable at
// ~1400 instructions/second.
#include <gui.h>

class Counter {
public:
    int value;
    Counter() { value = 0; }
    void add(int n) { value = value + n; }
    void reset() { value = 0; }
    int get() { return value; }
};

int main() {
    Counter c;
    int show;
    int pct;
    show = 1;
    pct = 0;

    while (1) {
        gui_begin();

        gpu_clear(GUI_BG);
        gui_panel(8, 8, 240, 176, LGRAY);
        gui_label(20, 18, "Quattro GPU + GUI", GUI_TEXT);
        gpu_line(20, 30, 236, 30, GUI_BORDER);

        if (gui_button(20, 40, 60, 20, "+1")) c.add(1);
        if (gui_button(90, 40, 60, 20, "+10")) c.add(10);
        if (gui_button(160, 40, 70, 20, "reset")) c.reset();

        gui_label(20, 72, "count:", GUI_TEXT);
        gui_progress(20, 90, 210, 12, c.get());

        show = gui_checkbox(20, 112, "show shapes", show);
        if (show) {
            gpu_circle(60, 150, 20, RED);
            gpu_circle(60, 150, 12, YELLOW);
            gpu_rect(100, 132, 36, 36, GREEN);
            gpu_frame(100, 132, 36, 36, GUI_BORDER);
            gpu_line(150, 132, 200, 168, MAGENTA);
            gpu_line(150, 168, 200, 132, BLUE);
        }

        pct = c.get();
        if (pct > 100) c.reset();

        gui_end();
    }
    return 0;
}
