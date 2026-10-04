#!/usr/bin/env python3
"""Check the FLTR page's response curve is redrawn for the new modes.

Boots the real firmware (digiemu), opens the FLTR page and, for each TYPE, forces
the kit TYPE/FREQ/RESO, forces a redraw, and captures the published framebuffer.
The graph area must differ between the stock curve and each new mode's curve.

TYPE is written straight into the pattern's kit (the same word the page draw reads)
because the emulator's encoder input cannot land on every value (each detent
moves the parameter by two display units). A redraw is requested each frame by
setting the view controller's dirty byte (ctrl+0x20), exactly as core's ev_tick
handlers do. The curve itself is painted by core's ev_draw handler
(digifilter_draw); the site core patched, 0x4000a7d6, gives the controller.

    python tests/digiemu_filter_curve.py --digiemu <checkout> --fw <folder>
"""
import argparse
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--steps", type=int, default=520)
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
UI_KIT = 0x4199DC44
ACTIVE = 0x4197B6B4
SITE = 0x4000A7D6             # core's ev_draw site: sp = ctrl, sp+4 = bmp
FLTR_KIND = 6
# graph box to compare (bitmap coords, row 0 = bottom): the FLTR page's response area
GX0, GX1, GY0, GY1 = 2, 126, 22, 52
TYPES = (1, 8, 9, 10, 11)     # stock, BP, BP2, COMB, TRASH


def rd(u, addr, n):
    try:
        return bytes(u.mem_read(addr, n))
    except Exception:
        return b""


def u32(u, addr):
    b = rd(u, addr, 4)
    return struct.unpack(">I", b)[0] if b else 0


def kit_word_addr(u, slot):
    kit = u32(u, UI_KIT)
    t = u32(u, ACTIVE)
    if not kit or t > 7:
        return 0
    return kit + 0x20 + t * 0xA2 + 0x14 + 2 * slot


def force(u, ty):
    """The active track's TYPE / FREQ / RESO, as the page and DSP read them."""
    a0 = kit_word_addr(u, 0x19)
    if not a0:
        return -1
    u.mem_write(a0, struct.pack(">H", ty << 8))          # TYPE
    u.mem_write(a0 + 2, struct.pack(">H", 64 << 8))       # FREQ index 64
    u.mem_write(a0 + 4, struct.pack(">H", 8 << 11))       # RESO index 8
    return struct.unpack(">H", rd(u, a0, 2))[0] >> 8


state = {"n": 0, "ctrl": 0, "shots": {}}
spin0 = G.spin
PLAN = {120: ("press", 21), 170: ("release", 21)}
# force a TYPE, let the frame settle, capture; then the next one
STEP = 16
BASE = 240
FORCES = {BASE + i * STEP: TYPES[i] for i in range(len(TYPES))}
CAPS = {BASE + i * STEP + STEP // 2: TYPES[i] for i in range(len(TYPES))}


def ctrl_hook(u, address, size, user):
    if not state["ctrl"]:
        state["ctrl"] = u32(u, u.reg_read(UC_M68K_REG_A7))


def region(raw):
    px = set()
    for y in range(GY0, GY1):
        row = raw[y * 128:(y + 1) * 128]
        for x in range(GX0, GX1):
            if x < len(row) and row[x]:
                px.add((x, y))
    return px


def spin(m, pc, *args, **kw):
    uc = m.uc
    if state["n"] == 1:
        uc.hook_add(UC_HOOK_CODE, ctrl_hook, begin=SITE, end=SITE)
        uc.ctl_flush_tb()
    act = PLAN.get(state["n"])
    if act:
        E.inbox.append((act[0], act[1], 0))
    if state["ctrl"]:
        uc.mem_write(state["ctrl"] + 0x20, b"\x01")   # request a recompose
    ty = FORCES.get(state["n"])
    if ty is not None:
        got = force(uc, ty)
        print("spin %d force TYPE %d (kit %d)" % (state["n"], ty, got))
    r = spin0(m, pc, *args, **kw)
    cap = CAPS.get(state["n"])
    if cap is not None and getattr(E, "fb", None):
        state["shots"][cap] = bytes(E.fb)
    state["n"] += 1
    if state["n"] >= a.steps:
        E.stop_flag.set()
    return r


G.spin = spin
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"], "shots:", sorted(state["shots"]))

if os.environ.get("DUMP"):
    t = int(os.environ["DUMP"])
    raw = state["shots"].get(t)
    if raw is None:
        print("FAIL: no shot for TYPE %d" % t)
        sys.exit(1)
    print("bitmap for TYPE %d" % t)
    for y in range(63, -1, -1):
        row = raw[y * 128:(y + 1) * 128]
        print("%2d %s" % (y, "".join("#" if row[x] else "." for x in range(128))))
    sys.exit(0)

if 1 not in state["shots"]:
    print("FAIL: no stock-type shot (did the FLTR page draw?)")
    sys.exit(1)

ok = True
stock = region(state["shots"][1])
regs = {}
for t in (8, 9, 10, 11):
    if t not in state["shots"]:
        print("  TYPE %d: not captured" % t)
        ok = False
        continue
    reg = region(state["shots"][t])
    regs[t] = reg
    diff = len(reg ^ stock)
    print("  TYPE %d: graph pixels %d, differs from stock TYPE 1 by %d" % (t, len(reg), diff))
    if diff == 0:
        ok = False

# BP (8) and COMB (10) must draw different shapes
if 8 in regs and 10 in regs:
    d = len(regs[8] ^ regs[10])
    print("  BP vs COMB differ by %d pixels" % d)
    if d == 0:
        ok = False

print("PASS" if ok else "FAIL: a new mode drew the stock curve")
sys.exit(0 if ok else 1)
