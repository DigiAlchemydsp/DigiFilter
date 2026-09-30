# releases

Prebuilt DigiFilter for the **Digitakt mk1, OS 1.53**.

| file | |
|---|---|
| `elemods/digifilter-1.0i.elemod` | the mod (current) |
| `DigiFilter-1.0i.zip` | the release package: `elemods/` + `sources/` + README (install/build) + LICENSE |
| `elemods/digifilter-1.0h.elemod`, `DigiFilter-1.0h.zip` | the previous release |

The `.elemod` needs `core` (e.g. `core-2.1.elemod`, from
[elekloader](https://github.com/irpina/elekloader)) and the stock OS file
`Digitakt_OS1.53.syx`. The zip's README has the full install and
build-from-source instructions.

Install:

```sh
python -m elekloader.patch --stock Digitakt_OS1.53.syx \
    --mod core-2.1.elemod --mod releases/elemods/digifilter-1.0i.elemod \
    --out Digitakt_OS1.53-digifilter.syx --version 2.0t
```

Then flash the `.syx` with Elektron Transfer.

New in 1.0i: the filter envelope now modulates the new modes; the DSP is
optimized (no more than the stock filter's cost per voice per block); the
second FLTR page drives COMB/TRASH delay/harmonics/damping/feedback trim.
Known issue: **BP (TYPE 8) can clip at some frequencies** (no SVF output
saturation).

The package contains the mod's own bytes only; no Elektron firmware. See
[../LICENSE](../LICENSE). Rebuild with `elekloader.sdk.build` from the sources
under `../` (see [../README.md](../README.md)).
