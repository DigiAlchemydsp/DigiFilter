#!/usr/bin/env python3
"""Validate the filter-envelope modulation on the new modes, live in digiemu.

At the per-voice filter call 0x400780c4 it forces, for voice 0, the TYPE, the
base FREQ word (params@2), the ENV DEPTH word (params@6, biased 0x4000), the
RESO engine slot, and the engine's per-voice envelope level at 0x4199df58
(recomputed each block by the envelope stage, so writing it here at the call is
what our DSP sees). It then injects one cycle of a 1500 Hz tone and compares the
settled peak with tests/filter_model.py, using the modulated cutoff

    envmod = ((-env) * ((envw - 0x4000) << 17)) >> 31
    fi     = clamp((freq_word + (envmod >> 16)) >> 8, 0, 127)

    python tests/digiemu_filter_env_mod.py --digiemu <checkout> --fw <folder> \
        --type 8 --fi 64 --qi 8 --envw 0x6000 --env -1073741824

A run with --envw 0x4000 (ENV depth 0) must give fi == base; a nonzero depth
must shift fi with the sign of -env. Run one at a time (two emulators must not
share a firmware session).
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
ap.add_argument("--type", type=int, default=8)
ap.add_argument("--fi", type=int, default=64, help="base FREQ index (0..127)")
ap.add_argument("--qi", type=int, default=8, help="RESO index (0..15)")
ap.add_argument("--envw", type=lambda s: int(s, 0), default=0x6000,
                help="ENV DEPTH word (0x4000 = 0)")
ap.add_argument("--env", type=lambda s: int(s, 0), default=-1073741824,
                help="forced per-voice envelope level (signed int32)")
ap.add_argument("--steps", type=int, default=900)
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
ENV = 0x4199DF58
AMP = 1 << 20
N = 32
TONE = [int(AMP * math.sin(2 * math.pi * i / N)) for i in range(N)]
state = {"n": 0, "blocks": 0, "out": [], "buf": 0, "cap": 0, "fi_seen": set()}


def rd(u, addr, n):
    try:
        return bytes(u.mem_read(addr, n))
    except Exception:
        return b""


def call_hook(u, address, size, user):
    d0 = u.reg_read(UC_M68K_REG_D0)        # voice*0x80
    params = u.reg_read(UC_M68K_REG_D3)
    voice = d0 >> 7
    if voice != 0:
        return
    state["blocks"] += 1
    if state["blocks"] < 8:
        return
    buf = 0x80001A18 + d0
    u.mem_write(params, bytes([a.type]))
    u.mem_write(params + 2, struct.pack(">H", a.fi << 8))        # FREQ base
    u.mem_write(params + 6, struct.pack(">H", a.envw))          # ENV DEPTH
    u.mem_write(0x80001502 + 106 * voice + 2 * 0x1B, struct.pack(">H", a.qi << 11))
    u.mem_write(ENV + 12 * voice, struct.pack(">i", a.env))     # envelope level
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


def mulsh(x, y, sh):
    p = x * y
    return p >> sh


# the same formula filter.c uses
depth = (a.envw - 0x4000) << 17
envmod = ((-a.env) * depth) >> 31
fi_exp = max(0, min(127, ((a.fi << 8) + (envmod >> 16)) >> 8))

G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"], "blocks:", state["blocks"], "captured:", len(state["out"]))
if len(state["out"]) < 3:
    print("FAIL: the per-voice filter call was not reached often enough")
    sys.exit(1)

out = state["out"][-1]
peak = max(abs(v) for v in out)
print("TYPE=%d fi_base=%d envw=0x%04x env=%d -> envmod=%d fi_exp=%d" %
      (a.type, a.fi, a.envw, a.env, envmod, fi_exp))
print("output peak=%d (%.4f A)" % (peak, peak / float(AMP)))
if peak == 0:
    print("FAIL: the filter produced silence")
    sys.exit(1)

mode = {8: "BP", 9: "BP2", 10: "COMB", 11: "TRASH"}[a.type]
if a.type in (8, 9):
    q = a.qi if a.type == 8 else (a.qi >> 1)
    x = [math.sin(2 * math.pi * i / N) for i in range(N)]
    yy = FM.svf_block("BP", x * 300, 48000.0, float(HZ[fi_exp]), QX10[q] / 10.0)
    model = max(abs(v) for v in yy[-N:])
else:
    import re as _re
    co = [int(x) for x in _re.findall(r"\d+", txt.split("COMB_DELAY[128]")[1].split("};")[0])]
    div = 1 if a.type == 10 else 2
    model = FM.comb_gain(1500.0, 48000.0, max(2, co[fi_exp] // div), a.qi / 16.0)
err = abs(peak / float(AMP) - model) / max(model, 1e-9)
print("mode=%s model |H|=%.5f dsp=%.5f rel err %.1f%%" % (mode, model, peak / float(AMP), err * 100))
ok = err < 0.15
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
