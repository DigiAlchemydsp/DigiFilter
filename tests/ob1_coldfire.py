#!/usr/bin/env python3
"""Compare the linked ColdFire kernel with native audio, including both taps and voice state."""
import ctypes
import struct

import numpy as np
from unicorn import UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, Uc
from unicorn.m68k_const import UC_CPU_M68K_CFV4E, UC_M68K_REG_A7

import ob1_bench as B
import ob1_check as C


def main():
    image, sym = B.build()
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_CPU_M68K_CFV4E)
    uc.mem_map(0, 0x400000)
    uc.mem_write(B.BASE, image)
    so = C.build()
    worst = 0

    def call(name, args):
        stack = struct.pack('>%dI' % (len(args) + 1), B.RET,
                            *(x & 0xffffffff for x in args))
        uc.mem_write(B.STACK - len(stack), stack)
        uc.reg_write(UC_M68K_REG_A7, B.STACK - len(stack))
        uc.emu_start(sym[name], B.RET, count=200000)

    for tap in (4, 2):
        for fi, qi in ((0, 0), (32 << 8, 64), (64 << 8, 80),
                       (64 << 8, 81), (127 << 8, 127), (-256, -1), (128 << 8, 128)):
            for voice in (0, 7):
                so.ob1_vcf_reset(voice)
                call('ob1_vcf_reset', [voice])
            for b in range(64):
                voice = 0 if b % 2 == 0 else 7
                x = np.rint(np.sin(2 * np.pi * 220 * (32 * b + np.arange(32)) / 48000)
                            * ((1 << 31) - 1)).astype(np.int32)
                if b >= 32:
                    x[:] = 0
                native = x.copy()
                word = fi + (b % 8) * 16 if 0 < fi < (127 << 8) else fi
                so.ob1_vcf_run(tap, word, qi, native.ctypes.data_as(ctypes.POINTER(ctypes.c_int)), voice)
                uc.mem_write(sym['ob1_io'], struct.pack('>32i', *x))
                call('ob1_vcf_run', [tap, word, qi, sym['ob1_io'], voice])
                linked = np.array(struct.unpack('>32i', uc.mem_read(sym['ob1_io'], 128)), dtype=np.int64)
                error = int(np.max(abs(linked - native.astype(np.int64))))
                worst = max(worst, error)
            print('OB%d FREQ word %d RESO %d: native/ColdFire agree' % (tap, fi, qi))
    # Keep arithmetic differences below a quarter of a 16-bit output step.
    assert worst < (1 << 14), worst
    print('PASS: worst native/ColdFire difference %d Q31 LSB' % worst)


if __name__ == '__main__':
    main()
