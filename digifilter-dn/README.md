# DigiFilter-DN — extra filter modes for Digitone mk1/Keys

Per-voice filter modes for the **Digitone mk1 / Keys, OS 1.44**:
`BP`, `BP2`, `COMB`, `TRASH`, `OB4`, `OB2` as **TYPE 4..9**, on top of stock
`OFF / LP2 / HP / LP4` (TYPE 0..3). These are the same DigiFilter modes as the
Digitakt build; the Filter+FX modes live in their own repository.

Port of [DigiFilter](../README.md) (Digitakt mk1) to the Digitone filter
section, incl. OB-1 (Simon Johansson). Each mode runs per voice and uses that
voice's own **FREQ** (slot 55), **RESO** (slot 56) and filter envelope, exactly
like the stock types. Stock TYPE values keep running the stock multimode filter
— nothing here reimplements a stock mode.

| TYPE | mode | what it is |
|---|---|---|
| 4 | **BP** | band pass (trapezoidal SVF, same kernel as the Digitakt port) |
| 5 | **BP2** | wider band pass (about half the resonance) |
| 6 | **COMB** | feedback comb, delay from FREQ, feedback from RESO |
| 7 | **TRASH** | second comb at half the delay (higher harmonic series) |
| 8 | **OB4** | OB-1 ladder 4-pole (self-oscillation near the top of RESO) |
| 9 | **OB2** | OB-1 ladder 2-pole (same ladder, stage-2 output) |

> Digitone **mk1 / Keys only**. Digitone II's machines are out of scope.

## Controls

- **FREQ (E on page 1)** cutoff / comb pitch; **RESO (F)** resonance, and for
  COMB/TRASH the comb **feedback** (0..127, up to 31/32, metallic near
  self-oscillation, saturated). **TYPE (G)** picks the mode. **ENV (H)** and
  the envelope ADSR modulate FREQ for the new modes too, exactly as the stock
  types (the render's own envelope-modulated cutoff drives them).
- OB4/OB2 use **75% of the RESO 0..127 travel**, the same scaling as the
  Digitakt build, so the top of the knob is not buried in ladder saturation.
- Second page: `DEL/BASE/WIDTH` stock always (the base filter stays
  accessible). For COMB/TRASH, free **C/G** add **HARM/DAMP** (slots 65/26,
  divider 1..4 / 0..127 texts, ENV-style dials). Other modes leave page 2
  stock.

## Saving

The stock temp save (**FUNC+YES**) resets TYPE values above 3 on reload. The
adapter mirrors TYPE 4..9 into the low byte of **BASE** (a stock savable 8.8
param) and restores it on the next UI tick after a load. Use
**FUNC+YES/FUNC+NO** normally.

HARM/DAMP are new params (182/183) and remain best-effort across the stock
pattern/temp format; use **PTN > SAVE PATTERN TO** / **SAVE PATTERN KIT TO**
(or **GLOBAL > PROJECT > SAVE**) when you need them stored in a project.

## How it works

Six patch sites plus `ev_tick` / `ev_draw` / `ev_key` / `ev_enc`:

1. widen the Filter Type range field to max 9;
2. re-point the TYPE label formatter so 4..9 print
   `BP / BP2 / COMB / TRASH / OB4 / OB2`;
3. widen the value-text delegate to 9 and point it at a 10-entry table;
4. hook the per-voice filter call (TYPE 4..9) and run the shared DigiFilter
   DSP (SVF, combs, OB-1 ladder);
5. add the HARM/DAMP params 182/183 and map page-2 C/G for COMB/TRASH;
6. draw the FLTR graph and TYPE-box icon from `ev_draw`.

The DSP is integer-only (no FPU, no libgcc). FREQ is the render's
envelope-modulated cutoff, so ENV/ADSR modulate every mode like the stock
filter. The audio path is per voice and in place: `fw_voices` → our
SVF/comb/OB (or the stock filter for TYPE 0..3) → mixer/effects/AMP as stock.

## Building

Repository root:

```sh
python tools/build_release.py \
    --elekloader <elekloader checkout> \
    --stock-dt <Digitakt_OS1.54.syx> \
    --stock-dn <Digitone_OS1.44.syx> \
    --toolchain-bin <m68k-elf bin>
```

Or this mod alone:

```sh
export ELEKLOADER_CROSS=m68k-elf-
export PYTHONPATH="<elekloader checkout>"
python -m elekloader.sdk.build digifilter-dn --stock <...OS1.44.syx>
python -m elekloader.lint out/digifilter-dn-1.3.elemod --stock <...OS1.44.syx> --with <core-dn1-4.0-os1.44.elemod>
python -m elekloader.patch --stock <...OS1.44.syx> --mod <core-dn1-4.0-os1.44.elemod> --mod out/digifilter-dn-1.3.elemod --out test.syx --version 1.3a --check
```

## Files

| file | contents |
|---|---|
| `mod.json` | id `digifilter-dn`, device `digitone-mk1`, os `1.44`, 6 sites, type 4..9, HARM/DAMP params, `core` 4.0 |
| `filter_glue.s` | TYPE names/list (10 entries) and per-voice dispatcher |
| `filter_ui.c` | DN integration, FLTR curves/icons, page-2 dials, tick/key/enc/draw, TYPE persistence |
| `README.md` | this file |
| `RE_NOTES_DN.md` | RE notes (sites/slots/pages/verification) |
| `../shared/df_dsp.c/h` | shared SVF/comb math + state |
| `../shared/filter_dsp.s` | shared SVF EMAC (`digifilter_svf`) |
| `../shared/ob1_vcf.c/h` | shared OB-1 ladder |
| `../shared/filter_tables.h` / `ob1_tables.h` | shared tables (`G27/K27/COMB_DELAY`, `OB1_CURVE`) |
| `../shared/svf_a1_tables.h` / `ob1_fbsat_table.h` | precomputed SVF a1 and OB saturation tables |

## Licence

GPL-2.0-or-later. Unofficial, not affiliated with Elektron. No firmware
committed.
