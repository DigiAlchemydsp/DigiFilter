#!/usr/bin/env python3
"""Discover which FLTR-page encoder moves which parameter slot.

    python tests/digiemu_filter_enc.py --digiemu <checkout> --fw <folder>
"""
import argparse
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--steps", type=int, default=3200)
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
state = {"n": 0, "prev": None, "out": []}


def rd(u, addr, n):
    try:
        return bytes(u.mem_read(addr, n))
    except Exception:
        return b""


def u32(u, addr):
    return struct.unpack(">I", rd(u, addr, 4))[0]


def words(u):
    kit = u32(u, UI_KIT)
    if not kit:
        return None
    snd = kit + 0x20
    return [struct.unpack(">H", rd(u, snd + 0x14 + 2 * s, 2))[0] for s in range(53)]


spin0 = G.spin
PLAN = {120: ("press", 21), 170: ("release", 21)}
for e in range(1, 9):
    base = 260 + (e - 1) * 320
    for k in range(6):
        PLAN[base + 10 * k] = ("enc", e)
    PLAN[base + 80] = ("snap", e)


def spin(m, pc, *args, **kw):
    uc = m.uc
    act = PLAN.get(state["n"])
    if act:
        if act[0] == "enc":
            E.inbox.append(("encoder", act[1], 4))
        elif act[0] == "snap":
            w = words(uc)
            if state["prev"] is not None and w is not None:
                changed = [(s, state["prev"][s], w[s]) for s in range(53) if state["prev"][s] != w[s]]
                state["out"].append("enc %d -> slots changed: %s" % (act[1], changed))
            state["prev"] = w
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"])
print("FILTER slots: 0x19=TYPE 0x1a=FREQ 0x1b=RESO 0x1c=EnvDepth 0x1d..0x20=ADSR")
for line in state["out"]:
    print(" ", line)
sys.exit(1 if E.error else 0)
