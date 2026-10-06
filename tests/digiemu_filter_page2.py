#!/usr/bin/env python3
"""Check the second FLTR page's COMB/TRASH controls coexist with the stock ones.

Boots a firmware with core+digifilter, opens the second FLTR page (FLTR twice),
forces the active track's TYPE to a COMB mode, then turns each encoder and
reports which parameter slots move. The stock encoders must keep working AND the
free B/C/G encoders must drive the new comb controls (spare slots):

    A -> 0x23 stock Env Delay      E -> 0x21 stock Base
    B -> (free)                    F -> 0x22 stock Width
    C -> 0x2f Harmonics            G -> 0x30 Damping
    D -> 0x24 stock SRR            H -> 0x25 stock Routing

The kind-7 layout must read {39,0,14,42,40,41,15,43} and descriptors 14/15
(commandeered 'Error' placeholders) must be filter descriptors on slots
0x2f/0x30 with our labels; switching to a stock TYPE restores the layout. (The
comb feedback is the RESO/GAIN knob on page 1, not a second-page control.)

    python tests/digiemu_filter_page2.py --digiemu <checkout> --fw <folder>
"""
import argparse
import os
import struct
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--digiemu", required=True)
ap.add_argument("--fw", required=True)
ap.add_argument("--steps", type=int, default=5400)
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
import emu.gui as G  # noqa: E402

SNAP = [os.path.join(dp, f) for dp, _, fs in os.walk(FW + "/snapshots") for f in fs if f == "gui.snap"][0]
UI_KIT = 0x4199DC44
ACTIVE = 0x4197B6B4
LAYOUT7 = 0x4197CF88 + 7 * 44
DESC = 0x401A9D9C
EXPECT = {1: 0x23, 2: None, 3: 0x2F, 4: 0x24, 5: 0x21, 6: 0x22, 7: 0x30, 8: 0x25}
COMB_LAYOUT = [39, 0, 14, 42, 40, 41, 15, 43]
STOCK_LAYOUT = [39, 0, 0, 42, 40, 41, 0, 43]
SET_SLOTS = (0x21, 0x22, 0x23, 0x24, 0x25, 0x2E, 0x2F, 0x30)
state = {"n": 0, "prev": None, "out": {}, "layout": None, "desc": None,
         "stock_layout": None, "stock_desc": None}


def rd(u, addr, n):
    return bytes(u.mem_read(addr, n))


def u32(u, addr):
    return struct.unpack(">I", rd(u, addr, 4))[0]


def u16(u, addr):
    return struct.unpack(">H", rd(u, addr, 2))[0]


def kit_base(u):
    kit = u32(u, UI_KIT)
    t = u32(u, ACTIVE)
    if not kit or not (0 <= t <= 7):
        return 0
    return kit + 0x20 + t * 0xA2 + 0x14


def set_type(u, ty):
    b = kit_base(u)
    if b:
        u.mem_write(b + 2 * 0x19, struct.pack(">H", ty << 8))


def preset(u):
    b = kit_base(u)
    if not b:
        return
    for s in SET_SLOTS:
        u.mem_write(b + 2 * s, struct.pack(">H", 0x4000))


def words(u):
    b = kit_base(u)
    if not b:
        return None
    # compare the parameter values (high byte); the mod mirrors the new controls
    # into the low bytes of Base/Width/Env Delay for persistence, which we ignore
    return [u16(u, b + 2 * s) >> 8 for s in range(53)]


def read_desc(u):
    out = []
    for i in (14, 15):
        d = DESC + i * 0x34
        out.append((u16(u, d + 2), u16(u, d + 6), u32(u, d + 0x30)))
    return out


spin0 = G.spin
PLAN = {120: ("press", 21), 160: ("release", 21),
        240: ("press", 21), 280: ("release", 21),
        360: ("type",), 420: ("type",), 460: ("type",),
        520: ("snap", 0),       # seed the baseline word list
        560: ("check",),
        4700: ("stock",), 5000: ("check2",)}


def spin(m, pc, *args, **kw):
    uc = m.uc
    act = PLAN.get(state["n"])
    if act:
        if act[0] == "enc":
            E.inbox.append(("encoder", act[1], 4))
        elif act[0] in ("press", "release"):
            E.inbox.append((act[0], act[1], 0))
        elif act[0] == "type":
            set_type(uc, 10)               # COMB
        elif act[0] == "snap":
            w = words(uc)
            if state["prev"] is not None and w is not None:
                changed = [s for s in range(53) if state["prev"][s] != w[s]]
                state["out"][act[1]] = changed
            state["prev"] = w
        elif act[0] == "check":
            state["layout"] = [u32(uc, LAYOUT7 + 8 + 4 * i) for i in range(8)]
            state["desc"] = read_desc(uc)
        elif act[0] == "stock":
            set_type(uc, 1)                # back to a stock type
        elif act[0] == "check2":
            state["stock_layout"] = [u32(uc, LAYOUT7 + 8 + 4 * i) for i in range(8)]
            state["stock_desc"] = read_desc(uc)
    r = spin0(m, pc, *args, **kw)
    state["n"] += 1
    if state["n"] >= a.steps:
        E.stop_flag.set()
    return r


base = 700
for e in range(1, 9):
    b = base + (e - 1) * 500
    PLAN[b + 5] = ("type",)
    PLAN[b + 10] = ("preset",)
    PLAN[b + 100] = ("snap", 0)          # baseline after the preset settles
    for k in range(6):
        PLAN[b + 160 + 10 * k] = ("enc", e)
    PLAN[b + 280] = ("snap", e)


def spin2(m, pc, *args, **kw):
    if PLAN.get(state["n"], (None,))[0] == "preset":
        preset(m.uc)
    return spin(m, pc, *args, **kw)


G.spin = spin2
E = G.Emulator(SNAP, syx=os.environ["DT2_SYX"], realtime=False, audio=True)
E.run()
print("error:", E.error, "steps:", state["n"])
if E.error:
    sys.exit(1)

ok = True
for e in range(1, 9):
    want = EXPECT[e]
    got = state["out"].get(e)
    if got is None:
        print("  enc %d: not captured" % e)
        ok = False
        continue
    if want is None:
        good = got == []
        print("  enc %d: free (changed %s) %s" % (e, got, "OK" if good else "FAIL"))
    else:
        good = got == [want]
        print("  enc %d: -> 0x%02x (changed %s) %s" % (e, want, got, "OK" if good else "FAIL"))
    ok = ok and good

print("layout kind7:", state["layout"], "(want %s)" % COMB_LAYOUT)
if state["layout"] != COMB_LAYOUT:
    ok = False
print("new descriptors (group, slot, name):",
      [(g, "0x%02x" % s, "0x%08x" % n) for g, s, n in (state["desc"] or [])])
for (g, s, n), ws in zip(state["desc"] or [], (0x2F, 0x30)):
    if g != 6 or s != ws or not (0x47BE0000 <= n < 0x47BF0000):
        ok = False

print("stock-type layout:", state["stock_layout"], "(want %s)" % STOCK_LAYOUT)
if state["stock_layout"] != STOCK_LAYOUT:
    ok = False
print("stock-type descriptors:", state["stock_desc"])
for g, s, n in (state["stock_desc"] or []):
    if g != 0xFFFF:                     # restored to the 'Error' placeholders
        ok = False

print("PASS" if ok else "FAIL: the second FLTR page controls are wrong")
sys.exit(0 if ok else 1)
