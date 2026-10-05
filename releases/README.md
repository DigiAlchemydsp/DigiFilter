# releases

Prebuilt DigiFilter for the **Digitakt mk1, OS 1.53**.

| file | |
|---|---|
| `elemods/digifilter-1.0j.elemod` | the mod (current) |
| `DigiFilter-1.0j.zip` | the release package: `elemods/` + `sources/` + README (install/build) + LICENSE |
| `elemods/digifilter-1.0i.elemod`, `DigiFilter-1.0i.zip` | the previous release |
| `elemods/digifilter-1.0h.elemod`, `DigiFilter-1.0h.zip` | the first release |

The `.elemod` needs `core` (e.g. `core-2.1.elemod`, from
[elekloader](https://github.com/irpina/elekloader)) and the stock OS file
`Digitakt_OS1.53.syx`. The zip's README has the full install and
build-from-source instructions. See [../CHANGELOG.md](../CHANGELOG.md) for the
full history.

Install:

```sh
python -m elekloader.patch --stock Digitakt_OS1.53.syx \
    --mod core-2.1.elemod --mod releases/elemods/digifilter-1.0j.elemod \
    --out Digitakt_OS1.53-digifilter.syx --version 2.0t
```

Then flash the `.syx` with Elektron Transfer.

New in 1.0j: the resonance range is capped for the new modes so they no longer
clip or run away — BP/BP2 use a maximum Q of ~5, COMB/TRASH a feedback of 13/16
(+14 dB at the teeth), and the drawn FREQ/RES curve uses the same cap, so it
shows the resonance the audio actually gets. See
[../CHANGELOG.md](../CHANGELOG.md).

New in 1.0i: the FLTR page's FREQ/RES response curve **and the small TYPE-box
glyph** are painted for the new modes from a core `ev_draw` handler (so they
survive multi-mod builds, where patching the page drawView slot was overwritten
by another mod's `ev_draw` subscription) — a narrower, smooth band-pass bell for
BP/BP2 (no vertical brickwall at the edges) and evenly spaced comb teeth for
COMB/TRASH whose spacing sweeps across the whole FREQ range and whose depth rises
with RESO (no dead zones); the filter envelope modulates the new modes; the DSP
is optimized (no more than the stock filter's cost per voice per block); the
second FLTR page drives COMB/TRASH delay/harmonics/damping/feedback trim.

The package contains the mod's own bytes only; no Elektron firmware. See
[../LICENSE](../LICENSE). Rebuild with `elekloader.sdk.build` from the sources
under `../` (see [../README.md](../README.md)).
