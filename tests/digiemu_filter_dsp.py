#!/usr/bin/env python3
"""Validate the digifilter SVF against the model, live in digiemu (deterministic).

Boots a firmware that contains core+digifilter. At the per-voice filter call
0x400780c4 (called every block for every voice) it forces, for voice 0:
  - the stack `active` argument to 1,
  - the TYPE byte to the requested value (8..11),
  - the FREQ word (0x80001f18+2v) and the RESO word (params+6),
then writes one cycle of a 1500 Hz sine into the voice buffer just before the
call, and reads the buffer back at 0x400780c6. The settled peak is compared with
tests/filter_model.py for the mode. Nothing needs the UI or a sounding sample.

    python tests/digiemu_filter_dsp.py --digiemu <checkout> --fw <folder> \
        --type 8 --fi 100 --qi 8

Run one at a time (two emulators must not share a firmware session).
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
ap.add_argument("--type", type=int, default=8, help="TYPE to force (8..11)")
ap.add_argument("--fi", type=int, default=100, help="forced FREQ index (0..127)")
ap.add_argument("--qi", type=int, default=8, help="forced RESO index (0..15)")
ap.add_argument("--steps", type=int, default=900)
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
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0, UC_M68K_REG_D3  # noqa: E402
import emu.gui as G  # noqa: E402

SNAP = [os.path.join(dp, f) for dp, _, fs in os.walk(FW + "/snapshots") for f in fs if f == "gui.snap"][0]
CALL, RET = 0x400780BA, 0x400780C6      # dispatch (chooses a3); then after the call
FREQ = 0x80001F18
AMP = 1 << 20
N = 32
TONE = [int(AMP * math.sin(2 * math.pi * i / N)) for i in range(N)]  # 1500 Hz @ 48k

state = {"n": 0, "blocks": 0, "out": [], "buf": 0, "cap": 0}


def rd(u, addr, n):
    try:
        return bytes(u.mem_read(addr, n))
    except Exception:
        return b""


def u32(u, addr):
    return struct.unpack(">I", rd(u, addr, 4))[0]


def call_hook(u, address, size, user):
    d0 = u.reg_read(UC_M68K_REG_D0)        # voice*0x80
    params = u.reg_read(UC_M68K_REG_D3)    # this voice's params
    voice = d0 >> 7
    if voice != 0:
        return
    state["blocks"] += 1
    if state["blocks"] < 8:
        return
    buf = 0x80001A18 + d0
    u.mem_write(params, bytes([a.type]))                     # force TYPE (read by the dispatch)
    u.mem_write(params + 2, struct.pack(">H", a.fi << 8))    # CUTOFF (index<<8)
    u.mem_write(0x80001502 + 106 * voice + 2 * 0x1B, struct.pack(">H", a.qi << 11))
    u.mem_write(buf, struct.pack(">%di" % N, *TONE))         # the test input
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


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"], "voice0 blocks:", state["blocks"], "captured:", len(state["out"]))
if len(state["out"]) < 3:
    print("FAIL: the per-voice filter call was not reached often enough")
    sys.exit(1)

out = state["out"][-1]
if a.type < 8:
    # stock TYPE: our hook must tail-call the stock filter unchanged. Print the
    # raw result so two firmwares (custom vs stock) can be diffed byte for byte.
    print("stock TYPE %d OUT=%s" % (a.type, out))
    sys.exit(0)

mode = MODES[a.type - 8]
peak = max(abs(v) for v in out)
print("TYPE=%d mode=%s fi=%d (%d Hz) qi=%d  output peak=%d (%.4f A)"
      % (a.type, mode, a.fi, HZ[a.fi], a.qi, peak, peak / float(AMP)))
if peak == 0:
    print("FAIL: the filter produced silence")
    sys.exit(1)
if peak > (1 << 30):
    print("FAIL: output looks unstable (%d)" % peak)
    sys.exit(1)

TONE_HZ = 1500.0
if a.type in (8, 9):
    # BP and BP2 are the SVF band-pass; BP2 uses the k of half the Q step
    qi = a.qi if a.type == 8 else (a.qi >> 1)
    x = [math.sin(2 * math.pi * i / N) for i in range(N)]
    yy = FM.svf_block("BP", x * 300, 48000.0, float(HZ[a.fi]), QX10[qi] / 10.0)
    model = max(abs(v) for v in yy[-N:])
elif a.type == 10:
    model = FM.comb_gain(TONE_HZ, 48000.0, max(2, COMB_D[a.fi]), a.qi / 16.0)
else:
    model = FM.comb_gain(TONE_HZ, 48000.0, max(2, COMB_D[a.fi] // 2), a.qi / 16.0)
err = abs(peak / float(AMP) - model) / max(model, 1e-9)
print("model |H(f)| = %.5f   dsp = %.5f   rel err %.1f%%" % (model, peak / float(AMP), err * 100))
ok = err < 0.15
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
