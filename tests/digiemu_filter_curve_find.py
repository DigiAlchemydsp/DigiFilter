#!/usr/bin/env python3
"""Find the UI code that reads the filter type/coefficients (candidate curve drawer)."""
import argparse
import os
import struct
import sys
import types

ap = argparse.ArgumentParser()
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--steps", type=int, default=1400)
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
from unicorn import UC_HOOK_MEM_READ  # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_PC  # noqa: E402
import emu.gui as G  # noqa: E402

SNAP = [os.path.join(dp, f) for dp, _, fs in os.walk(FW + "/snapshots") for f in fs if f == "gui.snap"][0]
# filter coefficient / state / clamped-type regions
RANGES = [(0x8000F1DC, 0x8000F204), (0x8000F584, 0x8000F6E4), (0x8000F3A4, 0x8000F464)]
state = {"n": 0, "pc": {}}


def hook(u, access, address, size, value, user):
    pc = u.reg_read(UC_M68K_REG_PC)
    state["pc"][pc] = state["pc"].get(pc, 0) + 1


spin0 = G.spin
PLAN = {120: ("press", 21), 170: ("release", 21)}


def spin(m, pc, *args, **kw):
    uc = m.uc
    if state["n"] == 1:
        for lo, hi in RANGES:
            uc.hook_add(UC_HOOK_MEM_READ, hook, begin=lo, end=hi)
        uc.ctl_flush_tb()
    act = PLAN.get(state["n"])
    if act:
        E.inbox.append((act[0], act[1], 0))
    if state["n"] in (300, 500, 700):
        E.inbox.append(("encoder", 7, 4))       # change type -> redraw
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"])
for pc in sorted(state["pc"], key=lambda x: -state["pc"][x]):
    print("  pc=0x%08x  x%d" % (pc, state["pc"][pc]))
sys.exit(1 if E.error else 0)
