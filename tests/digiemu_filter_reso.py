#!/usr/bin/env python3
"""Fit the UI Resonance -> DSP word mapping.

Opens FLTR, sweeps the RESO encoder, and logs the kit's RESO slot against the
per-voice DSP words (params+6 = reso input, params+2 = freq input) read at the
per-voice filter call (0x400780c4).

    python tests/digiemu_filter_reso.py --digiemu <checkout> --fw <folder>
"""
import argparse
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
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
from unicorn.m68k_const import UC_M68K_REG_A7  # noqa: E402
import emu.gui as G  # noqa: E402

SNAP = [os.path.join(dp, f) for dp, _, fs in os.walk(FW + "/snapshots") for f in fs if f == "gui.snap"][0]
CALL = 0x400780C4
UI_KIT = 0x4199DC44
RESO_SLOT = 0x14 + 2 * 0x1B      # sound-block byte offset of slot 0x1b
FREQ_SLOT = 0x14 + 2 * 0x1A
state = {"n": 0, "samples": {}}


def rd(u, addr, n):
    try:
        return bytes(u.mem_read(addr, n))
    except Exception:
        return b""


def u16(u, addr):
    return struct.unpack(">H", rd(u, addr, 2))[0]


def u32(u, addr):
    return struct.unpack(">I", rd(u, addr, 4))[0]


def call_hook(u, address, size, user):
    sp = u.reg_read(UC_M68K_REG_A7)
    params, buf, active, voice = (u32(u, sp + 4 * i) for i in (0, 1, 2, 3))
    if voice != 0:
        return
    kit = u32(u, UI_KIT)
    if not kit:
        return
    snd = kit + 0x20
    r = u16(u, snd + RESO_SLOT) >> 8
    f = u16(u, snd + FREQ_SLOT) >> 8
    p6 = u16(u, params + 6)
    p2 = u16(u, params + 2)
    state["samples"][(r, f)] = (p6, p2)


spin0 = G.spin
PLAN = {120: ("press", 21), 170: ("release", 21)}


def spin(m, pc, *args, **kw):
    uc = m.uc
    if state["n"] == 1:
        uc.hook_add(UC_HOOK_CODE, call_hook, begin=CALL, end=CALL)
        uc.ctl_flush_tb()
    act = PLAN.get(state["n"])
    if act:
        E.inbox.append((act[0], act[1], 0))
    n = state["n"]
    # sweep RESO down first, then up
    if n >= 220 and n < 520 and n % 6 == 0:
        E.inbox.append(("encoder", 2, -4))
    if n >= 520 and n < a.steps - 100 and n % 6 == 0:
        E.inbox.append(("encoder", 2, 4))
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"], "samples:", len(state["samples"]))
print("  RESO  FREQ   params+6   params+2   p6/256  p6>>11")
for (r, f) in sorted(state["samples"]):
    p6, p2 = state["samples"][(r, f)]
    print("  %4d  %4d   0x%04x     0x%04x     %6.1f    %d" % (r, f, p6, p2, p6 / 256.0, p6 >> 11))
sys.exit(1 if E.error else 0)
