#!/usr/bin/env python3
"""Find where the UI Filter Type lands in the running DSP.

Boots digiemu, opens FLTR, snapshots the per-voice param/state regions, changes
TYPE with encoder G (7), triggers track 1, then diffs the regions and reports
which offsets moved. Read-only.

    python tests/digiemu_filter_type.py --digiemu <checkout> --fw <folder>
"""
import argparse
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--steps", type=int, default=2000)
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
import emu.gui as G  # noqa: E402

SNAP = [os.path.join(dp, f) for dp, _, fs in os.walk(FW + "/snapshots") for f in fs if f == "gui.snap"][0]
UI_KIT = 0x4199DC44
V0 = 0x80002760
VSIZE = 0x6A
NRANGE = 8 * VSIZE
STATE0 = 0x8000EDC4
STATE1 = 0x8000EE36

# (name, base, len) regions to diff
REGIONS = [("params 0x80002760", V0, NRANGE),
           ("params+ 0x80002760..0x80002b2c", V0, 0x3CC),
           ("state 0x8000edc4", STATE0, 0x100),
           ("state 0x8000ee36", STATE1, 0x100)]

state = {"n": 0, "uc": None, "before": {}, "after": {}, "tyb": None, "tya": None}
out = []


def rd(u, addr, n):
    return bytes(u.mem_read(addr, n))


def snap_region(u, key):
    state[key] = {name: rd(u, base, ln) for name, base, ln in REGIONS}
    kit = struct.unpack(">I", rd(u, UI_KIT, 4))[0]
    return [struct.unpack(">H", rd(u, kit + 0x20 + t * 0xA2 + 0x46, 2))[0] for t in range(8)] if kit else []


PLAN = {150: ("press", 21), 200: ("release", 21),
        260: ("snapb",), 300: ("encoder", 7, 4), 315: ("encoder", 7, 4),
        330: ("encoder", 7, 4), 345: ("encoder", 7, 4), 360: ("encoder", 7, 4),
        380: ("press", 24), 430: ("release", 24),
        600: ("snapa",)}

spin0 = G.spin


def spin(m, pc, *args, **kw):
    state["uc"] = m.uc
    act = PLAN.get(state["n"])
    if act:
        if act[0] in ("press", "release"):
            E.inbox.append((act[0], act[1], 0))
        elif act[0] == "encoder":
            E.inbox.append(("encoder", act[1], act[2]))
        elif act[0] == "snapb":
            state["tyb"] = snap_region(m.uc, "before")
        elif act[0] == "snapa":
            state["tya"] = snap_region(m.uc, "after")
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"])
print("kit TYPE before:", state["tyb"])
print("kit TYPE after :", state["tya"])
for name, base, ln in REGIONS:
    b, af = state["before"].get(name, b""), state["after"].get(name, b"")
    diffs = [(i, b[i], af[i]) for i in range(min(len(b), len(af))) if b[i] != af[i]]
    print("== %s: %d bytes differ" % (name, len(diffs)))
    for i, x, y in diffs[:64]:
        print("   +0x%03x  %02x -> %02x   (0x%08x)" % (i, x, y, base + i))
sys.exit(1 if E.error else 0)
