# releases

Prebuilt DigiFilter for the **Digitakt mk1, OS 1.53 and OS 1.54**.

Published releases: [GitHub Releases](https://github.com/DigiAlchemydsp/DigiFilter/releases)
(`v1.1a` is current / Latest).

| file | |
|---|---|
| `elemods/digifilter-1.1a.elemod` | the mod, **OS 1.53** (current) |
| `elemods/digifilter-1.1a-os1.54.elemod` | the mod, **OS 1.54** |
| `DigiFilter-1.1a.zip` | the release package: both elemods + `sources/` + README (install/build) + LICENSE |
| `elemods/digifilter-1.1.elemod`, `DigiFilter-1.1.zip` | the previous release (OS 1.53) |
| `elemods/digifilter-1.0k.elemod`, `DigiFilter-1.0k.zip` | an earlier release |
| `elemods/digifilter-1.0j.elemod`, `DigiFilter-1.0j.zip`, `elemods/digifilter-1.0i.elemod`, `DigiFilter-1.0i.zip`, `elemods/digifilter-1.0h.elemod`, `DigiFilter-1.0h.zip` | earlier releases |

Each `.elemod` needs `core` from
[elekloader](https://github.com/irpina/elekloader) and the matching stock OS file
(`Digitakt_OS1.53.syx` or `Digitakt_OS1.54.syx`). The zip's README has the full
install and build-from-source instructions. See
[../CHANGELOG.md](../CHANGELOG.md) for the full history.

Install (OS 1.53; for 1.54 use the 1.54 stock, the `-os1.54` elemod and a 1.54
`core`):

```sh
python -m elekloader.patch --stock Digitakt_OS1.53.syx \
    --mod core-2.1.elemod --mod releases/elemods/digifilter-1.1a.elemod \
    --out Digitakt_OS1.53-digifilter.syx --version 2.0t
```

Then flash the `.syx` with Elektron Transfer.

New in 1.1a: a performance pass over the per-voice DSP — BP/BP2 recompute the
state-variable filter's coefficients only when the cutoff/resonance move, so with
static knobs they cost ~60 % fewer instructions (~1229 vs 3113 per voice per
block, below the stock filter) and ~22 % fewer while modulated; the audio is
bit-for-bit the same. The mod now also builds for **OS 1.54** from the same
source tree. See [../CHANGELOG.md](../CHANGELOG.md) and
[../HANDOFF-OPTIMIZATION.md](../HANDOFF-OPTIMIZATION.md).

New in 1.1: two more types, **OB4 (12)** and **OB2 (13)**, the Oberheim OB-1's
filter — its 4-pole lowpass ladder and its 2-pole output — self-oscillating at
the top of RESO (from about 121), with the FLTR page drawing their response.
Contributed by Simon Johansson (PR #2); how they were made and checked is in
[docs/ob1.md](../docs/ob1.md). See [../CHANGELOG.md](../CHANGELOG.md).

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

Stress-tested on hardware over 3 days: **PASS** (a Digitakt mk1). **1.1a** was
tested on hardware (Digitakt mk1) on both **OS 1.53** and **OS 1.54**: PASS.

## Credits

- **Digital Alchemy DSP** — the band-pass **BP / BP2**, **COMB**, **TRASH** modes
  and the per-voice DSP / FLTR-page response curve.
- **Simon Johansson** (PR #2) — the **OB4 / OB2** Oberheim OB-1 ladder modes
  ([../docs/ob1.md](../docs/ob1.md)).
