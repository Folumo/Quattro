#ifndef _GUI_H
#define _GUI_H
#include <gpu.h>
/* An immediate-mode GUI toolkit.

   Immediate mode (no retained widget tree, no callbacks) is the right shape for
   this machine: a widget is just "draw it and hit-test the mouse", so one frame
   is a straight line of code and costs only a few hundred CPU instructions.
   A retained tree would need allocation, invalidation and dispatch that a
   1400-instruction/second CPU cannot afford.

   Usage:
       while (1) {
           gui_begin();
           gui_panel(...);
           if (gui_button(x, y, w, h, "Click")) { ... }
           gui_end();
       }
*/

/* theme */
#define GUI_BG      1
#define GUI_FACE    7
#define GUI_BORDER  0
#define GUI_TEXT    0
#define GUI_HOVER   11
#define GUI_DOWN    9
#define GUI_ACCENT  9

extern int gui_mx;
extern int gui_my;
extern int gui_btn;
extern int gui_prev;

void gui_begin();
void gui_end();
int gui_hit(int x, int y, int w, int h);
int gui_clicked(int x, int y, int w, int h);
void gui_panel(int x, int y, int w, int h, int color);
void gui_label(int x, int y, char *s, int color);
int gui_button(int x, int y, int w, int h, char *label);
int gui_checkbox(int x, int y, char *label, int checked);
void gui_progress(int x, int y, int w, int h, int pct);
#endif
