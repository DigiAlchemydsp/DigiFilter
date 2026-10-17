#!/usr/bin/env python3
"""Compare output and sound-affecting state with a Git baseline, natively or on ColdFire.

Run with mise-managed Python; --coldfire requires digiemu's patched Unicorn.
The baseline is compiled independently, including its own state and random seed.
"""
import argparse
import ctypes
from pathlib import Path
import random
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASELINE = 'ec79957fee71e9cc2d11f980b515fb57044897eb'
# Cache keys are implementation metadata; compare every pre-existing DSP state field.
SNAPSHOT = '''
int ob1_test_state[74];
int ob1_test_io[32];
void ob1_test_snapshot(void) {
    int v, j, *p = ob1_test_state;
    for (v = 0; v < 8; v++) {
        for (j = 0; j < 4; j++) *p++ = st[v].s[j];
        *p++ = st[v].c.G; *p++ = st[v].c.k8;
        *p++ = st[v].c.r; *p++ = st[v].c.g4r;
        *p++ = st[v].fresh;
    }
    *p++ = seed; *p = (int)lcg;
}
'''


def build(folder, name, source, coldfire):
    file = folder / (name + '.c')
    file.write_text(source + SNAPSHOT)
    if coldfire:
        elf = folder / (name + '.elf')
        subprocess.run(['m68k-elf-gcc', '-mcpu=54455', '-O2', '-ffreestanding',
                        '-fno-builtin', '-nostdlib', '-fomit-frame-pointer', '-Wall',
                        '-I', str(ROOT), str(file), '-Wl,-Ttext=0x10000',
                        '-Wl,-e,ob1_vcf_run', '-o', str(elf)], check=True)
        binary = folder / (name + '.bin')
        subprocess.run(['m68k-elf-objcopy', '-O', 'binary', str(elf), str(binary)], check=True)
        symbols = {line.split()[2]: int(line.split()[0], 16) for line in
                   subprocess.check_output(['m68k-elf-nm', str(elf)], text=True).splitlines()
                   if len(line.split()) == 3}
        return ColdFire(binary.read_bytes(), symbols)
    lib = folder / (name + '.so')
    subprocess.run(['cc', '-O2', '-shared', '-fPIC', '-Wall', '-Wextra', '-I', str(ROOT),
                    str(file), '-o', str(lib)], check=True)
    return Native(lib)


class Native:
    def __init__(self, path):
        self.lib = ctypes.CDLL(str(path))
        self.lib.ob1_vcf_run.argtypes = [ctypes.c_int] * 3 + [ctypes.POINTER(ctypes.c_int), ctypes.c_int]

    def reset(self, voice):
        self.lib.ob1_vcf_reset(voice)

    def run(self, tap, fi8, qi, values, voice):
        buf = (ctypes.c_int * 32)(*values)
        self.lib.ob1_vcf_run(tap, fi8, qi, buf, voice)
        return list(buf)

    def state(self):
        self.lib.ob1_test_snapshot()
        return list((ctypes.c_int * 74).in_dll(self.lib, 'ob1_test_state'))


class ColdFire:
    def __init__(self, image, symbols):
        from unicorn import UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, Uc
        from unicorn.m68k_const import UC_CPU_M68K_CFV4E
        self.uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_CPU_M68K_CFV4E)
        self.uc.mem_map(0, 0x400000)
        self.uc.mem_write(0x10000, image)
        self.symbols = symbols

    def call(self, name, args):
        from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_PC
        stack = struct.pack('>%dI' % (len(args) + 1), 0x1f0000,
                            *(v & 0xffffffff for v in args))
        self.uc.mem_write(0x200000 - len(stack), stack)
        self.uc.reg_write(UC_M68K_REG_A7, 0x200000 - len(stack))
        self.uc.emu_start(self.symbols[name], 0x1f0000, count=200000)
        assert self.uc.reg_read(UC_M68K_REG_PC) == 0x1f0000, 'Instruction limit reached'

    def reset(self, voice):
        self.call('ob1_vcf_reset', [voice])

    def run(self, tap, fi8, qi, values, voice):
        address = self.symbols['ob1_test_io']
        self.uc.mem_write(address, struct.pack('>32i', *values))
        self.call('ob1_vcf_run', [tap, fi8, qi, address, voice])
        return list(struct.unpack('>32i', self.uc.mem_read(address, 128)))

    def state(self):
        self.call('ob1_test_snapshot', [])
        return list(struct.unpack('>74i', self.uc.mem_read(self.symbols['ob1_test_state'], 296)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--coldfire', action='store_true')
    args = parser.parse_args()
    # The feedback weights factor exactly after, not before, the existing Q15 truncation.
    for z2 in range(32768):
        z4 = (z2 * z2) >> 15
        original_weight = z2 * 21845 - z4 * 8738
        factored_weight = (5 * z2 - 2 * z4) * 4369
        assert original_weight == factored_weight and 0 <= factored_weight < 2**31
    original = subprocess.check_output(['git', 'show', args.baseline + ':ob1_vcf.c'], cwd=ROOT, text=True)
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        old = build(folder, 'baseline', original, args.coldfire)
        new = build(folder, 'candidate', (ROOT / 'ob1_vcf.c').read_text(), args.coldfire)
        rng = random.Random(314159)
        controls = [(fi, qi) for fi in [-256, 0, 1, 255, 256, 8193, 16384, 32511, 32512, 32768]
                    for qi in [-1, 0, 64, 79, 80, 81, 127, 128]]
        blocks = 0
        for fi, qi in controls:
            for block in range(32):
                voice = block % 8
                tap = [2, 4, 0x102, 0x104][(blocks // 8) % 4]
                if blocks % 31 == 0:
                    old.reset(voice)
                    new.reset(voice)
                # Include unchanged keys, one-LSB fractional changes, clamps, and returns to prior keys.
                cutoff = fi + (1 if block >= 24 else 0)
                pattern = (blocks // 8) % 7
                values = ([0] * 32 if pattern == 0 else
                          [2**31 - 1] + [0] * 31 if pattern == 1 else
                          [rng.randrange(-2**31, 2**31) for _ in range(32)] if pattern == 2 else
                          [2**31 - 1] * 32 if pattern == 3 else
                          [-2**31] * 32 if pattern == 4 else
                          [(-1 if i % 2 else 1) * (2**31 - 1) for i in range(32)] if pattern == 5 else
                          [(i - 16) * 2**26 for i in range(32)])
                before = old.run(tap, cutoff, qi, values, voice)
                after = new.run(tap, cutoff, qi, values, voice)
                assert before == after, ('Output differs', blocks, tap, cutoff, qi, voice)
                assert old.state() == new.state(), ('DSP state differs', blocks, tap, cutoff, qi, voice)
                blocks += 1
        # A zero destination is not enough: preserve the first nonzero-to-zero ramp,
        # then compare the fast path with live residual states and changing cutoff.
        for voice in range(8):
            old.reset(voice)
            new.reset(voice)
            history = [127] * 64 + [0] * 64 + [1] * 8 + [0] * 8 + [81] * 64 + [0] * 64
            for block, qi in enumerate(history):
                tap = 2 if (block // 16) % 2 else 4
                cutoff = (32 << 8) + block % 256
                values = [2**31 - 1] + [0] * 31 if block == 0 else [0] * 32
                assert old.run(tap, cutoff, qi, values, voice) == new.run(tap, cutoff, qi, values, voice), (
                    'Zero-feedback transition output', voice, block, qi)
                assert old.state() == new.state(), ('Zero-feedback transition state', voice, block, qi)
                blocks += 1
        print(f'PASS: {blocks} blocks, {blocks * 32} samples, exact output and all original DSP state; '
              f'{"ColdFire" if args.coldfire else "native"} versus {args.baseline}')


if __name__ == '__main__':
    main()
