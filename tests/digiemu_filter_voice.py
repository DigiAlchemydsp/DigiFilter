#!/usr/bin/env python3
"""Verify the per-voice filter call at 0x400780c4 and its buffer/args live.

    python tests/digiemu_filter_voice.py --digiemu <checkout> --fw <folder>
"""
import argparse
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--steps", type=int, default=1100)
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
from unicorn.m68k_const import UC_M68K_REG_A3, UC_M68K_REG_A7  # noqa: E402
import emu.gui as G  # noqa: E402

SNAP = [os.path.join(dp, f) for dp, _, fs in os.walk(FW + "/snapshots") for f in fs if f == "gui.snap"][0]
CALL = 0x400780C4      # jsr %a3@  (a3 = 0x40072844 from 0x400780a4)
FREQ = 0x80001F18
state = {"n": 0, "shown": 0, "log": [], "tag": "idle", "capture": True, "hits": 0,
         "max": {}, "samples": {}, "out": 0}


def rd(u, addr, n):
    try:
        return bytes(u.mem_read(addr, n))
    except Exception:
        return b""


def u32(u, addr):
    return struct.unpack(">I", rd(u, addr, 4))[0]


def absmax(u, addr, nbytes):
    b = rd(u, addr, nbytes)
    if not b:
        return 0
    return max(abs(v) for v in struct.unpack(">%di" % (len(b) // 4), b))


def hook(u, address, size, user):
    state["hits"] = state.get("hits", 0) + 1
    sp = u.reg_read(UC_M68K_REG_A7)
    a1, a2, a3, a4 = (u32(u, sp + 4 * i) for i in (0, 1, 2, 3))
    m = absmax(u, a2, 0x80)
    key = "voice%d" % a4
    if m > state["max"].get(key, 0):
        state["max"][key] = m
        state["samples"][key] = (state["hits"], a1, a2, a3, rd(u, a1, 1)[0], rd(u, a1, 0x18).hex())
    state["out"] = max(state.get("out", 0), absmax(u, 0x4BA8F280, 0x80))
    if state["shown"] < 6 and (m or a3):
        state["shown"] += 1
        state["log"].append("hit#%d voice=%d active=%d TYPE=%d bufmax=%d params=%s freq=%s"
                            % (state["hits"], a4, a3, rd(u, a1, 1)[0], m, rd(u, a1, 0x18).hex(),
                               struct.unpack(">8H", rd(u, FREQ, 16))))


spin0 = G.spin
PLAN = {150: ("press", 21), 200: ("release", 21),
        300: ("press", 24), 950: ("release", 24)}


def spin(m, pc, *args, **kw):
    uc = m.uc
    if state["n"] == 1:
        uc.hook_add(UC_HOOK_CODE, hook, begin=CALL, end=CALL)
        uc.ctl_flush_tb()
    act = PLAN.get(state["n"])
    if act:
        if act[0] in ("press", "release"):
            E.inbox.append((act[0], act[1], 0))
        elif act[0] == "cap":
            state.update(capture=True, shown=0, tag=act[1])
        elif act[0] == "dec":
            state["capture"] = False
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"], "calls:", state["hits"])
print("\n".join(state["log"]))
print("-- per-voice buffer max over run --")
for k in sorted(state["max"]):
    hit, a1, a2, a3, ty, p = state["samples"][k]
    print("  %s max=%d  TYPE=%d active=%d params=0x%08x buf=0x%08x" % (k, state["max"][k], ty, a3, a1, a2))
    print("     params+0..0x18=%s" % p)
print("-- output 0x4ba8f280 max over run: %d" % state["out"])
sys.exit(1 if E.error else 0)
