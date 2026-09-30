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

- **FREQ/RES response curve**: the FLTR page graph still draws the stock shapes
  for TYPE 8..11. It is drawn by page UI code from UI-model state, not from the
  filter RAM: `tests/digiemu_filter_curve_find.py` shows every read of the
  coefficient/state/clamped-type RAM (`0x8000f1dc`/`0x8000f584`/`0x8000f3a4`)
  comes from the **DSP** region (`0x40072xxx`), not from UI code. See §10 for
  the UI map gathered so far. Cosmetic.
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

### 10.4 The response-curve UI (still open)

From `digi1_mods` "TECHNICAL_NOTES": the track parameter pages are a page view
whose current page is a *kind*; the kind → layout table is `0x400657b2`
(20 × 44 bytes at RAM `0x4197cf88`; `+8..` are the knobs' descriptor indices).
The view's draw dispatches on the kind (e.g. the TRIG view's draw `0x400368ba`
asks kind == 15 for the piano-roll, else `0x40031802`). The FLTR page has its
own kind and a draw that paints the response curve; the curve code clamps the
type to the stock `EQ:5`. Finding that draw (and either feeding it coefficients
for our modes or painting our own curve) is the remaining work. The curve
finder test's result (all RAM readers are DSP code) rules out simply writing the
coefficient tables.
