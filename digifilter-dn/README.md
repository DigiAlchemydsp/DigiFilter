# Filter+FX-DN — extra filter/FX modes for Digitone mk1/Keys

Seven per-voice filter/FX modes for the **Digitone mk1 / Keys, OS 1.44**, on
top of stock `OFF / LP2 / HP / LP4` (TYPE 0..3):

| TYPE | mode | controls |
|---|---|---|
| 4 | **VOWEL** | FREQ = vowel path i-e-a-o-u; RESO = formant width |
| 5 | **BANK** | FREQ = bank shift; RESO = Q |
| 6 | **FOLD** | FREQ = drive 1–8×; RESO = fold bias |
| 7 | **CRUSH** | FREQ = sample-hold rate; RESO = bit depth |
| 8 | **RING** | FREQ = carrier frequency; RESO = dry/ring depth |
| 9 | **PHASER** | FREQ = LFO rate; RESO = depth |
| 10 | **FLANGER** | FREQ = LFO rate; RESO = depth/feedback |

Each mode runs per voice and uses that voice's own FREQ, RESO and filter
envelope. Stock TYPE values keep running the stock multimode filter.

## Second page

VOWEL and BANK add two controls on page-2 free C/G (params 182/183), labelled
per mode:

| mode | C | G |
|---|---|---|
| VOWEL | **SIZE** (0..+1 octave) | **F4** (3300 Hz band ÷..×) |
| BANK | **SPRD** (up to +1 octave on top) | **TILT** (dark↔bright) |

Other modes leave page 2 stock. Value 0 is the neutral/default sound.

## Saving

The stock temp save (**FUNC+YES**) resets TYPE values above 3 on reload. The
adapter mirrors TYPE 4..10 into the low byte of **BASE** (a stock savable 8.8
param) and restores it on the next UI tick after a load. Use
**FUNC+YES/FUNC+NO** normally.

The AUX params 182/183 are new and remain best-effort across the stock
pattern/temp format; use **PTN > SAVE PATTERN TO** / **SAVE PATTERN KIT TO**
(or **GLOBAL > PROJECT > SAVE**) when you need them stored in a project.

## How it works

Six patch sites plus `ev_tick` / `ev_draw` / `ev_key` / `ev_enc`:

1. widen the Filter Type range field to max 10;
2. re-point the TYPE label formatter so 4–10 print
   `VOWEL / BANK / FOLD / CRUSH / RING / PHASER / FLANGER`;
3. widen the value-text delegate to 10 and point it at an 11-entry table;
4. hook the per-voice filter call (TYPE 4–10) and run the shared Filter+FX DSP;
5. add the AUX1/AUX2 params 182/183 and map page-2 C/G for VOWEL/BANK;
6. draw the FLTR graph and TYPE-box icon from `ev_draw`.

The DSP is integer-only (no FPU, no libgcc): four RBJ biquads in
`shared/biquad_dsp.s` for VOWEL/BANK, and the FOLD/CRUSH/RING/PHASER/FLANGER
models in `shared/fx_dsp.c`. FREQ is the render's envelope-modulated cutoff,
so ENV/ADSR modulate every mode like the stock filter.

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
python -m elekloader.lint out/digifilter-dn-1.2.elemod --stock <...OS1.44.syx> --with <core-dn1-4.0-os1.44.elemod>
python -m elekloader.patch --stock <...OS1.44.syx> --mod <core-dn1-4.0-os1.44.elemod> --mod out/digifilter-dn-1.2.elemod --out test.syx --version 1.2a --check
```

## Files

| file | contents |
|---|---|
| `mod.json` | id `digifilter-dn`, device `digitone-mk1`, os `1.44`, 6 sites, AUX params, `core` 4.0 |
| `filter_glue.s` | TYPE names/list (11 entries) and per-voice dispatcher |
| `filter_ui.c` | DN integration, FX curves/icons, page-2 dials, tick/key/enc/draw |
| `../shared/fx_dsp.c` | VOWEL/BANK/FOLD/CRUSH/RING/PHASER/FLANGER DSP |
| `../shared/biquad_dsp.s` | four independent biquads (ColdFire EMAC) |
| `../shared/biquad_tables.h`, `analog_tables.h`, `mod_tables.h` | coefficients, formant/bank data, sine/LFO tables |
| `../shared/filter_tables.h` | G27/K27, used by the response graph |

## Licence

GPL-2.0-or-later. Unofficial, not affiliated with Elektron. No firmware
committed.
