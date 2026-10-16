# DigiFilter — optimization handoff (1.1a)

A performance pass over the per-voice DSP. **The extra modes' audio is
bit-for-bit identical to 1.1** — only the machine cost changed. This is the
companion to `HANDOFF.md` (session 3, the 1.0k feature work) and the ledger is
also recorded in `RE_NOTES.md` §13 and `CHANGELOG.md`.

Version is **1.1a**. **Status: shipped** — merged to `master`, pushed, and
published as [GitHub release `v1.1a`](https://github.com/DigiAlchemydsp/DigiFilter/releases/tag/v1.1a)
(its package carries **both OS elemods**). Tested on hardware (Digitakt mk1),
OS 1.53 and OS 1.54: **PASS**. It also folds in 1.1 (the OB-1 modes), which was
not released separately.

Where it landed (`master`):

| commit | |
|---|---|
| `499b3a5` | the optimization + OS 1.54 port (code, tests, docs) |
| `72ba614`, `c24944b` | the 1.1a release package (+ the hardware-test rebuild) |
| `af2c765` | merge into `master` |
| `bfd5451` | fold in the 1.1 package (OS 1.53) |
| `c5f3733` | README Releases + Credits sections |
| `8543712` | rebuild the package with the credits/releases docs |
| tag `v1.1a` | the published release |

---

## 0. Result at a glance

Instructions per voice per 32-frame render block (SDK flags, MCF54418, counted in
the patched Unicorn; `tests/df_bench.py`):

| mode | TYPE | 1.1 | 1.1a static | 1.1a swept |
|---|---|---|---|---|
| BP | 8 | 3113 | **1229** (-60 %) | **2424** (-22 %) |
| BP2 | 9 | 3125 | **1229** | **2429** |
| COMB | 10 | 1726 | 1727 | 1727 |
| TRASH | 11 | 1726 | 1727 | 1727 |
| OB4 | 12 | — | ~3178 | ~3180 |
| OB2 | 13 | — | ~3146 | ~3148 |

"static" = knobs held (the coefficient cache hits); "swept" = FREQ stepped one
index between blocks (envelope / LFO). BP/BP2 with static knobs are now
**cheaper than the stock filter** (~2400). COMB/TRASH and OB4/OB2 are untouched.

Footprint: `.run` 15108 → 15156 B, `.bss` 9640 → 9832 B (+192 B for the 8-voice
coefficient cache), 3 sites, 102 → 106 relocations, `imports nothing`; RAM
26132 → 26372 of 131072.

---

## 1. Where the cost was

Two costs dominate the SVF modes, and neither is the sample loop:

1. **`mode_coef` ran twice per block per voice** (`filter.c:svf_run`), even when
   the cutoff and resonance had not moved. Each call inlines **`div55` — a
   32-step software division** (~500 instructions) plus several 32×32 `mulsh`
   products. The render's smoothed cutoff drifts by a fraction per block, so the
   indices usually do not change.
2. **Four separate 8-frame `digifilter_svf` calls** per block, each saving and
   restoring 15 registers *and* MACSR/ACC0/ACCEXT01 (~60 instructions of
   prologue/epilogue, ×4).
3. The SVF MAC loop accumulated both `v1` and `v2` in `ACC0`, serialising the
   two multiplies behind one another — the anti-pattern the eMAC manual warns
   about (`DSPLIBCOLDDFIRE.md` §2.2.1.6, "calculate real and imaginary parts
   simultaneously for better instruction pipelining").

---

## 2. What changed

### `filter.c` — coefficient cache and a fused block call (`svf_run`)

The last block's coefficient set is cached in `svf_c[8]`:

- **Static knobs** (`svf_fi/qi[v]` unchanged): no `mode_coef` at all, and the
  block runs **one** `digifilter_svf(buf, 32, …)` for all 32 frames instead of
  four 8-frame calls.
- **Moving knobs**: one `mode_coef` (was two) is built and ramped from the cached
  set across the four 8-frame sub-blocks — the same linear ramp, so the result is
  identical.
- `mode_coef` writes `c->c1 = k` directly: `mulsh(k, ONE27, 27) == k` exactly for
  `k >= 0`, so the 32×32 `mulsh` is dropped.

`svf_have[v]` is still cleared on a TYPE change (`prev_filt_type`), so the cache
never straddles a mode switch.

### `filter_dsp.s` — dual-accumulator sample loop

`v1 = a1*ic1 + a2*v3` and `v2 = a2*ic1 + a3*v3` are independent, so they now
accumulate in **`ACC0` and `ACC1`** and interleave; the two `movclr.l` reads no
longer stall behind a serial pair. This is a pipeline/cycle effect, not an
instruction-count one (the loop length is unchanged; the prologue gains one
`move.l %d0,%acc1`).

---

## 3. Verification

- **Bit-for-bit output equality**, baseline (HEAD) vs optimized, running the whole
  `digifilter_filt` path for a 19-block sequence that steps FREQ/RESO and switches
  BP→BP2→COMB, comparing the 32-frame buffers and the filter state after every
  call: **0 mismatches**.
- **digiemu end-to-end** (`tests/digiemu_filter_dsp.py`, firmware
  `dt1-2.0t-86d6bd7b`, core 2.1 + digifilter):
  - BP TYPE 8 fi 100 qi 8 → 1.3 % vs model, **PASS**
  - BP2 TYPE 9 fi 80 qi 10 → 0.0 %, **PASS**
  - COMB TYPE 10 fi 64 fb 64 → 0.1 %, **PASS**
  - stock TYPE 1 → output byte-unchanged from stock
- `tests/filter_model.py` → OK. `tests/ob1_model.py` → OK (OB-1 untouched).
- Build + `elekloader.lint` against core 2.1 → `OK: links …`, `imports nothing`.
- `elekloader.patch` with core + digifilter → `OK: the mods combine`.
- **Hardware** (Digitakt mk1): OS 1.53 and OS 1.54 → **PASS**.

---

## 4. The bench (`tests/df_bench.py`, `tests/df_bench.c`)

A permanent per-voice cost bench, in the style of `tests/ob1_bench.py`. It builds
`filter.c` + `ob1_vcf.c` + `filter_dsp.s` with the SDK's own flags, links at
0x10000, and runs `digifilter_filt()` in Unicorn (needs digiemu's patched EMAC
build), counting instructions for the static and swept paths of every mode.

```powershell
# from a digiemu checkout, with m68k-elf-gcc on PATH:
python <DigiFilter>\tests\df_bench.py
```

The 1.1↔1.1a deltas above (and the ~1230 / ~2420 / ~1730 targets) are the
regression guard.

---

## 5. Reproduce the build

```powershell
$env:PATH = "C:\SysGCC\m68k-elf\bin;" + $env:PATH
$env:ELEKLOADER_CROSS = "m68k-elf-"
$env:PYTHONPATH = "C:\Users\benan\Music\ELEKTRON\elekloader"
$stock = "C:\Users\benan\Music\ELEKTRON\digiemu-main\portable\firmware\dt1-1.53-9bdd44bb\Digitakt_OS1.53.syx"
$core  = "C:\Users\benan\Music\ELEKTRON\elekloader\mods\core\out\core-2.1.elemod"
python -m elekloader.sdk.build . --stock $stock
python -m elekloader.lint  out\digifilter-1.1a.elemod --stock $stock --with $core
python -m elekloader.patch --stock $stock --mod $core --mod out\digifilter-1.1a.elemod `
    --out "$env:TEMP\opencode\df-1.1a.syx" --version 2.0t --check
```

The resulting image's sha256 (`86d6bd7b…`) is identical to the build the digiemu
tests above were run against.

---

## 6. Considered and not done

- **`div55` → hardware divide.** Not possible: the MCF54418's `DIVU.L` takes a
  32-bit dividend; the 68020-style 64-bit `Dr:Dq` form is not a ColdFire
  instruction (the assembler rejects `divu.l %d0,%d1:%d2`). With the cache it now
  runs only when the cutoff index changes, so it is off the static path. A
  reciprocal table (`A1[128][16]`) or a Newton–Raphson reciprocal would remove it
  from the swept path too, but was left as unnecessary.
- **Fusing the ramp path's four 8-frame calls** into one call that reloads the
  coefficients mid-block would save ~3 prologues (~5 % of the swept path), at the
  cost of a second copy of the sample loop. Not worth the duplication yet.
- **OB4/OB2** are now the most expensive path (~3000). Its ladder is a chain of
  dependent multiplies (hard to use more accumulators); left untouched.
- **Comb** is already the cheapest (~1730) and unchanged.

---

## 7. Files touched

| file | change |
|---|---|
| `filter.c` | `svf_run` coefficient cache + fused 32-frame call; `mode_coef` `c1 = k`; per-OS address macros |
| `filter_dsp.s` | `ACC0`/`ACC1` interleaved MAC loop; clear `%acc1` in the prologue |
| `filter_ui.c` | per-OS address macros (the port) |
| `tests/df_bench.py`, `tests/df_bench.c` | new per-voice cost bench |
| `CHANGELOG.md` | 1.1a entry (+ the hardware-test note) |
| `README.md` | cost/build figures; `## Releases` and `## Credits` sections |
| `RE_NOTES.md` | §13 optimization, §14 OS 1.54 |
| `releases/README.md` | the 1.1a + 1.1 packages, hardware test, Credits |
| `releases/` | `DigiFilter-1.1a.zip` (both OS elemods), `digifilter-1.1a*.elemod`, folded-in 1.1 |
| `mod.json` | version `1.1` → `1.1a`; `"ports": {"1.54": …}` |

---

## 8. OS 1.54 port and test artifacts

The same tree now builds for **OS 1.54** as well. `tools/port_os.py` (the
DigiFilter ecosystem's porter, from the Tone+FX Digitakt port) mapped the mod's
firmware addresses — all 20 were already in its `os154.json` from the 1.0i port,
so no hand work was needed — and rewrote the sources so each moved address is a
`F_…` (C) or `.LF_…` (assembly) macro resolving per OS, and added the
`"ports": {"1.54": …}` block (sites, `defsym OS154`, `cflags -DOS154`) to
`mod.json`. The 1.53 build is **byte-for-byte unchanged** (the patched 1.53
`.syx` is still `86d6bd7b…`).

Moved addresses (1.53 → 1.54): `0x4199dc44`→`0x4199ec44` (UI_KIT),
`0x4199df58`→`0x4199ef58` (ENV_LEVEL), `0x4197b6b4`→`0x4197c6b4` (ACTIVE_TRACK),
`0x4197cf88`→`0x4197df88` (page layout), `0x401a9d9c`→`0x401aa09c` (descriptor
table), `0x400c19a6`→`0x400c1bce` (FILLRECT), and the three site addresses
`0x401aa45c`, `0x401539b2`, `0x400780ba` (the third unchanged).

### Build and validate (1.54)

```powershell
$env:PYTHONPATH = "<elekloader 0.5+>"          # the OS 1.54-capable checkout
$env:ELEKLOADER_CROSS = "m68k-elf-"
python -m elekloader.sdk.build . --stock <Digitakt_OS1.54.syx> --out out
python -m elekloader.lint  out/digifilter-1.1a-os1.54.elemod --stock <Digitakt_OS1.54.syx> --with <core-4.0-os1.54.elemod>
```

Validated live in digiemu (firmware `dt1-2.0t-ef1ba0b5`, core 4.0 + digifilter
1.1a): BP TYPE 8 (1.3 %), BP2 TYPE 9 (0.0 %), COMB TYPE 10 (0.1 %) against the
model — the **same peaks as the 1.53 build** — and the second FLTR page maps all
eight encoders and reads the kind-7 layout/descriptors correctly (a translated
copy of `tests/digiemu_filter_page2.py`; the committed test hardcodes the 1.53
addresses and the core-2.1 `0x47BE0000` mod region, so it needs the 1.54
addresses to run against a 1.54 image).

### Artifacts

Committed (in `releases/`, published as the GitHub release `v1.1a`):

| file | what |
|---|---|
| `releases/elemods/digifilter-1.1a.elemod` | OS 1.53 mod |
| `releases/elemods/digifilter-1.1a-os1.54.elemod` | OS 1.54 mod |
| `releases/DigiFilter-1.1a.zip` | package: both elemods + sources + docs + README |
| `releases/elemods/digifilter-1.1.elemod`, `releases/DigiFilter-1.1.zip` | the 1.1 package (also folded in) |

Local, ready to flash (gitignored `out/`):

| file | what |
|---|---|
| `out/digifilter-1.1a-1.53-test.syx` | OS 1.53 + core 2.1 + digifilter 1.1a |
| `out/digifilter-1.1a-os1.54-test.syx` | OS 1.54 + core 4.0 + digifilter 1.1a |

