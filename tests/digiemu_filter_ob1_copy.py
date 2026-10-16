#!/usr/bin/env python3
"""Does an OB-1 Filter Type (12 OB4, 13 OB2; docs/ob1.md) survive copying a track's Sound to another track?

Writes TYPE into track 1's kit, then copies track 1's Sound and pastes it to track 2 as the manual says
(TRK + RECORD copies, TRK + a trig key selects the track, TRK + STOP pastes), and checks track 2's TYPE.

    python tests/digiemu_filter_ob1_copy.py --digiemu <checkout> --fw <folder> [--type 13]
"""
import argparse
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--type", type=int, default=13)
ap.add_argument("--steps", type=int, default=700)
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
TRK, RECORD, STOP, TRIG2 = 2, 9, 11, 25        # key codes (digiemu devices/digitakt.toml)
state = {"n": 0, "uc": None}


def types_of(u):
    kit = struct.unpack(">I", bytes(u.mem_read(UI_KIT, 4)))[0]
    if not kit:
        return None
    return [struct.unpack(">H", bytes(u.mem_read(kit + 0x20 + t * 0xA2 + 0x46, 2)))[0] >> 8 for t in range(8)]


def chord(at, hold, tap):
    return {at: [("press", hold)], at + 10: [("press", tap)], at + 30: [("release", tap)],
            at + 40: [("release", hold)]}


EVENTS = {}
for ev in (chord(300, TRK, RECORD), chord(420, TRK, TRIG2), chord(540, TRK, STOP)):
    for k, v in ev.items():
        EVENTS.setdefault(k, []).extend(v)

spin0 = G.spin


def spin(m, pc, *args, **kw):
    uc = m.uc
    state["uc"] = uc
    n = state["n"]
    if n == 150:
        kit = struct.unpack(">I", bytes(uc.mem_read(UI_KIT, 4)))[0]
        uc.mem_write(kit + 0x20 + 0x46, struct.pack(">H", a.type << 8))
        print("wrote track1 TYPE=%d -> %s" % (a.type, types_of(uc)))
    for ev in EVENTS.get(n, []):
        E.inbox.append((ev[0], ev[1], 0))
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
got = types_of(state["uc"])
print("error:", E.error, "steps:", state["n"], "TYPEs:", got)
ok = not E.error and got and got[1] == a.type
print("PASS" if ok else "FAIL: track 2 is not TYPE %d after the paste" % a.type)
sys.exit(0 if ok else 1)
