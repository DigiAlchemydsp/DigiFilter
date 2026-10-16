#!/usr/bin/env python3
"""Run the linked control, dispatcher and filter in patched Unicorn, for OS 1.53 and 1.54.

Uses the same ColdFire build pattern as df_bench.py. Does not boot a firmware or
claim a real-UI/hardware test. Run in digiemu's Python environment with m68k-elf-gcc.
"""
from pathlib import Path
import ctypes
import struct
import subprocess
import tempfile

from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_HOOK_CODE
from unicorn.m68k_const import (UC_CPU_M68K_CFV4E, UC_M68K_REG_A7, UC_M68K_REG_A1,
                               UC_M68K_REG_A3, UC_M68K_REG_D0, UC_M68K_REG_D1,
                               UC_M68K_REG_D3, UC_M68K_REG_PC)

import df_bench as B
import ob1_programmer as P
from ob1_check import build as host_kernel

ROOT = Path(__file__).resolve().parent.parent


def check(version):
    reference = host_kernel()
    with tempfile.TemporaryDirectory() as directory:
        elf = Path(directory) / 'control.elf'
        binary = Path(directory) / 'control.bin'
        flags = ['-DOS154'] if version == '1.54' else []
        sources = [ROOT / name for name in ('filter.c', 'ob1_vcf.c', 'filter_dsp.s',
                                            'filter_glue.s', 'tests/df_bench.c')]
        subprocess.run([B.CROSS + 'gcc'] + B.CFLAGS + flags + ['-I', str(ROOT)] +
                       [str(path) for path in sources] + ['-Wl,-Ttext=0x10000',
                       '-Wl,-e,df_filt_run', '-Wl,--undefined=digifilter_dispatch',
                       '-Wl,--gc-sections', '-o', str(elf)], check=True)
        sym = {parts[2]: int(parts[0], 16) for line in subprocess.check_output(
               [B.CROSS + 'nm', str(elf)], text=True).splitlines()
               if len(parts := line.split()) == 3}
        subprocess.run([B.CROSS + 'objcopy', '-O', 'binary', str(elf), str(binary)], check=True)
        u = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_CPU_M68K_CFV4E)
        for address, size in ((0, 0x600000), (0x80000000, 0x20000),
                              (0x4199d000, 0x5000), (0x421f3000, 0x3000)):
            u.mem_map(address, size)
        u.mem_write(B.BASE, binary.read_bytes())
        params, buffer = sym['df_params'], sym['df_buf']
        env_base = 0x4199ef58 if version == '1.54' else 0x4199df58
        lfo_base = 0x421f4e50 if version == '1.54' else 0x421f3e50
        captured = []
        worst_resonant_error = [0.0]

        def w16(address, value):
            u.mem_write(address, struct.pack('>H', value))

        def w32(address, value):
            u.mem_write(address, struct.pack('>I', value & 0xffffffff))

        def r32(address):
            return struct.unpack('>I', u.mem_read(address, 4))[0]

        def capture(uc, address, size, data):
            sp = uc.reg_read(UC_M68K_REG_A7)
            captured.append(tuple(r32(sp + 4 * i) for i in (1, 2, 3, 5)))

        u.hook_add(UC_HOOK_CODE, capture, begin=sym['ob1_vcf_run'], end=sym['ob1_vcf_run'])

        def call(name, args=()):
            for i, value in enumerate((B.RET,) + tuple(args)):
                w32(B.STACK - 64 + 4 * i, value)
            u.reg_write(UC_M68K_REG_A7, B.STACK - 64)
            u.emu_start(sym[name], B.RET, count=1000000)
            assert u.reg_read(UC_M68K_REG_PC) == B.RET

        def block(type_, word, voice=0, delta1=0, delta2=0, depth=0x4000, env=0,
                  targets=(0x1a, 0x1a), reso=64, amplitude=1 << 20):
            u.mem_write(params, bytes([type_]) + bytes(255))
            w16(params + 2, 0x7f00)         # deliberately different from the raw base
            w16(params + 6, depth)
            engine = 0x80001502 + 106 * voice
            w16(engine + 2 * 0x1a, word)
            w16(engine + 2 * 0x1b, reso << 8)
            w32(env_base + 12 * voice, env)
            for lfo, delta in enumerate((delta1, delta2)):
                w32(lfo_base + 80 * voice - 40 * lfo, targets[lfo])
                w32(lfo_base + 80 * voice - 40 * lfo + 4, delta)
            samples = [amplitude, -amplitude] * 16
            u.mem_write(buffer, struct.pack('>32i', *samples))
            fresh = r32(sym['digifilter_ob_control'] + 12 * voice + 8)
            captured.clear()
            call('digifilter_filt', (params, buffer, 0, voice))
            if type_ in (12, 13):
                assert len(captured) == 1
                tap, fi8, qi, got_voice = captured[0]
                assert (tap, qi, got_voice) == (4 if type_ == 12 else 2, reso, voice)
                output = struct.unpack('>32i', u.mem_read(buffer, 128))
                if fresh:
                    reference.ob1_vcf_reset(voice)
                host = (ctypes.c_int * 32)(*samples)
                reference.ob1_vcf_run(tap, fi8, qi, host, voice)
                error = max(abs(a - b) for a, b in zip(output, host))
                # Use the model checks' 1e-3 relative budget where self-oscillation amplifies rounding.
                peak = max(map(abs, host))
                tolerance = max(256, peak * 1e-3) if qi >= 119 else 256
                assert error <= tolerance, (version, tap, fi8, qi, error, tolerance)
                if qi >= 119:
                    worst_resonant_error[0] = max(worst_resonant_error[0], error / max(peak, 1))
                return fi8
            assert not captured

        def expected(word, delta=0):
            return max(0, min(0x7f00, round(P.knob_cutoff8(word)) + delta))

        for voice in range(8):
            word = voice * 4000
            assert abs(block(12, word, voice) - expected(word)) <= 1
            # The held base survives a tap switch; both LFOs change it immediately.
            assert abs(block(13, 0x7f00, voice, 37, -11) - expected(word, 26)) <= 1
            assert abs(block(12, 0, voice, 0, 0, 0x6000, -(1 << 30)) -
                       expected(word, 8192)) <= 1
            assert block(12, word, voice, -65536) == 0
            assert block(12, word, voice, 65536) == 0x7f00
            assert abs(block(12, word, voice, 5000, 5000, targets=(0x1b, 53)) -
                       expected(word)) <= 1

        # Stock modes bypass the C path: exercise the actual dispatcher and its saved wrapper.
        wrapper = 0x40070000
        for voice in range(8):
            u.mem_write(params, b'\1')
            for register, value in ((UC_M68K_REG_D0, voice << 7), (UC_M68K_REG_D1, 0x12345678),
                                    (UC_M68K_REG_D3, params), (UC_M68K_REG_A1, 0x11223344),
                                    (UC_M68K_REG_A3, wrapper)):
                u.reg_write(register, value)
            call('digifilter_dispatch')
            assert u.reg_read(UC_M68K_REG_D0) == 0x80001a18 + (voice << 7)
            assert u.reg_read(UC_M68K_REG_D1) == 0x12345678
            assert u.reg_read(UC_M68K_REG_D3) == params
            assert u.reg_read(UC_M68K_REG_A1) == 0x11223344
            assert u.reg_read(UC_M68K_REG_A3) == wrapper
            assert r32(sym['digifilter_ob_control'] + 12 * voice + 8) == 1
            assert abs(block(12, 0x7f00, voice) - expected(0x7f00)) <= 1

        block(8, 0)                     # re-entry from another extra filter also resets
        assert abs(block(12, 0) - expected(0)) <= 1
        for elapsed in range(1, 26):
            expected_word = 0 if elapsed < 24 else 0x7f00
            assert abs(block(12, 0x7f00, delta1=elapsed) -
                       expected(expected_word, elapsed)) <= 1, elapsed
        for index in range(300):
            block(12 if index % 2 else 13, (index * 997) % 0x7f01,
                  delta1=(index % 17) * 64, reso=127, amplitude=(1 << 31) - 1)
        print('PASS OS %s: both taps, eight voices, LFOs, envelope, clamps, hold timing, dispatcher and re-entry' % version)
        print('  Full-scale resonant sweep: worst host/ColdFire error %.2e of block peak' %
              worst_resonant_error[0])


if __name__ == '__main__':
    for version in ('1.53', '1.54'):
        check(version)
