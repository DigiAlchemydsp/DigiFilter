#!/usr/bin/env python3
"""Validate the second FLTR page's COMB controls (Feedback, Harmonics).

Forces voice 0's TYPE (10 COMB / 11 TRASH), FREQ and the second page's comb
controls: Feedback (params+0x10, slot 0x21) and Harmonics (params+0x14, slot
0x23). The comb becomes COMB_DELAY[fi] / (div * (1 + harm*3/127)) with feedback
g = fb*13/2032, and the output peak is compared with tests/filter_model.py
comb_gain.

    python tests/digiemu_filter_comb2.py --digiemu <checkout> --fw <folder> \
        --type 10 --fi 100 --fb 64 --harm 0
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
ap.add_argument("--type", type=int, default=10)
ap.add_argument("--fi", type=int, default=100)
ap.add_argument("--fb", type=int, default=64, help="Feedback 0..127 (slot 0x21)")
ap.add_argument("--harm", type=int, default=0, help="Harmonics 0..127 (slot 0x23)")
ap.add_argument("--steps", type=int, default=900)
a = ap.parse_args()

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import filter_model as FM  # noqa: E402

txt = open(os.path.join(os.path.dirname(HERE), "filter_tables.h")).read()
COMB_D = [int(x) for x in re.findall(r"\d+", txt.split("COMB_DELAY[128]")[1].split("};")[0])]

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
from unicorn.m68k_const import UC_M68K_REG_D0, UC_M68K_REG_D3  # noqa: E402
import emu.gui as G  # noqa: E402

SNAP = [os.path.join(dp, f) for dp, _, fs in os.walk(FW + "/snapshots") for f in fs if f == "gui.snap"][0]
CALL, RET = 0x400780BA, 0x400780C6
AMP = 1 << 20
N = 32
TONE = [int(AMP * math.sin(2 * math.pi * i / N)) for i in range(N)]
state = {"n": 0, "blocks": 0, "out": [], "buf": 0, "cap": 0}


def rd(u, addr, n):
    try:
        return bytes(u.mem_read(addr, n))
    except Exception:
        return b""


def call_hook(u, address, size, user):
    d0 = u.reg_read(UC_M68K_REG_D0)
    params = u.reg_read(UC_M68K_REG_D3)
    voice = d0 >> 7
    if voice != 0:
        return
    state["blocks"] += 1
    if state["blocks"] < 8:
        return
    buf = 0x80001A18 + d0
    u.mem_write(params, bytes([a.type]))
    u.mem_write(params + 2, struct.pack(">H", a.fi << 8))
    u.mem_write(params + 6, struct.pack(">H", 0x4000))          # no env
    # Feedback is the RESO/GAIN knob: engine slot 0x1b, 0..127 << 8
    u.mem_write(0x80001502 + 106 * voice + 2 * 0x1B, struct.pack(">H", a.fb << 8))
    u.mem_write(params + 0x2c, struct.pack(">H", a.harm << 8))  # Harmonics 0x2f
    u.mem_write(buf, struct.pack(">%di" % N, *TONE))
    state["buf"] = buf
    state["cap"] = 1


def ret_hook(u, address, size, user):
    if not state["cap"]:
        return
    state["cap"] = 0
    state["out"].append(struct.unpack(">%di" % N, rd(u, state["buf"], 4 * N)))


spin0 = G.spin


def spin(m, pc, *args, **kw):
    uc = m.uc
    if state["n"] == 1:
        uc.hook_add(UC_HOOK_CODE, call_hook, begin=CALL, end=CALL)
        uc.hook_add(UC_HOOK_CODE, ret_hook, begin=RET, end=RET)
        uc.ctl_flush_tb()
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps or len(state["out"]) >= 6:
        E.stop_flag.set()
    return r


div = 1 if a.type == 10 else 2
hdiv = 1 + a.harm * 3 // 127
delay = COMB_D[a.fi] // (div * hdiv)
delay = max(3, min(255, delay))

G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "blocks:", state["blocks"], "captured:", len(state["out"]))
if len(state["out"]) < 3:
    print("FAIL: the per-voice filter call was not reached often enough")
    sys.exit(1)
out = state["out"][-1]
peak = max(abs(v) for v in out)
model = FM.comb_gain(1500.0, 48000.0, delay, a.fb * 31.0 / (127.0 * 32.0))
err = abs(peak / float(AMP) - model) / max(model, 1e-9)
print("TYPE=%d fi=%d fb=%d harm=%d -> hdiv=%d delay=%d"
      % (a.type, a.fi, a.fb, a.harm, hdiv, delay))
print("model |H|=%.5f dsp=%.5f rel err %.1f%%" % (model, peak / float(AMP), err * 100))
ok = err < 0.15
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
