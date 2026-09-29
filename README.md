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

## Status (WIP)

The **audio path is done and validated** (BP / BP2 / COMB / TRASH, with
smoothing), but the **UI is not finished**: the FLTR page's FREQ/RES **response
curve** still only draws up to `EQ:5` and does not reflect the new types. The
graph is drawn by page UI code from UI-model state (not from the filter RAM), so
extending it is still open work. See [RE_NOTES.md](RE_NOTES.md) "Open items".

Everything in this repo builds (`BUILT`), lints against `core` and combines with
`digihealth` (`OK: the mods combine`); the remaining gap is that UI drawing.

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
smoothed comb delay) so modulating the filter does not step or click.

## Building

You need the m68k cross toolchain, an elekloader checkout, the stock
`Digitakt_OS1.53.syx`, and `core` (2.1). Example (Windows PowerShell):

```powershell
$env:PATH = "C:\SysGCC\m68k-elf\bin;" + $env:PATH
$env:ELEKLOADER_CROSS = "m68k-elf-"
$env:PYTHONPATH = "<elekloader checkout>"

$repo  = "<this folder>"
$stock = "<Digitakt_OS1.53.syx>"
$core  = "<elekloader>\mods\core\out\core-2.1.elemod"

# build (writes $repo\out\digifilter-1.0h.elemod)
python -m elekloader.sdk.build $repo --stock $stock

# lint against core (and, if you use it, digihealth)
python -m elekloader.lint $repo\out\digifilter-1.0h.elemod --stock $stock --with $core

# combine into a flashable custom firmware (--check first)
python -m elekloader.patch --stock $stock --mod $core --mod $repo\out\digifilter-1.0h.elemod `
    --out custom-2.0t.syx --version 2.0t --check
```

Requirements and the SDK reference are in the elekloader guide
(`02-mod-json.md`, `04-patching-sites.md`, `05-workflow.md`).

**Coexistence:** the third site is chosen so this mod does **not** overlap
digihealth 1.0 (which rewrites the same `lea` we used to). `--with digihealth`
links and combines cleanly.

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
