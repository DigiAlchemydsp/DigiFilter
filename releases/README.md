# releases

Prebuilt DigiFilter for the **Digitakt mk1, OS 1.53**.

| file | |
|---|---|
| `elemods/digifilter-1.0h.elemod` | the mod |
| `DigiFilter-1.0h.zip` | the release package: `elemods/` + `sources/` + README (install/build) + LICENSE |

The `.elemod` needs `core` (e.g. `core-2.1.elemod`, from
[elekloader](https://github.com/irpina/elekloader)) and the stock OS file
`Digitakt_OS1.53.syx`. The zip's README has the full install and
build-from-source instructions.

Install:

```sh
python -m elekloader.patch --stock Digitakt_OS1.53.syx \
    --mod core-2.1.elemod --mod releases/elemods/digifilter-1.0h.elemod \
    --out Digitakt_OS1.53-digifilter.syx --version 2.0t
```

Then flash the `.syx` with Elektron Transfer.

The package contains the mod's own bytes only; no Elektron firmware. See
[../LICENSE](../LICENSE). Rebuild with `elekloader.sdk.build` from the sources
under `../` (see [../README.md](../README.md)).
