#!/usr/bin/env python3
"""Audio test: sweep the cutoff on COMB / TRASH and look for zipper/clicks.

Forces the mode, injects a continuous one-cycle-per-block 1500 Hz tone into the
voice buffer at the per-voice filter call (0x400780c4), sweeps params@2 (cutoff
index) one step per block, and stitches the output into one stream. A smooth
filter gives a continuous waveform; a delay/coefficient step shows as a large
sample-to-sample jump.

    python tests/digiemu_filter_mod.py --digiemu <checkout> --fw <folder> --type 10
"""
import argparse
import math
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--type", type=int, default=10)
ap.add_argument("--hold", type=int, default=-1, help="hold this cutoff index instead of sweeping")
ap.add_argument("--steps", type=int, default=1600)
a = ap.parse_args()

FW = os.path.join(a.digiemu, "portable", "firmware", a.fw)
sys.path.insert(0, a.digiemu)
syxname = [f for f in os.listdir(FW) if f.endswith(".syx")][0]
os.environ.update({
    "DT2_SYX": os.path.join(FW, syxname), "DT2_SECTIONS": FW + "/sections",
    "DT2_SNAPSHOTS": FW + "/snapshots", "DT2_PLUSDRIVE": FW + "/plusdrive.img",
    "DT2_MAIN_IMG": FW + "/sections/section_3_MAIN_OS.bin",
    "DT2_DEVICES": FW + "/devices" if os.path.isdir(FW + "/devices") else os.path.join(a.digiemu, "devices"),
    "DIGIKIT_PIT3_PROBE": "1"})
os.chdir(FW)
_tk = types.ModuleType("tkinter")
_tk.Frame = type("Frame", (), {})
_tk.Tk = type("Tk", (), {})
sys.modules["tkinter"] = _tk
for _n in ("ttk", "messagebox", "filedialog", "font"):
    sys.modules["tkinter." + _n] = types.ModuleType("tkinter." + _n)
from unicorn import UC_HOOK_CODE  # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_D0, UC_M68K_REG_D3  # noqa: E402
import emu.gui as G  # noqa: E402

SNAP = [os.path.join(dp, f) for dp, _, fs in os.walk(FW + "/snapshots") for f in fs if f == "gui.snap"][0]
CALL, RET = 0x400780BA, 0x400780C6
AMP = 1 << 20
N = 32
TONE = [int(AMP * math.sin(2 * math.pi * i / N)) for i in range(N)]
state = {"n": 0, "buf": 0, "cap": 0, "block": 0, "fi": 0, "stream": [], "fis": [], "maxjump": 0.0,
         "at": 0}


def rd(u, addr, n):
    try:
        return bytes(u.mem_read(addr, n))
    except Exception:
        return b""


def u32(u, addr):
    return struct.unpack(">I", rd(u, addr, 4))[0]


def call_hook(u, address, size, user):
    d0 = u.reg_read(UC_M68K_REG_D0)
    params = u.reg_read(UC_M68K_REG_D3)
    voice = d0 >> 7
    buf = 0x80001A18 + d0
    if voice != 0:
        return
    # start sweeping after 20 warm-up blocks
    state["block"] += 1
    if a.hold >= 0:
        fi = a.hold
    elif state["block"] < 20:
        fi = 64
    else:
        t = (state["block"] - 20) % 256
        fi = t if t < 128 else 255 - t          # 0..127..0 triangle
    state["fi"] = fi
    u.mem_write(params, bytes([a.type]))
    u.mem_write(params + 2, struct.pack(">H", fi << 8))
    u.mem_write(0x80001502 + 106 * voice + 2 * 0x1B, struct.pack(">H", 8 << 11))
    state["buf"] = buf
    u.mem_write(buf, struct.pack(">%di" % N, *TONE))
    state["cap"] = 1


def ret_hook(u, address, size, user):
    if not state["cap"]:
        return
    state["cap"] = 0
    out = struct.unpack(">%di" % N, rd(u, state["buf"], 4 * N))
    if state["block"] < 20:
        return
    state["fis"].append(state["fi"])
    for v in out:
        state["stream"].append(v)


spin0 = G.spin


def spin(m, pc, *args, **kw):
    uc = m.uc
    if state["n"] == 1:
        uc.hook_add(UC_HOOK_CODE, call_hook, begin=CALL, end=CALL)
        uc.hook_add(UC_HOOK_CODE, ret_hook, begin=RET, end=RET)
        uc.ctl_flush_tb()
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps or len(state["stream"]) >= 64 * 32:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
s = state["stream"]
print("error:", E.error, "blocks:", state["block"], "samples:", len(s))
if len(s) < 64:
    print("FAIL: not enough audio captured")
    sys.exit(1)
peak = max(abs(v) for v in s)
# expected max slope of the 1500 Hz sine of amplitude ~AMP
import statistics
jumps = [abs(s[i] - s[i - 1]) for i in range(1, len(s))]
mx = max(jumps)
# locate the biggest jump and the block index
idx = jumps.index(mx)
blk = idx // N
print("peak=%.3f A   max sample jump=%.0f (%.3f A) at sample %d (block ~%d, fi ~%s)"
      % (peak / AMP, mx, mx / AMP, idx, blk, state["fis"][blk] if blk < len(state["fis"]) else "?"))
print("median jump=%.0f  (a click is a big multiple of this)" % statistics.median(jumps))
# sample-level extreme checks
first = s[:8]
print("first samples:", first)
print("PASS (no huge jump)" if mx < AMP * 0.5 else "CLICKS (jump > 0.5 A)")
sys.exit(0)
