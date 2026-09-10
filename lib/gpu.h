#ifndef _GPU_H
#define _GPU_H
/* Low-level access to the Quattro GPU: a command-driven blitter. You set a few
   registers and write CMD; the device does the pixel work. Never loop over
   pixels yourself -- the CPU only runs ~1400 instructions/second. */

/* memory-mapped registers (the GPU's window is 256..287) */
#define GPU_CMD     256
#define GPU_X       257
#define GPU_Y       258
#define GPU_W       259
#define GPU_H       260
#define GPU_COLOR   261
#define GPU_ADDR    262
#define GPU_X2      263
#define GPU_Y2      264
#define GPU_MX      265
#define GPU_MY      266
#define GPU_BTN     267
#define GPU_STATUS  268
#define GPU_CLICK   269   /* consuming read: 1 if a click was latched */
#define GPU_CLICKX  270
#define GPU_CLICKY  271

#define GPU_WIDTH   256
#define GPU_HEIGHT  192

/* the 16-colour palette */
#define BLACK 0
#define BLUE 1
#define GREEN 2
#define CYAN 3
#define RED 4
#define MAGENTA 5
#define BROWN 6
#define LGRAY 7
#define DGRAY 8
#define LBLUE 9
#define LGREEN 10
#define LCYAN 11
#define LRED 12
#define LMAGENTA 13
#define YELLOW 14
#define WHITE 15

void gpu_set(int reg, int val);
int gpu_get(int reg);
void gpu_clear(int color);
void gpu_pixel(int x, int y, int color);
void gpu_rect(int x, int y, int w, int h, int color);
void gpu_frame(int x, int y, int w, int h, int color);
void gpu_line(int x, int y, int x2, int y2, int color);
void gpu_circle(int x, int y, int r, int color);
void gpu_text(int x, int y, char *s, int color);
void gpu_blit(int x, int y, int w, int h, int *data);
int gpu_mouse_x();
int gpu_mouse_y();
int gpu_buttons();
/* gpu_click() returns 1 once per completed click and clears the latch, so a
   quick click is never missed however slowly the program polls. Read the
   position with gpu_click_x()/gpu_click_y() after it returns 1. */
int gpu_click();
int gpu_click_x();
int gpu_click_y();
#endif
