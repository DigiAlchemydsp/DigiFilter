# OB4 and OB2: the Oberheim OB-1's filter

Two filter types, TYPE 12 and 13, modelled on the Oberheim OB-1's VCF: **OB4** is its 4-pole lowpass and
**OB2** its 2-pole output. On the OB-1 the 2-pole mode takes stage 2 while the resonance loop stays closed
from stage 4, so OB2 resonates and self-oscillates like OB4 but rolls off at 12 dB per octave. Both use the
track's FREQ, RESO and filter envelope as the other types do. This page is how they were made and checked;
the README has how to use them.

## The circuit

From the OB-1's synth board schematic (sheet 1342; the full reading:
https://github.com/simonjohansson/DigiFilter/issues/2): four CA3080 one-pole stages, alternating
non-inverting and inverting, so stage 4 follows the input; a fifth 3080 (U28) feeds stage 4 back to the
input as negative feedback, the ladder's resonance; the MODE switch takes the output from stage 2 or 4.
Cutoff is 1 V/oct through an exponential converter; resonance is linear in its control voltage, and the
OB-1 self-oscillates (a trimmer sets where). The stages run at ~1/455 of the signal, so the filter is
clean until there is resonance: then U28 saturates.

## How it was checked

1. **SPICE** (`tests/spice/`, ngspice): the stages as tanh transconductors into 300 pF, the dividers and
   U28's loop. It confirmed the reading (a 4-pole cascade, 24 dB/oct, the passband falling as 1/(1 + k)),
   gave the loop gain (k ~ 4.15 per mA of U28's bias, self-oscillation at ~0.96 mA, independent of the
   cutoff), and showed where the circuit distorts.
2. **The model** (`tests/ob1_model.py`): a zero-delay-feedback ladder of trapezoidal one-poles with U28's
   tanh in the feedback and each stage's OTA tanh. Its linear response is exactly the analog prototype's
   bilinear transform; its distortion matches SPICE's within 1.3 dB without resonance and 0.5 dB at k 3.3.
3. **The kernel** (`ob1_vcf.c`): Q31 fixed point with ColdFire EMAC multiplies, U28's saturation as tanh's
   series to the fifth power, the coefficients ramped across each block, and a -102 dB seed near
   self-oscillation so it starts from silence. Checked against the model on the host (`tests/ob1_check.py`,
   `tests/ob1_artefacts.py`).
4. **The firmware** (digiemu, core 4.0 + DigiFilter, OS 1.53; `tests/digiemu_filter_ob1_*.py`): the
   kernel in the firmware against its host build, TYPE 13 chosen with the encoder through the render, the
   FLTR page, saving and reloading a project, copying a track's Sound, and a stock 1.53 loading such a
   project.
5. **A unit** (Digitakt mk1, OS 1.53), with the elektrob-1 OB-1 machine as the source.

## Figures

`tests/ob1_plots.py` draws the first three (cc, matplotlib; ngspice for the SPICE ones). The FLTR page is
from digiemu.

![OB4's and OB2's response at FREQ 64 for four RESO settings: the model's lines and the kernel's points](img/ob1-response.png)

![The circuit in SPICE against the model's ladder at six resonance currents, both outputs](img/ob1-spice.png)

![Distortion against input level: SPICE, the model and the kernel, without resonance and at k 3.3](img/ob1-thd.png)

![The FLTR page for the stock LP, OB4 and OB2 at FREQ 64, RESO 64](img/ob1-fltr.png)

## Results

| | |
|---|---|
| model | the linear ladder matches the analog prototype; 24 / 12 dB per octave; passband 0.25 / (1 + k); self-oscillation from k = 4; distortion within 1.3 dB of SPICE (no resonance) and 0.5 dB (k 3.33) |
| saturation | with resonance in U28, the resonance OTA (knee 1.61 x a VCO at stage 4); without, only the stages' own OTAs, and slightly (knee 4.9). The kernel has U28's |
| kernel vs model | linear: worst error 3.4e-4 of the peak over FREQ 16-127 x RESO 0-115 x both outputs; distortion within 0.4 dB at 0.5-2 x a VCO, k 3.34 |
| level | the render's blocks are Q31; a full-scale sample is two OB-1 VCOs at ON (`IN_SHIFT`), so a hot mix saturates as two would. The output saturates rather than wraps |
| full-scale input and sweeps | no wrap-around at low cutoff; a full-scale sweep FREQ 20-90-20 at RESO 100 steps no more than a gliding model (0.0348 against 0.0346) |
| cutoff sweep | one FREQ step a block: within 1.8e-3 of a sample-by-sample glide |
| self-oscillation | from silence at RESO 127: about 0.05 s at FREQ 96, 0.35 s at 64, 1 s at 48, 3 s at 32 (the margin past k = 4 sets it; the seed's random sign lets a low cutoff start); the seed only from RESO 119 up |
| artefacts | silence in gives exactly silence out below RESO 119; after a loud note the output settles within 176 LSB (-142 dB) of zero (fixed point's dead band); stable at every corner of the knobs; aliasing 147 dB or more under the fundamental |
| cost | 3035 (OB4) and 2971 (OB2) instructions per block; through the dispatch ~3080 / ~3010. Stock LP 2378, BP ~2800 |
| in the firmware | `digifilter_filt` for TYPE 12/13 in a restored snapshot matches the host build within 156 LSB of Q31 at one VCO's level |
| FLTR page | OB4/OB2 draw their response (by RESO) and a lowpass glyph in the TYPE box (`tests/digiemu_filter_ob1_curve.py`) |
| real UI path | TYPE stepped to 13 with the encoder, through the render, FREQ 80, RESO 64, 1500 Hz: 0.07654 against the model's 0.07653 (`tests/digiemu_filter_ob1_real.py`) |
| save / reload | TYPE 12 and 13 saved to the +Drive, rebuilt from the card, loaded back: unchanged (`tests/digiemu_filter_ob1_persist.py`); stock 1.53 loads and plays such a project |
| copy / paste | a track's Sound with TYPE 12 or 13 copied to another track: unchanged (`tests/digiemu_filter_ob1_copy.py`) |

## Tunable, and not checked

- `IN_SHIFT` (the level) and `K_MAX8` (where RESO self-oscillates, ~121, and how fast RESO 127 starts) in `ob1_vcf.c`.
- Not checked: a Sound with TYPE 12/13 exported to the +Drive and imported back. Sounds are saved by the same serializer as projects (RE_NOTES §8), which the project save/reload exercises.
- OS 1.53 only, as DigiFilter.

## Files

| file | what |
|---|---|
| `ob1_vcf.c`, `ob1_vcf.h` | the kernel |
| `ob1_tables.h` | the ladder's G per FREQ index (the stock FREQ curve) and the FLTR page's curves; generated |
| `tests/ob1_model.py` | the floating-point reference and its self-test; `--table` writes `ob1_tables.h` |
| `tests/ob1_check.py` | the kernel (host build) against the model |
| `tests/ob1_artefacts.py` | the kernel's digital artefacts: silence, stability, aliasing |
| `tests/ob1_bench.c`, `tests/ob1_bench.py` | the kernel's ColdFire cost per block, in Unicorn |
| `tests/ob1_plots.py` | the figures |
| `tests/spice/` | the circuit (ngspice): `ob1_ac.cir` the responses against the resonance, `ob1_thd.cir` the distortion |
| `tests/digiemu_filter_ob1_*.py` | the firmware in digiemu: curve, real UI path, save/reload, copy/paste |

From the repository's root:

```sh
python3 tests/ob1_model.py                  # the model's self-test
python3 tests/ob1_model.py --table > ob1_tables.h
python3 tests/ob1_check.py                  # the kernel against the model (needs cc)
python3 tests/ob1_artefacts.py
cd tests/spice && ngspice -b ob1_ac.cir     # the circuit (needs ngspice)
# the cost needs a Unicorn that runs EMAC (digiemu's patched build), from a digiemu checkout:
uv run --with numpy python <DigiFilter>/tests/ob1_bench.py
```
