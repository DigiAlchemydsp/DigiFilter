#!/usr/bin/env python3
"""Draw the OB-1 filter modes' figures for docs/ob1.md (docs/img/ob1-*.png).

- ob1-response.png: OB4's and OB2's response at FREQ 64 for four RESO settings, the model (tests/ob1_model.py,
  the analog prototype prewarped) as lines, the fixed-point kernel (ob1_vcf.c on the host, linear) as points.
- ob1-spice.png: the circuit (tests/spice/ob1_vcf.cir in ngspice, small signal) against the model's prototype,
  at six resonance currents; the model's k for each from SPICE's own passband, 1 / (1 + k).
- ob1-thd.png: THD against input level, without resonance and at k 3.3: SPICE (tests/spice/ob1_thd.cir),
  the model (both saturations), the kernel (U28's).

Needs cc, matplotlib and numpy; ngspice for the two SPICE figures (without it, only ob1-response.png):
    uv run --with matplotlib --with numpy python tests/ob1_plots.py
"""
import ctypes
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import ob1_model as M  # noqa: E402
import ob1_check as C  # noqa: E402

OUT = os.path.join(ROOT, 'docs', 'img')
SPICE = os.path.join(HERE, 'spice')
FC_SPICE = 991.0              # the SPICE runs' stage corner: 44 uA x (220 / 100.22K) / (2 VT x 2 pi x 300 pF)
GAIN_SPICE = 0.966            # one VCO at the mixer to stage 4 at DC (455 x 100 / 47.1K)
IRS = ['0', '0.2m', '0.4m', '0.6m', '0.8m', '0.9m']


def kernel_response(so, tap, fi, qi, n=1 << 15):
    """The kernel's magnitude response (linear) from its impulse response -> (freqs, dB vs unity)."""
    so.ob1_vcf_reset(0)
    buf = (ctypes.c_int * 32)()
    amp, h = 1 << 24, []
    for b in range(n // 32):
        for i in range(32):
            buf[i] = amp if (b == 0 and i == 0) else 0
        so.ob1_vcf_run(tap | 0x100, fi << 8, qi, buf, 0)
        h += [v / amp for v in buf]
    H = np.abs(np.fft.rfft(np.array(h)))
    f = np.fft.rfftfreq(n, 1 / M.FS)
    return f, 20 * np.log10(np.maximum(H / M.LEVEL, 1e-12))


def response_plot(so):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    f = np.logspace(np.log10(20), np.log10(20000), 400)
    for ax, tap, name in ((axes[0], 4, 'OB4'), (axes[1], 2, 'OB2')):
        for qi, col in ((0, 'C0'), (32, 'C1'), (64, 'C2'), (78, 'C3')):
            k = M.gain_k(qi)
            model = [20 * math.log10(M.h_analytic(x, M.corner_hz(64), k, tap) / M.LEVEL) for x in f]
            ax.semilogx(f, model, col, label='RESO %d (k %.2f)' % (qi, k))
            kf, kdb = kernel_response(so, tap, 64, qi)
            pick = np.unique(np.searchsorted(kf, np.logspace(np.log10(25), np.log10(18000), 28)))
            ax.semilogx(kf[pick], kdb[pick], 'o', color=col, ms=3.5)
        ax.set_title('%s at FREQ 64 (corner %.0f Hz)' % (name, M.corner_hz(64)))
        ax.set_xlabel('Hz')
        ax.set_ylim(-80, 30)
        ax.grid(True, which='both', alpha=0.3)
    axes[0].set_ylabel('dB (against unity at RESO 0)')
    axes[0].legend(loc='lower left', fontsize=8)
    fig.suptitle('Lines: the model (analog prototype, prewarped). Points: the fixed-point kernel (ob1_vcf.c).',
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'ob1-response.png'), dpi=110)


def spice_runs(tmp):
    lines = ['.include %s' % os.path.join(SPICE, 'ob1_vcf.cir'), '.control', 'set wr_singlescale',
             'set wr_vecnames']
    for ir in IRS:
        lines += ['alterparam Ir = %s' % ir, 'reset', 'ac dec 100 10 30k',
                  'wrdata %s vdb(y4) vdb(y2)' % os.path.join(tmp, 'ac_%s.dat' % ir)]
    lines += ['quit', '.endc']
    cir = os.path.join(tmp, 'ac.cir')
    open(cir, 'w').write('\n'.join(lines) + '\n')
    subprocess.run(['ngspice', '-b', cir], check=True, capture_output=True)
    runs = {}
    for ir in IRS:
        d = np.loadtxt(os.path.join(tmp, 'ac_%s.dat' % ir), skiprows=1)
        runs[ir] = (d[:, 0], d[:, 1], d[:, 2])
    return runs


def spice_plot(runs):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    lo0 = runs['0'][1][0]
    for ax, col_db, tap, name in ((axes[0], 1, 4, 'stage 4 (OB4)'), (axes[1], 2, 2, 'stage 2 (OB2)')):
        for i, ir in enumerate(IRS):
            f, y4, y2 = runs[ir]
            k = 10 ** ((lo0 - y4[0]) / 20) - 1                         # from SPICE's passband, 1 / (1 + k)
            spice = (y4, y2)[col_db - 1]
            s = 1j * f / FC_SPICE
            model = 20 * np.log10(GAIN_SPICE * np.abs(((1 + s) ** 2 if tap == 2 else 1) / ((1 + s) ** 4 + k)))
            c = 'C%d' % i
            ax.semilogx(f, spice, c, lw=2.2, alpha=0.45, label='U28 %s A: k %.2f' % (ir, k))
            ax.semilogx(f, model, c, ls='--', lw=1)
        ax.set_title('the circuit, %s' % name)
        ax.set_xlabel('Hz')
        ax.set_ylim(-80, 25)
        ax.grid(True, which='both', alpha=0.3)
    axes[0].set_ylabel('dB')
    axes[0].legend(loc='lower left', fontsize=8)
    fig.suptitle('Wide: SPICE (tests/spice/ob1_vcf.cir, small signal). Dashed: the model\'s ladder, '
                 '1 / ((1 + s)^4 + k), at the same corner.', fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'ob1-spice.png'), dpi=110)


def spice_thd():
    """-> {k0: [thd%...], k33: [...]} at 1.25, 2.5, 5, 10, 20 V, from ob1_thd.cir's printed fourier output."""
    out = subprocess.run(['ngspice', '-b', 'ob1_thd.cir'], cwd=SPICE, check=True, capture_output=True,
                         text=True).stdout
    thd = [float(x) for x in re.findall(r'THD: ([0-9.eE+-]+) %', out)]
    return {0.0: thd[0::2], 3.33: thd[1::2]}


def thd_plot(so, spice):
    amps = [0.25, 0.5, 1.0, 2.0, 4.0]                                  # x one VCO (1.25 .. 20 V)
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    for k, qi, col in ((0.0, 0, 'C0'), (3.33, 73, 'C3')):
        model = [M.thd(a, k) for a in amps]
        kamps = [a for a in amps if a <= 2.0]                         # two VCOs is a full-scale sample
        fi = 127 * ((990 - 10) / 20990) ** (1 / 3)
        kern = [C.kernel_thd(so, fi, qi, a) for a in kamps]
        ax.loglog(amps, spice[k], col, lw=2.2, alpha=0.45, label='SPICE, k %.2f' % k)
        ax.loglog(amps, model, col, ls='--', lw=1, label='model, k %.2f' % k)
        if k:
            ax.loglog(kamps, kern, 'o', color=col, ms=4, label='kernel, k %.2f' % k)
        else:                   # the kernel leaves out the stages' saturation: under the axis without resonance
            ax.plot([], [], 'o', color=col, ms=4, label='kernel, k 0: < 1e-4 % (no stage saturation)')
    ax.set_xticks(amps)
    ax.set_xticklabels(['0.25', '0.5', '1', '2', '4'])
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_xlabel('input, x one OB-1 VCO at ON (a full-scale Digitakt sample)')
    ax.set_ylabel('THD %')
    ax.set_ylim(1e-4, 10)
    ax.grid(True, which='both', alpha=0.3)
    ax.legend(fontsize=8)
    ax.set_title('Distortion: 200 Hz through OB4, corner ~990 Hz', fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'ob1-thd.png'), dpi=110)


def main():
    os.makedirs(OUT, exist_ok=True)
    so = C.build()
    response_plot(so)
    wrote = ['ob1-response.png']
    if shutil.which('ngspice'):
        with tempfile.TemporaryDirectory() as tmp:
            spice_plot(spice_runs(tmp))
        thd_plot(so, spice_thd())
        wrote += ['ob1-spice.png', 'ob1-thd.png']
    else:
        print('no ngspice on the PATH: ob1-spice.png and ob1-thd.png need it (e.g. brew install ngspice); '
              'left as they are')
    print('wrote', ', '.join(wrote))


if __name__ == '__main__':
    main()
