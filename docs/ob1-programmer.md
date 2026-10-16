# OB-1 programmer and cutoff stepping

Research for [#12](https://github.com/simonjohansson/DigiFilter/issues/12). The original
OB-1 digitizes the programmable frequency knob into six-bit values and reconstructs a held
analog voltage before adding continuous modulation. This nominal model covers the drawn
DC networks and scan timing constraints. DigiFilter uses the reconstruction intervals
and nominal scan period in its OB4/OB2 control path; the original analog pot ADC remains
a separate research model.

The ADC reference voltage, comparator output levels, trim positions and switching delays
are not measured. The exact ADC-code boundary convention and serial-to-hold timing remain
open. The ADC equations below are not a complete pot-to-code conversion. The Digitakt
encoder maps directly to DAC words, using the explicit calibration choices below.

## Sources and schematic revision

- [Original schematic set](https://synthfool.com/docs/Oberheim/Oberheim_OB1/Oberheim_OB-1_Schematics.pdf):
  1339 pot board, 1341 programmer revision A (revised March 19, 1979), and 1342
  synthesizer revision B (revised April 2, 1979), sheets 1 and 3. PDF pages 2, 4, 5 and 7.
- [Electrongate scans](https://www.electrongate.com/obfiles/index.html):
  [1339](https://www.electrongate.com/obfiles/OB-1-1339.jpg),
  [1341](https://www.electrongate.com/obfiles/OB-1-1341.jpg),
  [1342 sheet 1](https://www.electrongate.com/obfiles/OB-1-1342a.jpg),
  [1342 sheet 3](https://www.electrongate.com/obfiles/OB-1-1342c.jpg).
- [Original owner's manual](https://www.synthxl.com/wp-content/uploads/2020/10/oberheim-ob1-user-manual.pdf),
  page 3: the self-oscillating filter's frequency control covers about five octaves in
  half-step increments; fine tune is not programmable.
- [R. Grieb's programmer notes](http://www.tauntek.com/progdesc.txt), February 25, 2016:
  circuit interpretation and measurements from serial 201, without CEM3310 envelopes.
  These describe one unit, rather than a universal clock calibration.
- [CD4041UB](https://www.ti.com/lit/ds/symlink/cd4041ub.pdf),
  [CD4014B](https://www.ti.com/lit/ds/symlink/cd4014b.pdf),
  [CD4024B](https://www.ti.com/lit/ds/symlink/cd4024b.pdf) and
  [CD4027B](https://www.ti.com/lit/ds/symlink/cd4027b.pdf) datasheets: pin polarity,
  synchronous parallel load, negative-edge counters and positive-edge J-K flip-flops.
  Modern datasheets establish logic behavior here, not original-part analog timing.

## Signal path

On 1339 the VCF FREQ potentiometer runs between the labelled +10 V rail and ground.
Its wiper goes to A3's channel 2 (pin 15); PA/PB/PC select the channel, and P2* enables
this group. U17 on 1341 supplies the scan address. Cutoff is slot 10, resonance slot 11.

The MUX voltage goes to U5, an LM301 comparator. U16's six buffered counter bits drive
the ramp DAC on its other input. U4, a 4014, captures parallel data and supplies a
serial stream. U25 selects that stream in manual mode or the SRAM stream for recalled
programs. Manual mode therefore retains conversion and reconstruction.

On 1342/3, U45 shifts the serial data back into six parallel bits. U46/U47 drive the
reconstruction resistor network; U48 scales and offsets its output. U57 channel 2
(pin 15), C47 (0.1 uF), and U58's follower produce FF, the held base cutoff voltage.
Channel 3, C48 and U59 similarly produce FR for resonance. FF and FR are distinct from
FM, the modulation-depth voltage held by U63, C55 and U64.

The drawn bit positions put B1..B6 into U4 parallel stages 1..6 and D1..D6 along
U45's shift chain. The B bus also has diode pull-down drivers, and the path through
U20/U26/U25 includes inversions. The ramp count, stored word and reconstructed word
must therefore remain separate until the gate and edge trace establishes their
polarity and alignment. The DC equations below use `a` for the ramp counter and `d`
for the reconstruction word; they do not assume `a = d`.

## ADC ramp and comparator thresholds

The nominal ramp network drawn on 1341 has six starred 100K branches from U16,
five 49.9K links R16..R20, a starred 100K bottom termination, and R15 = 10M from the
top node to -15 V. Starred parts use the drawing's matched-resistor note. The earlier
interpretation that R21..R26 were absent is not used: those branches are drawn, and the
small revision note is not clear enough to identify them as unpopulated parts.

Let `a = sum(b[i] * 2**i)` for `i = 0..5`, and let `VR` be the actual high output
voltage of the idealized U16 drivers. A Thevenin reduction gives the ramp exactly for
these nominal resistors. Start at the bottom (S1):

```text
v = VR * b[0] / 2
r = 50K
for i = 1..5:
    g = 1/100K + 1/(49.9K + r)
    v = (VR*b[i]/100K + v/(49.9K + r)) / g
    r = 1/g
Vadc(a) = (v/r - 15/10M) / (1/r + 1/10M)
```

This is close to `VR*a/64`, but includes the negative bias, loading by R15, and the
49.9K/100K ratio. In the ideal-output calculation code zero is about -74.577 mV;
the real buffer output resistance and offsets can change this result.

U5's positive input combines MUX through a 1K resistor with its own output through
a 100K feedback resistor. Their small reference labels are not transcribed here.
At equality on the ascending ramp:

```text
Vadc(a) = (100*Vmux + Voh) / 101
Vmux_boundary(a) = (101*Vadc(a) - Voh) / 100
```

`Voh` is the comparator's actual high-state output under its load. The positive
feedback means that ADC thresholds are not simply midpoints between ideal DAC codes.
For example, a 2 V change in `Voh` moves an equality boundary by 20 mV. The -15 V bias
and the feedback can also affect how many codes the +10 V pot reaches at its ends.

These are comparator equality voltages, **not yet a code-selection rule**. U4 has a
synchronous parallel load, gated by comparator and timing logic. Whether the retained
code is the crossing count or the preceding count depends on the load-clock sequence.
A direct `round(pot*63)` or unverified floor/ceil substitution would hide that question.

## Reconstruction DAC

The CD4041 true outputs used on 1342/3 are pins 1, 4, 8 and 11 for inputs 3, 6, 10
and 13 respectively. U46 duplicates D3 onto two true-output drivers; U47 does the same
for D6. Neither pair is a true/complement output short.

All starred reconstruction resistors are matched 100K, 1%. R263 is 301K. The first
three bits feed an attenuating network before the summing amplifier; the upper three
feed its virtual ground more directly:

| Input | Nominal path |
|---|---|
| D1 | R256 + R257 = 200K into node A |
| Ground | R258 + R259 = 200K from node A |
| D2 | R260 = 100K into node A |
| D3 | R261 and R262, each 100K, into node A |
| Node A to summing input | R263 parallel R264, then R265 = 100K |
| D4 | R266 + R267 = 200K into the summing input |
| D5 | R268 = 100K into the summing input |
| D6 | R269 and R270, each 100K, into the summing input |

For `d = D1 + 2*D2 + 4*D3 + 8*D4 + 16*D5 + 32*D6`, node A has open-circuit
voltage `VR*(d & 7)/8` and Thevenin resistance 25K. Thus:

```text
Rlink = 301K || 100K = 75.062344K
Isum = VR * ((d & 7) / (8 * (25K + Rlink + 100K)) + (d >> 3) / 200K)
Rfeedback = 11.5K + T17_effective       # T17 is a 1K trim
Vdac(d) = Rfeedback * (Isum - 15/1M)
```

The two U48 inversions restore increasing output with increasing code. R271 and R272
are both 12.1K and cancel in the nominal overall gain. R273's +15 V feed supplies the
offset. At code zero, `Vdac = -15*Rfeedback/1M`, or -172.5..-187.5 mV across T17's
nominal range. These are calculated ideal-amplifier values, not measured endpoints.

The effective low-bit denominator is 1.600498753M rather than exactly 1.6M. A step
within a group of eight codes is consequently about 0.0312% smaller than an ideal
binary step; a carry into the next group is slightly larger. This follows the printed
301K and 100K values and should not be confused with measured DAC nonlinearity.

Ignoring that small difference, one code changes FF by roughly
`VR * Rfeedback / 1.6M` volts. The actual `VR` and T17 setting are not printed, so a
numerical volts-per-code value cannot yet be assigned to an original unit.

## Scan timing and held cutoff

U21 is a seven-bit 4024 counter. The reset decode uses S1, S2, S3, S5 and S7: the
first matching count is 87. U10 clocks on the complementary phase and keeps reset
active through the next counter edge. A settled-state, read-before-write model gives
88 counting states (0..87) plus one reset state, hence 89 C4 periods per slot.

U17 selects 22 slots, resetting at PE/PB/PC = 1 (count 22). Its groups are:

| Slots | Contents |
|---|---|
| 0..7 | Eight envelope controls through A1/U56 |
| 8..15 | OF1, OF2, **FF**, FR, OW1, OW2, OM1, OM2 through A3/U57 |
| 16..19 | Four switch rows; A2's corresponding analog inputs are grounded |
| 20..21 | FM and programmed volume through A2/U63 |

For a settled U21 count, the T3 decode selects 64..69 while TS is clear: six transfer
counts. The TS request is set after the S1/S2/S3/S7 decode at 71 and resets with T1;
the nominal settled-state model has TS high at counts 72..87. STB and EN gate the
analog-output selection. These constraints do not yet establish the individual
U4/U45 clock edges, the final FF switch opening time, or the retained ADC count.

Grieb reports C4 = 126.66 kHz and approximately 89 C4 periods per slot. Using those
inputs gives:

```text
slot interval = 89 / 126660 = 702.669 us
frame interval = 22 * 89 / 126660 = 15.458708 ms
cutoff refresh rate = 126660 / (22 * 89) = 64.688458 Hz
```

His intermediate 707.6 us and 15.57 ms figures are inconsistent with those inputs;
his stated 64.68 Hz agrees with the calculation above. His approximate oscillator
measurement of 505 kHz also does not divide by four to exactly 126.66 kHz. Keep C4 as
the explicit measured input rather than mixing these rounded figures.

FF is selected once per frame, with FR one slot later. A knob movement just after
its scan can therefore wait nearly a frame for the next conversion, plus transfer
and acquisition latency. FF holds between acquisitions rather than gliding through
every intermediate voltage. A fast sweep can skip codes because the knob is scanned.

C47 is 0.1 uF, but it does not establish a settling time by itself. During selection,
its charging resistance includes U57's on resistance and the DAC/op-amp drive behavior.
During hold, capacitor leakage, switch leakage and follower bias affect droop. No
fixed time constant, droop rate or switching-glitch amplitude is assigned here.

## Modulation and cutoff frequency

On 1342/1 FF enters the U21 cutoff summer through starred R149 = 100K. Key CV and
VCF BEND take separately switched inputs through U22; the fine-tune and performance
controls also bypass the programmer's ADC. This U21 is an analog 741, not the counter
U21 on 1341.

ENV2 and the LFO are selected and passed through U23, a 3080 whose bias is controlled
by FM through Q29. The envelope or LFO waveform itself is therefore continuous even
though its programmed depth comes from a separate held six-bit setting. U23's output
joins the cutoff control path before Q27's exponential conversion.

A suitable nominal frequency relation is:

```text
f(t) = f_reference * 2**(g_FF * (FF(t) - FF_reference) + modulation_octaves(t))
```

`g_FF` is the calibrated octaves-per-volt sensitivity at FF, not automatically the
internal exponential transistor's sensitivity. The frequency summer, T15 and divider
must be included when relating the DAC to that converter. Absolute cutoff, `g_FF`,
the reachable pot codes and the comparator clock convention are still required to
turn the manual's approximate five-octave/semitone description into a full table.

Quantizing Digitakt's final cutoff would also quantize its continuous envelope/LFO
signal. Its original stock frequency curve spans about twelve octaves, so reducing
that curve to 64 equally spaced settings would give steps larger than two semitones.

## Digitakt control implementation

The selected mapping uses 64 DAC words with nominal semitone spacing, spanning about
five octaves rather than retaining the old twelve-octave base range. This is an
intentional change to the playback of existing OB4/OB2 sounds. Stored parameter
values, TYPE numbers and the file format are unchanged.

`ob1_control.h` maps the engine's raw FREQ word `w` to the nearest word:

```text
d = floor(clamp(w, 0, 127*256) * 63 / (127*256) + 0.5)
```

This is an encoder mapping, not a claim about the original pot ADC's thresholds.
The DAC intervals are normalized so that the nominal binary LSB is a semitone; the
301K network's small low-bit correction is retained. Code 32 keeps the old FREQ 64
reference at 327 Hz. This gives a nominal unmodulated base range of 51.496..1959.638 Hz
after 8.8-index rounding, with adjacent targets 99.781..100.225 cents apart.
Original-unit absolute pitch and reachable pot codes are not established by this choice.

The controller samples raw engine FREQ once per nominal scan frame. Changes arriving
through that field take the stepped base path; the new checks inject them directly,
rather than exercising the sequencer's parameter-lock/slide UI. Sampling occurs on
the first audio-block boundary at or after the scan:
23 or 24 blocks per hold at 48 kHz/32 frames, at most one block (0.667 ms) late.
The clock starts when that voice enters OB4/OB2. A new note keeps the running filter
and clock; switching OB4/OB2 output taps also keeps them. Leaving for another TYPE
marks the state fresh, including stock types that bypass the C filter function.

### Continuous modulation boundary

The stock LFO stage runs after parameter smoothing and before the per-voice filter.
It records each LFO's destination and signed contribution separately, before clamping
the rendered parameter to 0..0x7f00. Reading that contribution is necessary: subtracting
the base from an already clamped parameter loses modulation at the ends of the old range.

| Value | OS 1.53 | OS 1.54 |
|---|---|---|
| Raw engine FREQ | `0x80001502 + 106*v + 2*0x1a` | Same |
| First LFO destination | `0x421f3e50 + 80*v` | `0x421f4e50 + 80*v` |
| First LFO contribution | Destination address + 4 | Same offset |
| Second LFO state | First LFO state - 40 | Same offset |
| Filter envelope level | `0x4199df58 + 12*v` | `0x4199ef58 + 12*v` |

The LFO stages at `0x400ed53e` (1.53) and `0x400ed766` (1.54) establish those state
fields. An isolated run of each original firmware routine, with a held waveform,
confirmed destination 26 and signed contributions of +4096/-4096, including upper
and lower parameter-clamping cases. These are firmware/emulator observations.

`cutoff_index8()` adds each LFO contribution whose destination is FREQ, then the
existing filter-envelope term, to the held base before clamping to the DSP's supported
range. Envelope and LFO signals retain fractional cutoff resolution at every resonance
setting. Their existing Digitakt depths are preserved; this does not model the original
OB-1 modulation-depth OTA's complete calibration.

The response graph uses the same target mapping as the controller. Coefficient tables
and the kernel's physical-cutoff interface remain unchanged. The existing four-subblock
coefficient ramp is retained as an acquisition approximation; its 32-sample duration
is not a measured original-hardware settling time. Leakage, switching glitches and exact
within-block conversion/acquisition timing remain outside this implementation.

## Numerical check and remaining work

From the repository root:

```sh
mise exec python@3.13.15 -- python tests/ob1_programmer.py
mise exec python@3.13.15 -- python tests/ob1_control_check.py
# With patched Unicorn in digiemu's environment and the ColdFire toolchain on PATH:
python tests/ob1_control_firmware.py
python tests/df_bench.py
```

The check requires ngspice, as the existing circuit checks do. It covers the two
nominal resistor networks, all 64 code values,
comparator equality thresholds, input validation, the 89-period scan model, the
six-count transfer decode, TS request, and the measured-clock arithmetic. It also runs
`tests/spice/ob1_programmer.cir`, an independent node-by-node netlist, and compares all
64 ADC and DAC voltages with the equations to within 0.1 uV. Both networks receive
the same test word for this DC comparison; this does not equate their words in the
actual serial circuit. The Python code uses only the standard library and has no
firmware callers. Its voltage fixtures are examples, not replacement calibration values.

`ob1_control_check.py` compares every legal 8.8 FREQ input with the resistor model,
checks all 64 targets and spacing, and checks ten seconds of held-control timing,
reset and eight independent voice states. `ob1_control_firmware.py` runs the linked
ColdFire C and assembly for both OS defines: both output taps, both LFOs, the envelope,
clamps, control hold, and dispatcher/re-entry state. These tests do not boot a complete
firmware or establish physical-hardware agreement.

Validation of this implementation also passed the existing kernel, model and artefact
checks. A 300-block full-scale resonant sweep agreed between the host kernel and linked
ColdFire execution within 2.64e-5 of the block peak on both OS versions. A separate
96-block comparison per mode against merged baseline `404f72f`, with swept cutoff,
resonance and envelope modulation, produced bit-identical BP/BP2/COMB/TRASH audio.
The instruction benchmark includes a scan update and measures maxima of 3142 for OB4
and 3077 for OB2 per voice/block at RESO 127; instruction counts do not establish
eight-voice hardware timing.

Full SDK builds and Core 4.0 patch/link checks passed for OS 1.53 and 1.54, with no
unresolved imports. GCC 16 requires temporarily passing `-Wno-error=int-conversion`
for an existing UI pointer-to-integer diagnostic; the source and build configuration
for that unrelated diagnostic are unchanged.

### Complete firmware checks (2026-10-16)

Source commit `0ecbc40`, Core 4.0 + DigiFilter, version display `STEP`:

| Check | OS 1.53 | OS 1.54 |
|---|---|---|
| SDK packet/content checksums, framing and in-place depack | Pass | Pass |
| Bootstrap execution, strict cold boot and timed UI/playback tour | Pass | Pass |
| Timed tour: minimum estimated render margin | 37.66% | 37.49% |
| Stock tour: minimum estimated render margin | 37.82% | 37.66% |
| Eight OB4 voices, RESO 127, full-scale input, moving cutoff | 28.46% margin | 28.28% margin |
| Real encoder selection, cutoff endpoints and intermediate held bases | Pass | Pass |
| Real UI-to-audio fixture, OB2 at FREQ 80 / RESO 64 | 0.1% model error | 0.1% model error |
| OB4/OB2 response curves and Sound copy/paste | Pass | Pass |
| Both TYPEs saved to separate cards, cold rebuilt and reloaded | Pass | Pass |

The full `emu.fwcheck` runs used freshly booted images and stock baselines, DDR
aliasing, strict mode, timing and the firmware's own float/drawing instructions.
There were no new strict violations or missed audio deadlines. Both builds retain
the stock boot's single read from address zero, marked `in_stock`. All 13 named
screens match stock. Frame publication times differ; the audio comparison flags
only the final 100 ms window, with zero reported RMS difference and recordings
about 1 ms different in length.

The tour's large encoder bursts do not reliably select OB2. Separate, spaced panel
turns verified TYPE 13 and both FREQ endpoints against the held DAC-model targets.
The eight-voice timing fixture explicitly forces TYPE 12, RESO 127, full-scale saw
input and swept raw FREQ at the dispatcher: 449 blocks per voice over 300 ms.
Those timing results are cycle estimates at 250 MHz with zero-wait memory, not
physical-device measurements. Functional UI checks use the emulator's normal host
shortcuts and idle skipping, with the DDR model and OS-specific kit/track addresses.

Local reports, input scripts, screenshots and fixture runners are under
`work/firmware-check/`, including `os1.53/report.json`, `os1.54/report.json` and
`SUMMARY.md`. The SDK separately verifies the checksums that this public copy of
digiemu omits. Physical flashing/listening, sequencer lock/slide UI validation,
and original OB-1 settling/absolute calibration measurements remain untested.

Before #12 can supply an implementation-ready quantizer:

- Resolve U4's gated parallel-load/serial-shift clock edges, including the retained
  count at a comparator crossing. Trace data polarity through the B-bus drivers,
  U20/U26/U25 and U45 to the output strobe in manual and recalled-program modes.
- Establish endpoint behavior when the comparator is already low or never crosses
  during a conversion. Do not assume saturation to code 0/63 without that trace.
- Finish the FF-to-octaves gain calculation with the cutoff trims; retain actual
  reference voltage and calibration as measured inputs where the drawing has no value.
- Bound acquisition/hold behavior from the switch and amplifier specifications, then
  use original-hardware captures for any claimed settling, droop or glitch match.

The existing kernel and generated tables are unchanged apart from a comment documenting
the acquisition approximation. The FREQ control law changes as described above.
Physical OB-1 agreement belongs to
[#15](https://github.com/simonjohansson/DigiFilter/issues/15), independently of the
nominal network checks.
