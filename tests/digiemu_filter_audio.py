#!/usr/bin/env python3
"""Capture the multimode filter's audio pointers and per-voice coefficients live.

Hooks the sample-loop read (0x40075ec6) and the coefficient loop (0x400761de)
in 0x400757fe, plus a snapshot of the per-voice biquad tables, to learn the
voice sample buffer, the output buffer and the coefficient layout.

    python tests/digiemu_filter_audio.py --digiemu <checkout> --fw <folder>
"""
import argparse
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--steps", type=int, default=1200)
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
from unicorn.m68k_const import (  # noqa: E402
    UC_M68K_REG_A0, UC_M68K_REG_A1, UC_M68K_REG_A2, UC_M68K_REG_A3,
    UC_M68K_REG_A4, UC_M68K_REG_A5, UC_M68K_REG_D4, UC_M68K_REG_PC)
import emu.gui as G  # noqa: E402

SNAP = [os.path.join(dp, f) for dp, _, fs in os.walk(FW + "/snapshots") for f in fs if f == "gui.snap"][0]
LOOP1 = 0x40075EC6     # movel %a2@+,%d6   (sample read)
LOOP2 = 0x400761DE     # coefficient loop
state = {"n": 0, "uc": None, "shown": 0, "log": [], "tag": "idle", "capture": True}


def rd(u, addr, n):
    try:
        return bytes(u.mem_read(addr, n))
    except Exception:
        return b""


def s32(u, addr):
    return struct.unpack(">i", rd(u, addr, 4))[0]


def hook_loop(u, address, size, user):
    if not state["capture"]:
        return
    state["shown"] += 1
    if state["shown"] > 6:
        state["capture"] = False
        return
    g = u.reg_read
    state["log"].append(
        "tag=%s pc=0x%08x a0=0x%08x a1=0x%08x a2=0x%08x a3=0x%08x a4=0x%08x a5=0x%08x d4=%d"
        % (state["tag"], address, g(UC_M68K_REG_A0), g(UC_M68K_REG_A1), g(UC_M68K_REG_A2),
           g(UC_M68K_REG_A3), g(UC_M68K_REG_A4), g(UC_M68K_REG_A5), g(UC_M68K_REG_D4)))
    a2 = g(UC_M68K_REG_A2)
    state["log"].append("   [a2]=%s  [a4]=%s  [a5]=%s"
                        % (rd(u, a2, 16).hex(), rd(u, g(UC_M68K_REG_A4), 16).hex(),
                           rd(u, g(UC_M68K_REG_A5), 16).hex()))


def dump_tables(u):
    for name, base, n in (("coef 0x8000f584", 0x8000F584, 0x20),
                          ("st   0x8000f3a4", 0x8000F3A4, 0x20),
                          ("st   0x8000f3c4", 0x8000F3C4, 0x20),
                          ("coef 0x8000f5a4", 0x8000F5A4, 0x10)):
        state["log"].append("%-16s %s" % (name, rd(u, base, n).hex()))
        state["log"].append("            %s" % [hex(s32(u, base + 4 * i)) for i in range(n // 4)])


spin0 = G.spin
PLAN = {150: ("press", 21), 200: ("release", 21),
        300: ("press", 24), 360: ("release", 24),
        500: ("cap", "note"),
        780: ("dec"), 820: ("cap", "steady")}


def spin(m, pc, *args, **kw):
    uc = m.uc
    state["uc"] = uc
    if state["n"] == 1:
        uc.hook_add(UC_HOOK_CODE, hook_loop, begin=LOOP1, end=LOOP1)
        uc.hook_add(UC_HOOK_CODE, hook_loop, begin=LOOP2, end=LOOP2)
        uc.ctl_flush_tb()
    act = PLAN.get(state["n"])
    if act:
        if act[0] in ("press", "release"):
            E.inbox.append((act[0], act[1], 0))
        elif act[0] == "cap":
            state.update(capture=True, shown=0, tag=act[1])
            dump_tables(uc)
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
print("error:", E.error, "steps:", state["n"])
print("\n".join(state["log"]))
sys.exit(1 if E.error else 0)
