#!/usr/bin/env python3
"""Check that BP's cutoff tracks FLTR encoder E (FREQ) like the stock types.

Sets the track TYPE to BP, then sweeps encoder E and, for each cutoff the voice
reports (params@2), injects a 1500 Hz tone and compares the output with the BP
model. The output must change with the cutoff.

    python tests/digiemu_filter_cutoff.py --digiemu <checkout> --fw <folder>
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
ap.add_argument("--steps", type=int, default=1800)
a = ap.parse_args()

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import filter_model as FM  # noqa: E402

txt = open(os.path.join(os.path.dirname(HERE), "filter_tables.h")).read()
HZ = [int(x) for x in re.findall(r"\d+", txt.split("HZ[128]")[1].split("};")[0])]
QX10 = [int(x) for x in re.findall(r"\d+", txt.split("QX10[16]")[1].split("};")[0])]

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
state = {"n": 0, "phase": "type", "fi": 0, "buf": 0, "cap": 0, "res": {}}


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
    if state["phase"] != "sweep":
        return
    d0 = u.reg_read(UC_M68K_REG_D0)
    params = u.reg_read(UC_M68K_REG_D3)
    voice = d0 >> 7
    if voice != 0:
        return
    buf = 0x80001A18 + d0
    u.mem_write(params, bytes([8]))                     # force BP (cutoff is real)
    state["fi"] = u16(u, params + 2) >> 8
    state["qi"] = u16(u, 0x80001502 + 106 * voice + 2 * 0x1B) >> 11
    state["buf"] = buf
    u.mem_write(buf, struct.pack(">%di" % N, *TONE))
    state["cap"] = 1


def ret_hook(u, address, size, user):
    if not state["cap"]:
        return
    state["cap"] = 0
    out = struct.unpack(">%di" % N, rd(u, state["buf"], 4 * N))
    state["res"][state["fi"]] = (max(abs(v) for v in out), state["qi"])


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
    n = state["n"]
    if n == 210:
        state["phase"] = "sweep"
    if state["phase"] == "sweep" and 240 <= n <= 1700 and n % 8 == 0:
        E.inbox.append(("encoder", 5, -4))          # FREQ down
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps or len(state["res"]) >= 8:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"], "cattoffs seen:", sorted(state["res"]))
ok = True
for fi, (peak, qi) in sorted(state["res"].items()):
    x = [math.sin(2 * math.pi * i / N) for i in range(N)]
    yy = FM.svf_block("BP", x * 300, 48000.0, float(HZ[fi]), QX10[qi] / 10.0)
    model = max(abs(v) for v in yy[-N:])
    err = abs(peak / float(AMP) - model) / max(model, 1e-9)
    print("  fi=%3d (%5d Hz) qi=%d  dsp=%.4f  model=%.4f  err %.1f%%"
          % (fi, HZ[fi], qi, peak / float(AMP), model, err * 100))
    if len(state["res"]) > 1 and err > 0.2:
        ok = False
if len(state["res"]) < 2:
    print("FAIL: the cutoff did not change (only one value seen)")
    ok = False
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
