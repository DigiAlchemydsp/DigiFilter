# releases

Prebuilt DigiFilter for the **Digitakt mk1 (OS 1.54)** and **Digitone mk1 /
Keys (OS 1.44)**. Latest OS only; one elemod per machine.

Published releases: [GitHub Releases](https://github.com/DigiAlchemydsp/DigiFilter/releases)
(`v1.2` is current / Latest).

| file | |
|---|---|
| `elemods/digifilter-1.2.elemod` | the Digitakt mk1 mod, **OS 1.54** |
| `elemods/digifilter-dn-1.2.elemod` | the Digitone mk1/Keys mod, **OS 1.44** |
| `DigiFilter-1.2.zip` | the release package: both elemods + `sources/` + README + LICENSE |
| older elemods/zips | previous releases, kept for reference |

Each elemod needs its matching core and stock OS file:

| machine | elemod | core | stock |
|---|---|---|---|
| Digitakt mk1 | `digifilter-1.2.elemod` | `core-4.0-os1.54.elemod` | `Digitakt_OS1.54.syx` |
| Digitone mk1/Keys | `digifilter-dn-1.2.elemod` | `core-dn1-4.0-os1.44.elemod` | `Digitone_OS1.44.syx` |

Install (repeat with the other machine's files):

```sh
python -m elekloader.patch --stock Digitakt_OS1.54.syx \
    --mod core-4.0-os1.54.elemod \
    --mod releases/elemods/digifilter-1.2.elemod \
    --out Digitakt_OS1.54-digifilter.syx --version 1.2
```

Then flash the `.syx` with Elektron Transfer.

New in 1.2: a unified layout - `shared/` DSP, `digifilter-dt/` and
`digifilter-dn/` adapters. Both mods target only the latest OS and require core
4.0. The Digitakt side is DigiFilter (BP/BP2/COMB/TRASH/OB4/OB2); the Digitone
side is Filter+FX (VOWEL/BANK/FOLD/CRUSH/RING/PHASER/FLANGER), with TYPE 4..10
and VOWEL/BANK AUX1/AUX2 on page 2. On the Digitakt, the FLTR TYPE box now
clears the full 17x17 cell and uses bitmap icons. The DT audio path is the 1.1b
DSP.

See [../CHANGELOG.md](../CHANGELOG.md) for the full history and the device
READMEs for controls, performance and validation.

The package contains the mods' own bytes only; no Elektron firmware. See
[../LICENSE](../LICENSE). Rebuild with `tools/build_release.py` (see
[../README.md](../README.md)).
