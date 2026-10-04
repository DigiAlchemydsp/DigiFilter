# DigiFilter — handoff (session 2)

Per-track filter modes for the **Digitakt mk1, OS 1.53**: `BP`, `BP2`, `COMB`,
`TRASH` (TYPE 8–11). Audio path was already implemented and validated as 1.0h;
this session covers three open asks plus one addition:

1. the **filter envelope** must affect the new modes — **DONE, validated**;
2. the DSP must be **cheaper (CPU)** without stepping/clicks — **DONE**
   (COMB/TRASH now cheaper than the stock filter);
3. the FLTR page **FREQ/RES response curve** UI must reflect the new types —
   **DONE** (the page drawView is hooked; see §3);
4. *(added)* more controls on the **second FLTR page** (comb delay/harmonics)
   — **DONE, validated**.

Build/lint/patch pass (`BUILT`, `OK: links as core 2.1`, `OK: the mods
combine`). The `filter.c` changes are §1 (envelope), §2 (CPU) and §4 (second
page). The authoritative technical write-up is RE_NOTES.md §10.

---

## 0. Environment (all present on this machine)

| what | where |
|---|---|
| elekloader checkout | `C:\Users\benan\Music\ELEKTRON\elekloader` |
| core 2.1 mod | `...\elekloader\mods\core\out\core-2.1.elemod` |
| digiemu source | `C:\Users\benan\Music\ELEKTRON\digiemu-main` |
| m68k toolchain | `C:\SysGCC\m68k-elf\bin` |
| stock OS 1.53 | `...\digiemu-main\portable\firmware\dt1-1.53-9bdd44bb\Digitakt_OS1.53.syx` |
| digi toolchain cache of the image | `%TEMP%\digifilter-dt153.bin` (from `tools/disas.py`) |

Build shell (PowerShell):

```powershell
$env:PATH = "C:\SysGCC\m68k-elf\bin;" + $env:PATH
$env:ELEKLOADER_CROSS = "m68k-elf-"
$env:PYTHONPATH = "C:\Users\benan\Music\ELEKTRON\elekloader"
$stock = "C:\Users\benan\Music\ELEKTRON\digiemu-main\portable\firmware\dt1-1.53-9bdd44bb\Digitakt_OS1.53.syx"
$core  = "C:\Users\benan\Music\ELEKTRON\elekloader\mods\core\out\core-2.1.elemod"
python -m elekloader.sdk.build . --stock $stock
python -m elekloader.lint out\digifilter-1.0h.elemod --stock $stock --with $core
python -m elekloader.patch --stock $stock --mod $core --mod out\digifilter-1.0h.elemod `
    --out "$env:TEMP\opencode\df-custom.syx" --version 2.0t
```

Last run (verified this session): `BUILT`; `OK: links as core 2.1 …`;
`OK: the mods combine`; RAM 13320 / 131072.

### Emulator

The **patched Unicorn** is required. It was installed this session from the
frozen app:

```
copy C:\Users\benan\Downloads\digiemu-win64-0.2.0\digiemu\_internal\unicorn\lib\unicorn.dll
  -> C:\Users\benan\AppData\Local\Programs\Python\Python312\Lib\site-packages\unicorn\lib\unicorn.dll
```

The stock DLL was backed up as `unicorn.dll.stock.bak` beside it. Verify with
`python -m emu.unicorn_compat` → `"compatible": true`.

A digiemu firmware with **core 2.1 + digifilter 1.0h** was set up as
**`dt1-2.0t-e40c4615`**:

```powershell
python -m emu.portable --add "$env:TEMP\opencode\df-custom.syx" --yes   # from digiemu-main
```

`python -m emu.portable --list` lists it. The `/gui` tests take
`--digiemu C:\Users\benan\Music\ELEKTRON\digiemu-main --fw dt1-2.0t-e40c4615`.

**Rebuild flow after any code change:** re-run `sdk.build` + `patch`
(to `%TEMP%\opencode\df-custom.syx`) and `emu.portable --add … --yes`
(it makes a *new* folder named by the new hash), then point the tests at it.

---

## 1. Filter envelope does not affect the new modes — FIXED & VALIDATED

> **RESOLVED.** The exact formula was pinned (see below) and implemented in
> `filter.c`'s `cutoff_index()`; `tests/digiemu_filter_env_mod.py` passes for
> BP, BP2 and COMB (depth up/down, and a depth-0 control). The section is kept
> for the derivation.

### The parameter record (measured live, not guessed)

The per-voice record the render passes to the stock filter is
`params = 0x800027a4 + v*0x6a` (`= 0x80002760 + v*0x6a + 0x44`). Measured by
turning each FLTR encoder and reading the words:

| offset | field | note |
|---|---|---|
| byte `+0` | **TYPE** | `params[0]` |
| word `+2` | **FREQ** (base cutoff) | `index<<8`, low byte is smoothing fraction |
| word `+4` | **RESO** | mirrors the engine settings slot `0x1b` |
| word `+6` | **ENV DEPTH** | biased: `0x4000` = 0, `0x7f00` = max, `0x0000` = min |

FLTR encoder map (rotation code = wire channel + 1; `encoder_channel = code-1`):

| code | knob | slot |
|---|---|---|
| 1 | A | `0x1d` ATK |
| 2 | B | `0x1e` DEC |
| 3 | C | `0x1f` SUS |
| 4 | D | `0x20` REL |
| 5 | E | `0x1a` FREQ |
| 6 | F | `0x1b` RESO |
| 7 | G | `0x19` TYPE |
| 8 | H | `0x1c` ENV DEPTH |

> `filter.c` reads RESO from the engine slot `0x80001502+106v+2*0x1b`; that also
> tracks encoder F, so it works, but `params+4` is the direct render copy.

### What the stock filter does with ENV DEPTH

`0x40072844` (the stock per-voice filter) computes the **modulated cutoff**:

```
cutoff(24.8) = (FREQ_word << 16) + envmod            ; clamped 0 .. 0x7f000000
envmod       = MSAC(envelope_level[voice], (ENV_word - 0x4000) << 17)   ; MACSR 0xa0
envelope_level[voice] = *(int32*)(0x4199df58 + voice*12)
```

- `0x4199df58 + v*12` is the **filter-envelope output**, produced every block
  by the envelope stage `0x40073304` (called from the render at `0x40078096`,
  before the per-voice filter loop). The state word for voice *v* is at
  `0x4199df54 + v*12` (stride 12, output at +4).
- The accessor used by the stock filter is `0x40073412(v)`:
  `return *(int32*)(0x4199df58 + v*12)` (disassembly: `arg*12 + 0x4199df58`).
- The stock filter also stores the raw `envmod` at `0x4399dad4 + v*4`
  (written `0x400728ba`, read back at `0x40078296`).
- The envelope stage's per-voice source record `a2` has envelope fields at
  `+0x4c, +0x4e, +0x50, +0x52, +0x58`; tables at `0x4018f244/0x4018f444/0x4018f644`.

`digifilter_filt` (filter.c) reads only `params@2` (base FREQ) and never adds
`envmod`, so **the filter envelope is simply ignored for TYPE 8–11**. That is
the reported bug.

### The exact fixed-point (RESOLVED)

`MSAC` computes `ACC = ACC - (Rx*Ry)` in the stock filter's setup, so with
`ACC = 0` the result is `-(env * depth)` and the `env` sign flips. `df_cutfit.py`
(lowering FREQ so the cutoff does not clamp, forcing the depth) fitted it
exactly:

```
envmod = ((-env) * ((ENV_word - 0x4000) << 17)) >> 31     ; arithmetic (floor)
       = mulsh((int32)(0u - (uint32)env), depth, 31)
```

`env` is the signed level at `0x4199df58 + v*12` (e.g. `0x80000000` at the note
start), so a positive ENV depth opens the cutoff at the attack and closes it as
the envelope decays. Implemented in `cutoff_index()`:

```c
int base = PARAM_CUTOFF(params);                       /* FREQ index<<8 */
int depth = (PARAM_ENV(params) - 0x4000) << 17;
if (depth) base += mulsh((int32)(0u - (uint32)ENV_LEVEL(v)), depth, 31) >> 16;
return clampi(base >> 8, 0, 127);
```

Validated by `tests/digiemu_filter_env_mod.py` (BP/BP2/COMB; depth up, depth
down, and a depth-0 control).

> Note: `commit()`, `digifilter_live` and `digifilter_voice()` in `filter.c`
> are **dead code for audio** — only `digifilter_filt` runs, from the
> `0x400780ba` site. They are only relevant if the UI curve is made to read
> them.

---

## 2. CPU cost — DONE (no downsampling needed)

Measured with a per-voice instruction counter around the dispatch
(`0x400780ba` → `0x400780c6`), per voice per render block:

| TYPE | before | after |
|---|---|---|
| 1 (stock) | 2397 | 2397 |
| 8/9 BP/BP2 | 4200 | 2811/2825 |
| 10/11 COMB/TRASH | 5604 | ~1745 |

Changes (all in `filter.c`; `filter_dsp.s` unchanged):

1. `mulsh` is `always_inline` (it was a real `jsr` in the hot loop).
2. `comb_run()`: the per-sample interpolation and feedback each became a single
   32×32 multiply, replacing two `mulsh` calls:
   `(fp*diff)>>16 == ((fp>>1)*((diff)>>13))>>2` and
   `(g*val)>>27 == ((g>>12)*(val>>11))>>4` (safe: each factor < 2^15/2^16).
3. `svf_run()`: compute the coefficients at the block's two ends and ramp
   between them (2 `mode_coef`/div55, was 4).

Smoothness was re-checked with `tests/digiemu_filter_mod.py` (BP 0.076 A, COMB
0.45 A, TRASH 0.39 A max sample jump). No downsampling was necessary; it remains
an option if a future change raises the cost.

Not done / possible later: `commit()` still runs on every `ev_tick` building the
now-unused `sets` (negligible, UI-rate); `div55` could still become a table.
The `active` argument is not usable as a "voice sounding" gate (0 in normal
playback).

---

## 3. FLTR response-curve UI — DONE

The track-parameter page view class vtable is `0x40184290`; its drawView slot
(`+0x10`) is the data word at `0x401842a0` = `0x400379ca`, the page drawView
that dispatches on the page kind (6 = FLTR -> `0x4003774a`, 7 = AMP ->
`0x40037564`, else the generic body `0x40031802`). Earlier the mod pointed
`0x401842a0` at `digifilter_fltrdraw` (filter_ui.c). **1.0i replaces this**: the
site is dropped (3 sites now) and the curve is painted from a core `ev_draw`
subscription (`digifilter_draw`, order 40) — it walks the view controller's view
list to the kind-6 view and paints when the active TYPE is 8..11. See §3.1.

The FLTR page kind is **6** (its layout at RAM `0x4197cf88` + 6*44 is the
`{ATK,DEC,SUS,REL,FREQ,RESO,TYPE,ENV}` descriptor-id set). The curve shapes are
the same as the DSP (filter_tables.h): BP/BP2 a band-pass bell at FREQ/RESO,
COMB/TRASH comb teeth. Validated live by `tests/digiemu_filter_curve.py`.

(The curve finder `digiemu_filter_curve_find.py` had ruled out writing the DSP
coefficient RAM; the resolution is the event handler, not the RAM.)

### 3.1 Multi-mod builds broke the vtable hook — FIXED (1.0i)

The user flashed a 9-mod combined firmware (`Custom Firm\TESTING\ULTITAKT-2.XX.syx`)
and the FLTR curve was **still stock**, despite that syx containing our own
`digifilter` 1.0i (elemod sha256 `17b7bc76…`, identical to `out/digifilter-1.0i.elemod`).

Decoding the syx main OS (section 3, `0x40000400`+) showed **three of our four
sites applied, but not the drawView slot**:

| addr | ours | ULTITAKT |
|---|---|---|
| `0x401aa45c` TYPE range | `00000b00` | `00000b00` ✓ |
| `0x401539b2` name fmt | `digifilter_typefmt` | `47be2cc0` ✓ |
| `0x400780ba` filter call | `digifilter_dispatch` | `47be2d18` ✓ |
| `0x401842a0` **FLTR drawView** | `digifilter_fltrdraw` (`0x47be168a`) | **`0x47be3892`** ✗ |

`0x47be3892` lies inside **`digimatrix_draw`** (`0x47be3620..0x47be39ac`). Cause:
`0x401842a0` is also the slot core's `ev_draw` dispatcher trampoline lives in;
`ULTITAKT`'s `link.tables.ev_draw` has **`entries: 2`** (digimatrix + another mod
subscribe to `ev_draw`), so core owns that slot and our raw `op:ptr` patch is lost.
Our 1-/2-mod digiemu test builds never triggered it, hence the passing test.

**Fix (done):** `digifilter` now subscribes to `ev_draw` (`digifilter_draw`,
order 40, like `digimatrix_draw`) and paints the curve from the handler (guard:
page kind 6, TYPE 8..11), and the `0x401842a0` `op:ptr` site is dropped. This
composes with the event chain instead of overwriting it. Verified: the combined
`core + digifilter + digimatrix` syx links with no overlap and the curve test
passes on it. (A latent bug was also found and fixed: the curve's TYPE slot word
is `type<<8`, and `read_track` had compared the raw word, so no curve was ever
painted — including under the old vtable hook.)

---

## 4. Second FLTR page — comb controls — DONE & VALIDATED

> **Implemented** in `filter.c` (`comb_run` + `digifilter_filt`) and validated
> with `tests/digiemu_filter_comb2.py`. Mapping below; defaults preserve the
> old comb exactly.

Today COMB/TRASH are one-knob: delay/pitch from **FREQ** and feedback from
**RESO**. The **second FLTR page** (FLTR pressed again) is 5 knobs, slots
`0x21..0x25`, which the stock filter uses as Base / Width / Env Delay / SRR
(+one). For our types the stock filter does not run, so those slots are free.
`params + 2s - 0x32` gives the render word (verified live; Base 0x21 at `+0x10`,
Env Delay 0x23 at `+0x14`, ...).

Implemented mapping (stock defaults preserve the old comb exactly):

| slot | stock name | new meaning | default → behaviour |
|---|---|---|---|
| `0x21` | Base | **delay offset** (coarse) | 0 → none (`>>8` samples) |
| `0x22` | Width | **harmonics** (delay divider 1..4) | max → 1 (none) |
| `0x23` | Env Delay | **damping** (one-pole on the feedback) | 0 → off |
| `0x24` | SRR | **feedback trim** (toward self-oscillation) | 0 → none |
| `0x25` | — | spare | — |

`comb_run()` grew `dly_off/hdiv/damp/fbtrim` parameters; `digifilter_filt` reads
them from the render record. Storage: reuse the saved slots `0x21..0x24`, so it
round-trips with the kit. Not yet wired to the UI (the DSP reinterprets the
values; the second page still shows the stock `Base/Width/...` labels) — adding
a knob listener (`digifilter_enc`) to relabel/clamp is optional polish.
Validated by `tests/digiemu_filter_comb2.py` (delay + harmonics vs `comb_gain`).

---

## 5. Diagnostics written this session (in `%TEMP%\opencode\`, not committed)

| file | what it does |
|---|---|
| `df_encmap.py` | turns encoders 1..8 and maps each to kit slots + live `params@2/4/6` + engine reso |
| `df_envdiag.py` | retriggers a voice and watches `params@2/6` |
| `df_envsrc.py` | reads `0x4199df58+0..8` at the filter call |
| `df_stockenv.py` | hooks `0x400728a8`, reads accessor return `d0` and the source memory |
| `df_envformula.py` | hooks `0x400728b8`, compares the firmware's `envmod` to `fractmul(env, depth)` |
| `df_cutfit.py` | hooks `0x400728f0`, reads the final modulated cutoff `d1`, fits the formula — **run this next** |

Run pattern:

```powershell
python "$env:TEMP\opencode\df_cutfit.py" --digiemu C:\Users\benan\Music\ELEKTRON\digiemu-main --fw dt1-2.0t-e40c4615
```

(Filter the noisy `[gui] input --feed` lines out; each run is ~1–3 min.)

## 6. Where things stand / next

Done this session (all validated live):

1. ENV modulation — `tests/digiemu_filter_env_mod.py` (BP/BP2/COMB, depth up,
   depth down, depth 0).
2. CPU — COMB/TRASH 5604 → ~1745, BP/BP2 4200 → ~2800; `tests/digiemu_filter_mod.py`
   still smooth.
3. Second FLTR page comb controls — `tests/digiemu_filter_comb2.py`.
4. FLTR curve UI — core `ev_draw` handler + `tests/digiemu_filter_curve.py`
   (see §3). Fixed for multi-mod builds in 1.0i (§3.1 / RE_NOTES.md §11):
   the `0x401842a0` site is dropped, `digifilter_draw` subscribes to `ev_draw`.
   Also fixed a latent bug where the kit TYPE word (`type<<8`) was compared raw,
   so no curve had ever actually been painted.

Regression on the latest firmware: `digiemu_filter_dsp.py` (BP/BP2/COMB/TRASH),
`digiemu_filter_cutoff.py`, `digiemu_filter_mod.py` (BP/COMB/TRASH),
`digiemu_filter_real.py` — all PASS.

Still open:

1. **BP (TYPE 8) can clip** at some frequencies (no SVF output saturation);
   documented in README "Known issues".
2. Optional: relabel the second page's knobs for COMB/TRASH via `digifilter_enc`;
   remove the now-unused `commit()`/`digifilter_voice()` path.
3. Optional: the empirical save/reload of TYPE 8..11.
4. Optional: the comb curve in `filter_ui.c` is flat at RESO 0 (COMB and TRASH
   look identical); give `comb_db2` a resonance-independent tooth envelope.

Version bumped to **1.0i** for the release; latest tested firmware in digiemu:
`dt1-2.0t-719c50b0` (core 2.1 + digimatrix 1.0b + digifilter 1.0i, multi-mod).
