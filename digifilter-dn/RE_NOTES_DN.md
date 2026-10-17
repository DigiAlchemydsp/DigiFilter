# DigiFilter-DN RE notes (Digitone mk1, OS 1.43 + 1.44)

**Device: Digitone mk1/Keys, OS 1.43 (main len 2732208, syx `c5a54cc0…`) and
1.44 (main len 2736304, syx `d4f200d0…`).** Image = stock main OS at
`0x40000400`. Marks: **[S]** static (image bytes), **[L]** needs live
(digiemu DN1 / hardware, pending — no DN1 emulator on this Mac).

Method: `m68k-elf-objdump -m m68k:cfv4e` + Python scans of `main_image`
(via `elekloader.formats`), never writing firmware into the repo. Numeric
addresses below are 1.43; 1.44 in parentheses.

## 1. Filter params — SOLVED [S]

Param records at `0x4018d104` (`0x4018d454` 1.44), 60 B each, ids 0..181
(group/slot/min/max/def/flags/CC/.../name/group/short/fmt/empty). Filter
group = 2:

| param | id | slot | min | max | def | fmt |
|---|---|---|---|---|---|---|
| FREQ | 27 | 55 | 0 | 0x7f00 | 0x7f00 | 0x40013cc8 |
| RESO | 28 | 56 | 0 | 0x7f00 | 0 | 0x40013cc8 |
| TYPE | 29 | 54 | 0 | **0x300** → `0x900` | 0x100 | **0x40014b6c** both |
| ATK | 30 | 58 | 0 | 0x7f00 | 0 | … |
| DEC | 31 | 59 | … | … | 0x4000 | … |
| SUS | 32 | 60 | … | … | 0 | … |
| REL | 33 | 61 | … | … | 0x4000 | … |
| ENV | 34 | 57 | 0 | 0x7f00 | 0x4000 | 0x40013d64 |
| DEL | 35 | 64 | 0 | 0x7f00 | 0 | … |
| BASE | 36 | 62 | 0 | 0x7f00 | 0 | … |
| WIDTH | 37 | 63 | 0 | 0x7f00 | 0x7f00 | … |
| HARM | 182 | 65 | 0 | 0x7f00 | 0 | (new, Filter group) |
| DAMP | 183 | 26 | 0 | 0x7f00 | 0 | (new, Filter group) |

Slot 65 globally free, slot 26 free on synth (Delay WID group 5 + MIDI CC
group 11 elsewhere). Both savable ASSUME. BASE/WIDTH slots 62/63 stock always
(base filter accessible). TYPE range field is record +12: `0x4018d7dc`
(`0x4018db2c` 1.44) `00000300` → `00000900` (site 0). Fmt ptr is record +0x34:
`0x4018d804` (`0x4018db54` 1.44) `40014b6c` → our fmt (site 1, `op:ptr`).

## 2. TYPE names — SOLVED [S]

Formatter `0x40014b6c` both versions: `d0 = 4(sp)>>8`, clamp 0..3
(`moveq #3` + `cmp`), `lea 0x40191090` (`0x401913e0` 1.44) table
`[OFF,LP2,HP,LP4]` (`0x401d897b,0x401d88d0,0x401d88d4,0x401d88d7`),
`sprintf %s` (`0x40000e82`). Only xrefs are the param records (no icon
table elsewhere — DN FLTR pages are knob grids, no stock curve). Our fmt
handles 4..9 (`BP/BP2/COMB/TRASH/OB4/OB2`) and `jmp FMT` otherwise (args
`value@4(sp)`, `dst@8(sp)`, unlike the Digitakt's `8(sp)/0xc(sp)`).

## 3. Render + per-voice filter — SOLVED [S], live [L] pending

Render (vector 191): `VOICE_PREP 0x40098fa4` (`0x40098fc4` 1.44) at
`0x4009e078` (`0x4009e098`), then voices' filter loop `VOICES_LOOP
0x4009e08c` (`0x4009e0ac`) 8×, mixer `0x40096a6c`, master `0x40096e14`
(`0x40096e34`). `a5` = filter `0x400984b6` (`0x400984d6`) via
`lea FILTER,%a5` at `0x4009e04e` (`0x4009e06e`, 6 B `4bf9…`). Loop body
pushes 3 (first call `0x400983c6`/`0x400983e6`) + 5 (filter) = 8 longs,
`jsr %a5@` at `0x4009e0bc` (`0x4009e0dc`), `lea 32,%sp` cleanup.

Filter `0x400984b6` clamps TYPE 0..3 (`cmp #2`/`#3` + `<=0→0`), reads FREQ
(`a3+4` → `0..0x7f000000`), TYPE (`a3+8>>8`), per-voice state at
`0x431f15cc`/`0x8000fa80` etc. Our hook is the free 6-B buffer computation
inside the loop, `0x4009e0b2` (`0x4009e0d2`): `addil #0x80004110,%d0`
(`068080004110`, `fw_voices+voice*128`). Dispatcher does the add, reads
TYPE from `fw_voice_params` slot 54 (`0x800034c4+18+158v+108`, `>>8`),
sets `a5` to ours (4..9) or `FILTER`, stashes voice/buf for the C DSP.
No orig-target memory (unlike Digitakt+digihealth) — `a5` is set once
before the loop, no wrapper. Stock bytes identical both versions.

`fw_voice_params` (`0x800034c4` both) + `fw_voices` (`0x80004110` both) via
core 3.1 (no hardcoded RAM in C besides via `core3.h`). `FW_VOICE_PARAM`
layout `9+79v+k` confirmed in `core3.h`/`core3.inc` (`SKIP 18, STRIDE
158`).

DSP reads HARM slot 65 / DAMP slot 26 (plain at defaults). BASE/WIDTH slots
62/63 stock always. FREQ is d7 (`0x400983c6`'s ENV-modulated result, stashed
by the dispatcher); RESO slot 56. Envelope applied all new (see §5).

## 4. FLTR pages — SOLVED [S]

Pages idx 6/7 via `list[pos]` (FLTR p1/p2). Page records in RAM at
`0x4136b558` (44 B: short/long ptrs + 8 ids + kind 9; `PAGE_REC 0x40089a2c`:
`mulsl #44` + `addil`). Static ctors at `0x4016aeb6`+ write:

- Page 1 `Multi-mode Filter` (`0x401dee2f`): `[30,31,32,33,27,28,29,34]`
  = ATK,DEC,SUS,REL,FREQ,RESO,TYPE,ENV (A..H). TYPE is G (2nd row, 3rd col).
- Page 2 `Base/Width Filter` (`0x401dee41`): `[35,0,0,0,36,37,0,0]`
  = DEL,-,-,-,BASE,WDTH,-,-. Free B/C/D/G/H (5 cells) — C/G free like the
  Digitakt, good for HARM/DAMP.

Tick rewrites C/G (no sites, like DT): stock `[35,0,0,0,36,37,0,0]` →
comb `[35,0,182,0,36,37,183,0]` (C=HARM,G=DAMP, E/F BASE/WIDTH stock always).
No new sites for HARM/DAMP — tick RAM + `core_params` (182/183 order 50/51).

Pedal shell geometry: `col_x [33,59,86,112]`, `ROW_Y 15/42`, 17 px knobs.
Curve in 20..71, glyphs with full-outer clear in 78..92, dials (86,42 C HARM /
86,15 G DAMP, ENV-style) for COMB/TRASH. Layouts same as DT per feedback
(centre 85/45.5).

## 5. Envelope / FREQ / RESO mapping — SOLVED [S], live [L]

The render computes each voice's cutoff before calling the filter: inside the
voices' loop it calls `0x400983c6` (`0x400983e6` 1.44) with (voice, a per-voice
value, `a2+0x50`) and keeps the result in **d7**. That routine reads FREQ
(`fw_voice_params` slot 55 via `a0@(2)`), ENV (slot 57 via `a0@(6)`), a key/vel
term and the voice's filter-envelope level (`0x41391784 + 12*v` via
`0x400990ae`), and returns `clamp(FREQ<<16 + keyterm + (ENV-0x4000)<<17 *
envlevel * 0x483244b3, 0, 0x7f000000)` — FREQ plus the filter envelope. The
render then stores d7 into the voice's 16-byte block (`a3@(0)`) right after the
filter call, and the stock filter consumes it (with `a0@(4)`, the raw value).

So base-FREQ-only was the bug: `digifilter_dn_filt` read slot 55 directly and
never saw ENV. The fix is adapter-only: the dispatcher (`filter_glue.s`) stashes
**d7** in `digifilter_dn_cut` at the dispatch site (it was already there, before
the render overwrites d0 with the buffer), and `digifilter_dn_filt` derives
`fi = cut>>24` (0..127, SVF/comb) and `fi8 = cut>>16` (0..127<<8, OB) from it.
`ENV = 0x4000` (default) is zero modulation, so the mapping is unchanged then.

`fi`/`fi8` for all new types now track ENV/ADSR exactly as the stock types.
RESO still comes straight from slot 56: `qi = RESO>>11` (BP/BP2, capped 13/15,
BP2 halves), `fb = RESO>>8` (COMB/TRASH → 0..31/32). 48 kHz
(`COMB_DELAY = round(48000/HZ)`) ASSUME; SVF/comb cost vs stock DN filter (DT:
stock ~2400, BP ~2800, COMB ~1750 per voice/block) verified in digiemu (§8).

## 6. Sites (0.1h, both OS, stock bytes verified via `patch --check`)

| site | 1.43 | 1.44 | stock | new/op |
|---|---|---|---|---|
| TYPE range | 0x4018d7dc | 0x4018db2c | 00000300 | 00000900, `bytes` data |
| TYPE fmt | 0x4018d804 | 0x4018db54 | 40014b6c | `ptr` → `digifilter_dn_typefmt` |
| dispatch | 0x4009e0b2 | 0x4009e0d2 | 068080004110 | `jsr` → `digifilter_dn_dispatch` |
| value-text max1 | 0x4008859c | 0x400885bc | 7403 | 7409 (`moveq #3`→`#9,d2`), `bytes` code |
| value-text max2 | 0x400885a2 | 0x400885c2 | 7003 | 7009 (`moveq #3`→`#9,d0`), `bytes` code |
| value-text table | 0x400885a4 | 0x400885c4 | 41f9401a7290 / 41f9401a75e0 | 41f9+`digifilter_dn_types` (10 ptrs: stock OFF/LP2/HP/LP4 + BP/BP2/COMB/TRASH/OB4/OB2), `bytes` code + relocs |

No new sites for HARM/DAMP — tick RAM + `core_params`.

`FILTER` 0x400984b6/0x400984d6, `FMT` 0x40014b6c both, `OFF/LP2/HP/LP4_STR`
per OS (1.43 `0x401d897b/d0/d4/d7`, 1.44 `0x401d8d4b/a0/a4/a7`), via `defsym`.
`PAGE2_C/G_AT` per OS (`0x4136b69c/ac` 1.43, `0x4136c69c/ac` 1.44) via `cflags`.
Display uses the value-text delegate (max+table), not param fmt — param fmt
hook kept for popup/other paths. No core-site overlap. Combines with `core` +
`machines` (different tables/ids, no overlap: machines `dn_machines` +
override SYN ids vs ours `core_params` 182/183 + filter TYPE values).

## 7. Verification (0.1h+thin)

- Host `tests/filter_model.py` → `OK` (shared SVF reference, tables unchanged).
- `sdk.build digifilter-dn` 1.43 + 1.44 → `BUILT` (6 sites, shared via `../`,
  no copies, integration in UI).
- `lint` both + `core-dn1` 4.0 (+ `machines-dn1` 0.1 for override/param
  coexistence) → `OK: links` (no `core_param_ui_make`; override removed;
  `core_params` only).
- `patch --check` both (+ machines) → `OK: the mods combine`, stock bytes,
  whole instructions.
- Manual GUI list/names/audio for BP/BP2/COMB/TRASH in 0.1f + OB pending 0.1h
  test (0.1h built after screenshots, untested). HARM/DAMP dials 0.1g pending
  (0.1f showed labels with empty dotted, dials added in 0.1g). Glyph outer gaps
  acceptable, curve rectangular open.
- Pending: `fwcheck` timing/margins, 1x screenshots, hardware photos,
  locks/polyphony/edge cases (TYPE 4..9 + 182/183, LFO/MIDI CC -1, presets,
  8-voice OB cost (see §8), mode-change clicks). 48kHz + slots saved ASSUME
  (verify save/reload + rate on device, like DT HANDOFF open items).

## 8. Per-voice cost guard — OB freeze fixed (0.1h)

`VOICES_LOOP` dispatches all 8 voices every block, sounding or not, and an
idle voice hands the filter a 32-word **all-zero** block (confirmed with an
empty pattern: 1199/1199 blocks zero for every voice; `fw_voice_len` also 0).
Running new DSP on that silence is pure waste, and 8× of it overran the audio
block: with TYPE OB4/OB2 and an empty pattern the render dropped to ~1428
blocks/s and PIT0/PIT2/PIT3/DTIM3 **all froze** (audio ISR starves the OS
timers; pattern/transport irrelevant, the emptiness is the worst case). Forced
N-voice boundary (voices ≥ N → stock FILTER): ≤6 sounding OB voices healthy,
7 marginal, 8 fall off.

Fix is adapter-only (no OB change): `digifilter_dn_filt` first scans the
voice's 32-word block; if all zero it drops the voice's DSP state once
(`df_reset` + `ob1_vcf_reset`, tracked by `dn_sounding[8]`) and returns
without running the DSP. Type-independent; sound with a sounding voice is
unchanged (the stock filter's own per-voice "active" mask arg is 0 in normal
playback, so it is not a usable gate). Earlier `digifilter_dn_filt` address is
unchanged (`0x43ec2896` both OS).

Verified in digiemu (fresh hash-matched snapshots, 64M ips): empty-pattern OB4
→ `ob1_vcf_run` called **0** times (was ~3424), PIT0/PIT2/DTIM3 healthy,
1500 blocks/s; 4 sounding voices → ~1800 OB calls, still healthy; 8 sounding
voices still overload (intrinsic OB cost, per-voice work unaffected). So a
4-note chord on one track (4 voices) is fixed.
