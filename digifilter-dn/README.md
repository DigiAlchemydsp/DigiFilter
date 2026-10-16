# DigiFilter-DN — extra filter modes for Digitone mk1/Keys

Per-track filter modes for the **Digitone mk1 / Keys, OS 1.43 + 1.44**:
`BP`, `BP2`, `COMB`, `TRASH`, `OB4`, `OB2` as **TYPE 4..9**, on top of stock
`OFF / LP2 / HP / LP4` (TYPE 0..3).

Port of [DigiFilter](../README.md) (Digitakt mk1) to the Digitone filter
section, incl. OB-1 (Simon Johansson). Each mode runs per voice and uses that
voice's own **FREQ** (slot 55) and **RESO** (slot 56), exactly like the stock
types. Stock TYPE values keep running the stock multimode filter — nothing here
reimplements a stock mode.

| TYPE | mode | what it is |
|---|---|---|
| 4 | **BP** | band pass (trapezoidal SVF, same kernel as the Digitakt port) |
| 5 | **BP2** | wider band pass (about half the resonance) |
| 6 | **COMB** | feedback comb, delay from FREQ, feedback from RESO |
| 7 | **TRASH** | second comb at half the delay (higher harmonic series) |
| 8 | **OB4** | OB-1 ladder 4-pole (upstream, self-osc ~121) |
| 9 | **OB2** | OB-1 ladder 2-pole (upstream, self-osc ~121) |

> Digitone **mk1 / Keys only**. Digitone II's machines are out of scope.

## Status — 0.1h+thin

- **Audio:** BP/BP2 SVF + COMB/TRASH combs + OB4/OB2 ladder/2-pole. FREQ/RESO
  (+ HARM/DAMP slots 65/26 for COMB/TRASH). Base FREQ only for new (envelope
  TODO all new). ASSUME 48 kHz + slots savable (verify reload).
- **TYPE list to 10** (0..9) with names. G turns past `LP4` to `OB2`.
  (0.1b list to 8/10, 0.1a audio+names.)
- **TYPE icons:** bell/wider/teeth/can/lowpass for 4..9 (full-outer clear in
  0.1f, highlight at outer). Gaps acceptable per feedback.
- **FREQ/RESO curve:** bell/teeth/lowpass (OB1_CURVE, no left taper for OB) for
  4..9 (stock LP4 0..3). Shape open pending 1x scale=1 shots + FREQ/RESO values
  for rectangular BP2 case.
- **HARM/DAMP dials** p2 C/G (ENV-style, 0.1g) for COMB/TRASH (slots 65/26);
  BASE/WIDTH stock always. OB uses FREQ/RESO (no HARM/DAMP, p2 stock).
- Thin 5 files, shared DSP via `../` (no copies, integration in UI).
- 6 sites, `ev_tick` 50 / `ev_draw` 40 / `ev_key,enc` 60. Model `OK`.

## Credits

- **Simon Johansson** (upstream PR #2) — OB4/OB2: OB-1 VCF ladder + 2-pole,
  SPICE/model/kernel/checks (`docs/ob1.md` upstream). Ported to DN (TYPE
  8,9, slots/FREQ/RESO base, curve/glyph lowpass, no envelope yet).

### Known issues / TODO (next)

- **Filter envelope not yet modulated for new types (base FREQ only).**
  Stock types keep envelope. TODO all new (DN envelope level/formula open).
- **Verify on device:** TYPE names/icons/curve for 4..9, HARM/DAMP dials
  (0.1g pending; 0.1f showed labels with empty dotted), audio
  BP/BP2/COMB/TRASH + OB (0.1h built after screenshots, untested), stock
  byte-identity 0..3, locks/polyphony/edge cases (TYPE 4..9 + 182/183,
  LFO/MIDI CC -1, presets, 8-voice OB cost, mode-change clicks), photos.
  Then `fwcheck` timing/margins, 1x screenshots, hardware photos.
- Slots 65/26 savable ASSUME + 48kHz ASSUME (verify save/reload + rate).

## Controls

- **FREQ (E on page 1)** cutoff / comb pitch; **RESO (F)** resonance, and for
  COMB/TRASH the comb **feedback** (0..127, up to 31/32, metallic near
  self-oscillation, saturated). **TYPE (G)** picks the mode. **ENV (H)** and
  the envelope ADSR do nothing for the new modes yet (see above).
- Second page: `DEL/BASE/WIDTH` stock always (base filter accessible). For
  COMB/TRASH, free **C/G** add **HARM/DAMP** (slots 65/26, divider 1..4 /
  0..127 texts, ENV-style dials). OB uses FREQ/RESO (no HARM/DAMP, p2 stock).

## How it works (sites)

| # | addr 1.43 / 1.44 | stock | op | what |
|---|---|---|---|---|
| 0 | `0x4018d7dc` / `0x4018db2c` | `00000300` | `bytes` data → `00000900` | TYPE range max 3→9 (param 29 record +12) |
| 1 | `0x4018d804` / `0x4018db54` | `40014b6c` | `ptr` → `digifilter_dn_typefmt` | TYPE names 4..9, tail-call stock `FMT` otherwise |
| 2 | `0x4009e0b2` / `0x4009e0d2` | `068080004110` | `jsr` → `digifilter_dn_dispatch` | per-voice dispatch (does `addil`, reads TYPE from `fw_voice_params` slot 54, sets `a5` to our DSP or `FILTER`) |
| 3 | `0x4008859c` / `0x400885bc` | `7403` | `bytes` code → `7409` | value-text delegate max 3→9 |
| 4 | `0x400885a2` / `0x400885c2` | `7003` | `bytes` code → `7009` | value-text delegate max 3→9 |
| 5 | `0x400885a4` / `0x400885c4` | `41f9…` | `bytes` code + reloc → `digifilter_dn_types` | value-text table lea (10-entry: stock OFF/LP2/HP/LP4 + BP/BP2/COMB/TRASH/OB4/OB2) |

No new sites for HARM/DAMP — tick RAM (`PAGE2_C/G_AT`) + `core_params`.
`FILTER` is `0x400984b6` (1.43) / `0x400984d6` (1.44) via `defsym` (stock
multimode filter, tail path for stock types). `FMT` is `0x40014b6c` both
versions. `subs` `ev_tick` 50 / `ev_draw` 40 / `ev_key,enc` 60. `contribs`
`core_params` 182/183 order 50/51. `resources` `param:182,183` + `core` 3.1.
`cflags` `PAGE2_C/G` per OS (`0x4136b69c/ac` 1.43, `0x4136c69c/ac` 1.44).
No core sites touched. `fw_voice_params` (`0x800034c4` both) via core 3.1.

Signal path per voice/block: `fw_voices` (Q1.31, `fw_voice_params` slots
with locks) → our SVF/comb/OB in place (or stock filter) → mixer/effects/AMP
as stock. Interrupt level, bounded stack, no alloc, EMAC preserved (SVF
saves `MACSR/ACC0/ACCEXT01`).

## Building

Needs m68k cross (`m68k-elf-`), an elekloader checkout (here
`tools/elekloader/`, ignored, with own git), stock
`Digitone_and_Digitone_Keys_OS1.43.syx` / `...1.44.syx` (ignored, never
committed), and `core-dn1`.

```sh
export ELEKLOADER_CROSS=m68k-elf-
export PYTHONPATH="<elekloader checkout>"

# 1.43 + 1.44
python3 -m elekloader.sdk.build digifilter-dn --stock <...OS1.43.syx>
python3 -m elekloader.sdk.build digifilter-dn --stock <...OS1.44.syx>
python3 -m elekloader.lint digifilter-dn/out/digifilter-dn-0.1h.elemod \
  --stock <...OS1.43.syx> --with <core-4.0.elemod>
python3 -m elekloader.patch --stock <...OS1.43.syx> --mod <core-4.0.elemod> \
  --mod digifilter-dn/out/digifilter-dn-0.1h.elemod --out test.syx \
  --version 0.1h --check
```

Must print `BUILT`, `OK: links as core ...`, `OK: the mods combine`.
Drop `--check` to write `test.syx`. Add `--with <machines-*.elemod>` /
`--mod` to combine with machines (verified). Never flash from the repo dir;
the unit recovers via stock `.syx` (bootloader untouched).

## Files

Thin DN (5 files) + shared via `../` (no copies):

| file | contents |
|---|---|
| `digifilter-dn/mod.json` | id `digifilter-dn`, device `digitone-mk1`, os `1.43` + `ports 1.44`, sources shared via `../`, 6 sites, `subs`/`contribs`/`resources`/`core` 3.1, `cflags` `PAGE2_C/G` per OS |
| `digifilter-dn/filter_glue.s` | `digifilter_dn_typefmt` (4..9 names, tail-call `FMT`), `digifilter_dn_types` (10-entry), `digifilter_dn_dispatch` (buffer + TYPE → `a5`), `.bss` voice/buf |
| `digifilter-dn/filter_ui.c` | `digifilter_dn_filt` (dispatcher globals + slots 54/55/56/65/26, TYPE base 4, base FREQ only) + UI (curve/glyphs/dials, `core_params` 182/183, `tick`/`enc`/`key`/`draw`) |
| `digifilter-dn/README.md` | this file |
| `digifilter-dn/RE_NOTES_DN.md` | RE notes (sites/slots/pages/verification) |
| `../df_dsp.c/h` | shared SVF/comb math + state (firmware-free, 1.1a verbatim) |
| `../filter_dsp.s` | shared SVF EMAC (`digifilter_svf`) |
| `../ob1_vcf.c/h` | shared OB-1 ladder |
| `../filter_tables.h` / `../ob1_tables.h` | shared tables (`G27/K27/COMB_DELAY`, `OB1_CURVE`) |

## Licence

GPL-2.0-or-later. Unofficial, not affiliated with Elektron. No firmware
committed.
