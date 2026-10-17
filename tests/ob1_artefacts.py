#!/usr/bin/env python3
"""The OB-1 kernel's digital artefacts, on its host build (as tests/ob1_check.py builds it).

- Silence: zero in for a second gives exactly zero out, at every FREQ x RESO below the seed's (RESO 80);
  and after a loud note, the output decays to within 256 LSB (-138 dB) of zero. Not exactly: an integrator
  can't move by less than an LSB, so a state can stick a few LSBs off zero (fixed point's dead band).
- Stability: FREQ 0 and 127, RESO 0 and 127, a full-scale square in: no wrap-around (a sample jumping
  across most of the range), the output bounded.
- Aliasing: a 2923.8 Hz sine (bin 499 of 8192 samples: it doesn't divide 48 kHz, so its harmonics past
  Nyquist fold to bins between its harmonics) through OB4 at RESO 78 (k 3.8, just below self-oscillation)
  and up to nearly full scale: the largest folded harmonic (9th to 30th) against the fundamental.

    python tests/ob1_artefacts.py
"""
import ctypes
import math
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ob1_check as C  # noqa: E402

VCO = 1 << 30                                    # one OB-1 VCO at ON in the render's Q31 (ob1_vcf.c)
FULL = (1 << 31) - 1                             # a full-scale sample: two VCOs
BLK = 1500                                       # blocks a second


def run(so, tap, fi, qi, x):
    """x: a list of samples (a multiple of 32) through voice 0 from reset -> the output."""
    so.ob1_vcf_reset(0)
    buf = (ctypes.c_int * 32)()
    out = []
    for b in range(len(x) // 32):
        for i in range(32):
            buf[i] = x[32 * b + i]
        so.ob1_vcf_run(tap, fi << 8, qi, buf, 0)
        out += list(buf)
    return out


def dft_mag(y, f, fs=48000.0):
    w = -2j * math.pi * f / fs
    return abs(sum(v * complex(math.cos(w.imag * i), math.sin(w.imag * i)) for i, v in enumerate(y)))


def main():
    so = C.build()
    fails = []

    # silence, from reset: below RESO 80 the seed is disabled
    worst = 0
    for fi in (0, 32, 64, 96, 127):
        for qi in (0, 32, 64, 79):
            for tap in (4, 2):
                y = run(so, tap, fi, qi, [0] * (32 * BLK))
                worst = max(worst, max(abs(v) for v in y))
    print('silence in, RESO <= 79: largest output sample %d LSB' % worst)
    if worst:
        fails.append('silence')

    # after a loud note: a full-scale saw, then silence, allowing the 256 LSB fixed-point dead band
    tails = []
    for fi, qi in ((32, 0), (32, 78), (64, 79)):
        saw = [round(((i * 220 % 48000) / 24000.0 - 1) * FULL) for i in range(32 * BLK)]
        y = run(so, 4, fi, qi, saw + [0] * (32 * BLK))
        tails.append(max(abs(v) for v in y[-32 * 100:]))
    print('after a full-scale saw, the last 100 blocks of silence: largest %s LSB' % tails)
    if max(tails) > 256:
        fails.append('tail')

    # stability: a full-scale 100 Hz square, every corner of the knobs
    for fi in (0, 127):
        for qi in (0, 127):
            for tap in (4, 2):
                sq = [FULL if (i // 240) % 2 else -FULL for i in range(32 * BLK)]
                y = run(so, tap, fi, qi, sq)
                peak = max(abs(v) for v in y)
                jump = max(abs(y[i + 1] - y[i]) for i in range(len(y) - 1))
                bad = jump > (1 << 30)
                if bad:
                    fails.append(('stable', fi, qi, tap))
                print('square, FREQ %3d RESO %3d OB%d: peak %.3f of full scale, largest step %.3f%s'
                      % (fi, qi, tap, peak / FULL, jump / FULL, '  <- unstable' if bad else ''))

    # aliasing: bin 499 of 8192 (2923.8 Hz); harmonics 9 and up fold below Nyquist between the harmonics
    N, K = 8192, 499
    f0 = 48000.0 * K / N
    for amp in (0.5, 1.0, 1.95):                 # x a VCO, up to a full-scale sample
        x = [round(amp * VCO * math.sin(2 * math.pi * K * i / N)) for i in range(2 * N)]
        y = run(so, 4, 64, 78, x)[N:]
        def mag(b):
            w = 2 * math.pi * b / N
            return math.hypot(sum(v * math.cos(w * i) for i, v in enumerate(y)),
                              sum(v * math.sin(w * i) for i, v in enumerate(y)))
        fund = mag(K)
        folded = [(h, mag(N - h * K % N if h * K % N > N // 2 else h * K % N)) for h in range(9, 31)
                  if h * K % N > N // 2 or (h * K // (N // 2)) % 2]
        h, worst_alias = max(folded, key=lambda t: t[1])
        db = 20 * math.log10(max(worst_alias, 1e-9) / fund)
        print('%.1f Hz sine at %.2f x a VCO, OB4 FREQ 64 RESO 78: largest folded harmonic (the %dth) '
              '%.1f dB under the fundamental' % (f0, amp, h, -db))
        if -db < 60:
            fails.append(('alias', amp))
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
