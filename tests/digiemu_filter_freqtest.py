#!/usr/bin/env python3
"""Find which FLTR encoder drives the stock cutoff field.

Opens FLTR, turns each encoder in turn, and logs at the per-voice filter call
(0x400780c4) the words the stock function reads: params@2 (F1), params@4 (F2),
params@6 (reso), plus the render freq array 0x80001f18.

    python tests/digiemu_filter_freqtest.py --digiemu <checkout> --fw <folder>
"""
import argparse
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--steps", type=int, default=3600)
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
state = {"n": 0, "enc": 0, "seen": {}}


def rd(u, addr, n):
    try:
        return bytes(u.mem_read(addr, n))
    except Exception:
        return b""


def u32(u, addr):
    return struct.unpack(">I", rd(u, addr, 4))[0]


def u16(u, addr):
    return struct.unpack(">H", rd(u, addr, 2))[0]


def call_hook(u, address, size, user):
    sp = u.reg_read(UC_M68K_REG_A7)
    params, buf, active, voice = (u32(u, sp + 4 * i) for i in (0, 1, 2, 3))
    if voice != 0:
        return
    s = 0x80001502
    key = (state["enc"], rd(u, params, 1)[0],
           u16(u, params + 2), u16(u, s + 2 * 0x1A), u16(u, s + 2 * 0x1B))
    state["seen"][key] = state["seen"].get(key, 0) + 1


spin0 = G.spin
PLAN = {120: ("press", 21), 170: ("release", 21)}
for e in range(1, 9):
    base = 240 + (e - 1) * 400
    for k in range(10):
        PLAN[base + 10 * k] = ("enc", e)


def spin(m, pc, *args, **kw):
    uc = m.uc
    if state["n"] == 1:
        uc.hook_add(UC_HOOK_CODE, call_hook, begin=CALL, end=CALL)
        uc.ctl_flush_tb()
    act = PLAN.get(state["n"])
    if act:
        if act[0] == "press":
            E.inbox.append(("press", act[1], 0))
        elif act[0] == "release":
            E.inbox.append(("release", act[1], 0))
        else:
            state["enc"] = act[1]
            E.inbox.append(("encoder", act[1], -4))
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"])
print(" enc |  TYPE   params@2   slot0x1a(FREQ)   slot0x1b(RESO)")
seen = {}
for (e, t, p2, a, b), n in state["seen"].items():
    seen.setdefault(e, set()).add((t, p2, a, b))
for e in sorted(seen):
    vals = seen[e]

    def col(i):
        xs = sorted({v[i] for v in vals})
        return [hex(x) for x in xs] if len(xs) <= 6 else "[%d: %s..%s]" % (len(xs), hex(xs[0]), hex(xs[-1]))
    print("  %d  | %-7s  %-9s  %-15s  %s" % (e, col(0), col(1), col(2), col(3)))
sys.exit(1 if E.error else 0)
