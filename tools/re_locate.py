#!/usr/bin/env python3
"""Phase 0 RE helper for digifilter.

    python tools/re_locate.py <cmd> [args]

Commands:
    info                     image length, sha256, load address
    scan  <hex32> [hex32..]  find big-endian 32-bit constants in the image
    scan16 <hex16> ...       find big-endian 16-bit constants
    str   <text> [text..]    find ASCII strings (printable, >= 4)
    dis   <hexaddr> [n]      disassemble n instructions from addr
    disr  <hexaddr> <hexend> disassemble the range

The image is the stock Digitakt mk1 1.53 main OS, loaded at 0x40000400.
Needs PYTHONPATH=<elekloader checkout>.
"""
import os
import struct
import sys

_el = os.environ.get("ELEKLOADER")
if _el:
    sys.path.insert(0, _el)
from elekloader import formats  # noqa: E402
from elekloader.isa import coldfire  # noqa: E402

STOCK = os.environ.get("STOCK", "")
_cache = {}


def image():
    if "img" not in _cache:
        stock, dev, rel = formats.load(STOCK)
        img = formats.main_image(stock, dev)
        _cache["img"] = img
        _cache["load"] = dev.main_load
        _cache["dev"] = dev
    return _cache["img"]


def load():
    image()
    return _cache["load"]


def a(off):
    return load() + off


def off(addr):
    return addr - load()


def scan32(*vals):
    img = image()
    for v in vals:
        v = int(v, 16) if isinstance(v, str) else v
        pat = struct.pack(">I", v & 0xFFFFFFFF)
        hits, i = [], img.find(pat)
        while i >= 0:
            hits.append(i)
            i = img.find(pat, i + 1)
        print("0x%08x -> %d hit(s): %s" % (v, len(hits), " ".join("0x%08x" % a(h) for h in hits)))


def scan16(*vals):
    img = image()
    for v in vals:
        v = int(v, 16) if isinstance(v, str) else v
        pat = struct.pack(">H", v & 0xFFFF)
        hits, i = [], img.find(pat)
        while i >= 0:
            hits.append(i)
            i = img.find(pat, i + 1)
        print("0x%04x -> %d hit(s): %s" % (v, len(hits), " ".join("0x%08x" % a(h) for h in hits[:40])))


def strings(*needles):
    img = image()
    for n in needles:
        b = n.encode("ascii")
        hits, i = [], img.find(b)
        while i >= 0:
            hits.append(i)
            i = img.find(b, i + 1)
        print("%-10r -> %d hit(s): %s" % (n, len(hits), " ".join("0x%08x" % a(h) for h in hits[:40])))


def _dis(start, end):
    img = image()
    read = coldfire.reader(img, load())
    pc = start
    while pc < end:
        ins = coldfire.decode(read(pc), pc)
        w = img[off(pc):off(pc) + ins.length]
        extra = ""
        if ins.target is not None:
            extra = " -> 0x%08x" % ins.target
        print("0x%08x  %-24s %-6s len=%d%s" % (pc, w.hex(), ins.op, ins.length, extra))
        pc += ins.length


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "info":
        img = image()
        import hashlib
        print("load 0x%08x  len %d  sha256 %s" % (load(), len(img), hashlib.sha256(img).hexdigest()))
    elif cmd == "scan":
        scan32(*rest)
    elif cmd == "scan16":
        scan16(*rest)
    elif cmd == "str":
        strings(*rest)
    elif cmd == "dis":
        start = int(rest[0], 16)
        n = int(rest[1]) if len(rest) > 1 else 1
        pc = start
        for _ in range(n):
            _dis(pc, pc + 64)
            break
        # print just n instructions
        read = coldfire.reader(image(), load())
        pc = start
        for _ in range(n):
            ins = coldfire.decode(read(pc), pc)
            raw = image()[off(pc):off(pc) + ins.length].hex()
            extra = " -> 0x%08x" % ins.target if ins.target is not None else ""
            print("0x%08x  %-24s %-22s len=%d%s" % (pc, raw, ins.op, ins.length, extra))
            pc += ins.length
    elif cmd == "disr":
        _dis(int(rest[0], 16), int(rest[1], 16))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
