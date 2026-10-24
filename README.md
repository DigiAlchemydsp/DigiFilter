# DigiFilter

Per-track filter modes for the **Digitakt mk1 (OS 1.54)** and
**Digitone mk1 / Digitone Keys (OS 1.44)**. Both machines get the same
DigiFilter modes: BP, BP2, COMB, TRASH, OB4 and OB2. Latest OS only; one
elemod per machine. The Filter+FX modes are a separate project/repository and
are not part of this release.

| device | TYPE | modes |
|---|---|---|
| Digitakt | 8..13 | **BP**, **BP2**, **COMB**, **TRASH**, **OB4**, **OB2** |
| Digitone | 4..9 | **BP**, **BP2**, **COMB**, **TRASH**, **OB4**, **OB2** |

Each mode runs per voice/track and uses that voice's own FREQ, RESO and filter
envelope. Stock TYPE values keep running the stock filter.

- Both machines: COMB/TRASH use HARM/DAMP on the second FLTR page's free
  encoders.
- OB4/OB2 use 75% of the RESO travel on both machines.

The FLTR page redraws its FREQ/RES response curve and TYPE-box icon for the new
modes.

> **Note:** Using multiple COMB / TRASH filters will slow down your machine,
> especially poly tracks on the Digitone. Watch and manage your levels when
> adjusting and/or changing filter types.

## Layout

| path | contents |
|---|---|
| `shared/` | firmware-free DSP: SVF/comb/OB and tables |
| `digifilter-dt/` | Digitakt mk1 adapter, manifest, UI, DT notes |
| `digifilter-dn/` | Digitone mk1/Keys adapter, manifest, UI, DN notes |
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

The script builds the two elemods, lints and patch-checks both, stages them in
`releases/elemods/`, writes local test `.syx` files under `out/`, and creates
`releases/DigiFilter-1.3.zip`. The Digitakt source is unchanged from 1.2, so
you can reuse its 1.2 elemod with `--dt-elemod` if you do not need to rebuild
it. Override the cores with `--core-dt` / `--core-dn` if they live elsewhere.

Install with elekloader: add your stock OS, the matching core and the elemod,
then build the custom `.syx` and flash it with Elektron Transfer.

## Device notes

- [Digitakt mk1 — DigiFilter](digifilter-dt/README.md)
- [Digitone mk1 / Keys — DigiFilter-DN](digifilter-dn/README.md)

## Testing

```sh
# Digitakt DSP
python tests/filter_model.py
python tests/comb_equivalence.py
python tests/ob1_table_accuracy.py
python tests/df_bench.py          # needs digiemu's patched Unicorn

# Digitone: builds and runs the shared DigiFilter DSP on the host
python tests/df_bench.py          # needs digiemu's patched Unicorn
```

See the device READMEs and `docs/ob1.md` for the emulator and hardware checks.

## Credits

- **Digital Alchemy DSP** - the Digitakt DigiFilter modes and the Digitone
  DigiFilter port, DSP and FLTR-page drawing.
- **Simon Johansson** - OB4/OB2, the Oberheim OB-1 VCF model.
- **x2k_77-m1** - the original Digitone port and TYPE icons.

## Licence

GPL-2.0-or-later. No Elektron firmware is included or committed.
