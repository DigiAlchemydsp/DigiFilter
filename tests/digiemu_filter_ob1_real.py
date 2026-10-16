#!/usr/bin/env python3
"""Validate an OB-1 filter mode through the REAL UI path, as digiemu_filter_real.py does for 8..11.

Boots the firmware, opens FLTR, steps track 1's TYPE up with the encoder past 13 (its maximum, so it settles
on OB2), and once the render's TYPE byte, params[0], is 13, at the per-voice filter call 0x400780c4: forces
FREQ 80, RESO 64 and ENV depth 0 in the render's record (as digiemu_filter_dsp.py does; kit writes
reach the render only on a parameter change) and injects a 1500 Hz tone into voice 0's buffer, on the
filter's slope. After 40 blocks the output's peak is compared with tests/ob1_model.py's response. If the
dispatch does not engage, TYPE 13 is clamped to the stock EQ 5 and the result is far off.

    python tests/digiemu_filter_ob1_real.py --digiemu <checkout> --fw <folder>
"""
import argparse
import math
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--steps", type=int, default=1600)
a = ap.parse_args()

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ob1_model as M  # noqa: E402

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
TYPE, SETTLE = 13, 40                          # OB2; blocks before the measurement
AMP = 1 << 20                                  # 1/1024 of a VCO: the linear regime
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
    if voice != 0 or rd(u, params, 1)[0] != TYPE:
        return
    u.mem_write(params + 2, struct.pack(">H", 80 << 8))                  # FREQ 80
    u.mem_write(params + 6, struct.pack(">H", 0x4000))                   # ENV depth 0
    u.mem_write(0x80001502 + 106 * voice + 2 * 0x1B, struct.pack(">H", 64 << 8))   # RESO 64
    state["meta"] = (u16(u, params + 2), u16(u, 0x80001502 + 106 * voice + 2 * 0x1B))
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
        E.inbox.append(("encoder", 7, 4))                               # TYPE up, past 13
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps or len(state["out"]) >= SETTLE + 1:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"], "captured:", len(state["out"]))
if not state["meta"] or len(state["out"]) <= SETTLE:
    print("FAIL: the render never ran TYPE %d for %d blocks through the real path" % (TYPE, SETTLE + 1))
    sys.exit(1)

fword, rword = state["meta"]
fi, qi = fword / 256.0, min(127, rword >> 8)
out = state["out"][-1]
peak = max(abs(v) for v in out) / float(AMP)
model = M.h_analytic(1500.0, M.corner_hz(fi), M.gain_k(qi), 2)
err = abs(peak - model) / model
print("real path: TYPE %d (OB2) FREQ %.2f (%.0f Hz) RESO %d (k %.2f): out %.5f, model |H| %.5f, rel err %.1f%%"
      % (TYPE, fi, M.corner_hz(fi), qi, M.gain_k(qi), peak, model, err * 100))
ok = err < 0.05
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
