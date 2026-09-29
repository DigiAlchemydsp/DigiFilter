#!/usr/bin/env python3
"""Who reads/writes the per-voice Filter Type and the coeff-index fields?

Hooks memory reads/writes to two addresses and logs the PC: the per-voice TYPE
byte (params + v*0x6a + 0x44) and the multimode coeff value (+0xa4).

    python tests/digiemu_filter_reader.py --digiemu <checkout> --fw <folder>
"""
import argparse
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--steps", type=int, default=1500)
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
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE  # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_PC  # noqa: E402
import emu.gui as G  # noqa: E402

SNAP = [os.path.join(dp, f) for dp, _, fs in os.walk(FW + "/snapshots") for f in fs if f == "gui.snap"][0]
V0 = 0x80002760
STRIDE = 0x6A
WATCH = {}
for v in range(8):
    WATCH[V0 + v * STRIDE + 0x44] = "type%d" % v
    WATCH[V0 + v * STRIDE + 0xA4] = "coef%d" % v

state = {"n": 0, "uc": None, "hits": {}}


def hook_mem(u, access, address, size, value, user):
    name = WATCH.get(address)
    if name is None:
        return
    pc = u.reg_read(UC_M68K_REG_PC)
    key = (name, pc, "w" if access == UC_HOOK_MEM_WRITE else "r")
    state["hits"][key] = state["hits"].get(key, 0) + 1


spin0 = G.spin
PLAN = {150: ("press", 21), 200: ("release", 21),
        300: ("press", 24), 360: ("release", 24),
        700: ("press", 10), 760: ("release", 10)}


def spin(m, pc, *args, **kw):
    uc = m.uc
    state["uc"] = uc
    if state["n"] == 1:
        uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, hook_mem,
                    begin=V0, end=V0 + 8 * STRIDE + 0xC0)
        uc.ctl_flush_tb()
    act = PLAN.get(state["n"])
    if act:
        E.inbox.append((act[0], act[1], 0))
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"])
print("accesses to TYPE / coeff fields (name, pc, r/w -> count):")
for (name, pc, rw), n in sorted(state["hits"].items()):
    print("  %-7s pc=0x%08x %s  x%d" % (name, pc, rw, n))
sys.exit(1 if E.error else 0)
