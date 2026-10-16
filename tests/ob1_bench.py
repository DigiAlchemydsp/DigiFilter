#!/usr/bin/env python3
"""Count the OB-1 kernel's ColdFire instructions per 32-sample block in Unicorn.

Builds ob1_vcf.c + tests/ob1_bench.c with m68k-elf-gcc as the SDK does (-mcpu=54455 -O2, no libgcc),
linked at 0x10000, and runs ob1_bench() block by block with a sine at 1/32 of full scale. It needs a Unicorn
that executes the ColdFire's EMAC (mac.l, movclr.l): digiemu's patched build. From a digiemu checkout:

    uv run --with numpy python <DigiFilter>/tests/ob1_bench.py
"""
import os
import subprocess
import sys
import tempfile

import numpy as np
from unicorn import UC_ARCH_M68K, UC_HOOK_CODE, UC_MODE_BIG_ENDIAN, Uc
from unicorn.m68k_const import UC_CPU_M68K_CFV4E, UC_M68K_REG_A7

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE, STACK, RET = 0x10000, 0x200000, 0x1f0000
CROSS = os.environ.get('ELEKLOADER_CROSS', 'm68k-elf-')


def build():
    d = tempfile.mkdtemp()
    elf, bin_ = os.path.join(d, 'ob1.elf'), os.path.join(d, 'ob1.bin')
    subprocess.check_call([CROSS + 'gcc', '-mcpu=54455', '-O2', '-ffreestanding', '-fno-builtin', '-nostdlib',
                           '-fomit-frame-pointer', '-Wall', '-I', ROOT, os.path.join(ROOT, 'ob1_vcf.c'),
                           os.path.join(ROOT, 'tests', 'ob1_bench.c'), '-Wl,-Ttext=0x10000',
                           '-Wl,-e,ob1_bench', '-o', elf])
    subprocess.check_call([CROSS + 'objcopy', '-O', 'binary', elf, bin_])
    syms = {l.split()[2]: int(l.split()[0], 16) for l in subprocess.check_output(
        [CROSS + 'nm', elf], text=True).splitlines() if len(l.split()) == 3}
    return open(bin_, 'rb').read(), syms


def main():
    image, sym = build()
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_CPU_M68K_CFV4E)
    uc.mem_map(0, 0x400000)
    uc.mem_write(BASE, image)
    n = [0]
    uc.hook_add(UC_HOOK_CODE, lambda u, a, s, d: n.__setitem__(0, n[0] + 1))
    t = 0
    print('%-6s %-6s %-4s %s' % ('FREQ', 'RESO', 'tap', 'instructions a block (median of 16)'))
    for tap, name in ((4, 'OB4'), (2, 'OB2')):
        for fi, qi in ((64, 0), (64, 120), (16, 64), (112, 64)):
            costs = []
            for b in range(20):
                x = (np.sin(2 * np.pi * 220 * (t + np.arange(32)) / 48000) * (1 << 26)).astype(np.int64)
                t += 32
                uc.mem_write(sym['ob1_io'], b''.join(int(v & 0xffffffff).to_bytes(4, 'big') for v in x))
                uc.mem_write(STACK - 16, b''.join(v.to_bytes(4, 'big') for v in (RET, tap, fi << 8, qi)))
                uc.reg_write(UC_M68K_REG_A7, STACK - 16)
                n[0] = 0
                uc.emu_start(sym['ob1_bench'], RET, count=200000)
                if b >= 4:
                    costs.append(n[0])
            print('%-6d %-6d %-4s %d' % (fi, qi, name, int(np.median(costs))))


if __name__ == '__main__':
    sys.exit(main())
