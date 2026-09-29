#!/usr/bin/env python3
"""Phase 4: does a new Filter Type survive a project save + reload?

    python tests/digiemu_filter_persist.py --digiemu <checkout> --fw <folder> set [--type 9]
    python tests/digiemu_filter_persist.py --digiemu <checkout> --fw <folder> read

`set` writes the track-1 TYPE into the active kit and drives
SETTINGS > PROJECT > SAVE (keys 6, YES, YES). `read` boots the (possibly
rebuilt) firmware and prints each track's TYPE. Run `emu.portable --rebuild` in
between to reload from the +Drive.
"""
import argparse
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("mode", choices=["set", "read"])
ap.add_argument("--type", type=int, default=9)
ap.add_argument("--steps", type=int, default=900)
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
state = {"n": 0, "uc": None}


def rd(u, addr, n):
    try:
        return bytes(u.mem_read(addr, n))
    except Exception:
        return b""


def u32(u, addr):
    return struct.unpack(">I", rd(u, addr, 4))[0]


def types_of(u):
    kit = u32(u, UI_KIT)
    if not kit:
        return None
    return [struct.unpack(">H", rd(u, kit + 0x20 + t * 0xA2 + 0x46, 2))[0] >> 8 for t in range(8)]


spin0 = G.spin


def spin(m, pc, *args, **kw):
    uc = m.uc
    state["uc"] = uc
    n = state["n"]
    if a.mode == "set":
        if n == 150:
            kit = u32(uc, UI_KIT)
            uc.mem_write(kit + 0x20 + 0x46, struct.pack(">H", a.type << 8))
            print("wrote track1 TYPE=%d -> %s" % (a.type, types_of(uc)))
        # FUNC + YES ("save pattern to project"), then YES to confirm
        seq = {300: ("press", 1), 340: ("press", 12), 360: ("release", 12),
               400: ("release", 1), 460: ("press", 12), 480: ("release", 12)}
        if n in seq:
            E.inbox.append((seq[n][0], seq[n][1], 0))
    else:
        if n == 300:
            print("TYPEs after rebuild:", types_of(uc))
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"])
if state["uc"]:
    print("final TYPEs:", types_of(state["uc"]))
sys.exit(1 if E.error else 0)
