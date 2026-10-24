# DigiFilter — Digitakt mk1

Extra per-track filter modes for the **Digitakt mk1, OS 1.54**, on top of the
stock `OFF / LP / HP / EQ:1..5`:

| TYPE | mode | what it is |
|---|---|---|
| 8 | **BP** | band pass (state-variable filter) |
| 9 | **BP2** | a wider band pass (about half the resonance) |
| 10 | **COMB** | feedback comb, delay from FREQ, feedback from RESO |
| 11 | **TRASH** | second comb at half the delay (a higher harmonic series) |
| 12 | **OB4** | the Oberheim OB-1's 4-pole lowpass ladder, self-oscillating at the top of RESO |
| 13 | **OB2** | the OB-1's 2-pole output: 12 dB/oct, resonating from the same 4-pole loop |

Each mode runs per track and uses that track's own FREQ, RESO and filter
envelope, exactly like the stock types. Stock TYPE values keep running the
stock filter — nothing here reimplements a stock mode.

The **FLTR page** redraws its FREQ/RES response curve for the new types and
shows a 17x17 bitmap icon in the TYPE box. The icons include their own border,
so the full cell (77..93 / 7..23) is cleared before drawing; this also masks
the stock `EQ n` artwork cleanly.

![The FLTR page for LP, BP, BP2, COMB and TRASH](../docs/img/fltr-types.png)

**OB4** and **OB2** are modelled on the OB-1's VCF: a ladder of four OTA
stages with the resonance fed back from the fourth, saturating where the
circuit does. How they were made and checked is in
[../docs/ob1.md](../docs/ob1.md).

Their FREQ control follows the measured reference curve, from 10 Hz to 21 kHz
with cubic travel. Existing OB4/OB2 Sounds change at the same knob settings;
their saved format is unchanged.

![The FLTR page for LP, OB4 and OB2](../docs/img/ob1-fltr.png)

> Digitakt **mk1 only**. Digitakt II's filter machines are out of scope.

## Status

The audio path is done and validated (BP / BP2 / COMB / TRASH and OB4 / OB2),
including the filter envelope, the comb controls, the FLTR-page response curve
and the TYPE-box icons. Version **1.2** is OS 1.54 only and pins core 4.0.

**1.1a** passed hardware testing on a Digitakt mk1 on OS 1.53 and OS 1.54.
**1.1b** is emulator-verified (bit-exact for BP/BP2 and COMB/TRASH; the OB
saturation table is bounded at ~-100 dBFS). **1.2** reuses the 1.1b DSP; its
UI icon/type-box change and core-4.0 build are pending hardware verification.

## Known issues

- **BP (TYPE 8)** output is saturated to ±2^27 in the SVF (like the comb), so
  a high-Q peak on hot material clips cleanly instead of wrapping the 32-bit
  sample. It is still a hard clip at the top of the range; back off RESO/ENV
  depth or use BP2 for very hot samples. (The resonance range is capped at
  Q ~5.)

## Controls

- **FREQ (E)** sets the cutoff / comb pitch; **RESO / GAIN (F)** is the
  resonance, and for COMB/TRASH it is the comb **feedback** (0…127, up to
  31/32 for a metallic, near-self-oscillating ring); the filter envelope
  (H + ADSR) modulates the cutoff exactly as the stock types do.
- For **OB4/OB2**, **RESO / GAIN (F)** is the resonance, scaled to **75% of
  the 0..127 travel** (knob 127 = effective 95) so the ladder does not saturate
  as hard at the top. It still self-oscillates, from about knob 108.
- **Second FLTR page**, while TYPE is COMB or TRASH, adds **C = Harmonics**
  (delay divider 1–4) and **G = Damping** (a one-pole on the feedback), each
  shown as a round dial like the stock SRR knob. They sit alongside the stock
  **Base / Width / Env Delay / SRR** knobs, which keep working and saving.

## How it works

Three patch sites plus `ev_draw` / `ev_tick` subscriptions (addresses and the
full reverse-engineering are in [RE_NOTES.md](RE_NOTES.md)):

1. widen the Filter Type range field from max 7 to max 13;
2. re-point the TYPE label formatter so 8–13 print
   `BP / BP2 / COMB / TRASH / OB4 / OB2`;
3. hook the per-voice filter call in the render and run our own DSP for TYPE
   8–13, tail-calling the stock filter for everything else;
4. subscribe to core's `ev_draw` (`digifilter_draw`, order 40): after the page
   has drawn, when the shown page kind is FLTR (6) and the active track's TYPE
   is 8–13, mask the stock graph and TYPE box and paint the response curve plus
   the mode's 17x17 TYPE-box icon;
5. on each UI tick, when the active track's TYPE is COMB/TRASH, put the comb's
   extra controls on the second FLTR page's free C/G encoders. The stock
   Base/Width/Env Delay/SRR knobs are left untouched.

The DSP is integer-only (no FPU, no libgcc): a trapezoidal state-variable
filter for BP/BP2, two feedback combs for COMB/TRASH, and a zero-delay-feedback
OTA ladder for OB4/OB2. It lives in [../shared/df_dsp.c](../shared/df_dsp.c)
and is shared with the Digitone port; this directory holds only the Digitakt
adapter (kit slots, envelope, dispatch).

Per voice per render block (measured in digiemu / `tests/df_bench.py`), TYPE 1
(stock) costs ~2400 instructions; **BP/BP2 ~1100 with static knobs and ~1670
while the cutoff is swept**; COMB/TRASH ~1700; OB4/OB2 ~3200 at RESO 64
(~1390 with the feedback at zero).

## Building

The mod builds for **OS 1.54** only and requires **core 4.0**
(`core-4.0-os1.54.elemod`). Needs the m68k cross toolchain and elekloader 0.5+.

From the repository root:

```sh
python tools/build_release.py \
    --elekloader <elekloader checkout> \
    --stock-dt <Digitakt_OS1.54.syx> \
    --stock-dn <Digitone_OS1.44.syx> \
    --toolchain-bin <m68k-elf bin>
```

Or build this mod alone:

```sh
export PATH="<m68k-elf bin>:$PATH"
export ELEKLOADER_CROSS=m68k-elf-
export PYTHONPATH="<elekloader checkout>"

python -m elekloader.sdk.build digifilter-dt --stock <Digitakt_OS1.54.syx>
python -m elekloader.lint  out/digifilter-1.2.elemod --stock <Digitakt_OS1.54.syx> --with <core-4.0-os1.54.elemod>
python -m elekloader.patch --stock <Digitakt_OS1.54.syx> --mod <core-4.0-os1.54.elemod> --mod out/digifilter-1.2.elemod --out custom.syx --version 1.2 --check
```

That must print `BUILT`, then `OK: links as core …`, then `OK: the mods
combine`. Drop `--check` on the last command to write `custom.syx`. Add
`--with <digihealth.elemod>` / `--mod <digihealth.elemod>` if you use it — the
third site is chosen so this mod does **not** overlap digihealth 1.0.

## Files

| file | contents |
|---|---|
| `mod.json` | the mod: id, version, 1.54 sites, sources, `requires core 4.0` |
| `filter.c` | the Digitakt adapter: modes dispatch, kit slots, envelope |
| `filter_glue.s` | the raw site entry points (labels + the per-voice dispatcher) |
| `filter_ui.c` | `ev_draw` response curve + 17x17 TYPE icons, page-2 dials and `ev_tick` re-map |
| `../shared/df_dsp.c` | the shared SVF/comb core, coefficient cache and per-voice state |
| `../shared/filter_dsp.s` | the per-voice state-variable filter (ColdFire EMAC) |
| `../shared/filter_tables.h` | `g`, `k`, frequency and comb-delay tables |
| `../shared/ob1_vcf.c`, `ob1_vcf.h`, `ob1_tables.h`, `ob1_fbsat_table.h` | OB4/OB2: the OB-1 ladder, its tables and saturation table |
| `tests/filter_model.py` | floating-point reference (`svf_block`, `comb_gain`) |
| `tests/df_bench.py`, `tests/df_bench.c` | per-voice instruction and cycle bench |
| `tests/comb_equivalence.py` | COMB/TRASH output and state versus a Git baseline |
| `tests/ob1_table_accuracy.py` | the interpolated fbsat table's error bound |
| `tests/digiemu_filter_*.py` | headless digiemu traces/tests (need a digiemu checkout) |
| `tools/disas.py` | disassembly helper (`m68k-elf-objdump -m m68k:cfv4e`) |
| `tools/gen_ob1_fbsat.py` | generates `../shared/ob1_fbsat_table.h` |
| `tools/gen_svf_a1.py` | generates `../shared/svf_a1_tables.h` |
| `RE_NOTES.md` | reverse-engineering findings (and the 1.1a optimization ledger) |
| `HANDOFF-OPTIMIZATION.md` | the 1.1a performance pass |

## Testing

The OB4/OB2 [validation commands](../docs/ob1.md#files) cover the native
kernel, measured calibration targets and focused ColdFire/firmware simulator
checks.

```powershell
# floating-point model self-test (no toolchain needed)
python tests/filter_model.py

# per-voice cost bench (needs m68k-elf-gcc + digiemu's Unicorn):
python tests/df_bench.py

# bit-exact COMB/TRASH output + delay-line state versus a Git baseline:
python tests/comb_equivalence.py

# bound the OB saturation table's error against the exact polynomial:
python tests/ob1_table_accuracy.py

# live tests in digiemu (need a digiemu source checkout + a set-up firmware)
python tests/digiemu_filter_dsp.py  --digiemu <checkout> --fw <folder> --type 8
python tests/digiemu_filter_mod.py  --digiemu <checkout> --fw <folder> --type 10
python tests/digiemu_filter_cutoff.py --digiemu <checkout> --fw <folder>
python tests/digiemu_filter_curve.py --digiemu <checkout> --fw <folder>
python tests/digiemu_filter_page2.py --digiemu <checkout> --fw <folder>
```

## Releases

Prebuilt packages live in [`../releases/`](../releases/README.md) and on the
[GitHub Releases page](https://github.com/DigiAlchemydsp/DigiFilter/releases).
The current package, **`DigiFilter-1.2.zip`**, carries one elemod per machine:
`elemods/digifilter-1.2.elemod` for the Digitakt mk1 (OS 1.54) and
`elemods/digifilter-dn-1.2.elemod` for the Digitone mk1/Keys (OS 1.44).
`releases/elemods/` also keeps the older releases.

## Credits

- **Digital Alchemy DSP** — the band-pass **BP / BP2** (state-variable),
  **COMB** and **TRASH** modes, the per-voice DSP and the FLTR-page response
  curve.
- **Simon Johansson** — the **OB4** and **OB2** modes: the Oberheim
  OB-1's VCF as a zero-delay-feedback ladder and its 2-pole output (see
  [../docs/ob1.md](../docs/ob1.md)).
- **x2k_77-m1** — the 17x17 TYPE icons and the full-cell TYPE-box fix ported
  from the Digitone adapter.

## Licence

GPL-2.0-or-later. No Elektron firmware is included or committed.
