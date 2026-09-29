#!/usr/bin/env python3
"""Floating-point reference for Digi Filter's SVF modes.

The target DSP (filter_dsp.s) is the same trapezoidal state-variable filter as
Digi EQ's eq_dsp.s: v1 is the band, v2 the low, and a mode is an output mix
(m0, m1, m2) over (v0, v1, v2). This model is what the fixed-point coefficients
in filter.c are checked against, and what the emulator test compares to.

    python filter_model.py     # self-test: the mix matches the analytic |H|

Modes:
    BP     band-pass, mix (0, k, 0)
    BP2    band-pass with ~half the Q (a wider curve): same mix, k from K27[qi>>1]
(COMB and PHASER are delay-based, not SVF mixes, and are not modelled here.)

with k = 1/Q. The SVF transfer functions are H_lp = 1/D, H_bp = s/D,
D = s^2 + k*s + 1, so H_BP = k*H_bp relative to the input.
"""
import cmath
import math

MODES = {"BP": (0.0, 1.0, 0.0)}             # BP2 is the same mix at a lower Q


def mix(mode, k):
    """-> the (m0, m1, m2) of `mode` at 1/Q = k. NOTCH/AP/PEAK carry the k."""
    m0, m1, m2 = MODES[mode]
    return m0, m1 * k, m2


def h_analytic(mode, f, fs, q):
    """|H(e^{jw})| of `mode` by the analog prototype (s = j w/w0, prewarped)."""
    k = 1.0 / q
    w = 2.0 * math.pi * f / fs
    w0 = 2.0 * math.pi * f / fs                       # cutoff == f in the sweep below
    # prewarp s = j*tan(pi f / fs) / tan(pi fc / fs); here fc == f, so s = j
    s = 1j * math.tan(math.pi * f / fs) / math.tan(math.pi * w0 / (2 * math.pi))
    d = s * s + k * s + 1.0
    m0, m1, m2 = mix(mode, k)
    h = m0 + m1 * (s / d) + m2 * (1.0 / d)
    return abs(h)


def comb_gain(f, fs, d, g):
    """|H| of the feedback comb y = x + g*y[n-D] at frequency f."""
    z = cmath.exp(-2j * math.pi * f / fs)
    return abs(1.0 / (1.0 - g * z ** d))


def phaser_gain(f, fs, a, depth, stages=4):
    """|H| of `stages` first-order all-pass sections H=(z^-1-a)/(1-a z^-1),
    mixed as out = x + depth*ap (the same shape as filter.c's phaser)."""
    z = cmath.exp(-2j * math.pi * f / fs)
    h1 = (z - a) / (1.0 - a * z)
    return abs(1.0 + depth * h1 ** stages)


def svf_block(mode, x, fs, fc, q):
    """Run the model's sample loop -> the output list (matches the target DSP)."""
    k = 1.0 / q
    g = math.tan(math.pi * fc / fs)
    a1 = 1.0 / (1.0 + g * (g + k))
    a2 = g * a1
    a3 = g * a2
    m0, m1, m2 = mix(mode, k)
    ic1 = ic2 = 0.0
    out = []
    for v0 in x:
        v3 = v0 - ic2
        v1 = a1 * ic1 + a2 * v3
        v2 = ic2 + a2 * ic1 + a3 * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        out.append(m0 * v0 + m1 * v1 + m2 * v2)
    return out


def _selftest():
    fs = 48000.0
    fc, q = 1000.0, 0.707
    # a sine sweep at the cutoff: the sine output's gain should match |H| at fc
    for mode in MODES:
        want = h_analytic(mode, fc, fs, q)
        n = 4000
        x = [math.sin(2.0 * math.pi * fc * i / fs) for i in range(n)]
        y = svf_block(mode, x, fs, fc, q)
        amp = max(abs(v) for v in y[n // 2:])             # settled amplitude (input is 1.0)
        err = abs(amp - want)
        print("%-6s |H(fc)| model=%.4f  svf=%.4f  err=%.4f" % (mode, want, amp, err))
        assert err < 0.05, (mode, want, amp)
    print("filter_model: OK")


if __name__ == "__main__":
    _selftest()
