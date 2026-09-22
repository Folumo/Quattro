"""Q4 -- the 4-quarter (byte-wide) Quattro CPU.

A word is 4 quarters = 8 bits = one byte. Built from the same six gate
primitives as the 32-bit machine; the ALU is generated at width 4 by the shared
tools/gen_words.py. See cpu4.py for the ISA, count4.py for the component census,
and HARDWARE.md for how to wire it to real RAM, a clock, a display, and USB.
"""
from .cpu4 import Machine4, asm, run_demo, DEMOS

__all__ = ['Machine4', 'asm', 'run_demo', 'DEMOS']
