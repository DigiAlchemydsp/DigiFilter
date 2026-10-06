# releases

Prebuilt DigiFilter for the **Digitakt mk1, OS 1.53**.

| file | |
|---|---|
| `elemods/digifilter-1.0k.elemod` | the mod (current) |
| `DigiFilter-1.0k.zip` | the release package: `elemods/` + `sources/` + README (install/build) + LICENSE |
| `elemods/digifilter-1.0j.elemod`, `DigiFilter-1.0j.zip` | the previous release |
| `elemods/digifilter-1.0i.elemod`, `DigiFilter-1.0i.zip`, `elemods/digifilter-1.0h.elemod`, `DigiFilter-1.0h.zip` | earlier releases |

The `.elemod` needs `core` (e.g. `core-2.1.elemod`, from
[elekloader](https://github.com/irpina/elekloader)) and the stock OS file
`Digitakt_OS1.53.syx`. The zip's README has the full install and
build-from-source instructions. See [../CHANGELOG.md](../CHANGELOG.md) for the
full history.

Install:

```sh
python -m elekloader.patch --stock Digitakt_OS1.53.syx \
    --mod core-2.1.elemod --mod releases/elemods/digifilter-1.0k.elemod \
    --out Digitakt_OS1.53-digifilter.syx --version 2.0t
```

Then flash the `.syx` with Elektron Transfer.

New in 1.0k: while TYPE is COMB or TRASH the **RESO / GAIN** knob is the comb
feedback (0…127, up to 31/32 — near self-oscillation for a metallic ring), and
the second FLTR page's free encoders add **C = Harmonics** and **G = Damping**
(labelled HARM/DAMP, round dials like SRR) — **alongside** the stock
**Base / Width / Env Delay / SRR** knobs, which keep working and saving. The new
values are mirrored into saved kit words (best-effort persistence). Also fixed:
**BP (TYPE 8)** output is now saturated, so it no longer distorts on hot
material. See [../CHANGELOG.md](../CHANGELOG.md).

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
