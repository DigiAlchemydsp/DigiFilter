# Changelog

All notable changes to DigiFilter. Format-2
[elekloader](https://github.com/irpina/elekloader) mod for the Elektron
Digitakt **mk1, OS 1.53**. Versioned as `<major>.<minor><letter>`.

## [1.1a] - 2026-10-16

Performance pass on the per-voice DSP. The extra modes sound bit-for-bit
identical to 1.1; only the cost changed.

### Performance

- **BP / BP2** (the state-variable filter): the coefficients are now cached and
  recomputed only when the cutoff/resonance indices actually move, and with
  static knobs the SVF runs one `digifilter_svf` call for the whole 32-frame
  block instead of four 8-frame calls. Instructions per voice per render block:
  **3113 → 1229** static (-60 %), **3113 → 2424** while the cutoff is swept
  (-22 %). The coefficients are bit-identical, so the audio is too.
- The SVF sample loop keeps the `v1` and `v2` MAC chains in separate eMAC
  accumulators (ACC0/ACC1), so the two multiplies per sample interleave instead
  of serialising (DSPLIBUM §2.2.1.6).
- `mode_coef` writes `c1` directly (`c1 = k`, exact) instead of a 32×32 `mulsh`.

### Internals

- New `tests/df_bench.py` (+ `tests/df_bench.c`) counts the per-voice
  instructions per block for every mode in Unicorn, so the cost is tracked.
- **OS 1.54.** `mod.json` gains a `"ports": {"1.54": …}` block (the moved
  firmware addresses and the site bytes) and the sources name each moved address
  through a per-OS `F_…`/`.LF_…` macro, so the same tree builds for OS 1.53 and
  1.54 (elekloader 0.5+). The 1.53 build is byte-for-byte unchanged.

### Verified

- Tested on hardware (Digitakt mk1), OS 1.53 and OS 1.54: **PASS**.

## [1.1] - 2026-10-16

The OB-1's filter as two more types (contributed by Simon Johansson, PR #2).

### Added

- **OB4 (TYPE 12)**: the Oberheim OB-1's 4-pole lowpass ladder — four CA3080
  OTA stages with the resonance fed back from the fourth, saturating where the
  circuit does (U28). RESO self-oscillates from about 121, so it rings at FREQ
  with no input.
- **OB2 (TYPE 13)**: the OB-1's 2-pole output — stage 2 tapped while the
  resonance loop stays closed from stage 4, so it resonates and self-oscillates
  like OB4 but rolls off at 12 dB/oct.
- Both use the track's FREQ, RESO and filter envelope as the other modes do, and
  the FLTR page draws their lowpass response plus a TYPE-box glyph.
- New source `ob1_vcf.c`/`.h` (the fixed-point kernel) and `ob1_tables.h`, with
  `tests/ob1_*`, `tests/spice/` and `tests/digiemu_filter_ob1_*.py`; how they
  were made and checked is in [docs/ob1.md](docs/ob1.md).

### Changed

- Widens the Filter Type range field from max 11 to max 13 and renames TYPE
  11–13 (`BP / BP2 / COMB / TRASH / OB4 / OB2`) in `mod.json`,
  `filter_glue.s`, `filter.c` and `filter_ui.c`.

## [1.0k] - 2026-10-05

The second FLTR page gets its own COMB/TRASH controls, alongside the stock ones.

### Added

- While a track's TYPE is COMB or TRASH, the **RESO / GAIN knob on page 1** is
  the comb's feedback (0…127, up to **31/32** — near self-oscillation, for a
  metallic ringing comb), and the second FLTR page's free encoders add
  **C = Harmonics** (delay divider 1–4) and **G = Damping** (a one-pole on the
  feedback), labelled **HARM / DAMP** and drawn as round dials like the stock
  SRR knob.

### Fixed

- **BP (TYPE 8) no longer distorts** on hot material (notably FREQ 44–60): the
  SVF output is now saturated to ±2^27 like the comb, so a high-Q peak clips
  cleanly instead of wrapping the 32-bit sample.

### Changed

- The stock **Base / Width / Env Delay / SRR** controls are **not** replaced —
  they stay on their own encoders and keep saving with the kit, together with
  the new controls. The comb DSP uses the RESO/GAIN feedback and the new
  Harmonics/Damping only; there is no separate feedback control on page 2.
- The FLTR page-1 response curve's comb depth now follows the RESO/GAIN knob.

### Internals

- On each UI tick, when the active track is COMB/TRASH, `filter_ui.c:page2_setup`
  commandeers two unused `Error` descriptors (`14/15`) as real filter descriptors
  on spare sound slots (`0x2f/0x30`) and puts them on C/G; the stock layout and
  descriptors are restored for every other TYPE.
- The two values live in the spare slots. For kit persistence they are mirrored
  (0..127, stored as value+1) into the low bytes of the savable Base / Width
  words, which are otherwise always 0, and the spare slots are restored from them
  after a load. (The sound serializer only carries slots 0..45; the spare slots
  fall outside it.)
- New test `tests/digiemu_filter_page2.py`; the DSP/envelope/curve tests updated
  for the new controls.

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
