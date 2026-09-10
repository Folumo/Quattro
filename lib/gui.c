#include <gui.h>

int gui_mx;
int gui_my;
int gui_btn;
int gui_prev;      /* button state last frame, for click-edge detection */

void gui_begin() {
    gui_mx = gpu_mouse_x();
    gui_my = gpu_mouse_y();
    gui_btn = gpu_buttons();
}

void gui_end() {
    gui_prev = gui_btn;
}

int gui_hit(int x, int y, int w, int h) {
    if (gui_mx < x) return 0;
    if (gui_my < y) return 0;
    if (gui_mx >= x + w) return 0;
    if (gui_my >= y + h) return 0;
    return 1;
}

/* a click is a release inside the widget after a press (a proper edge) */
int gui_clicked(int x, int y, int w, int h) {
    if (gui_hit(x, y, w, h) && gui_prev && gui_btn == 0) return 1;
    return 0;
}

void gui_panel(int x, int y, int w, int h, int color) {
    gpu_rect(x, y, w, h, color);
    gpu_frame(x, y, w, h, GUI_BORDER);
}

void gui_label(int x, int y, char *s, int color) {
    gpu_text(x, y, s, color);
}

int gui_button(int x, int y, int w, int h, char *label) {
    int face;
    face = GUI_FACE;
    if (gui_hit(x, y, w, h)) {
        face = GUI_HOVER;
        if (gui_btn) face = GUI_DOWN;
    }
    gpu_rect(x, y, w, h, face);
    gpu_frame(x, y, w, h, GUI_BORDER);
    gpu_text(x + 5, y + (h / 2) - 4, label, GUI_TEXT);
    return gui_clicked(x, y, w, h);
}

int gui_checkbox(int x, int y, char *label, int checked) {
    int r;
    gpu_rect(x, y, 10, 10, GUI_FACE);
    gpu_frame(x, y, 10, 10, GUI_BORDER);
    if (checked) gpu_rect(x + 3, y + 3, 4, 4, GUI_ACCENT);
    gpu_text(x + 15, y + 1, label, GUI_TEXT);
    r = checked;
    if (gui_clicked(x, y, 10, 10)) {
        if (checked) r = 0;
        else r = 1;
    }
    return r;
}

void gui_progress(int x, int y, int w, int h, int pct) {
    int fill;
    if (pct > 100) pct = 100;
    fill = (w * pct) / 100;
    gpu_rect(x, y, w, h, GUI_FACE);
    if (fill > 0) gpu_rect(x, y, fill, h, GUI_ACCENT);
    gpu_frame(x, y, w, h, GUI_BORDER);
}
