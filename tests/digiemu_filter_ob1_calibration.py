#!/usr/bin/env python3
"""Check calibrated OB modes through the firmware dispatch and an eight-voice timed fixture."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import struct
import sys

import numpy as np

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--digiemu', required=True)
ap.add_argument('--fw', required=True, help='fresh firmware-check build folder')
ap.add_argument('--os', required=True, choices=('1.53', '1.54'))
a = ap.parse_args()
fw = Path(a.fw).resolve()
sys.path.insert(0, str(Path(a.digiemu).resolve()))
syx = next(fw.glob('*.syx'))
os.environ.update(DT2_SYX=str(syx), DT2_SECTIONS=str(fw / 'sections'),
                  DT2_SNAPSHOTS=str(fw / 'snapshots'), DT2_PLUSDRIVE=str(fw / 'plusdrive.img'),
                  DT2_MAIN_IMG=str(fw / 'sections/section_3_MAIN_OS.bin'),
                  DT2_DEVICES=str(fw / 'devices'))
from emu.session import Session
from emu import cftiming, ssi
from unicorn import UC_HOOK_CODE
from unicorn.m68k_const import UC_M68K_REG_D0, UC_M68K_REG_D3
import ob1_check as C

cases = [(tap, fi << 8, 64, 0x4000) for tap in (4, 2) for fi in (16, 64, 112)]
cases += [(tap, (64 << 8) + 128, 64, 0x6000) for tap in (4, 2)]
BLOCKS = 96
counts = [0] * 8
errors = [0] * len(cases)
stress_counts = [0] * 8
stress_peak = 0
pending = None
so = C.build()


def install(session):
    def before(uc, address, size, user):
        global pending
        voice = uc.reg_read(UC_M68K_REG_D0) >> 7
        assert 0 <= voice < 8
        params = uc.reg_read(UC_M68K_REG_D3)
        buf = 0x80001a18 + voice * 128
        case = counts[voice] // BLOCKS
        if case < len(cases):
            tap, fi, qi, envw = cases[case]
            x = np.rint(np.sin(2 * np.pi * np.arange(32) / 32) * (1 << 23)).astype(np.int32)
        else:
            tap, fi, qi, envw = 4, ((stress_counts[voice] % 128) << 8), 127, 0x4000
            n = stress_counts[voice] * 32 + np.arange(32)
            x = np.rint(np.sin(2 * np.pi * 110 * n / 48000) * ((1 << 31) - 1)).astype(np.int32)
            stress_counts[voice] += 1
        uc.mem_write(params, bytes([12 if tap == 4 else 13]))
        uc.mem_write(params + 2, struct.pack('>H', fi))
        uc.mem_write(params + 6, struct.pack('>H', envw))
        uc.mem_write(0x80001502 + 106 * voice + 2 * 0x1b, struct.pack('>H', qi << 8))
        env = -1 << 30
        env_addr = 0x4199df58 + (0x1000 if a.os == '1.54' else 0)
        uc.mem_write(env_addr + 12 * voice, struct.pack('>i', env))
        uc.mem_write(buf, struct.pack('>32i', *x))
        expected = None
        if case < len(cases):
            depth = (envw - 0x4000) << 17
            effective = max(0, min(127 << 8, fi + (((-env) * depth) >> 31 >> 16)))
            expected = x.copy()
            so.ob1_vcf_run(tap, effective, qi,
                           expected.ctypes.data_as(ctypes.POINTER(ctypes.c_int)), voice)
        pending = (voice, buf, case, expected)
        counts[voice] += 1

    def after(uc, address, size, user):
        global pending, stress_peak
        if pending is None:
            return
        voice, buf, case, expected = pending
        y = np.array(struct.unpack('>32i', uc.mem_read(buf, 128)), dtype=np.int64)
        if expected is not None:
            error = int(max(abs(y - expected.astype(np.int64))))
            errors[case] = max(errors[case], error)
            assert error < (1 << 14), (voice, case, error)
        else:
            stress_peak = max(stress_peak, int(max(abs(y))))
        pending = None

    session.m.uc.hook_add(UC_HOOK_CODE, before, begin=0x400780ba, end=0x400780ba)
    session.m.uc.hook_add(UC_HOOK_CODE, after, begin=0x400780c6, end=0x400780c6)
    session.m.uc.ctl_flush_tb()


snapshot = next((fw / 'snapshots').rglob('gui.snap'))
s = Session(str(snapshot), str(syx), hle=False, timing={'accel': 'max'},
            strict={'stop': False}, ddr=128 * 1024 * 1024, on_machine=install)
try:
    for _ in range(100):
        s.run_ms(10)
        if min(stress_counts) >= 150 or s.halted:
            break
    assert not s.halted, s.halted
    assert min(stress_counts) >= 150, stress_counts
    strict = s.strict_report()
    assert not strict['violations'], strict['violations']
    profile = ssi.PROFILES[s.device.audio['ssi_profile']]
    period = cftiming.measured_period(s.clock, profile.tx_vector)
    assert period
    deadlines = {str(v): cftiming.deadline_report(s.clock, v, period)
                 for v in (profile.tx_vector, ssi.FORCE_VECTOR)}
    assert all(d.get('runs', 0) and d['late'] == 0 and d['margin'] > .1
               for d in deadlines.values()), deadlines
    assert stress_peak < (1 << 31) - 1, stress_peak
    print(json.dumps(dict(passed=True,blocks_per_voice=counts,stress_blocks_per_voice=stress_counts,
                          worst_native_error_lsb=max(errors),case_errors_lsb=errors,
                          stress_peak=stress_peak,render_deadlines=deadlines,
                          emulated_ms=s.ms), indent=2))
finally:
    s.close()
