# Reverse-engineering notes (per-track `digifilter`)

**Device: Digitakt mk1, OS 1.53 only.** Image = stock main OS at `0x40000400`,
len 2475584, sha256 `4b47a950…c5df` (`.syx` sha256 `9bdd44bb…`).

Marks: **[S]** static (image bytes), **[L]** verified live in digiemu.

Method: `tools/disas.py` (`m68k-elf-objdump -m m68k:cfv4e`) for real
disassembly; headless digiemu runs (`tests/digiemu_*.py`) for live confirmation.

---

## 1. The filter parameter slot map — SOLVED [S][L]

Descriptors at `0x401a9d9c`, 0x34 B each: `w0`=group, `w1`=slot, `w3`=range
`(max<<8)`, `w4`=step`<<8`, `w6`=`(CC<<16)|0xffff`, `w10`/`w11`/`w12` = long
name / group / short name. Filter group = 6.

| param | descriptor | slot | CC |
|---|---|---|---|
| Filter Type | `0x401aa450` | **0x19** | 76 |
| Frequency | `0x401aa3b4` | **0x1a** | 74 |
| Resonance | `0x401aa41c` | **0x1b** | 75 |
| Env. Depth | `0x401aa554` | 0x1c | |
| Attack…Release | `0x401aa484..520` | 0x1d–0x20 | |
| Base | `0x401aa5bc` | 0x21 | 84 |
| Width | `0x401aa5f0` | 0x22 | 85 |
| Env. Delay | `0x401aa588` | 0x23 | |
| Sample-rate redux | `0x401aa624` | 0x24 | |

Sound block = `kit + 0x20 + t*0xa2`, slot `s` word at `+0x14 + 2s`.
**TYPE range field `0x401aa45c = 0x00000700`** (max 7), step `0x401aa460`.

## 2. TYPE names — SOLVED [S][L]

Formatter **`0x40065336`**: `value = arg2>>8`; 0..2 via table `0x4018d214`
(`"OFF","LP","HP"`), else `"EQ:%d"` (`0x401c6a8a`) with `value-2`. Its
`move.l #0x40065336,d0` immediate at **`0x401539b2`** = the rename site.
Stock UI list: `OFF / LP / HP / EQ:1 … EQ:5` = 0..7.

## 3. Runtime settings and smoothing [S]

- Engine load `0x40077282(ptr,voice)`: `0x800014f0+4*(305+v)=ptr`;
  `memcpy(0x80001502+106v, ptr+0x14, 0x6a)`; tail-jumps `0x400749cc` which
  re-copies the 53 words as `word<<16` to `0x80002b50+212v`. 8-voice wrapper
  `0x400772e6`.
- `0x4007725a(ptr,v)`: `0x800018bc+v = byte ptr[0x7e]` (machine byte).
- Smoothing `0x40074b9e` returns `d0 = 0x80002760`; per-block smoothed record at
  **`0x80002760 + 106v`**. **TYPE byte at `0x80002760 + t*0x6a + 0x44`** [L].

## 4. The render and the filter calls

Render ISR `FUN_40077420` (vector 191). Per block:

- **Multimode `0x400757fe`** at `0x40077fa6`, args
  `(0x80002760, 0x4199e466, d5, d7, 0x80001f18)` [S][L]. `0x80001f18+2v` =
  per-voice frequency (index<<8, 0..0x7f00) [L]; `0x4199e466` = class array
  from the machine byte. Inner loop v=0..7, state stride 0x5e, arg1 stride
  0x6a, ends `0x40076234`; writes output `0x4ba8f280` and DMA descs
  `0x80001200`/`0x80001204`.
- **Per-voice filter `0x40072844`** called at `0x400780c4` — see §6.

## 5. `0x400797d8` is preset (de)serialisation, NOT the live sanitizer [S]

Old note called `0x40079a60` a live sanitizer; it is inside `0x400797d8` (only
caller `0x4007f07a`, blob magic `0xbeefbace`, format 8). It expands a saved
sound blob into a runtime struct with per-field clamps (e.g. `a2@0x30 ←
a3@0x10`, rejected if `> 11` at `0x4007990e`). Relevant to persistence (§8).

## 6. THE INTEGRATION POINT — per-voice filter call [S][L]

The render's voice loop calls the stock per-voice filter through `a3`:

```
0x400780a4  lea 0x40072844,%a3     ; a3 = the target (digihealth rewrites this)
0x400780aa  movel d6,d0 ; lsll d2,d0 ; andl d4,d0
0x400780b2  movel d0,-(sp)          ; arg3 = active mask bit
0x400780b4  movel d2,d0 ; lsll #7,d0
0x400780ba  addil #0x80001a18,d0    ; buffer = 0x80001a18 + v*0x80  <- our jsr site
0x400780c0  movel d0,-(sp)          ; arg2 = buffer
0x400780c2  movel d3,-(sp)          ; arg1 = params = 0x800027a4 + v*0x6a
0x400780c4  jsr %a3@                ; arg4 (pushed first) = voice index
0x400780c6  addi.l #106,%d3         ; next voice
```

Function `0x40072844(params, buffer, active, voice)`:

| arg | value | meaning |
|---|---|---|
| params | `0x800027a4 + v*0x6a` | per-voice record; **byte 0 = TYPE** [L] |
| buffer | `0x80001a18 + v*0x80` | this voice's audio, **32 × int32**, in place |
| active | 0/1 | mask bit; the stock function ignores it |
| voice | 0..7 | voice == track for the checked tracks |

**Hook (1.0h).** digihealth 1.0 rewrites the `lea` at `0x400780a4` (its
profiling wrapper), so we must not touch it. We instead hook the free
instruction just before the call, **`0x400780ba`** (`addil #0x80001a18,%d0`,
`jsr` site; outside the FAST-AUDIO copied block) to `digifilter_dispatch`
(filter_glue.s). It does the displaced `add`, then per voice points `a3` at
`digifilter_filt` for `params[0]` in 8..11 and restores the original `a3` (the
digihealth wrapper, or the stock function) otherwise. `digifilter_filt`
(filter.c) runs our DSP for our types and tail-calls `0x40072844` for stock
types, so a profiling wrapper keeps seeing stock voices.

**Mode set:** **BP, BP2 (wider BP), COMB, TRASH** (TYPE 8..11). Notch/all-pass/
peak were dropped (the stock types already cover them); PHASER was dropped
(unstable/laggy) and replaced by TRASH, a second comb at half the delay.

**Controls [L]:** the params record (`params = 0x800027a4 + v*0x6a`) holds, per
word, `+0` TYPE, `+2` FREQ (index<<8), `+4` RESO, `+6` ENV DEPTH (bias 0x4000);
slot `s` at `params + 2s - 0x32`. FLTR encoders, wire code = channel+1:
A(1) ATK 0x1d, B(2) DEC 0x1e, C(3) SUS 0x1f, D(4) REL 0x20, E(5) FREQ 0x1a,
F(6) RESO 0x1b, G(7) TYPE 0x19, H(8) ENV DEPTH 0x1c. RESO also mirrors engine
settings slot 0x1b (`0x80001502 + 106v + 0x36`).

**Filter envelope [L]:** FREQ at `params@2` is the *base*; the envelope is added
by the stock filter (and now by ours), see §10.

**Smoothing:** SVF coefficients are computed at the block's two ends and ramped
across four 8-frame sub-blocks; COMB/TRASH use a fractional, per-sample-smoothed
delay + feedback, saturated, with the delay tapered to 3..255.

**Validated [L]:** BP 1.6%, BP2 2.2%, COMB 0.0% (`comb_gain`), TRASH matches a
div-2 comb; the real UI path engages; cutoff tracks encoder E (0.0% each step);
a stock TYPE is **byte-identical** to the stock firmware; modulation is smooth
(max sample-to-sample jump BP 0.076 A, COMB 0.45 A, TRASH 0.39 A on a 1-step/
block cutoff sweep); extremes (fi 0/127) stable.

**Cost [L]:** instructions per voice per render block — stock TYPE 1 ~2400,
BP/BP2 ~2800, COMB/TRASH ~1750.

## 7. The stock TYPE clamp (why the UI range alone is not enough) [L]

The raw TYPE byte is read each block at PC `0x40072fc8` and clamped:

```
0x40072fc8  mvsb %a0@,%d0      ; a0 = params+0x44 (TYPE)
0x40072fca  bges 0x40072fd0
0x40072fcc  clrl %d0
0x40072fce  bras 0x40072fd8
0x40072fd0  moveq #7,%d1       ; <-- max
0x40072fd2  cmpl %d0,%d1
0x40072fd4  bges 0x40072fd8
0x40072fd6  moveq #7,%d0
```

The clamped value is stored to `0x8000f1e4 + v*4` with flag `0x8000f1dc + v`.
So the widened UI range is silently clamped to 7 in the stock DSP. **Do not ship
`0x40072fd0` (`72 07` → `72 0b`) alone** — types 8..11 would then reach the
stock coefficient stage out of range. It is only needed if we route new types
through the stock EQ path (not the chosen §6 design).

## 8. Persistence — PASS (static) [S]

The sound serializer/deserializer tables `0x401ac1d4` / `0x401ac28c` are each a
**permutation of all 46 savable slots 0..45** (checked in the image), and the
deserializer `0x4007a236` copies them word-for-word (`movew` from the blob). So
slot 0x19 (TYPE) round-trips verbatim; there is no clamp in the load path. The
only clamps touching TYPE are elsewhere and do not affect the stored value:

- `0x40072fd0` (`moveq #7`) clamps the value only for the **stock DSP's** mode
  selection, and it writes a *separate* array (`0x8000f1e4+v*4`), not the kit;
  our hook reads the unclamped `params[0]`.
- the preset deserializer `0x400797d8` clamps one field at **11** (`0x4007990e`)
  — ≥ our maximum.

So TYPE 8..11 should survive save/reload. **Empirical confirmation pending:**
the save flow is the **PATTERN MENU (key 17) → "SAVE PATTERN TO PROJECT?"**
(string `0x401c4418`, handler around `0x4014d2cc`), followed by a YES confirm;
`tests/digiemu_filter_persist.py` drives a set/read pair around
`emu.portable --rebuild` but the menu sequence is not yet automated (a wrong
press can hit `CLEAR SEQUENCE`).

## 9. Open items

- **FREQ/RES response curve**: SOLVED (§10.4) — the FLTR page drawView is hooked
  and paints the BP/BP2/COMB/TRASH curves. Cosmetic only; audio is unaffected.
- **BP (TYPE 8) clips at some frequencies**: the SVF (`filter_dsp.s`) does not
  saturate its output (the comb does), so high RESO near the pass-band can run
  past full scale. A soft-clip in the kernel would fix it; for now document it
  (README "Known issues").
- **Empirical save/reload** of TYPE 8..11: the PATTERN MENU (key 17) →
  "SAVE PATTERN TO PROJECT?" (`0x401c4418`) + YES, then `emu.portable
  --rebuild`; static analysis says it round-trips (§8).
- Budget/coexistence with `digieq` etc. (our site is `0x400780ba`; Digi EQ owns
  `0x400721e6`).

## 10. Session 2: the filter envelope, the second page, cost, and the UI

Marked **[L]** where verified live in digiemu.

### 10.1 The filter envelope [L]

`0x40072844` builds the *modulated* cutoff as

```
cutoff(24.8) = (FREQ_word << 16) + envmod          ; clamped 0..0x7f000000
envmod       = ((-env_level) * ((ENV_word-0x4000) << 17)) >> 31   ; arithmetic
env_level    = *(int32*)(0x4199df58 + voice*12)
```

- `ENV_word` is `params@6`, biased 0x4000 (FLTR encoder H / slot 0x1c).
- `env_level` is the per-voice filter-envelope output. The envelope stage
  `0x40073304` (called each block from the render at `0x40078096`) walks 8
  voices: state at `0x4199df54 + v*12`, output at `0x4199df58 + v*12`. The stock
  filter reads it through the accessor `0x40073412(v)` (returns `*(v*12 +
  0x4199df58)`), and stores the raw `envmod` at `0x4399dad4 + v*4`.
- Fitted exactly (0 error) over live note data; `-env` is taken unsigned so
  `env = 0x80000000` (envelope start) gives `envmod = depth`.
- **Implemented** in `cutoff_index()` (filter.c). `fi = clamp((FREQ_word +
  (envmod>>16)) >> 8, 0, 127)`. Validated by `tests/digiemu_filter_env_mod.py`
  (BP, BP2, COMB; depth up/down and depth 0 control).

### 10.2 The second FLTR page: comb controls [L]

The render params record carries every slot; slot `s` is at `params + 2s -
0x32`. Turning the second page's knobs moves these words (Base 0x21 at `+0x10`,
Env Delay 0x23 at `+0x14`, ...). The stock filter uses them as Base / Width /
Env Delay / SRR, but for COMB/TRASH it does not run, so we reuse them:
Base = delay offset (`>>8` samples), Width = harmonics divider 1..4 (Width max
= 1), Env Delay = damping (one-pole on the feedback), SRR = feedback trim. The
stock defaults leave the comb unchanged. Validated by
`tests/digiemu_filter_comb2.py` (delay/harmonics vs `comb_gain`).

### 10.3 Cost [L]

Measured with a per-voice instruction counter around the dispatch
(`0x400780ba` → `0x400780c6`), per voice per block:

| TYPE | before | after |
|---|---|---|
| 1 (stock) | 2397 | 2397 |
| 8/9 BP/BP2 | 4200/— | 2811/2825 |
| 10/11 COMB/TRASH | 5604 | 1744 |

The wins: `mulsh` is `always_inline`; the comb's per-sample interpolation and
feedback each became a single 32×32 multiply (`(fp*diff)>>16 ==
((fp>>1)*((diff)>>13))>>2`; `(g*val)>>27 == ((g>>12)*(val>>11))>>4`); and
`svf_run` computes the coefficients at the block ends and ramps between them
(2 `mode_coef`/div55 instead of 4).

### 10.4 The response-curve UI (SOLVED) [S][L]

The FLTR page is a track-parameter page (SRC/FLTR/AMP/LFO share one view class).
The page-kind list is the view's `+124` vector with the index at `+144`; the
kind -> layout table is `0x400657b2` (20 x 44 bytes at RAM `0x4197cf88`, whose
`+8..` are the 8 knob descriptor ids). The FLTR page's layout is
`{ATK,DEC,SUS,REL,FREQ,RESO,TYPE,ENV}` = ids `{34,35,36,37,30,32,33,38}`
(descriptor ids, from the ROM table at `0x401a9d9c`), i.e. **kind 6** —
confirmed by reading the layout table out of a `gui.snap`.

The track-parameter view class vtable is **`0x40184290`**; its drawView (slot 4,
`+0x10`) is the data word at **`0x401842a0`** = **`0x400379ca`**. That drawView
dispatches on the page kind: kind 6 (FLTR) -> `0x4003774a`, kind 7 (AMP) ->
`0x40037564`, else the generic page body `0x40031802`. Inside the FLTR body the
FREQ/RES curve is drawn by `0x4003197e` (single call site `0x400378ae`).

**Implementation (mod `digifilter`):** the curve is now painted from core's
`ev_draw` event (see §11): `digifilter` subscribes `digifilter_draw` (order 40),
which walks the view controller's view list (the one drawAll iterates, sentinel
at ctrl+0x14, first node at ctrl+0x1c, view at node+8), takes the view whose kind
is 6, and reads the active track's TYPE/FREQ/RESO from the pattern's kit (the
TYPE slot word is `type<<8`). It then clears the stock graph interior (x 20..71)
and paints (see below), and clears the small TYPE box (x 78..92, same rows) and
draws a fixed mini version of the mode there. The stock page is left untouched
for stock types.

Curve rendering (the display depth scales with FREQ/RESO directly, so a knob
sweeps the whole range and clamps only at the extremes):

- **BP/BP2** — the SVF band-pass magnitude at FREQ/RESO in half-dB (the DSP's own
  `g`/`k` tables), with `k` scaled down (`*3/4` narrow, `*1/2` wide) so the bell
  is narrower than the DSP's as-drawn Q, and smoothed by three in-place
  `[1,2,1]/4` passes. The peak height comes from Q (deeper with RESO).
- **COMB** — the feedback comb magnitude `|1 / (1 - g·e^{-jwD})|` (a 256-entry
  Q15 cosine table + `log2`), so the teeth sharpen with RESO. The x-axis is
  logarithmic, so a literal harmonic comb crams every tooth into the top octave;
  the teeth are laid out **evenly across the display**, their spacing from FREQ
  with **no dead zone** (the step is capped so they stay a pixel apart).
- **TRASH** — the same, denser (its own series) with a lower feedback.

Every curve is **tapered towards the floor at both box edges**, so it never ends
in a vertical "brickwall".

Earlier the curve finder (`digiemu_filter_curve_find.py`) ruled out writing the
DSP's coefficient RAM; the resolution is the event handler here, not the RAM.
Validated live by `tests/digiemu_filter_curve.py` (the graph pixels change for the
new modes, and BP and COMB draw different shapes).

**Caveat — the drawView vtable slot is shared with the `ev_draw` event (see
§11).** Patching the `0x401842a0` slot with `op:ptr` worked in single-mod builds
but was lost in multi-mod builds: it is the drawView slot of the shared
track-parameter page view class and core's `ev_draw` dispatcher owns it whenever
any mod subscribes to that event. Subscribing to `ev_draw` (done in 1.0i) instead
of patching the slot composes with the event chain.

---

## 11. Multi-mod build: the FLTR curve slot is overwritten by the `ev_draw` event [S]

**Finding (04/10).** The user flashed `ULTITAKT-2.XX.syx` (a 9-mod combined
build) and the FLTR curve was still stock, even though the syx *does* contain our
`digifilter` 1.0i (sha256 `17b7bc76…`, same as `out/digifilter-1.0i.elemod`).

The main OS image in that `.syx` (section id 3, decoded length 2526532, base
`0x40000400`) has:

| address | meaning | bytes found | expected (ours) |
|---|---|---|---|
| `0x401aa45c` | TYPE range | `00000b00` | `00000b00` ✓ |
| `0x401539b2` | TYPE name fmt ptr | `47be2cc0` | `47be2cc0` ✓ (digifilter_typefmt) |
| `0x400780ba` | per-voice filter call | `4eb947be2d18` | ✓ (digifilter_dispatch) |
| `0x401842a0` | **FLTR drawView ptr** | **`47be3892`** | `47be168a` ✗ |

- `digifilter_fltrdraw` in that linked build = `0x47be168a` (from the build's
  `.map.json`), but the slot holds `0x47be3892`.
- `0x47be3892` falls **inside `digimatrix_draw`** (`0x47be3620` … `0x47be39ac`),
  i.e. the slot was overwritten with a `digimatrix` function, not ours.

Why: `0x401842a0` is the drawView slot of the shared track-parameter page view
class. Core's **event system** installs its `ev_draw` dispatcher trampoline into
this slot whenever a mod subscribes to `ev_draw`. In `ULTITAKT`, `digimatrix`
(and one more mod) subscribe to `ev_draw` — the sidecar `.json` shows
`link.tables.ev_draw`: `at 0x47bea3bc`, **`entries: 2`** — so core's trampoline
owns the slot, and our raw `op:ptr` patch of the same address is lost. Single-mod
and 2-mod test builds don't trigger it, which is why `tests/digiemu_filter_curve.py`
passes but the device shows the stock curve.

**Fix (implemented, 1.0i):** stop patching `0x401842a0` with `op:ptr`. Instead
`digifilter` subscribes to `ev_draw` (`digifilter_draw`, order 40, like
`digimatrix_draw`) and paints the curve from that handler: it walks the view
controller's view list to the view whose page kind is 6, and draws when the
active TYPE is 8..11. The `0x401842a0` site is gone (3 sites now). This composes
with the event chain instead of fighting it; `elekloader.lint` reports the
combined `core + digifilter + digimatrix` set still links with no overlap, and
the title-page curve test passes on that combined build.
