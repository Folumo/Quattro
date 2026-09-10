#include <gpu.h>

/* Each of these is a handful of stores: the whole cost of filling a 1200-pixel
   rectangle is ~12 CPU instructions, because the device does the painting. */

void gpu_set(int reg, int val) {
    int *p;
    p = reg;
    *p = val;
}

int gpu_get(int reg) {
    int *p;
    p = reg;
    return *p;
}

void gpu_clear(int color) {
    gpu_set(GPU_COLOR, color);
    gpu_set(GPU_CMD, 0);
}

void gpu_pixel(int x, int y, int color) {
    gpu_set(GPU_X, x);
    gpu_set(GPU_Y, y);
    gpu_set(GPU_COLOR, color);
    gpu_set(GPU_CMD, 1);
}

void gpu_rect(int x, int y, int w, int h, int color) {
    gpu_set(GPU_X, x);
    gpu_set(GPU_Y, y);
    gpu_set(GPU_W, w);
    gpu_set(GPU_H, h);
    gpu_set(GPU_COLOR, color);
    gpu_set(GPU_CMD, 2);
}

void gpu_frame(int x, int y, int w, int h, int color) {
    gpu_set(GPU_X, x);
    gpu_set(GPU_Y, y);
    gpu_set(GPU_W, w);
    gpu_set(GPU_H, h);
    gpu_set(GPU_COLOR, color);
    gpu_set(GPU_CMD, 3);
}

void gpu_line(int x, int y, int x2, int y2, int color) {
    gpu_set(GPU_X, x);
    gpu_set(GPU_Y, y);
    gpu_set(GPU_X2, x2);
    gpu_set(GPU_Y2, y2);
    gpu_set(GPU_COLOR, color);
    gpu_set(GPU_CMD, 4);
}

void gpu_circle(int x, int y, int r, int color) {
    gpu_set(GPU_X, x);
    gpu_set(GPU_Y, y);
    gpu_set(GPU_X2, r);
    gpu_set(GPU_COLOR, color);
    gpu_set(GPU_CMD, 5);
}

void gpu_text(int x, int y, char *s, int color) {
    gpu_set(GPU_X, x);
    gpu_set(GPU_Y, y);
    gpu_set(GPU_ADDR, s);           /* the GPU DMAs the string out of RAM */
    gpu_set(GPU_COLOR, color);
    gpu_set(GPU_CMD, 6);
}

void gpu_blit(int x, int y, int w, int h, int *data) {
    gpu_set(GPU_X, x);
    gpu_set(GPU_Y, y);
    gpu_set(GPU_W, w);
    gpu_set(GPU_H, h);
    gpu_set(GPU_ADDR, data);
    gpu_set(GPU_CMD, 7);
}

int gpu_mouse_x() { return gpu_get(GPU_MX); }
int gpu_mouse_y() { return gpu_get(GPU_MY); }
int gpu_buttons() { return gpu_get(GPU_BTN); }
int gpu_click() { return gpu_get(GPU_CLICK); }      /* consumes the latch */
int gpu_click_x() { return gpu_get(GPU_CLICKX); }
int gpu_click_y() { return gpu_get(GPU_CLICKY); }
