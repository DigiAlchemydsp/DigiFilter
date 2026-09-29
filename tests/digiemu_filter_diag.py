#!/usr/bin/env python3
"""Diagnose why new TYPE values do not engage in normal playback.

Sets track 1's FLTR TYPE to a new value via the UI (closed loop on the kit),
retriggers the track, and logs at the per-voice filter call (0x400780c4):
params[0] (the TYPE our hook reads), arg3 (the `active` mask), the buffer peak,
and the clamped type the stock DSP sees (0x8000f1e4).

    python tests/digiemu_filter_diag.py --digiemu <checkout> --fw <folder> --type 8
"""
import argparse
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--type", type=int, default=8)
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
from unicorn import UC_HOOK_CODE  # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_A7  # noqa: E402
import emu.gui as G  # noqa: E402

SNAP = [os.path.join(dp, f) for dp, _, fs in os.walk(FW + "/snapshots") for f in fs if f == "gui.snap"][0]
CALL = 0x400780C4
UI_KIT = 0x4199DC44
CLAMPED = 0x8000F1E4          # per-voice clamped type the stock DSP uses
state = {"n": 0, "phase": "type", "rel": set(), "seen": {}, "kit_type": None}


def rd(u, addr, n):
    try:
        return bytes(u.mem_read(addr, n))
    except Exception:
        return b""


def u32(u, addr):
    return struct.unpack(">I", rd(u, addr, 4))[0]


def kit_type(u):
    kit = u32(u, UI_KIT)
    return None if not kit else struct.unpack(">H", rd(u, kit + 0x20 + 0x46, 2))[0] >> 8


def call_hook(u, address, size, user):
    sp = u.reg_read(UC_M68K_REG_A7)
    params, buf, active, voice = (u32(u, sp + 4 * i) for i in (0, 1, 2, 3))
    if voice != 0:
        return
    p0 = rd(u, params, 1)[0]
    cl = struct.unpack(">I", rd(u, CLAMPED, 4))[0]
    kt = kit_type(u)
    key = (kt, p0, cl >> 16)
    state["seen"][key] = state["seen"].get(key, 0) + 1


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
    if 210 <= n <= 900 and n % 10 == 0:          # sweep TYPE 0..11 up
        E.inbox.append(("encoder", 7, 4))
    state["kit_type"] = kit_type(uc)
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"], "kit TYPE last seen:", state["kit_type"])
print("  kit_type  params[0]  clamped_type   count")
for k in sorted(state["seen"], key=lambda x: (x[0] is None, x[0] or 0, x[1])):
    print("     %-5s     %-3d        %-4d        %d" % (k[0], k[1], k[2], state["seen"][k]))
sys.exit(1 if E.error else 0)
