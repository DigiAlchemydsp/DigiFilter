#!/usr/bin/env python3
"""Check the private C control against the resistor model and scan schedule (host cc)."""
import ctypes
import math
from pathlib import Path
import subprocess
import tempfile

import ob1_model as M
import ob1_programmer as P

ROOT = Path(__file__).resolve().parent.parent


def main():
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / 'control.c'
        library = Path(directory) / 'control.so'
        source.write_text('''#include <stddef.h>
#include "ob1_control.h"
_Static_assert(sizeof(struct ob1_control) == 12, "dispatcher stride");
_Static_assert(offsetof(struct ob1_control, fresh) == 8, "dispatcher fresh offset");
static struct ob1_control states[8] = {[0 ... 7] = {.fresh = 1}};
int cutoff(int word) { return ob1_knob_cutoff8(word); }
int step(int voice, int word) { return ob1_control_run(&states[voice], word); }
void reset(int voice) { states[voice].fresh = 1; }
unsigned int phase(int voice) { return states[voice].phase; }
''')
        subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-fPIC', '-I', str(ROOT), str(source), '-o', str(library)], check=True)
        c = ctypes.CDLL(str(library))
        c.cutoff.argtypes = [ctypes.c_int]
        c.step.argtypes = [ctypes.c_int, ctypes.c_int]
        c.reset.argtypes = [ctypes.c_int]
        c.phase.argtypes = [ctypes.c_int]
        c.phase.restype = ctypes.c_uint

        targets = []
        for word in range(0x7f01):
            actual = c.cutoff(word)
            assert abs(actual - P.knob_cutoff8(word)) <= 0.51, (word, actual)
            targets.append(actual)
        assert targets == sorted(targets)
        levels = sorted(set(targets))
        assert len(levels) == 64
        assert c.cutoff(-1) == levels[0] and c.cutoff(0x10000) == levels[-1]
        assert c.cutoff(64 << 8) == 64 << 8
        pitches = [M.corner_hz(fi8 / 256) for fi8 in levels]
        intervals = [1200 * math.log2(b / a) for a, b in zip(pitches, pitches[1:])]
        assert max(abs(interval - 100) for interval in intervals) < 0.7
        print('PASS: all FREQ words match the DAC model within 0.51 index LSB; 64 targets')
        print('Nominal base range: %.3f..%.3f Hz; adjacent intervals %.3f..%.3f cents' %
              (pitches[0], pitches[-1], min(intervals), max(intervals)))

        # Independent elapsed-time calculation: sample at the first block boundary after a scan.
        period = 22 * 89 / 126660
        held, last_scan, updates = None, -1, []
        for block in range(15000):
            word = (block * 193) % 0x7f01
            scan = math.floor((block * 32 / 48000) / period)
            if scan != last_scan:
                held, last_scan = c.cutoff(word), scan
                updates.append(block)
            assert c.step(0, word) == held, block
            assert c.phase(0) < 22 * 89 * 48000
        assert updates[1] == 24
        assert set(b - a for a, b in zip(updates, updates[1:])) == {23, 24}
        c.reset(0)
        assert c.step(0, 0) == c.cutoff(0) and c.phase(0) == 0
        for voice in range(1, 8):
            assert c.step(voice, voice * 4000) == c.cutoff(voice * 4000)
            assert c.phase(voice) == 0
        assert c.step(0, 0x7f00) == c.cutoff(0)
        print('PASS: ten seconds of scan timing, 23/24-block holds, reset and eight independent voices')


if __name__ == '__main__':
    main()
