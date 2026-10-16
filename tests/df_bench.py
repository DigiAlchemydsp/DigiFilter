#!/usr/bin/env python3
"""Count the digifilter per-voice DSP path's ColdFire instructions per 32-frame block.

Builds the module's DSP sources (filter.c + ob1_vcf.c + filter_dsp.s) with
tests/df_bench.c using the same flags as the SDK, links at 0x10000 and runs
digifilter_filt() in Unicorn, counting executed instructions. Needs a Unicorn
that executes the ColdFire EMAC (mac.l, movclr.l): digiemu's patched build.

Each mode is measured twice: with the FREQ index held (the static-knob path, the
coefficient cache hit) and with FREQ stepped between blocks (the ramp path, one
mode_coef per block). The first call of each pair is a warm-up (mode-change reset
clears the state and the coefficient cache).

    # from a digiemu checkout, with m68k-elf-gcc on PATH:
    python <DigiFilter>/tests/df_bench.py

Reference (SDK flags, MCF54418): BP/BP2 static ~1230, swept ~2420; COMB/TRASH
~1730; OB4/OB2 ~3000; the stock per-voice filter ~2400.
"""
import os
import struct
import subprocess
import sys
import tempfile

from unicorn import UC_ARCH_M68K, UC_HOOK_CODE, UC_MODE_BIG_ENDIAN, Uc
from unicorn.m68k_const import UC_CPU_M68K_CFV4E, UC_M68K_REG_A7

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CROSS = os.environ.get('ELEKLOADER_CROSS', 'm68k-elf-')
BASE, STACK, RET = 0x10000, 0x200000, 0x1f0000
CFLAGS = ['-mcpu=54455', '-O2', '-ffreestanding', '-fno-builtin', '-nostdlib',
          '-fno-pic', '-fno-pie', '-fomit-frame-pointer', '-Wall',
          '-ffunction-sections', '-fdata-sections']


def build():
    d = tempfile.mkdtemp()
    elf = os.path.join(d, 'df.elf')
    subprocess.check_call([CROSS + 'gcc'] + CFLAGS + ['-I', ROOT,
                           os.path.join(ROOT, 'filter.c'), os.path.join(ROOT, 'ob1_vcf.c'),
                           os.path.join(ROOT, 'filter_dsp.s'),
                           os.path.join(ROOT, 'tests', 'df_bench.c'),
                           '-Wl,-Ttext=0x10000', '-Wl,-e,df_filt_run',
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
    uc.mem_map(0x80000000, 0x20000)
    uc.mem_write(BASE, open(bin_, 'rb').read())
    n = [0]
    uc.hook_add(UC_HOOK_CODE, lambda u, a, s, d: n.__setitem__(0, n[0] + 1))

    def block(type_, fi, qi, fb, step=False):
        # params: TYPE @0, FREQ word @2, ENV depth word @6; RESO = engine slot 0x1b
        uc.mem_write(sym['df_params'], bytes([type_]) + b'\x00' * 0xff)
        uc.mem_write(sym['df_params'] + 2, struct.pack('>H', fi << 8))
        uc.mem_write(sym['df_params'] + 6, struct.pack('>H', 0x4000))
        uc.mem_write(0x80001502 + 0x36,
                     struct.pack('>H', (qi << 11) if type_ in (8, 9) else (fb << 8)))
        buf = b''.join(struct.pack('>i', (1 << 20) if (i // 2) % 2 else -(1 << 20)) for i in range(64))
        for warm in range(2):
            if step and warm == 1:
                uc.mem_write(sym['df_params'] + 2, struct.pack('>H', ((fi + 8) & 0x7f) << 8))
            uc.mem_write(sym['df_buf'], buf)
            uc.mem_write(STACK - 4, RET.to_bytes(4, 'big'))
            uc.reg_write(UC_M68K_REG_A7, STACK - 4)
            n[0] = 0
            uc.emu_start(sym['df_filt_run'], RET, count=1000000)
        return n[0]

    print('%-6s %-6s %-6s %-5s %s' % ('TYPE', 'mode', 'FREQ', 'RESO', 'insn / voice / block'))
    for type_, name, fi, qi, fb in ((8, 'BP', 100, 8, 0), (9, 'BP2', 100, 8, 0),
                                    (10, 'COMB', 64, 0, 64), (11, 'TRASH', 64, 0, 64),
                                    (12, 'OB4', 64, 64, 0), (13, 'OB2', 64, 64, 0)):
        static = block(type_, fi, qi, fb)
        swept = block(type_, fi, qi, fb, step=True)
        print('%-6d %-6s %-6d %-5d %d static / %d swept' % (type_, name, fi, qi, static, swept))


if __name__ == '__main__':
    sys.exit(main())
