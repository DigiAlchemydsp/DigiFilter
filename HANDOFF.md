# DigiFilter — handoff

Per-track filter modes for the **Digitakt mk1, OS 1.53 only**: `BP`, `BP2`,
`COMB`, `TRASH` (TYPE 8–11), as an elekloader format-2 mod (`id: digifilter`).
Deep reverse-engineering is in [RE_NOTES.md](RE_NOTES.md); build steps are in
[README.md](README.md).

**Status: 1.0h — implemented and validated in digiemu; no site overlaps
(digifilter + core 2.1 + digihealth 1.0 combine cleanly).**

## Current build

- `mod.json` — id `digifilter`, version `1.0h`, `device: digitakt-mk1`,
  `os: 1.53`, `requires: [core]`, `subscribe ev_tick`.
- 3 sites:

| addr | stock | op | target | effect |
|---|---|---|---|---|
| `0x401aa45c` | `00000700` | `bytes` | `00000b00` | Filter Type range max 7 → 11 |
| `0x401539b2` | `40065336` | `ptr` | `digifilter_typefmt` | TYPE labels print `BP / BP2 / COMB / TRASH` for ≥8 |
| `0x400780ba` | `068080001a18` | `jsr` | `digifilter_dispatch` | per-voice: run our DSP for TYPE 8–11, else the stock filter |

Build result: `.run` 2956, `.bss` 8984, RAM 19016 of 131072 with core 2.1 +
digihealth.

## Build / test / run

```powershell
$env:PATH = "C:\SysGCC\m68k-elf\bin;" + $env:PATH
$env:ELEKLOADER_CROSS = "m68k-elf-"
$env:PYTHONPATH = "<elekloader checkout>"
$stock = "<Digitakt_OS1.53.syx>"
$core  = "<elekloader>\mods\core\out\core-2.1.elemod"

python -m elekloader.sdk.build . --stock $stock
python -m elekloader.lint out\digifilter-1.0h.elemod --stock $stock --with $core
python -m elekloader.patch --stock $stock --mod $core --mod out\digifilter-1.0h.elemod `
    --out custom.syx --version 2.0t --check
```

Must print `BUILT`, `OK: links as core 2.1 …`, `OK: the mods combine`.

## The integration point

The render's per-voice loop calls the stock filter `0x40072844(params, buffer,
active, voice)` through `a3` (set by `lea 0x40072844,%a3` at `0x400780a4`), with
`params = 0x800027a4 + v*0x6a` (byte 0 = TYPE) and `buffer = 0x80001a18 + v*0x80`
(32 int32 frames).

digihealth 1.0 rewrites `0x400780a4` (its profiling wrapper), so DigiFilter must
not touch it. Instead we hook the *free* 6-byte instruction just before the call,
`0x400780ba` (`addil #0x80001a18,%d0`), with `jsr digifilter_dispatch`.
`digifilter_dispatch` (in `filter_glue.s`):

- does that instruction's work (`d0 += 0x80001a18`);
- keeps `a3` = `digifilter_filt` only for `params[0]` in 8..11;
- restores the original `a3` (digihealth's wrapper, or `0x40072844`) otherwise.

So digihealth keeps profiling stock voices, and neither mod overlaps the other.

`digifilter_filt` (filter.c) reads TYPE / cutoff / reso, dispatches, and
tail-calls `0x40072844` for stock TYPE.

## Controls (verified live)

- **CUTOFF** = `params@2` (word = FREQ index<<8) — tracks FLTR **encoder E** and
  is **envelope-modulated** (the render smooths base+env into it).
- **RESO** = engine settings slot `0x1b` (`0x80001502 + 106*v + 0x36`) — FLTR
  encoder F; mapped to `qi` 0..15.
- **TYPE** = FLTR encoder G.

## DSP and smoothing

- **BP/BP2**: trapezoidal state-variable filter (`filter_dsp.s`, EMAC), driven
  by `mode_coef`; BP2 uses `K27[qi>>1]`. Coefficients ramp from the previous
  block across four 8-frame sub-blocks (`svf_run`).
- **COMB/TRASH**: feedback comb `y = x + g*y[n-D]`, `D = COMB_DELAY[fi]/div`
  (COMB div 1, TRASH div 2), `g = qi/16`. Fractional delay (power-of-two buffer)
  with per-sample smoothed delay + feedback, saturated output, delay tapered to
  3..255.
- Integer-only, no libgcc (`mulsh`, `div55`).

## Emulator (digiemu) setup

A source checkout is required (`emu/gui.py` etc.). The patched Unicorn can be
taken from the frozen app: copy
`digiemu-win64-*/_internal/unicorn/lib/unicorn.dll` over a venv's
`site-packages/unicorn/lib/unicorn.dll` (`unicorn==2.1.4`, `capstone==5.0.7`),
then `python -m emu.unicorn_compat` must print `compatible: true`. Set up the
firmware once with `python -m emu.portable --add Digitakt_OS1.53.syx --yes`.
Full details in RE_NOTES.md.

## Validation (1.0h)

`tests/digiemu_filter_dsp.py` (forced args, injected 1500 Hz tone, vs
`tests/filter_model.py`):

| TYPE | mode | model vs DSP |
|---|---|---|
| 8 | BP | 0.20285 vs 0.19967 (1.6%) |
| 9 | BP2 | 0.44823 vs 0.43850 (2.2%) |
| 10 | COMB | 0.78262 vs 0.78241 (0.0%) |
| 11 | TRASH | comb at div 2, matches |

Also: real UI path engages; cutoff tracks encoder E (0.0% at each step); stock
TYPE 1 is byte-identical to the stock firmware; modulation is smooth
(`tests/digiemu_filter_mod.py`: BP 0.073 A, COMB 0.45 A, TRASH 0.39 A max
sample-to-sample jump on a 1-step/block cutoff sweep); extremes (fi 0/127)
stable.

## Known open item

The FLTR page's **FREQ/RES response curve** still only tracks up to EQ:5. It is
drawn by page UI code from UI-model state, not from any filter RAM we can read
(see RE_NOTES "response curve"), so it needs a UI-framework trace to extend.
Cosmetic; audio is unaffected.

## Quick address index

See RE_NOTES.md §"Quick index". Key ones: render ISR `0x40077420`; stock
per-voice filter `0x40072844`; our dispatch site `0x400780ba`; TYPE raw byte
`0x80002760 + t*0x6a + 0x44`; TYPE descriptor `0x401aa450` (range `0x401aa45c`);
TYPE label formatter `0x40065336` (ptr immediate `0x401539b2`).
