# Changelog

All notable changes to DigiFilter. Format-2
[elekloader](https://github.com/irpina/elekloader) mods for the Elektron
**Digitakt mk1 (OS 1.54)** and **Digitone mk1/Keys (OS 1.44)**. Versioned as
`<major>.<minor><letter>`.

## [1.2] - 2026-10-22

Unified latest-OS release: one elemod per machine, built from one shared DSP
core.

### Added

- **Digitone mk1/Keys Filter+FX port**: VOWEL/BANK/FOLD/CRUSH/RING/PHASER/
  FLANGER as TYPE 4..10, per-voice FREQ/RESO, AUX1/AUX2 on page-2 C/G for
  VOWEL/BANK, TYPE names, response/transfer graphs and TYPE icons.
- `shared/`: the firmware-free DSP cores (`df_dsp.c/h`, `filter_dsp.s`,
  `ob1_vcf.c/h` for DT; `fx_dsp.c`, `biquad_dsp.s` and their tables for DN).
- `tools/build_release.py`: builds, lints, patch-checks and packages both
  elemods.

### Performance

- **DT comb core:** the comb's delay divisor (1..8) now uses a small reciprocal
  table instead of a software division. With digiemu's cycle model, COMB/TRASH
  drops from ~2090 to ~2046 cycles static and ~2075 to ~2025 swept per voice
  per block.
- **DN per-voice adapter:** reads its `fw_voice_params` block once per block
  (`TYPE`/`RESO`/`AUX1`/`AUX2`) instead of recomputing the voice base for every
  slot, and uses one-compare bounds checks instead of the generic clamps.
- **DN UI:** finds both FLTR pages in one view-list walk and caches the
  response/transfer curve until mode/FREQ/RESO changes.
- **DT:** curve caching and run-length icon drawing. BP/BP2 also drop about 1%
  of their cycles from the bounds-check change.

### Changed

- Repository split into `digifilter-dt/`, `digifilter-dn/` and `shared/`.
- **Latest OS only:** Digitakt 1.54 (1.53 removed) and Digitone 1.44 (1.43
  removed). The `ports` blocks and per-OS conditionals are gone.
- Both mods now require **core 4.0** (`core-4.0-os1.54` /
  `core-dn1-4.0-os1.44`).
- The Digitakt FLTR TYPE box now clears the full 17x17 cell (77..93 / 7..23)
  and draws the Digitone's bitmap icons, masking the stock `EQ n` artwork
  cleanly.
- **OB4/OB2 resonance (Digitakt)** is scaled to **75% of the 0..127 travel**,
  to keep the ladder out of heavy saturation at the top of the knob. The drawn
  OB curve uses the same scaled depth. Self-oscillation moves from about RESO 81
  to about knob 108.
- **DN TYPE persistence:** the stock temp save (FUNC+YES) resets the sound TYPE
  field above 3 on reload. TYPE 4..10 is now mirrored into the low byte of BASE
  (a stock savable 8.8 param) and restored on the next UI tick. Stock TYPE 0..3
  still persist natively; AUX1/AUX2 remain best-effort.

### Docs

- DN: document the Filter+FX modes, the VOWEL/BANK AUX1/AUX2 controls, the
  TYPE mirror that makes FUNC+YES/FUNC+NO persist TYPE 4..10, and the
  PTN/GLOBAL project paths for AUX1/AUX2.

### Releases

- `DigiFilter-1.2.zip` carries `elemods/digifilter-1.2.elemod` (Digitakt 1.54)
  and `elemods/digifilter-dn-1.2.elemod` (Digitone 1.44).

## [1.1b] - 2026-10-18

Performance passes on the SVF (BP/BP2) and the COMB/TRASH and OB4/OB2 paths. The
audio is bit-for-bit identical (verified against a Git baseline) except the OB
saturation table, whose drift is bounded at ~-100 dBFS; see `RE_NOTES.md`
§15–§16.

### Performance

- **BP / BP2**: the SVF's only division — its `a1 = 1/(1+g(g+k))` coefficient —
  is now a precomputed 14×128 table (`tools/gen_svf_a1.py`, generated from the
  module's own `div55` so the values are exact). The swept (envelope/LFO) path no
  longer runs any software division: **2424 → 1635** instructions per voice per
  block (-33 %). Static knobs: **1229 → 1072** (-13 %).
- The SVF sample loop drops the always-zero `c2*v2` MAC, updates `ic1`/`ic2` in
  place (8 → 6 instructions), and hoists the ±2^27 clamp constants out of the
  loop.
- The ramped block (cutoff moving) now runs in a single `digifilter_svf4` call
  that reloads the four sub-block coefficient sets, instead of four `8`-frame
  calls (one register/EMAC save-restore instead of four).
- **COMB / TRASH**: the damping-off loop is now its own path, so the per-sample
  `damp` branch and the stack-resident smoothing state are gone:
  **1727 → 1693** instructions and **2053 → 2016** core cycles per voice per
  block (~2 %).
- **OB4 / OB2**: the coefficient set is cached per voice and only recomputed
  when `(FREQ, RESO)` changes; static knobs skip the divide and the table walks.
- **OB4 / OB2 saturation**: U28's correction polynomial is now a 512-segment
  interpolated table (`ob1_fbsat_table.h`), replacing two `z^2`/`z^4` multiplies
  and the weight scaling. Together with the cache: **3183 → 3213** instructions
  but **5030 → 4867** cycles (-3.2 %) at RESO 64. The table is exact at its
  points; between them the error is bounded at ~1.4e3 internal LSB (~-100 dBFS),
  checked by `tests/ob1_table_accuracy.py`. Build with `-DOB1_FBSAT_EXACT` for
  the original polynomial.

### Internals

- New `svf_a1_tables.h` (+ `tools/gen_svf_a1.py`, `tools/gen_svf_a1.c`) and
  `ob1_fbsat_table.h` (+ `tools/gen_ob1_fbsat.py`). `.run` 15156 → 25296 B
  (+10.1 KB: the 7.3 KB SVF table, the 2.0 KB saturation table and ~0.8 KB of
  code), `.bss` 9832 → 9928 B (+96 B); RAM 33700 → 36608 of 131072, 3 sites,
  113 relocations, `imports nothing`.
- `tests/df_bench.py` now sets RESO correctly for the OB modes and reports
  MCF54418 core cycles through digiemu's `emu.cftiming` when available.
- New `tests/comb_equivalence.py`: COMB/TRASH output and delay-line state
  against a Git baseline, on ColdFire.
- New `tests/ob1_table_accuracy.py`: the fbsat table's error against the exact
  polynomial, plus the full OB path's output/state drift (ColdFire).
- The DSPLIB IIR32/FFT routines were evaluated and do not fit these kernels
  (serial ladder recursion; sparse delay-line IIR; non-Q31 operand scaling);
  see `RE_NOTES.md` §16.

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
