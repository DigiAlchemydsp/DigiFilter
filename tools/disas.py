#!/usr/bin/env python3
"""Disassemble the stock Digitakt mk1 OS 1.53 main image with real m68k mnemonics.

re_locate.py's own decoder gives op keys only. This wraps the cross binutils
`m68k-elf-objdump` (target `m68k:cfv4e`, the CFV4E core the Digitakt uses) which
decodes ColdFire/EMAC properly, including operands.

    python tools/disas.py <hexaddr> <hexend>      # range
    python tools/disas.py <hexaddr> +<hexcount>   # start + length

Set ELEKTOOL_OD to override the objdump path, STOCK to override the .syx.

The image is extracted once to %TEMP%/digifilter-dt153.bin and cached; firmware
bytes are never written into the repo.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.environ.get("ELEKLOADER", r"C:\Users\benan\Music\ELEKTRON\elekloader"))
from elekloader import formats  # noqa: E402

STOCK = os.environ.get("STOCK", r"C:\Users\benan\Music\ELEKTRON\Digitakt_OS1.53.syx")
OBJDUMP = os.environ.get("ELEKTOOL_OD", r"C:\SysGCC\m68k-elf\bin\m68k-elf-objdump.exe")
MACHINE = "m68k:cfv4e"


def image_path():
    p = os.path.join(tempfile.gettempdir(), "digifilter-dt153.bin")
    if not os.path.exists(p):
        stock, dev, rel = formats.load(STOCK)
        img = formats.main_image(stock, dev)
        with open(p, "wb") as f:
            f.write(img)
    return p


def load_addr():
    stock, dev, rel = formats.load(STOCK)
    return dev.main_load


def disasm(start, end):
    if end is None:
        end = start + 0x100
    base = load_addr()
    cmd = [
        OBJDUMP, "-D", "-b", "binary", "-m", MACHINE,
        "--adjust-vma=0x%x" % base,
        "--start-address=0x%x" % start, "--stop-address=0x%x" % end,
        image_path(),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    lines = []
    for ln in out.splitlines():
        if ":" in ln and ln[:1].strip() and "file format" not in ln and ".data" not in ln:
            # "400757fe:\t4fef ff78      \tlea ..."
            try:
                addr = int(ln.split(":")[0].strip(), 16)
            except ValueError:
                continue
            lines.append((addr, ln.split("\t", 1)[1].strip() if "\t" in ln else ln.split(":", 1)[1].strip()))
    return lines


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    start = int(sys.argv[1], 16)
    end = None
    if len(sys.argv) > 2:
        a = sys.argv[2]
        if a.startswith("+"):
            lines = disasm(start, start + int(a[1:], 16))
            for addr, txt in lines:
                print("0x%08x  %s" % (addr, txt))
            return 0
        end = int(a, 16)
    lines = disasm(start, end)
    for addr, txt in lines:
        print("0x%08x  %s" % (addr, txt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
