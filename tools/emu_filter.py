#!/usr/bin/env python3
"""Run the stock per-voice multimode filter (0x400757fe) in unicorn, in isolation.

Goal: find its audio buffer, its arguments and how the class byte (a2+0xa0)
selects the processing, so digifilter can insert its SVF at the right place.

    python tools/emu_filter.py [class]

Needs: pip install unicorn, PYTHONPATH to the elekloader checkout.
"""
import os
import struct
import sys

_el = os.environ.get("ELEKLOADER")
if _el:
    sys.path.insert(0, _el)
from elekloader import formats  # noqa: E402

from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_HOOK_CODE, UC_HOOK_MEM_WRITE  # noqa: E402
from unicorn.m68k_const import (  # noqa: E402
    UC_M68K_REG_D0, UC_M68K_REG_D1, UC_M68K_REG_D2, UC_M68K_REG_A2,
    UC_M68K_REG_A6, UC_M68K_REG_A7, UC_M68K_REG_PC, UC_M68K_REG_SR)

STOCK = os.environ.get("STOCK", "")
BASE = 0x40000400
IMGSIZE = 0x400000
FILTER = 0x400757FE
STACK = 0x47BF0000
RET = 0x47BE0000
VOICE = 0x47BE1000
BUF = 0x80001F18
ARGS = [VOICE, 0x4199E466, 0x00010000, 0x00010000, BUF]

MAPS = [
    (0x40000000, IMGSIZE),
    (0x41900000, 0x200000),
    (0x43900000, 0x200000),
    (0x47BE0000, 0x420000),
    (0x80000000, 0x40000),
]

uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
writes, external, path = [], [], []


def load():
    stock, dev, rel = formats.load(STOCK)
    img = formats.main_image(stock, dev)
    for base, size in MAPS:
        uc.mem_map(base, size)
    uc.mem_write(BASE, img)
    uc.mem_write(RET, b"\x4e\x75")               # rts, our return address
    uc.mem_write(RET - 4 if RET - 4 >= 0x47BE0000 else RET, b"")
    uc.mem_write(VOICE, bytes(0x400))
    uc.mem_write(BUF, bytes(0x400))
    for i in range(64):
        uc.mem_write(BUF + 4 * i, struct.pack(">i", (63 - i) << 12))
    for a in (0x80001228, 0x8000122C, 0x80001200, 0x80001204, 0x800011F8):
        uc.mem_write(a, struct.pack(">I", VOICE if a in (0x80001200, 0x80001204) else 0x00010000))


lastpc = []


def hook_code(u, address, size, user):
    lastpc.append(address)
    if len(lastpc) > 20:
        del lastpc[0]
    if not (BASE <= address < BASE + IMGSIZE):
        external.append(address)
        if len(external) > 2000:
            u.emu_stop()


def hook_mem(u, access, address, size, value, user):
    if not (BASE <= address < BASE + IMGSIZE) and len(writes) < 4000:
        writes.append((address, size, value))


def run(cls):
    load()
    uc.mem_write(VOICE + 0xA0, bytes([cls]))
    uc.mem_write(VOICE + 0x2A, bytes([1]))
    sp = STACK
    for a in reversed(ARGS):
        sp -= 4
        uc.mem_write(sp, struct.pack(">I", a))
    sp -= 4
    uc.mem_write(sp, struct.pack(">I", RET))
    uc.reg_write(UC_M68K_REG_SR, 0x2000)      # supervisor (do SR before A7: it resets A7)
    uc.reg_write(UC_M68K_REG_A7, sp)
    print("sp readback 0x%08x" % uc.reg_read(UC_M68K_REG_A7))
    uc.hook_add(UC_HOOK_CODE, hook_code)
    uc.hook_add(UC_HOOK_MEM_WRITE, hook_mem)
    print("class=%d  call 0x%08x args=%s" % (cls, FILTER, [hex(x) for x in ARGS]))
    try:
        uc.emu_start(FILTER, RET, count=500000)
        print("returned; a2=0x%08x d0=0x%08x" % (uc.reg_read(UC_M68K_REG_A2), uc.reg_read(UC_M68K_REG_D0)))
    except Exception as e:
        pc = None
        try:
            pc = uc.reg_read(UC_M68K_REG_PC)
        except Exception:
            pass
        print("STOPPED: %s at pc=0x%08x sp=0x%08x a6=0x%08x" %
              (e, pc or 0, uc.reg_read(UC_M68K_REG_A7), uc.reg_read(UC_M68K_REG_A6)))
        print("last PCs: %s" % " ".join("0x%08x" % a for a in lastpc))
    print("PC-outside-image hits: %d" % len(external))
    for a in external[:20]:
        print("   0x%08x" % a)
    only = [w for w in writes if not (BUF <= w[0] < BUF + 0x400)]
    print("writes outside image: %d (%d outside the buffer)" % (len(writes), len(only)))
    for a, s, v in only[:40]:
        print("   *0x%08x (%d) = 0x%x" % (a, s, v))
    print("buffer now: %s" % uc.mem_read(BUF, 32).hex())


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
