# DigiFilter — handoff (session 3)

Per-track filter modes for the **Digitakt mk1, OS 1.53**: `BP`, `BP2`, `COMB`,
`TRASH` (TYPE 8–11). The audio path, filter envelope, second FLTR page, response
curve and TYPE glyph were done in sessions 1–2 (1.0h–1.0i). This session is
**1.0k**, which reworks the second FLTR page and fixes BP clipping.

Version is **1.0k**, **uncommitted** (HEAD is `a415ed1`, the 1.0j release).

---

## 0. Environment (all present on this machine)

| what | where |
|---|---|
| elekloader checkout | `C:\Users\benan\Music\ELEKTRON\elekloader` |
| core 2.1 mod | `...\elekloader\mods\core\out\core-2.1.elemod` |
| digiemu source | `C:\Users\benan\Music\ELEKTRON\digiemu-main` |
| m68k toolchain | `C:\SysGCC\m68k-elf\bin` |
| stock OS 1.53 | `...\digiemu-main\portable\firmware\dt1-1.53-9bdd44bb\Digitakt_OS1.53.syx` |

Build shell (PowerShell):

```powershell
$env:PATH = "C:\SysGCC\m68k-elf\bin;" + $env:PATH
$env:ELEKLOADER_CROSS = "m68k-elf-"
$env:PYTHONPATH = "C:\Users\benan\Music\ELEKTRON\elekloader"
$stock = "C:\Users\benan\Music\ELEKTRON\digiemu-main\portable\firmware\dt1-1.53-9bdd44bb\Digitakt_OS1.53.syx"
$core  = "C:\Users\benan\Music\ELEKTRON\elekloader\mods\core\out\core-2.1.elemod"
python -m elekloader.sdk.build . --stock $stock
python -m elekloader.lint out\digifilter-1.0k.elemod --stock $stock --with $core
python -m elekloader.patch --stock $stock --mod $core --mod out\digifilter-1.0k.elemod `
    --out "$env:TEMP\opencode\df-custom.syx" --version 2.0t --check
```

Last run: `BUILT` (.run 8750, .bss 9636); `OK: links as core 2.1 …`; `OK: the
mods combine`; RAM 19772 / 131072.

### Emulator

The **patched Unicorn** is required (installed in a prior session; verify with
`python -m emu.unicorn_compat` → `"compatible": true`). Build a firmware with
core + digifilter, then add it (from `digiemu-main`):

```powershell
python -m elekloader.patch --stock $stock --mod $core --mod out\digifilter-1.0k.elemod `
    --out "$env:TEMP\opencode\df-1.0k.syx" --version 2.0t
python -m emu.portable --add "$env:TEMP\opencode\df-1.0k.syx" --yes   # makes a new folder by hash
```

The firmware used for the 1.0k tests is **`dt1-2.0t-2436b9a0`** (metallic comb +
BP saturation). Earlier 1.0k iterations were `dt1-2.0t-4e4ed21a`, `-07fd1719`,
`-9ddbdbd0`, `-85963c11`, `-5e2df294`, `-fce7d650`. After any code change,
re-run `sdk.build` + `patch` + `emu.portable --add` and point the tests at the
new folder.

---

## 1. Second FLTR page — its own COMB/TRASH controls (1.0k)

The second FLTR page (page kind **7**) is stock
`{EnvDelay, —, —, SRR, Base, Width, —, Routing}` = ids `[39,0,0,42,40,41,0,43]`
(encoders A..H; id 0 = empty box). For COMB/TRASH the mod adds controls on the
free **C/G** encoders and leaves the stock ones working:

| enc | A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|---|
| | DEL (stock) | — | **HARM** | SRR (stock) | BASE (stock) | WDTH (stock) | **DAMP** | ROUT (stock) |

- **Mechanism** (`filter_ui.c:page2_setup`, called from `digifilter_tick` every
  UI tick): for a COMB/TRASH track it **commandeers two unused `Error`
  descriptors** (`14/15`) into real filter descriptors — group 6, slot
  `0x2f/0x30`, range `0x7f00`, step `0x0100`, short names `HARM`/`DAMP` — and
  sets the kind-7 layout to `[39,0,14,42,40,41,15,43]`. Any other TYPE restores
  the stock layout and the original descriptor bytes.
- **Labels** are drawn by the stock page from the descriptor short names. The
  **value widget** is *not* (the parameter model rejects a slot past `0x2d`), so
  `digifilter_draw` paints a stock-style **round dial** (midpoint circle r=8 +
  needle) into the two empty C/G cells on page kind 7. Positions: x 85, top row
  y 41, bottom row y 15.
- **Feedback is the RESO/GAIN knob** (page 1, slot `0x1b`), 0..127 → **0 .. 31/32**
  (near self-oscillation, metallic). It combines the stock resonance/gain and the
  comb feedback and drives the response-curve teeth up. There is **no separate
  feedback control on page 2** (the earlier `FEED` was removed).
- The comb DSP reads: feedback from the engine RESO slot (`SET_RESO(v) >> 8`),
  Harmonics from slot `0x2f` (divider `1 + h*3/127`), Damping from `0x30`.
- **Persistence (best-effort):** the two values live in spare sound slots
  `0x2f/0x30`, which the sound serializer (a permutation of the savable slots
  **0..45**) does not carry. `filter.c:df_persist` mirrors them (0..127, stored
  as `value+1`) into the low byte of the savable Base/Width words and restores
  the spare slots from those low bytes after a load. **Not verified on device**
  (see §4).

Authoritative write-up: `RE_NOTES.md` §12.

## 2. BP (TYPE 8) clipping — FIXED (1.0k)

`filter_dsp.s` now **saturates the SVF output to ±2^27** (the same limit the comb
uses), so a high-Q peak on hot material clips cleanly instead of wrapping the
32-bit sample. The resonance range is also capped at Q ~5 (`mode_coef`, 13/15).
Debug notes: at FREQ 44–60 the band-pass gain is normalised (~1.0 across fi
38–67), so the distortion was the peak exceeding full scale on hot
material/transients; with the fix a 2× full-scale input clamps at exactly `2^27`.
A soft-clip would be gentler (open item).

## 3. Tests

New: `tests/digiemu_filter_page2.py` — opens the second FLTR page, forces TYPE
COMB, and checks A/D/E/F/H move the stock slots (`0x23/0x24/0x21/0x22/0x25`), B
moves nothing, C/G move `0x2f/0x30`, the layout reads `[39,0,14,42,40,41,15,43]`,
descriptors 14/15 are group-6 filter descriptors with mod names, and a stock TYPE
restores `[39,0,0,42,40,41,0,43]` + the `Error` descriptors.

Updated: `digiemu_filter_dsp.py` (feedback from the RESO engine slot; `--amp`,
`--tone` added; model `g = fb*31/(127*32)`), `digiemu_filter_comb2.py`,
`digiemu_filter_env_mod.py`, `digiemu_filter_curve.py` (feedback slot 0x2f).

All PASS on `dt1-2.0t-2436b9a0`: `filter_model.py`, dsp BP/BP2/COMB/TRASH (incl.
fb 127), comb2, env_mod, curve, page2, real.

Run (one emulator at a time — they share the firmware session):

```powershell
python tests/digiemu_filter_page2.py --digiemu C:\Users\benan\Music\ELEKTRON\digiemu-main --fw dt1-2.0t-2436b9a0
```

## 4. Open items / next

1. **Commit and push 1.0k** (working tree is uncommitted; release artifacts
   `releases/elemods/digifilter-1.0k.elemod` + `releases/DigiFilter-1.0k.zip`
   are present).
2. **Kit persistence of HARM/DAMP** is best-effort and **unverified**: the
   emulator's pattern-save sequence does not round-trip even the stock TYPE, so
   the low-byte channel could not be confirmed. Verify on device (save pattern →
   power cycle → read slots `0x2f/0x30`).
3. Optional: **soft-clip** in the SVF instead of the hard clip.
4. Optional: give the empty **B** cell (and the stock ROUT) a purpose, or move
   HARM/DAMP to B/C to leave one gap.
5. Untracked `shots/` holds UI screenshots (not referenced by the docs; decide
   whether to commit, move under `docs/`, or delete).

## 5. Diagnostics written this session (in `%TEMP%\opencode\`, not committed)

| file | what it does |
|---|---|
| `df_layout.py` | dumps the page-layout table and descriptor names from a running snapshot |
| `df_page2.py` | second-page encoder→slot probe (optionally re-maps the layout) |
| `df_names.py` | proves a descriptor short-name pointer can be repointed live |
| `df_commandeer.py` | proves an unused `Error` descriptor can be turned into a real knob |
| `df_widget.py` | why a commandeered descriptor's value box is empty (slot past 0x2d) |
| `df_shot.py` | captures FLTR page frames as PNGs (page 1, page 2 comb/stock) |
| `df_bp.py` | injects a phase-continuous tone at the BP cutoff to look for wrap |
