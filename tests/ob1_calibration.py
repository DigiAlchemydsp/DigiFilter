#!/usr/bin/env python3
"""Check the measured cutoff/resonance targets against the actual native kernel."""
import ctypes
import math
from pathlib import Path

import numpy as np

import ob1_check as C
import ob1_model as M

RATE, FULL = 48000, (1 << 31) - 1


def render(so, tap, fi, qi, source):
    so.ob1_vcf_reset(0)
    out = np.empty(len(source), dtype=np.int32)
    for n in range(0, len(source), 32):
        block = np.array(source[n:n + 32], dtype=np.int32, copy=True)
        so.ob1_vcf_run(tap, round(fi * 256), qi,
                       block.ctypes.data_as(ctypes.POINTER(ctypes.c_int)), 0)
        out[n:n + 32] = block
    return out / FULL


def position(hz):
    return 127 * ((hz - 10) / 20990) ** (1 / 3)


def main():
    assert (Path(C.ROOT) / 'ob1_tables.h').read_text() == M.table_c(), 'stale generated tables'
    so = C.build()
    t = np.arange(2 * RATE) / RATE
    for tap in (4, 2):
        for hz in (250, 1000, 4000):
            source = np.rint(.01 * FULL * np.sin(2 * np.pi * hz * t)).astype(np.int32)
            y = render(so, tap, position(hz), 0, source)[RATE:]
            attenuation = 20 * math.log10(np.std(y) / (.01 / math.sqrt(2)) / .25)
            target = -12.0412 if tap == 4 else -6.0206
            assert abs(attenuation - target) < .1, (tap, hz, attenuation)
            print('OB%d nominal %d Hz: %.2f dB at the cutoff' % (tap, hz, attenuation))
        source = np.full(2 * RATE, round(.01 * FULL), dtype=np.int32)
        for qi in (0, 32, 64, 79):
            y = render(so, tap, position(1000), qi, source)[RATE:]
            gain = np.mean(y) / (.01 * .25)
            loss = 20 * math.log10(gain)
            expected = -20 * math.log10(1 + 10 * (qi / 127) ** 2)
            assert abs(loss - expected) < .02, (tap, qi, loss, expected)
        for hz in (250, 1000, 4000):
            source = np.zeros(3 * RATE, dtype=np.int32)
            source[:32] = round(.01 * FULL)
            tails = []
            for qi in (80, 81):
                y = render(so, tap, position(hz), qi, source)
                tails.append(float(np.std(y[-RATE:])))
            assert tails[0] < 2e-5 and tails[1] > max(.001, 100 * tails[0]), (tap, hz, tails)
            print('OB%d %d Hz onset: RESO 80 tail %.2g, RESO 81 tail %.2g' % (tap, hz, *tails))
        levels = {}
        source = np.zeros(3 * RATE, dtype=np.int32)
        source[:32] = round(.01 * FULL)
        for qi in (83, 87, 95, 127):
            y = render(so, tap, position(1000), qi, source)
            levels[qi] = float(np.std(y[-RATE:]))
        for qi, target in ((83, -6.9), (87, -3.9), (95, -1.7)):
            relative = 20 * math.log10(levels[qi] / levels[127])
            assert abs(relative - target) < 1.0, (tap, qi, relative, target)
            print('OB%d RESO %d relative oscillation level: %.2f dB (target %.1f)' % (tap, qi, relative, target))
    print('PASS: measured cutoff, bass loss, onset and relative oscillation levels')


if __name__ == '__main__':
    main()
