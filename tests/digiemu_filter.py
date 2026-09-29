#!/usr/bin/env python3
"""Trace the stock per-voice multimode filter inside the real firmware (digiemu, headless).

Boots the settled Digitakt 1.53 snapshot in digiemu's own emulator, hooks the
render's filter call (0x40077fa6) and the multimode filter entry (0x400757fe),
and dumps the arguments, the per-voice class/frequency arrays and the arg1
struct, before and while a voice sounds. Read-only: nothing is patched.

    python tests/digiemu_filter.py --digiemu <checkout> --fw <folder> [--steps N]

`--fw` is a folder name under <checkout>/portable/firmware (e.g.
dt1-1.53-9bdd44bb). Run with the checkout's python (the patched-Unicorn venv).
"""
import argparse
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--steps", type=int, default=1500)
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
    UC_M68K_REG_A1, UC_M68K_REG_A2, UC_M68K_REG_A7, UC_M68K_REG_D5, UC_M68K_REG_D7)
import emu.gui as G  # noqa: E402

SNAP = [os.path.join(dp, f) for dp, _, fs in os.walk(FW + "/snapshots") for f in fs if f == "gui.snap"][0]
FILTER = 0x400757FE
CALL = 0x40077FA6
COEFF_READ = 0x4007592E          # mvzb %a1@(164),%d0 : reads the coeff index
FREQ_ARR = 0x80001F18
CLASS_ARR = 0x4199E466
PATTERN_BASE = 0x80002760

state = {"n": 0, "filt": 0, "call": 0, "coef": 0, "capture": True, "coefcap": False, "tag": "idle", "uc": None}
log, calllog, coeflog = [], [], []


def rd(u, addr, n):
    return bytes(u.mem_read(addr, n))


def u32(u, addr):
    return struct.unpack(">I", rd(u, addr, 4))[0]


def u16(u, addr):
    return struct.unpack(">H", rd(u, addr, 2))[0]


def s32(u, addr):
    return struct.unpack(">i", rd(u, addr, 4))[0]


def dump_struct(u, arg1, tag):
    rows = []
    rows.append("  arg1=0x%08x  +0x00=%s" % (arg1, rd(u, arg1, 0x40).hex()))
    rows.append("  +0xa0 cl=%d  +0xa4=%d  +0xa8=%d  +0xac=%d"
                % (rd(u, arg1 + 0xA0, 1)[0], s32(u, arg1 + 0xA4), s32(u, arg1 + 0xA8), s32(u, arg1 + 0xAC)))
    return "\n".join(rows)


def filt_hook(u, address, size, user):
    state["filt"] += 1
    if not state["capture"] or state["filt"] > 4000:
        return
    sp = u.reg_read(UC_M68K_REG_A7)
    arg1, arg2, arg3, arg4, arg5 = (u32(u, sp + 4 * i) for i in (1, 2, 3, 4, 5))
    cls = rd(u, arg2, 8)
    freq = [u16(u, arg5 + 2 * i) for i in range(8)]
    log.append("hit #%d tag=%s arg1=0x%08x arg2=0x%08x arg3=0x%08x arg4=0x%08x arg5=0x%08x"
               % (state["filt"], state["tag"], arg1, arg2, arg3, arg4, arg5))
    log.append("  class=%s  freq=%s" % (cls.hex(), freq))
    log.append(dump_struct(u, arg1, state["tag"]))
    state["capture"] = False


def coef_hook(u, address, size, user):
    if not state["coefcap"]:
        return
    state["coef"] += 1
    if state["coef"] > 8:
        state["coefcap"] = False
        return
    a1 = u.reg_read(UC_M68K_REG_A1)
    coeflog.append("coef #%d tag=%s a1=0x%08x  +0xa0=%d +0xa4=%d +0xa8=%d +0xac=%d +0xb4=%d"
                   % (state["coef"], state["tag"], a1, rd(u, a1 + 0xA0, 1)[0],
                      s32(u, a1 + 0xA4), s32(u, a1 + 0xA8), s32(u, a1 + 0xAC), s32(u, a1 + 0xB4)))


def call_hook(u, address, size, user):
    state["call"] += 1
    if state["call"] > 4000:
        return
    a2 = u.reg_read(UC_M68K_REG_A2)
    d5 = u.reg_read(UC_M68K_REG_D5)
    d7 = u.reg_read(UC_M68K_REG_D7)
    sp = u.reg_read(UC_M68K_REG_A7)
    arg1 = u32(u, sp)
    calllog.append("call #%d a2=0x%08x sp_arg1=0x%08x d5=0x%08x d7=0x%08x  freq=%s"
                   % (state["call"], a2, arg1, d5, d7,
                      [u16(u, FREQ_ARR + 2 * i) for i in range(8)]))


PLAN = {1: ("install",),
        200: ("press", 24), 260: ("release", 24),
        300: ("capture", "trig1"), 320: ("decapture",),
        420: ("press", 10), 460: ("release", 10),
        600: ("capture", "play"), 620: ("decapture",),
        900: ("capture", "steady"), }


spin0 = G.spin


def spin(m, pc, *args, **kw):
    uc = m.uc
    state["uc"] = uc
    if state["n"] == 1:
        uc.hook_add(UC_HOOK_CODE, filt_hook, begin=FILTER, end=FILTER)
        uc.hook_add(UC_HOOK_CODE, call_hook, begin=CALL, end=CALL)
        uc.hook_add(UC_HOOK_CODE, coef_hook, begin=COEFF_READ, end=COEFF_READ)
        uc.ctl_flush_tb()
    act = PLAN.get(state["n"])
    if act:
        if act[0] in ("press", "release"):
            E.inbox.append((act[0], act[1], 0))
        elif act[0] == "capture":
            state.update(capture=True, tag=act[1], filt=0, coef=0, coefcap=True)
        elif act[0] == "decapture":
            state["capture"] = False
            state["coefcap"] = False
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"], "filter hits:", state["filt"], "calls:", state["call"])
print("---- filter call site ----")
print("\n".join(calllog[:12]) or "(none)")
print("---- filter entry ----")
print("\n".join(log) or "(none)")
print("---- coeff-index reads (0x4007592e) ----")
print("\n".join(coeflog) or "(none)")
print("---- raw arrays now ----")
try:
    uc = state["uc"]
    print("class 0x4199e466:", rd(uc, CLASS_ARR, 8).hex())
    print("freq  0x80001f18:", [u16(uc, FREQ_ARR + 2 * i) for i in range(8)])
    print("params 0x80002760:", rd(uc, PATTERN_BASE, 0x40).hex())
except Exception as e:
    print("read failed:", e)
sys.exit(1 if E.error else 0)
