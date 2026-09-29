#!/usr/bin/env python3
"""Which field carries the envelope-modulated cutoff? Retrigger the voice and
watch params@2/@4/@6 and the render freq array at the filter call (0x400780c4)."""
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
from unicorn import UC_HOOK_CODE  # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_A7  # noqa: E402
import emu.gui as G  # noqa: E402

SNAP = [os.path.join(dp, f) for dp, _, fs in os.walk(FW + "/snapshots") for f in fs if f == "gui.snap"][0]
CALL = 0x400780C4
state = {"n": 0, "seen": []}


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
    state["seen"].append((u16(u, params + 2), u16(u, params + 4), u16(u, params + 6),
                          u16(u, 0x80001F18), active))


spin0 = G.spin
PLAN = {120: ("press", 21), 170: ("release", 21), 260: ("press", 24), 320: ("release", 24)}
for _k in range(25):                       # encoder H = Env Depth, up
    PLAN[360 + 8 * _k] = ("encoder", 8, 4)
for _k in range(10):                       # encoder E = FREQ, down to mid
    PLAN[600 + 8 * _k] = ("encoder", 5, -4)


def spin(m, pc, *args, **kw):
    uc = m.uc
    if state["n"] == 1:
        uc.hook_add(UC_HOOK_CODE, call_hook, begin=CALL, end=CALL)
        uc.ctl_flush_tb()
    act = PLAN.get(state["n"])
    if act:
        if act[0] == "encoder":
            E.inbox.append(("encoder", act[1], act[2]))
        else:
            E.inbox.append((act[0], act[1], 0))
    if 700 <= state["n"] < 1300 and state["n"] % 30 == 0:
        E.inbox.append(("press", 24, 0))
    if 700 <= state["n"] < 1300 and state["n"] % 30 == 10:
        E.inbox.append(("release", 24, 0))
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"], "samples:", len(state["seen"]))
cols = ["params@2", "params@4", "params@6", "freqarr", "active"]
for i, name in enumerate(cols):
    xs = sorted({s[i] for s in state["seen"]})
    if len(xs) <= 10:
        print("  %-9s %s" % (name, [hex(x) for x in xs]))
    else:
        print("  %-9s %d distinct: %s..%s" % (name, len(xs), hex(xs[0]), hex(xs[-1])))
sys.exit(0)
