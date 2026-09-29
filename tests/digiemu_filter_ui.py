#!/usr/bin/env python3
"""Drive the Digitakt FLTR page in digiemu and watch the per-voice filter
struct, to find where the UI TYPE becomes the DSP class/coefficient index.

    python tests/digiemu_filter_ui.py --digiemu <checkout> --fw <folder> [--steps N]

Prints, for each encoder turn: the pattern kit's TYPE slot (sound block,
+0x46), and the per-voice base +0xa0/+0xa4/+0xa8/+0xac. Read-only.
"""
import argparse
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--steps", type=int, default=2600)
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
VOICE0 = 0x80002760
STRIDE = 0x6A
state = {"n": 0, "uc": None}
rows = []


def rd(u, addr, n):
    return bytes(u.mem_read(addr, n))


def s32(u, addr):
    return struct.unpack(">i", rd(u, addr, 4))[0]


def snap(uc, label):
    kit = struct.unpack(">I", rd(uc, UI_KIT, 4))[0]
    types = []
    if kit:
        for t in range(8):
            types.append(struct.unpack(">H", rd(uc, kit + 0x20 + t * 0xA2 + 0x46, 2))[0])
    v = [("%d/%d/%d/%d" % (rd(uc, VOICE0 + i * STRIDE + 0xA0, 1)[0],
                            s32(uc, VOICE0 + i * STRIDE + 0xA4),
                            s32(uc, VOICE0 + i * STRIDE + 0xA8),
                            s32(uc, VOICE0 + i * STRIDE + 0xAC))) for i in range(4)]
    rows.append("%-16s kit=0x%08x TYPE=%s\n    v0..3 a0/a4/a8/ac = %s" % (label, kit, types, v))


# schedule: (step, action)
PLAN = {150: ("press", 21), 200: ("release", 21)}
t = 260
for enc in range(1, 9):
    for k in range(3):
        PLAN[t] = ("encoder", enc, 4)
        t += 10
    PLAN[t] = ("snap", "enc %d +" % enc)
    t += 120

spin0 = G.spin


def spin(m, pc, *args, **kw):
    state["uc"] = m.uc
    act = PLAN.get(state["n"])
    if act:
        if act[0] in ("press", "release"):
            E.inbox.append((act[0], act[1], 0))
        elif act[0] == "encoder":
            E.inbox.append(("encoder", act[1], act[2]))
        elif act[0] == "snap":
            snap(m.uc, act[1])
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
snap(state["uc"], "final")
print("error:", E.error, "steps:", state["n"])
print("\n".join(rows))
sys.exit(1 if E.error else 0)
