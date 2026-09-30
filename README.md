# DigiFilter

**Work in progress (WIP).** Extra per-track filter modes for the Elektron
Digitakt mk1 (OS 1.53).

A format-2 [elekloader](https://github.com/irpina/elekloader) mod, id
`digifilter`. It adds four filter types on top of the stock `OFF / LP / HP /
EQ:1..5`:

| TYPE | mode | what it is |
|---|---|---|
| 8 | **BP** | band pass (state-variable filter) |
| 9 | **BP2** | a wider band pass (about half the resonance) |
| 10 | **COMB** | feedback comb, delay from FREQ, feedback from RESO |
| 11 | **TRASH** | second comb at half the delay (a higher harmonic series) |

Each mode runs per track and uses that track's own FREQ, RESO and filter
envelope, exactly like the stock types. Stock TYPE values keep running the
stock filter — nothing here reimplements a stock mode.

> Digitakt **mk1 only**. Digitakt II's filter machines are out of scope.

## Status

The **audio path is done and validated** (BP / BP2 / COMB / TRASH), including
the **filter envelope** and the **second FLTR page's comb controls** (delay,
harmonics, damping, feedback trim), and the DSP is **budgeted at or below the
stock filter's cost** per voice per block. The one remaining gap is cosmetic:
the FLTR page's FREQ/RES **response curve** still draws the stock shapes for
TYPE 8–11. The graph is drawn by page UI code from UI-model state (not from the
filter RAM), so extending it is still open work. See
[RE_NOTES.md](RE_NOTES.md) "Open items".

Everything in this repo builds (`BUILT`), lints against `core` and combines with
`digihealth` (`OK: the mods combine`).

## Known issues

- **BP (TYPE 8) can clip at some frequencies.** The band-pass SVF has no output
  saturation (the comb does), so with high RESO near the pass-band the output
  can exceed full scale. Back off RESO/ENV depth or use BP2. (Tracked for a
  soft-clip in the SVF.)
- **Response curve** (above) still shows the stock shapes for TYPE 8–11.

## Controls

- **FREQ (E)** sets the cutoff / comb pitch; **RESO (F)** the resonance /
  comb feedback; the **filter envelope (H + ADSR)** modulates the cutoff exactly
  as the stock types do.
- **Second FLTR page**, while TYPE is COMB or TRASH, reuses the stock knobs:
  **Base (A)** = delay offset, **Width (B)** = harmonics (delay divider 1–4),
  **Env Delay (C)** = damping, **SRR (D)** = feedback trim. Their stock
  defaults (Base 0, Width max, Env Delay 0, SRR 0) leave the comb unchanged.

## How it works

Three patch sites (addresses and the full reverse-engineering are in
[RE_NOTES.md](RE_NOTES.md)):

1. widen the Filter Type range field from max 7 to max 11;
2. re-point the TYPE label formatter so 8–11 print `BP / BP2 / COMB / TRASH`;
3. hook the per-voice filter call in the render and run our own DSP for TYPE
   8–11, tail-calling the stock filter for everything else.

Our DSP is integer-only (no FPU, no libgcc): a trapezoidal state-variable
filter for BP/BP2 and two feedback combs for COMB/TRASH. The cutoff and
resonance are smoothed (a coefficient ramp across the block, and a fractional,
smoothed comb delay) so modulating the filter does not step or click. The
filter envelope is added to the cutoff exactly as the stock filter does.

Per voice per render block (measured in digiemu), TYPE 1 (stock) costs ~2400
instructions; BP/BP2 ~2800; COMB/TRASH ~1750 — so the new modes are no more
expensive than the stock filter. The SVF computes its coefficients at the
block's two ends and ramps between them, and the comb's interpolation and
feedback each use a single 32×32 multiply.

## Building

Needs the m68k cross toolchain, an elekloader checkout, the stock
`Digitakt_OS1.53.syx`, and `core` (2.1). Set up the shell, then build:

```sh
export PATH="<m68k-elf bin>:$PATH"          # e.g. C:\SysGCC\m68k-elf\bin on Windows
export ELEKLOADER_CROSS=m68k-elf-
export PYTHONPATH="<elekloader checkout>"

python -m elekloader.sdk.build . --stock <Digitakt_OS1.53.syx>
python -m elekloader.lint  out/digifilter-1.0i.elemod --stock <Digitakt_OS1.53.syx> --with <core-2.1.elemod>
python -m elekloader.patch --stock <Digitakt_OS1.53.syx> --mod <core-2.1.elemod> --mod out/digifilter-1.0i.elemod --out custom.syx --version 2.0t --check
```

That must print `BUILT`, then `OK: links as core 2.1 …`, then `OK: the mods
combine`. Drop `--check` on the last command to write `custom.syx`.

`core` is elekloader's `mods/core` (built, or its release). Add
`--with <digihealth.elemod>` / `--mod <digihealth.elemod>` if you use it — the
third site is chosen so this mod does **not** overlap digihealth 1.0.

## Files

| file | contents |
|---|---|
| `mod.json` | the mod: id, version, sites, sources, `requires core` |
| `filter.c` | modes, coefficients, the comb DSP, the site entry point |
| `filter_dsp.s` | the per-voice state-variable filter (ColdFire EMAC) |
| `filter_glue.s` | the raw site entry points (labels + the per-voice dispatcher) |
| `filter_tables.h` | `g`, `k`, frequency and comb-delay tables |
| `tests/filter_model.py` | floating-point reference (`svf_block`, `comb_gain`) |
| `tests/digiemu_filter_*.py` | headless digiemu traces/tests (need a digiemu checkout) |
| `tools/disas.py` | disassembly helper (`m68k-elf-objdump -m m68k:cfv4e`) |
| `tools/re_locate.py`, `tools/emu_filter.py` | early image/unicorn helpers |
| `RE_NOTES.md` | the reverse-engineering findings |

## Testing

```powershell
# floating-point model self-test (no toolchain needed)
python tests/filter_model.py

# live tests in digiemu (need a digiemu source checkout + a set-up firmware)
python tests/digiemu_filter_dsp.py  --digiemu <checkout> --fw <folder> --type 8
python tests/digiemu_filter_mod.py  --digiemu <checkout> --fw <folder> --type 10
python tests/digiemu_filter_cutoff.py --digiemu <checkout> --fw <folder>
```

## Licence

GPL-2.0-or-later. No Elektron firmware is included or committed.
