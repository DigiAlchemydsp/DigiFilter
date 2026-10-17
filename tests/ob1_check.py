#!/usr/bin/env python3
"""Check the fixed-point OB-1 kernel (ob1_vcf.c, built for the host) against the reference (ob1_model.py).

Builds ob1_vcf.c as a shared library with the host's cc (the same code as on the ColdFire, with its multiply
in C instead of EMAC) and runs it and the model on the same input:

- the linear response on a grid of FREQ x RESO x tap: a step held for half the run, then released (an
  impulse into a 4-pole lowpass at 14 Hz comes out a few hundred LSBs tall, which measures the output's
  rounding, not the filter); each one's worst error relative to its peak;
- the saturation: THD of a 200 Hz sine at 0.5, 1 and 2 x one VCO, against the model with the kernel's parts
  (U28's saturation, not the stages');
- real levels: a full-scale saw (two VCOs, as OB-1 hot) at low cutoff, against the model and with no
  wrap-around (the crackle at FREQ 30-80 before the kernel scaled its Q31 input);
- a full-scale sweep, FREQ 20-90-20 one step a block, whose steps must be no larger than a gliding model's;
- a small sweep, one FREQ step a block, against the model gliding sample by sample (the kernel ramps its
  coefficients across each block);
- self-oscillation from digital silence: RESO 127 must start, including at the 10 Hz endpoint.

    python tests/ob1_check.py            # exit 1 if any check exceeds its tolerance
"""
import cmath
import ctypes
import math
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import ob1_model as M  # noqa: E402

TOL = 1e-3                      # error under 1e-3 of the response's peak (linear, k <= 3.8)
VCO = 1 << 30                   # one OB-1 VCO at ON in the render's Q31 (a full-scale sample is two, ob1_vcf.c)
AMP = VCO // 2                  # the step: half a VCO
BLOCKS = 256                    # 8192 samples


def build():
    windows = sys.platform == 'win32'
    lib = os.path.join(tempfile.mkdtemp(), 'ob1_vcf.dll' if windows else 'ob1_vcf.so')
    compiler = os.environ.get('CC', 'gcc' if windows else 'cc')
    flags = [] if windows else ['-fPIC']
    subprocess.check_call([compiler, '-O2', '-shared', *flags, '-Wall', '-Wextra', '-I', ROOT,
                           os.path.join(ROOT, 'ob1_vcf.c'), '-o', lib])
    so = ctypes.CDLL(lib)
    so.ob1_vcf_run.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int),
                               ctypes.c_int]
    return so


def kernel_step(so, tap, fi, qi):
    so.ob1_vcf_reset(0)
    out = []
    buf = (ctypes.c_int * 32)()
    for b in range(BLOCKS):
        for i in range(32):
            buf[i] = AMP if b < BLOCKS // 2 else 0
        so.ob1_vcf_run(tap | 0x100, fi << 8, qi, buf, 0)
        out += [v / AMP for v in buf]
    return out


def model_step(tap, fi, qi):
    n = 32 * BLOCKS
    return M.Ladder().run([1.0] * (n // 2) + [0.0] * (n // 2), M.corner_hz(fi), M.gain_k(qi), tap,
                          nonlinear=False)


def kernel_thd(so, fi, qi, amp, f0=200.0):
    """THD (%) as ob1_model.thd measures it, through the kernel: 96 periods, the last 48."""
    per = int(M.FS / f0)
    n = per * 96
    x = [round(amp * 0.966 * math.sin(2 * math.pi * f0 * i / M.FS) * VCO) for i in range(n)]
    so.ob1_vcf_reset(0)
    buf = (ctypes.c_int * 32)()
    y = []
    for b in range(n // 32):
        for i in range(32):
            buf[i] = x[32 * b + i]
        so.ob1_vcf_run(4, round(fi * 256), qi, buf, 0)
        y += list(buf)
    y = y[per * 48:]
    a = [abs(sum(v * cmath.exp(-2j * math.pi * h * 48 / len(y) * i) for i, v in enumerate(y))) for h in range(1, 8)]
    return 100 * math.sqrt(sum(v * v for v in a[1:])) / a[0]


def main():
    so = build()
    worst = 0.0
    fails = []
    for fi in (0, 16, 32, 48, 64, 80, 96, 112, 127):
        for qi in (0, 32, 64, 78):             # 78: k ~3.8, below oscillation
            for tap in (4, 2):
                k, m = kernel_step(so, tap, fi, qi), model_step(tap, fi, qi)
                peak = max(abs(v) for v in m)
                err = max(abs(a - b) for a, b in zip(k, m)) / peak
                worst = max(worst, err)
                flag = '' if err < TOL else '  <- over %.0e' % TOL
                if flag:
                    fails.append((fi, qi, tap))
                print('FREQ %3d (%7.1f Hz)  RESO %3d (k %.2f)  OB%d: max error %.2e%s'
                      % (fi, M.corner_hz(fi), qi, M.gain_k(qi), tap, err, flag))
    print('worst %.2e; %d of %d over %.0e' % (worst, len(fails), 9 * 4 * 2, TOL))
    # Keep the distortion fixture near its 990 Hz, k ~3.3 physical operating point.
    thd_fi = 127 * ((990 - 10) / 20990) ** (1 / 3)
    for qi in (0, 73):
        for amp in (0.5, 1.0, 2.0):                 # two VCOs is a full-scale sample
            got = kernel_thd(so, thd_fi, qi, amp)
            want = M.thd(amp, M.gain_k(qi), fc=M.corner_hz(thd_fi), stages=False)
            db = abs(20 * math.log10(max(got, 1e-6) / max(want, 1e-6)))
            bad = qi and db > 1.0                   # within 1 dB (RESO 0: both ~0, nothing to compare)
            if bad:
                fails.append(('thd', qi, amp))
            print('THD RESO %3d at %.0f x one VCO: kernel %.4f%%, model %.4f%%  (%.2f dB)%s'
                  % (qi, amp, got, want, db, '  <- over 1 dB' if bad else ''))
    buf = (ctypes.c_int * 32)()
    # real levels: a full-scale saw at low cutoff, the states must not wrap (they did at Q31 before IN_SHIFT)
    n = 32 * 750
    saw = [round(((i * 110 % 48000) / 24000.0 - 1) * (2 * VCO - 1)) for i in range(n)]
    for fi in (13, 23, 45):
        for qi in (16, 58, 77):
            so.ob1_vcf_reset(0)
            y = []
            for b in range(n // 32):
                for i in range(32):
                    buf[i] = saw[32 * b + i]
                so.ob1_vcf_run(4, round(fi * 256), qi, buf, 0)
                y += list(buf)
            ref = M.Ladder().run([v / VCO for v in saw], M.corner_hz(fi), M.gain_k(qi), 4, stages=False)
            err = max(abs(a / VCO - r) for a, r in zip(y, ref)) / max(abs(r) for r in ref)
            jump = max(abs(y[i + 1] - y[i]) for i in range(n - 1)) / float(1 << 31)
            bad = err > 5e-2 or jump > 0.25           # 5e-2: U28's series against tanh, at two VCOs
            if bad:
                fails.append(('level', fi, qi))
            print('full-scale saw, FREQ %d RESO %d: against the model %.1e of peak, largest step %.3f%s'
                  % (fi, qi, err, jump, '  <- over' if bad else ''))
    # a sweep at real level, as on the unit: a full-scale saw, FREQ 20-90-20 one step a block, RESO 100; its
    # steps must be no larger than a gliding model's (the crackle was largest in sweeps)
    so.ob1_vcf_reset(0)
    lad, k, m, n = M.Ladder(), [], [], 0
    for b in range(140):
        fe = 20 + (b if b < 70 else 140 - b)
        fs = 20 + (b - 1 if 0 < b <= 70 else 141 - b if b > 70 else 0)
        xs = [(((n + i) * 110 % 48000) / 24000.0 - 1) * 2 for i in range(32)]
        for i in range(32):
            buf[i] = min(round(xs[i] * VCO), (1 << 31) - 1)
        so.ob1_vcf_run(4, fe << 8, 73, buf, 0)
        k += [v / VCO for v in buf]
        for i in range(32):
            m += lad.run([xs[i]], M.corner_hz(fs + (fe - fs) * (i + 0.5) / 32), M.gain_k(73), 4, stages=False)
        n += 32
    kj = max(abs(k[i + 1] - k[i]) for i in range(len(k) - 1))
    mj = max(abs(m[i + 1] - m[i]) for i in range(len(m) - 1))
    bad = kj > 1.1 * mj
    if bad:
        fails.append(('sweep at level',))
    print('sweep at full scale, FREQ 20-90-20, RESO 73: largest step %.4f, a gliding model\'s %.4f%s'
          % (kj, mj, '  <- clicks' if bad else ''))
    # a cutoff sweep, FREQ 40 to 110 one step a block, RESO 64, a 220 Hz sine: the kernel's ramp against a glide
    buf = (ctypes.c_int * 32)()
    so.ob1_vcf_reset(0)
    lad, k, m, n = M.Ladder(), [], [], 0
    for b in range(80):
        f_end, f_start = 40 + min(b, 70), 40 + min(max(b - 1, 0), 70)
        for i in range(32):
            buf[i] = round(math.sin(2 * math.pi * 220 * (n + i) / M.FS) * AMP)
        so.ob1_vcf_run(4 | 0x100, f_end << 8, 64, buf, 0)
        k += [v / AMP for v in buf]
        for i in range(32):
            fi = f_start + (f_end - f_start) * (i + 0.5) / 32
            m += lad.run([math.sin(2 * math.pi * 220 * n / M.FS)], M.corner_hz(fi), M.gain_k(64), 4, nonlinear=False)
            n += 1
    peak = max(abs(v) for v in m)
    err = max(abs(a - b) for a, b in zip(k, m)) / peak
    if err > 5e-3:
        fails.append(('sweep',))
    print('cutoff sweep, one step a block, against a glide: max error %.2e of peak%s'
          % (err, '  <- over 5e-3' if err > 5e-3 else ''))
    # The lowest cutoff needs enough cycles for the quiet seed to reach the measurement threshold.
    for fi, limit in ((0, 16.0), (32, 3.5), (48, 1.5), (64, 1.0), (96, 0.2), (112, 0.2)):
        so.ob1_vcf_reset(0)
        start = None
        for b in range(int(1500 * limit * 2)):
            for i in range(32):
                buf[i] = 0
            so.ob1_vcf_run(4, fi << 8, 127, buf, 0)
            if max(abs(v) for v in buf) > VCO * 0.01:
                start = b / 1500.0
                break
        bad = start is None or start > limit
        if bad:
            fails.append(('osc', fi))
        print('self-oscillation from silence, FREQ %d RESO 127: %s (limit %.1f s)%s'
              % (fi, 'none' if start is None else '%.2f s' % start, limit, '  <- too slow' if bad else ''))
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
