# DigiFilter

Per-track filter modes for the **Digitakt mk1 (OS 1.54)** and
**Digitone mk1 / Digitone Keys (OS 1.44)**. The Digitakt side is DigiFilter
(BP/BP2/COMB/TRASH/OB4/OB2); the Digitone side is Filter+FX
(VOWEL/BANK/FOLD/CRUSH/RING/PHASER/FLANGER). Latest OS only; one elemod per
machine.

| device | TYPE | modes |
|---|---|---|
| Digitakt | 8..13 | **BP**, **BP2**, **COMB**, **TRASH**, **OB4**, **OB2** |
| Digitone | 4..10 | **VOWEL**, **BANK**, **FOLD**, **CRUSH**, **RING**, **PHASER**, **FLANGER** |

Each mode runs per voice/track and uses that voice's own FREQ, RESO and filter
envelope. Stock TYPE values keep running the stock filter.

- Digitakt: COMB/TRASH use HARM/DAMP on the second FLTR page's free encoders.
- Digitone: VOWEL/BANK use AUX1/AUX2 on page 2 (SIZE/F4 or SPRD/TILT).

The FLTR page redraws its FREQ/RES response curve and TYPE-box icon for the new
modes.

## Layout

| path | contents |
|---|---|
| `shared/` | firmware-free DSP: SVF/comb/OB (DT) and Filter+FX (DN), tables |
| `digifilter-dt/` | Digitakt mk1 adapter, manifest, UI, DT notes |
| `digifilter-dn/` | Digitone mk1/Keys Filter+FX adapter, manifest, UI, notes |
| `docs/` | shared design notes (OB-1 model, reference mapping) |
| `tests/`, `tools/` | host/emulator checks and generators |
| `releases/` | prebuilt elemods and release packages |

## Build

Needs the m68k cross toolchain, elekloader 0.5+, both stock OS files, and the
matching cores (`core-4.0-os1.54`, `core-dn1-4.0-os1.44`).

```sh
python tools/build_release.py \
    --elekloader <elekloader checkout> \
    --stock-dt <Digitakt_OS1.54.syx> \
    --stock-dn <Digitone_OS1.44.syx> \
    --toolchain-bin <m68k-elf bin>
```

The script builds `digifilter-1.2.elemod` and `digifilter-dn-1.2.elemod`,
lints and patch-checks both, stages them in `releases/elemods/`, writes local
test `.syx` files under `out/`, and creates `releases/DigiFilter-1.2.zip`.
Override the cores with `--core-dt` / `--core-dn` if they live elsewhere.

Install with elekloader: add your stock OS, the matching core and the elemod,
then build the custom `.syx` and flash it with Elektron Transfer.

## Device notes

- [Digitakt mk1 — DigiFilter](digifilter-dt/README.md)
- [Digitone mk1 / Keys — Filter+FX](digifilter-dn/README.md)

## Testing

```sh
# Digitakt DSP
python tests/filter_model.py
python tests/comb_equivalence.py
python tests/ob1_table_accuracy.py
python tests/df_bench.py          # needs digiemu's patched Unicorn

# Digitone Filter+FX DSP
python tests/fx_smoke.py          # needs digiemu's patched Unicorn
```

See the device READMEs and `docs/ob1.md` for the emulator and hardware checks.

## Credits

- **Digital Alchemy DSP** - the Digitakt DigiFilter modes and the Digitone Filter+FX port, DSP and FLTR-page drawing.
- **Simon Johansson** - OB4/OB2, the Oberheim OB-1 VCF model.
- **x2k_77-m1** - the original Digitone port and TYPE icons.

## Licence

GPL-2.0-or-later. No Elektron firmware is included or committed.
