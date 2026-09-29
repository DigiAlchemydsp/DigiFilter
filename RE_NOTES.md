# Reverse-engineering notes (per-track `digifilter`)

**Device: Digitakt mk1, OS 1.53 only.** Image = stock main OS at `0x40000400`,
len 2475584, sha256 `4b47a950…c5df` (`.syx` sha256 `9bdd44bb…`).

Marks: **[S]** static (image bytes), **[L]** verified live in digiemu
(`C:\Users\benan\Music\ELEKTRON\digiemu-main`, setup in HANDOFF §1).

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

```
0x400780a4  lea 0x40072844,%a3     ; stock bytes 47 f9 40 07 28 44  <- ptr site
0x400780aa  movel d6,d0 ; lsll d2,d0 ; andl d4,d0
0x400780b2  movel d0,-(sp)          ; arg3 = active mask bit
0x400780b4  movel d2,d0 ; lsll #7,d0 ; addi.l #0x80001a18,d0
0x400780c0  movel d0,-(sp)          ; arg2 = buffer = 0x80001a18 + v*0x80
0x400780c2  movel d3,-(sp)          ; arg1 = params = 0x800027a4 + v*0x6a
0x400780c4  jsr %a3@                ; arg4 (pushed first) = voice index
0x400780c6  addi.l #106,%d3         ; next voice
```

Function `0x40072844(params, buffer, active, voice)`:

| arg | value | meaning |
|---|---|---|
| params | `0x800027a4 + v*0x6a` | per-voice record; **byte 0 = TYPE** [L] |
| buffer | `0x80001a18 + v*0x80` | this voice's audio, **32 × int32**, in place |
| active | 0/1 | voice-sounding mask |
| voice | 0..7 | voice == track for the checked tracks |

The function computes a general biquad (coeffs `0x8000f584 + v*0x20`, state
`0x8000f3c4 + v*0x20`, plus `0x8000f5a4 + v*8`) and applies it to the 32-frame
buffer (`moveq #32` loop at `0x40072e50`). It reads TYPE from
`0x8000f1e4[v]` at `0x40072904..` and dispatches (`==4/5/6/7` special, else EQ
path at `0x40072b2a`; types `>7` skip the coefficient computation to
`0x40072d6a`).

**Hook design:** patch the `lea` at **`0x400780a4`** (`ptr` → `digifilter_filt`,
outside the FAST-AUDIO copied block). `digifilter_filt(params, buffer, active,
voice)`:

1. `active == 0` or `TYPE < 8` or `TYPE > 11` → `jmp 0x40072844`;
2. else `digifilter_svf(buffer, 32, coef, state)` for `TYPE-8` with coefficients
   from the track's FREQ/RESO; `rts`.

This reads TYPE 8..11 directly from `params[0]`, so **no clamp patch is needed**
and there is no audio-buffer RE left to do.

**Mode set [owner, 2026-09-29]:** notch/all-pass/peak are dropped (the stock
types already cover them); the four slots are **BP, BP2 (wider BP), COMB,
PHASER**. BP/BP2 are the SVF band-pass (BP2 takes `k` from `K27[qi>>1]`); COMB
is a feedback comb (`COMB_DELAY[fi]` samples, feedback `qi/16`); PHASER is four
first-order all-pass stages (`a=(1-g)/(1+g)`, depth `qi/16`).

**Validated [L]** (`tests/digiemu_filter_dsp.py`, custom firmware
`dt1-2.0t-2af35ba1`): forcing the call args and injecting a 1500 Hz tone, BP
matches `svf_block` 1.6%, BP2 2.2%, COMB matches `comb_gain` 0.0%, PHASER
matches `phaser_gain` 0.4%; RESO tracks the model across qi 0..12; a stock TYPE
(1) is **byte-identical** to the stock firmware. FREQ from `0x80001f18+2v>>8`;
**RESO from the engine settings slot 0x1b** (`0x80001502+106v+0x36`, `>>11` ->
qi 0..15); buffer `0x80001a18+v*0x80`, 32 frames.

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

- **RESO mapping**: `qi = (engine RESO slot 0x1b) >> 8` → 0..127 scaled to the
  16-step `K27`/`qi` 0..15 (currently `>>8` then clamp 0..15, i.e. `qi=reso/8`
  with the extra bits dropped). Want a sweep that logs the RESO slot against the
  audible Q to fit `qi` properly (FREQ is settled: `0x80001f18+2v >> 8`).
- **COMB/PHASER params**: delay/pitch from FREQ and feedback/depth from RESO are
  first-cut; decide whether a different control (e.g. Base/Width) should drive
  them.
- Whether the mk1 FLTR page draws any type graphic (none found so far).
- Budget/coexistence with `digieq` etc. (site `0x400780a4`; Digi EQ owns
  `0x400721e6`).
