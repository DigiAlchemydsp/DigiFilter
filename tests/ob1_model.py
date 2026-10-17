#!/usr/bin/env python3
"""Floating-point reference for the OB-1 filter modes, OB4 and OB2 (TYPE 12, 13).

The Oberheim OB-1's VCF (synth board sheet 1342): four OTA one-pole stages with negative feedback
from the fourth (a ladder), and a MODE switch that takes the output from stage 4
(4-pole) or stage 2 (2-pole), the feedback always from stage 4. Modelled as a zero-delay-feedback
ladder of trapezoidal (TPT) one-poles: exactly the bilinear transform of the analog prototype

    y4 = x / ((1 + s)^4 + k),    y2 = x (1 + s)^2 / ((1 + s)^4 + k),    s = j w / wc (prewarped)

with the circuit's two saturations (fitted to SPICE's distortion, tests/spice/ob1_thd.cir, within 1.3 dB):
    the feedback through U28's tanh, k KF tanh(y4 / KF): the distortion with resonance;
    each stage's OTA, its input difference through KS tanh(d / KS): the (slight) distortion without.
Units: 1.0 is one OB-1 VCO at ON (+-5 V at the mixer, assumed), which reaches stage 4 at 0.966; the
Digitakt's Q31 render maps one VCO to 2^30 and full scale to two VCOs. This is what the fixed-point kernel
(ob1_vcf.c) and the emulator tests are checked against.

Knobs:
    FREQ  the measured reference control: wc = 10 + 20990 (fi / 127)^3 Hz
    RESO  quadratic below oscillation, compressed above it to preserve the existing saturation/headroom
    level x 0.25, as every stock TYPE

    python tests/ob1_model.py           # self-test
    python tests/ob1_model.py --table   # print ob1_tables.h (G, and the FLTR page's curves)
"""
import cmath
import math
import sys

FS = 48000.0
F64 = 327.0                 # the response graph's logarithmic frequency axis
STEPS_PER_OCT = 10.57       # graph columns per octave
K_MAX = 4.2                 # retain the existing maximum feedback and saturation behavior
LEVEL = 0.25                # every stock TYPE's output scaling (measured: OFF passes x 0.25)
KF = 1.61                   # U28's knee on y4: 2 VT / (220 / 33.2K) / 4.83 V (one VCO at stage 4)
KS = 4.9                    # a stage's knee on its input difference: 2 VT x 455 / 4.83 V


def corner_hz(fi):
    """The ladder's corner for a cutoff index (0..127, fractional)."""
    return 10.0 + 20990.0 * (fi / 127.0) ** 3


def gain_k(reso):
    """RESO 0..127 -> the loop gain."""
    k = 10.0 * (reso / 127.0) ** 2
    return k if k <= 4.0 else 4.25 - 0.375 / (k - 2.5)


def tpt_G(fc, fs=FS):
    """A TPT one-pole's G = g / (1 + g), g = tan(pi fc / fs)."""
    g = math.tan(math.pi * min(fc, 0.49 * fs) / fs)
    return g / (1.0 + g)




class Ladder:
    """One voice. run() takes and returns a list of floats (input units in, x LEVEL out)."""

    def __init__(self):
        self.s = [0.0] * 4

    def run(self, x, fc, k, tap=4, nonlinear=True, fs=FS, stages=True):
        G = tpt_G(fc, fs)
        s = self.s
        out = []
        for xn in x:
            # y4 = G^4 u + S, with S the stages' states carried through: solve u = x - k y4
            S = G ** 3 * (1 - G) * s[0] + G ** 2 * (1 - G) * s[1] + G * (1 - G) * s[2] + (1 - G) * s[3]
            u = (xn - k * S) / (1.0 + k * G ** 4)
            if nonlinear:                           # U28: the feedback through its tanh, on y4's estimate
                u = xn - k * KF * math.tanh((G ** 4 * u + S) / KF)
            ys = []
            inp = u
            for j in range(4):
                d = inp - s[j]
                if nonlinear and stages:            # each stage's OTA
                    d = KS * math.tanh(d / KS)
                v = G * d
                y = v + s[j]
                s[j] = y + v
                ys.append(y)
                inp = y
            out.append(LEVEL * (ys[1] if tap == 2 else ys[3]))
        return out


def h_analytic(f, fc, k, tap=4, fs=FS):
    """|H| of the analog prototype at f, prewarped to fc (what the linear TPT ladder must match)."""
    s = 1j * math.tan(math.pi * f / fs) / math.tan(math.pi * fc / fs)
    d = (1 + s) ** 4 + k
    return abs(LEVEL * ((1 + s) ** 2 if tap == 2 else 1) / d)


def h_measured(fs_hz, fc, k, tap=4, n=1 << 17, fs=FS):
    """|H| at each of fs_hz from the model's impulse response (linear). n covers k = 3.8's ring at 100 Hz."""
    h = Ladder().run([1.0] + [0.0] * (n - 1), fc, k, tap, nonlinear=False, fs=fs)
    return [abs(sum(v * cmath.exp(-2j * math.pi * f / fs * i) for i, v in enumerate(h) if v)) for f in fs_hz]


def thd(amp, k, fc=990.0, f0=200.0, stages=True):
    """THD (%) of a sine at amp x one VCO, as tests/spice/ob1_thd.cir measures it: the 4-pole output, the
    stage corner 990 Hz (44 uA), 200 Hz in; 48 whole periods after 48 to settle, no window."""
    per = int(FS / f0)
    x = [amp * 0.966 * math.sin(2 * math.pi * f0 * i / FS) for i in range(per * 96)]
    y = Ladder().run(x, fc, k, 4, True, stages=stages)[per * 48:]
    def bin_(h):
        w = -2j * math.pi * h * 48 / len(y)
        return abs(sum(v * cmath.exp(w * i) for i, v in enumerate(y)))
    a = [bin_(h) for h in range(1, 8)]
    return 100 * math.sqrt(sum(v * v for v in a[1:])) / a[0]


def curve_db(d, k, tap):
    """The FLTR page's curve: the analog prototype's response, in dB against unity at k = 0, d FREQ steps
    above the cutoff (the page's frequency axis is FREQ steps)."""
    s = 1j * 2.0 ** (d / STEPS_PER_OCT)
    return 20 * math.log10(abs(((1 + s) ** 2 if tap == 2 else 1) / ((1 + s) ** 4 + k)))


def table_c():
    """ob1_tables.h: G at each whole FREQ index 0..128 (128 for interpolation), Q31; and the FLTR page's
    curves, half-dB by distance from the cutoff (-64..64 steps), at RESO 0, 16, .. 112, 127, OB4 and OB2."""
    rows = [min(int(round(tpt_G(corner_hz(i)) * 2 ** 31)), 2 ** 31 - 1) for i in range(129)]
    lines = ['/* Generated by tests/ob1_model.py --table: G = g / (1 + g), g = tan(pi wc / 48000), the',
             ' * ladder\'s corner wc = 10 + 20990 (i / 127)^3 Hz, Q31. */',
             '#ifndef OB1_TABLES_H', '#define OB1_TABLES_H', '',
             'static const int OB1_G[129] = {']
    for i in range(0, 129, 6):
        lines.append('    ' + ', '.join('%d' % v for v in rows[i:i + 6]) + ',')
    positions = [max(0, min(127, round(64 + STEPS_PER_OCT * math.log2(corner_hz(i) / F64))))
                 for i in range(128)]
    lines += ['};', '', '/* Cutoff positions on the response graph\'s logarithmic frequency axis. */',
              'static const unsigned char OB1_POSITION[128] = {']
    for i in range(0, 128, 16):
        lines.append('    ' + ', '.join(str(v) for v in positions[i:i + 16]) + ',')
    lines += ['};', '',
              '/* The FLTR page\'s curves (tests/ob1_model.py curve_db): half-dB, clamped to -64..+63.5 dB, against',
              ' * unity at RESO 0; [tap: 0 OB4, 1 OB2][RESO: 0, 16, .. 112, 127][FREQ steps from the cutoff + 64]. */',
              'static const signed char OB1_CURVE[2][9][129] = {']
    for tap in (4, 2):
        lines.append('    {')
        for lvl in range(9):
            k = gain_k(16 * lvl if lvl < 8 else 127)
            vals = [max(-128, min(127, int(round(2 * curve_db(d, k, tap))))) for d in range(-64, 65)]
            lines.append('        {' + ', '.join('%d' % v for v in vals) + '},')
        lines.append('    },')
    lines += ['};', '', '#endif', '']
    return '\n'.join(lines)


def self_test():
    ok = True

    def check(name, cond, detail):
        nonlocal ok
        ok &= cond
        print('%-48s %s  %s' % (name, 'ok' if cond else 'FAIL', detail))

    # 1. the linear ladder is the bilinear transform of the prototype, both taps, with resonance
    worst = 0.0
    for fc in (100.0, 1000.0, 8000.0):
        for k in (0.0, 2.0, 3.8):
            for tap in (4, 2):
                fs_hz = [f for f in (fc / 4, fc / 2, fc, 2 * fc) if f < 0.45 * FS]
                for f, m in zip(fs_hz, h_measured(fs_hz, fc, k, tap)):
                    worst = max(worst, abs(20 * math.log10(m / h_analytic(f, fc, k, tap))))
    check('linear TPT ladder = prototype (dB)', worst < 0.05, 'worst %.4f dB' % worst)

    # 2. passband: LEVEL / (1 + k), the ladder's bass loss
    for k in (0.0, 2.0, 4.0):
        p = h_analytic(1e-3, 1000.0, k)
        check('passband at k = %.0f' % k, abs(p - LEVEL / (1 + k)) < 1e-6, '%.4f' % p)

    # 3. slopes four octaves up, well below Nyquist (where the bilinear warp steepens them): 24 and 12 dB/oct
    for tap, want in ((4, 24.0), (2, 12.0)):
        a, b = h_analytic(1600.0, 100.0, 0.0, tap), h_analytic(3200.0, 100.0, 0.0, tap)
        slope = 20 * math.log10(a / b)
        check('slope, %d-pole tap (dB/oct)' % tap, abs(slope - want) < 1.5, '%.2f' % slope)

    # 4. self-oscillation: k < 4 decays from a kick, k > 4 grows (linear) / settles to a tone (soft)
    def tail(k, nonlinear):
        y = Ladder().run([1e-3] + [0.0] * 47999, 1000.0, k, 4, nonlinear)
        return max(abs(v) for v in y[-2000:])
    check('k = 3.9 decays', tail(3.9, False) < 1e-6, '%.2e' % tail(3.9, False))
    check('k = 4.1 grows (linear)', tail(4.1, False) > 1e-2, '%.2e' % tail(4.1, False))
    t = tail(4.1, True)
    check('k = 4.1 settles to a bounded tone (tanh)', 1e-2 < t < LEVEL * KF, '%.3f' % t)

    # 5. distortion against SPICE: tests/spice/ob1_thd.cir's THD, within 3 dB
    spice = {0.0: (0.007, 0.030, 0.120), 3.33: (0.22, 0.92, 4.1)}       # at 1, 2, 4 x one VCO
    for k, want in spice.items():
        got = [thd(a, k) for a in (1.0, 2.0, 4.0)]
        worst = max(abs(20 * math.log10(g / w)) for g, w in zip(got, want))
        check('THD vs SPICE at k = %.2f (dB)' % k, worst < 3.0,
              ' '.join('%.3f%%' % g for g in got) + '  worst %.1f dB' % worst)

    # 6. the knob maps
    check('cutoff endpoints', corner_hz(0) == 10 and corner_hz(127) == 21000, '10..21000 Hz')
    check('cutoff at half travel', abs(corner_hz(63.5) - 2633.75) < 1e-9, '%.2f Hz' % corner_hz(63.5))
    check('resonance onset bracket', gain_k(80) < 4 < gain_k(81), 'RESO 80 decays, 81 grows')
    check('maximum feedback retained', abs(gain_k(127) - K_MAX) < 1e-12, 'k %.2f' % gain_k(127))
    for reso, loss in ((31.75, -4.22), (63.5, -10.88), (79.375, -13.82)):
        got = -20 * math.log10(1 + gain_k(reso))
        check('measured bass loss at RESO %.3f' % reso, abs(got - loss) < 0.02, '%.2f dB' % got)
    check('resonance map monotonic', all(gain_k(i + 1) > gain_k(i) for i in range(127)), '0..127')
    return ok


if __name__ == '__main__':
    if '--table' in sys.argv:
        sys.stdout.write(table_c())
    else:
        sys.exit(0 if self_test() else 1)
