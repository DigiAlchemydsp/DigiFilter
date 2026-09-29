#!/usr/bin/env python3
"""Validate the new filters through the REAL UI path (not forced args).

Boots the firmware, opens FLTR, steps track 1's TYPE up to a new value with the
encoder, and injects a 1500 Hz test tone into the voice buffer at the per-voice
filter call 0x400780c4 (only when the track's TYPE, params[0], is 8..11). The
result is compared with tests/filter_model.py. If the hook does not engage, the
output is the stock clamp (EQ:5) and the test fails.

    python tests/digiemu_filter_real.py --digiemu <checkout> --fw <folder>
"""
import argparse
import math
import os
import re
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--steps", type=int, default=1400)
a = ap.parse_args()

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import filter_model as FM  # noqa: E402

txt = open(os.path.join(os.path.dirname(HERE), "filter_tables.h")).read()
HZ = [int(x) for x in re.findall(r"\d+", txt.split("HZ[128]")[1].split("};")[0])]
QX10 = [int(x) for x in re.findall(r"\d+", txt.split("QX10[16]")[1].split("};")[0])]
G27 = [int(x) for x in re.findall(r"\d+", txt.split("G27[128]")[1].split("};")[0])]
COMB_D = [int(x) for x in re.findall(r"\d+", txt.split("COMB_DELAY[128]")[1].split("};")[0])]
MODES = ["BP", "BP2", "COMB", "TRASH"]

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
CALL, RET = 0x400780C4, 0x400780C6
FREQ = 0x80001F18
RESO = 0x80001502 + 2 * 0x1B
AMP = 1 << 20
N = 32
TONE = [int(AMP * math.sin(2 * math.pi * i / N)) for i in range(N)]  # 1500 Hz @ 48k
state = {"n": 0, "out": [], "meta": None, "buf": 0, "cap": 0}


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
    t = rd(u, params, 1)[0]
    if t < 8 or t > 11:
        return
    state["meta"] = (t, u16(u, params + 2),
                     u16(u, 0x80001502 + 106 * voice + 2 * 0x1B))
    state["buf"] = buf
    u.mem_write(buf, struct.pack(">%di" % N, *TONE))
    state["cap"] = 1


def ret_hook(u, address, size, user):
    if not state["cap"]:
        return
    state["cap"] = 0
    state["out"].append(struct.unpack(">%di" % N, rd(u, state["buf"], 4 * N)))


spin0 = G.spin
PLAN = {120: ("press", 21), 170: ("release", 21)}


def spin(m, pc, *args, **kw):
    uc = m.uc
    if state["n"] == 1:
        uc.hook_add(UC_HOOK_CODE, call_hook, begin=CALL, end=CALL)
        uc.hook_add(UC_HOOK_CODE, ret_hook, begin=RET, end=RET)
        uc.ctl_flush_tb()
    act = PLAN.get(state["n"])
    if act:
        E.inbox.append((act[0], act[1], 0))
    if 210 <= state["n"] <= 900 and state["n"] % 8 == 0:
        E.inbox.append(("encoder", 7, 4))
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps or len(state["out"]) >= 6:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"], "captured:", len(state["out"]))
if not state["meta"] or not state["out"]:
    print("FAIL: the hook never saw TYPE 8..11 in the real path (output stayed stock EQ:5)")
    sys.exit(1)

t, fword, rword = state["meta"]
fi = max(0, min(127, fword >> 8))
qi = max(0, min(15, rword >> 11))
mode = MODES[t - 8]
out = state["out"][-1]
peak = max(abs(v) for v in out)
print("real path: TYPE=%d mode=%s fi=%d (%d Hz) qi=%d  peak=%d (%.4f A)"
      % (t, mode, fi, HZ[fi], qi, peak, peak / float(AMP)))
if t in (8, 9):
    q = qi if t == 8 else (qi >> 1)
    x = [math.sin(2 * math.pi * i / N) for i in range(N)]
    yy = FM.svf_block("BP", x * 300, 48000.0, float(HZ[fi]), QX10[q] / 10.0)
    model = max(abs(v) for v in yy[-N:])
elif t == 10:
    model = FM.comb_gain(1500.0, 48000.0, max(2, COMB_D[fi]), qi / 16.0)
else:
    model = FM.comb_gain(1500.0, 48000.0, max(2, COMB_D[fi] // 2), qi / 16.0)
err = abs(peak / float(AMP) - model) / max(model, 1e-9)
print("model |H| = %.5f   dsp = %.5f   rel err %.1f%%" % (model, peak / float(AMP), err * 100))
ok = err < 0.15
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
