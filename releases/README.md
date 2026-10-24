# releases

Prebuilt DigiFilter for the **Digitakt mk1 (OS 1.54)** and **Digitone mk1 /
Keys (OS 1.44)**. Both machines use the same modes (BP/BP2/COMB/TRASH/OB4/OB2)
and the same release version. Latest OS only; one elemod per machine.

Published releases: [GitHub Releases](https://github.com/DigiAlchemydsp/DigiFilter/releases)
(`v1.3` is current / Latest).

| file | |
|---|---|
| `elemods/digifilter-1.3.elemod` | the Digitakt mk1 mod, **OS 1.54** |
| `elemods/digifilter-dn-1.3.elemod` | the Digitone mk1/Keys mod, **OS 1.44** |
| `DigiFilter-1.3.zip` | the release package: both elemods + sources + README + LICENSE |
| `archive/1.3-mixed/` | the unpublished mixed draft (Digitakt 1.2 + Digitone 1.3) |
| older elemods/zips | previous releases, kept for reference |

Each elemod needs its matching core and stock OS file:

| machine | elemod | core | stock |
|---|---|---|---|
| Digitakt mk1 | `digifilter-1.3.elemod` | `core-4.0-os1.54.elemod` | `Digitakt_OS1.54.syx` |
| Digitone mk1/Keys | `digifilter-dn-1.3.elemod` | `core-dn1-4.0-os1.44.elemod` | `Digitone_OS1.44.syx` |

Install (repeat with the other machine's files):

```sh
python -m elekloader.patch --stock Digitakt_OS1.54.syx \
    --mod core-4.0-os1.54.elemod \
    --mod releases/elemods/digifilter-1.3.elemod \
    --out Digitakt_OS1.54-digifilter.syx --version 1.3

python -m elekloader.patch --stock Digitone_OS1.44.syx \
    --mod core-dn1-4.0-os1.44.elemod \
    --mod releases/elemods/digifilter-dn-1.3.elemod \
    --out Digitone_OS1.44-digifilter.syx --version 1.3
```

Then flash the `.syx` with Elektron Transfer.

> **Note:** Using multiple COMB / TRASH filters will slow down your machine,
> especially poly tracks on the Digitone. Watch and manage your levels when
> adjusting and/or changing filter types.

New in 1.3: the Digitone gets DigiFilter-DN with the same BP/BP2/COMB/TRASH/
OB4/OB2 modes as the Digitakt (TYPE 4..9, HARM/DAMP on page 2, OB at 75% of
RESO). Both machines are built at 1.3 from the same shared DSP source and
require core 4.0. Filter+FX is a separate project/repository and is no longer
part of this release.

The previous 1.2 package (Digitakt DigiFilter + Digitone Filter+FX) is
superseded. The mixed 1.3 draft that paired Digitakt 1.2 with Digitone 1.3 is
kept under `archive/1.3-mixed/` for reference. See
[../CHANGELOG.md](../CHANGELOG.md) and the device READMEs for controls,
performance and validation.

The package contains the mods' own bytes only; no Elektron firmware. See
[../LICENSE](../LICENSE). Rebuild with `tools/build_release.py` (see
[../README.md](../README.md)).
