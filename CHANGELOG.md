# Changelog

All notable changes to DigiFilter. Format-2
[elekloader](https://github.com/irpina/elekloader) mod for the Elektron
Digitakt **mk1, OS 1.53**. Versioned as `<major>.<minor><letter>`.

## [1.0j] - 2026-10-05

Resonance-range caps; less clipping / runaway on the new modes.

### Fixed

- **BP (TYPE 8) clipping on transients.** The SVF's top Q step (Q 8) overshoots
  and clips; the resonance index is now capped to 13/15 (~Q 5) in
  `mode_coef()` (`filter.c`).
- **COMB/TRASH feedback runaway at some pitches.** The comb feedback is capped to
  13/16 (+14 dB at the teeth) instead of 15/16 (+24 dB) in `comb_run()`
  (`filter.c`).
- The FLTR response-curve handler caps the drawn resonance the same way, so the
  curve shows the resonance the audio actually gets (`filter_ui.c`).

### Changed

- `tests/digiemu_filter_dsp.py` models the capped resonance and settles
  high-feedback combs (more blocks).

## [1.0i] - 2026-10-04

Filter envelope, cheaper DSP, second-page comb controls, response-curve UI.

### Added

- The **filter envelope** now modulates the new modes (TYPE 8–11) exactly as the
  stock filter does.
- The **second FLTR page** drives COMB/TRASH: Base = delay offset, Width =
  harmonics (delay divider 1–4), Env Delay = damping, SRR = feedback trim.
- The **FLTR page's FREQ/RES response curve** and the small **TYPE-box glyph**
  are painted for the new modes from a core `ev_draw` handler
  (`digifilter_draw`): a band-pass bell for BP/BP2, comb teeth for COMB/TRASH.
- COMB/TRASH tooth spacing sweeps the whole FREQ range with no dead zone; RESO
  sets the tooth depth.
- Every curve tapers to the floor at both box edges (no vertical brickwall);
  BP/BP2 use a narrower bell whose peak height follows Q and animates smoothly.

### Changed

- DSP cost down (instructions per voice per render block): COMB/TRASH
  5604 → ~1745, BP/BP2 4200 → ~2800 (stock 2397). `mulsh` is inlined, the comb's
  interpolation/feedback each collapse to one 32×32 multiply, and the SVF
  coefficients are computed at the block ends and ramped between them.

### Fixed

- The curve is painted from an `ev_draw` subscription instead of patching the
  page drawView vtable slot `0x401842a0`, which multi-mod builds overwrote with
  core's `ev_draw` trampoline (so the curve was still stock on device).
- The kit TYPE word (`type<<8`) was compared raw, so no curve had ever actually
  been painted.

## [1.0h] - 2026-09-29

Initial release.

### Added

- Four per-track filter modes on the stock `OFF / LP / HP / EQ:1..5`:
  `BP` (TYPE 8), `BP2` (9, a wider band pass), `COMB` (10) and `TRASH`
  (11, a second comb at half the delay).
- Widens the TYPE range field to max 11, renames TYPE 8–11, and hooks the
  per-voice filter call (`0x400780ba`) to run the new DSP (tail-calling the stock
  filter otherwise).
