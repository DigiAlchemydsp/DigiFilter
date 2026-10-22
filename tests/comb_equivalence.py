#!/usr/bin/env python3
"""Compare the COMB/TRASH path and its delay-line state with a Git baseline.

Runs the whole digifilter_filt() dispatch on ColdFire in Unicorn (the code reads
firmware addresses, so there is no native build). The baseline is compiled
independently from the given commit. Checks output samples and every state field
the comb touches, over cutoff/feedback/harmonics/damping steps and mode changes.

    python <DigiFilter>/tests/comb_equivalence.py
"""
import argparse
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '00b2d0f'
ARGS = 0x80001502
ENV = 0x4199df58
STACK, RET = 0x200000, 0x1f0000

SNAPSHOT = '''
int test_state[2304];
int test_params[256];
int test_buf[64];
__attribute__((used)) void test_snapshot(void) {
    int v, i, *p = test_state;
    for (v = 0; v < 8; v++) {
        for (i = 0; i < COMB_N; i++) *p++ = comb_buf[v][i];
        *p++ = comb_pos[v]; *p++ = comb_init[v]; *p++ = comb_dly[v];
        *p++ = comb_g[v]; *p++ = comb_lp[v]; *p++ = prev_filt_type[v];
        *p++ = svf_have[v]; *p++ = svf_fi[v]; *p++ = svf_qi[v];
        *p++ = dsp_st[v][0]; *p++ = dsp_st[v][1];
    }
}
int test_run(int voice) {
    return digifilter_filt((unsigned char *)test_params, test_buf, 1, voice);
}
'''


def build(folder, name, source, dsp, ob1):
    c = folder / (name + '.c')
    c.write_text(source + SNAPSHOT)
    asm = folder / (name + '.s')
    asm.write_text(dsp)
    ob = folder / (name + '_ob1.c')
    ob.write_text(ob1)
    elf = folder / (name + '.elf')
    subprocess.run(['m68k-elf-gcc', '-mcpu=54455', '-O2', '-ffreestanding',
                    '-fno-builtin', '-nostdlib', '-fomit-frame-pointer', '-Wall',
                    '-ffunction-sections', '-fdata-sections',
                    '-I', str(ROOT), str(c), str(ob), str(asm),
                    '-Wl,-Ttext=0x10000', '-Wl,-e,test_run', '-Wl,--gc-sections',
                    '-Wl,-u,test_snapshot', '-o', str(elf)],
                   check=True)
    binary = folder / (name + '.bin')
    subprocess.run(['m68k-elf-objcopy', '-O', 'binary', str(elf), str(binary)], check=True)
    symbols = {line.split()[2]: int(line.split()[0], 16) for line in
               subprocess.check_output(['m68k-elf-nm', str(elf)], text=True).splitlines()
               if len(line.split()) == 3}
    return ColdFire(binary.read_bytes(), symbols)


class ColdFire:
    def __init__(self, image, symbols):
        from unicorn import UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, Uc
        from unicorn.m68k_const import UC_CPU_M68K_CFV4E
        self.uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_CPU_M68K_CFV4E)
        self.uc.mem_map(0, 0x600000)
        self.uc.mem_map(0x40000000, 0x2000000)     # ENV_LEVEL (firmware state)
        self.uc.mem_map(0x80000000, 0x20000)       # engine slots
        self.uc.mem_write(0x10000, image)
        self.symbols = symbols

    def call(self, name, args):
        from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_PC
        stack = struct.pack('>%dI' % (len(args) + 1), RET, *args)
        self.uc.mem_write(STACK - len(stack), stack)
        self.uc.reg_write(UC_M68K_REG_A7, STACK - len(stack))
        self.uc.emu_start(self.symbols[name], RET, count=2000000)
        assert self.uc.reg_read(UC_M68K_REG_PC) == RET, 'Instruction limit reached'

    def block(self, type_, fi, fb, harm, damp, env, voice):
        params = bytearray(256)
        params[0] = type_
        params[2:4] = struct.pack('>H', fi << 8)
        params[6:8] = struct.pack('>H', 0x4000)
        params[0x2c:0x2e] = struct.pack('>H', harm << 8)
        params[0x2e:0x30] = struct.pack('>H', damp)
        self.uc.mem_write(self.symbols['test_params'], bytes(params))
        self.uc.mem_write(ARGS + 0x36 + 106 * voice, struct.pack('>H', fb << 8))
        self.uc.mem_write(ENV + 12 * voice, struct.pack('>i', env))
        self.uc.mem_write(self.symbols['test_buf'], b'\0' * 128)
        self.call('test_run', [voice])
        return list(struct.unpack('>32i', self.uc.mem_read(self.symbols['test_buf'], 128)))

    def state(self):
        self.call('test_snapshot', [])
        return list(struct.unpack('>2304i', self.uc.mem_read(self.symbols['test_state'], 2304 * 4)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    args = parser.parse_args()
    old_src = subprocess.check_output(['git', 'show', args.baseline + ':filter.c'], cwd=ROOT, text=True)
    old_dsp = subprocess.check_output(['git', 'show', args.baseline + ':filter_dsp.s'], cwd=ROOT, text=True)
    old_ob1 = subprocess.check_output(['git', 'show', args.baseline + ':ob1_vcf.c'], cwd=ROOT, text=True)
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        old = build(folder, 'baseline', old_src, old_dsp, old_ob1)
        new = build(folder, 'candidate', (ROOT / 'filter.c').read_text(),
                    (ROOT / 'filter_dsp.s').read_text(), (ROOT / 'ob1_vcf.c').read_text())
        blocks = 0
        for voice in range(8):
            type_ = 10
            for n in range(96):
                if n % 17 == 16:
                    type_ = 11 if type_ == 10 else 10
                fi = (0, 1, 63, 64, 65, 126, 127)[(n // 3) % 7]
                fb = (0, 1, 31, 64, 96, 126, 127)[(n // 5) % 7]
                harm = (0, 1, 63, 127)[(n // 7) % 4]
                damp = (0, 1, 16384, 32768, 65535)[(n // 11) % 5]
                env = (0, 1 << 14, -(1 << 20), (n - 40) << 12)[(n // 13) % 4]
                a = old.block(type_, fi, fb, harm, damp, env, voice)
                b = new.block(type_, fi, fb, harm, damp, env, voice)
                assert a == b, ('Output differs', voice, n, type_, fi, fb, harm, damp, env)
                assert old.state() == new.state(), ('State differs', voice, n, type_, fi, fb, harm, damp, env)
                blocks += 1
        print(f'PASS: {blocks} blocks, exact output and all comb/SVF state; '
              f'ColdFire versus {args.baseline}')


if __name__ == '__main__':
    main()
