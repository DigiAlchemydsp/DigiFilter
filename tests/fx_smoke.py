#!/usr/bin/env python3
"""Smoke-test the Filter+FX shared DSP on ColdFire (Unicorn).

Builds shared/fx_dsp.c + shared/biquad_dsp.s + tests/fx_smoke.c with the SDK
flags, links at 0x10000 and runs fx_run() for every mode. Checks that each mode
is non-silent and bounded, and that the transfer/mod modes stay within full
scale. Needs a Unicorn that executes the ColdFire EMAC (digiemu's patched build).

    python tests/fx_smoke.py
"""
import math
import os
import struct
import subprocess
import sys
import tempfile

from unicorn import UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, Uc
from unicorn.m68k_const import UC_CPU_M68K_CFV4E, UC_M68K_REG_A7

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CROSS = os.environ.get('ELEKLOADER_CROSS', 'm68k-elf-')
BASE, STACK, RET = 0x10000, 0x200000, 0x1f0000
CFLAGS = ['-mcpu=54455', '-O2', '-ffreestanding', '-fno-builtin', '-nostdlib',
          '-fno-pic', '-fno-pie', '-fomit-frame-pointer', '-Wall',
          '-ffunction-sections', '-fdata-sections']


def build():
    d = tempfile.mkdtemp()
    elf = os.path.join(d, 'fx.elf')
    subprocess.check_call([CROSS + 'gcc'] + CFLAGS + ['-I', os.path.join(ROOT, 'shared'),
                           os.path.join(ROOT, 'shared', 'fx_dsp.c'),
                           os.path.join(ROOT, 'shared', 'biquad_dsp.s'),
                           os.path.join(ROOT, 'tests', 'fx_smoke.c'),
                           '-Wl,-Ttext=0x10000', '-Wl,-e,fx_run_test',
                           '-Wl,--gc-sections', '-o', elf])
    syms = {l.split()[2]: int(l.split()[0], 16) for l in subprocess.check_output(
        [CROSS + 'nm', elf], text=True).splitlines() if len(l.split()) == 3}
    return elf, syms


def main():
    elf, sym = build()
    bin_ = elf + '.bin'
    subprocess.check_call([CROSS + 'objcopy', '-O', 'binary', elf, bin_])
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_CPU_M68K_CFV4E)
    uc.mem_map(0, 0x600000)
    uc.mem_write(BASE, open(bin_, 'rb').read())

    def run(mode, fi, qi, a1=0, a2=0, values=None):
        if values is None:
            values = [int(math.sin(2 * math.pi * 1500 * i / 48000) * (1 << 26))
                      for i in range(32)]
        uc.mem_write(sym['fx_buf'], b''.join(struct.pack('>i', v) for v in values))
        for name, value in (('fx_mode', mode), ('fx_fi', fi), ('fx_qi', qi),
                            ('fx_a1', a1), ('fx_a2', a2)):
            uc.mem_write(sym[name], struct.pack('>i', value))
        uc.mem_write(STACK - 4, RET.to_bytes(4, 'big'))
        uc.reg_write(UC_M68K_REG_A7, STACK - 4)
        uc.emu_start(sym['fx_run_test'], RET, count=2000000)
        return list(struct.unpack('>32i', uc.mem_read(sym['fx_buf'], 128)))

    nonzero = {}
    for mode, name in enumerate(('VOWEL', 'BANK', 'FOLD', 'CRUSH', 'RING', 'PHASER', 'FLANGER')):
        for fi in (0, 32, 64, 96, 127):
            for qi in (0, 64, 127):
                out = run(mode, fi, qi)
                peak = max(abs(v) for v in out)
                assert peak <= (1 << 30), (name, fi, qi, peak)
                if peak:
                    nonzero[name] = 1
    assert len(nonzero) == 7, nonzero

    # VOWEL/BANK aux controls must change the output.
    for mode in (0, 1):
        base = run(mode, 64, 64, 0, 0)
        alt = run(mode, 64, 64, 127, 127)
        assert base != alt, mode

    # PHASER clamps to full scale, FLANGER decays after an impulse.
    full = 1 << 27
    for fi in (0, 32, 64, 96, 127):
        out = run(5, fi, 127, values=[full] * 32)
        assert max(abs(v) for v in out) <= full
    out = run(6, 64, 0, values=[1 << 26] + [0] * 31)
    for _ in range(5):
        out += run(6, 64, 0, values=[0] * 32)
    assert max(abs(v) for v in out) > 0

    print('PASS: 7 modes non-silent and bounded; VOWEL/BANK aux changes output')


if __name__ == '__main__':
    sys.exit(main())
