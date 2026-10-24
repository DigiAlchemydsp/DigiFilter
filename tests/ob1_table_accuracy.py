#!/usr/bin/env python3
"""Measure the fbsat table's error against the exact polynomial on ColdFire.

Builds ob1_vcf.c twice: once with -DOB1_FBSAT_EXACT (the original five-multiply
saturation) and once with the shipped 512-segment interpolated table. Runs both
over the same control/block sequence and reports the largest output and state
differences. The table deliberately trades exactness for cycles, so this is a
bounded-error test, not an equivalence test.

    python <DigiFilter>/tests/ob1_table_accuracy.py
"""
from pathlib import Path
import random
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STACK, RET = 0x200000, 0x1f0000

SNAPSHOT = '''
int ob1_test_state[74];
int ob1_test_io[32];
int test_fbsat(int y) {
    int r, v;
    __asm__ volatile("move.l %%macsr,%0\\n\\tmove.l #0x30,%%d1\\n\\tmove.l %%d1,%%macsr"
                     : "=d"(r) :: "d1");
    v = fbsat(y);
    __asm__ volatile("move.l %0,%%macsr" :: "d"(r));
    return v;
}
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


def build(folder, name, define=None):
    source = (ROOT / 'shared' / 'ob1_vcf.c').read_text()
    file = folder / (name + '.c')
    file.write_text(source + SNAPSHOT)
    elf = folder / (name + '.elf')
    cmd = ['m68k-elf-gcc', '-mcpu=54455', '-O2', '-ffreestanding',
           '-fno-builtin', '-nostdlib', '-fomit-frame-pointer', '-Wall',
           '-I', str(ROOT), '-I', str(ROOT / 'shared'), str(file), '-Wl,-Ttext=0x10000',
           '-Wl,-e,ob1_vcf_run', '-o', str(elf)]
    if define:
        cmd.insert(2, define)
    subprocess.run(cmd, check=True)
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
        self.uc.mem_map(0, 0x400000)
        self.uc.mem_write(0x10000, image)
        self.symbols = symbols

    def call(self, name, args):
        from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_PC
        stack = struct.pack('>%dI' % (len(args) + 1), RET, *args)
        self.uc.mem_write(STACK - len(stack), stack)
        self.uc.reg_write(UC_M68K_REG_A7, STACK - len(stack))
        self.uc.emu_start(self.symbols[name], RET, count=200000)
        assert self.uc.reg_read(UC_M68K_REG_PC) == RET, 'Instruction limit reached'

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

    def fbsat(self, y):
        self.call('test_fbsat', [y & 0xffffffff])
        from unicorn.m68k_const import UC_M68K_REG_D0
        return self.uc.reg_read(UC_M68K_REG_D0) - (1 << 32) if self.uc.reg_read(UC_M68K_REG_D0) & 0x80000000 else self.uc.reg_read(UC_M68K_REG_D0)


def main():
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        exact = build(folder, 'exact', '-DOB1_FBSAT_EXACT')
        table = build(folder, 'table')
        rng = random.Random(314159)
        inv_kf = 325645
        max_fb = 0
        for z in range(-32768, 32768):
            y = round(z * (1 << 31) / inv_kf)
            max_fb = max(max_fb, abs(exact.fbsat(y) - table.fbsat(y)))
        for _ in range(20000):
            y = rng.randrange(-(1 << 30), 1 << 30)
            max_fb = max(max_fb, abs(exact.fbsat(y) - table.fbsat(y)))
        print(f'fbsat: max error {max_fb} LSB over the z sweep and 20000 random y')
        assert max_fb <= (1 << 13), f'fbsat table error {max_fb} exceeds 8192 LSB'
        max_out = max_state = 0
        blocks = 0
        for fi, qi in ((64, 0), (64, 32), (64, 64), (64, 96), (16, 64),
                       (112, 64), (0, 127), (127, 127)):
            for block in range(40):
                voice = block % 8
                tap = [2, 4, 0x102, 0x104][(blocks // 8) % 4]
                if blocks % 31 == 0:
                    exact.reset(voice)
                    table.reset(voice)
                cutoff = fi + (block % 4)
                pattern = (blocks // 8) % 5
                values = ([0] * 32 if pattern == 0 else
                          [2**31 - 1] + [0] * 31 if pattern == 1 else
                          [rng.randrange(-2**31, 2**31) for _ in range(32)] if pattern == 2 else
                          [(i - 16) * 2**26 for i in range(32)] if pattern == 3 else
                          [(-1 if i % 2 else 1) * (2**30) for i in range(32)])
                a = exact.run(tap, cutoff, qi, values, voice)
                b = table.run(tap, cutoff, qi, values, voice)
                max_out = max(max_out, max(abs(x - y) for x, y in zip(a, b)))
                max_state = max(max_state, max(abs(x - y) for x, y in zip(exact.state(), table.state())))
                blocks += 1
        # Small signals and mid resonance keep the saturation polynomial in its
        # linear-ish region instead of pinned at the knee.
        import math
        for qi in (16, 24, 32, 40, 48, 56, 64):
            for voice in range(8):
                exact.reset(voice)
                table.reset(voice)
            for block in range(40):
                voice = block % 8
                values = [int(math.sin(2 * math.pi * 220 * (block * 32 + i) / 48000) * (1 << 20))
                          for i in range(32)]
                a = exact.run(4, 64 << 8, qi, values, voice)
                b = table.run(4, 64 << 8, qi, values, voice)
                max_out = max(max_out, max(abs(x - y) for x, y in zip(a, b)))
                max_state = max(max_state, max(abs(x - y) for x, y in zip(exact.state(), table.state())))
                blocks += 1
        print(f'{blocks} blocks: max output diff {max_out} LSB, max state diff {max_state} LSB')
        # 2^27 is the internal VCO unit; 1e-4 of that is -80 dBFS, well below
        # the filter's own quantisation. The table's expected bound is ~1400.
        assert max_out <= (1 << 12), f'output difference {max_out} exceeds 4096 LSB'
        assert max_state <= (1 << 16), f'state difference {max_state} exceeds 65536 LSB'
        print('PASS: within the table-error bound')


if __name__ == '__main__':
    main()
