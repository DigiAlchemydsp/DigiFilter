# Measured reference filter mapping

Measured on 16 October 2026. The target is the reference plugin's dry OB4 and OB2 behavior. These are
software measurements, not a calibration of a physical Oberheim OB-1. The resulting control calibration
and its remaining differences are described in [the filter reference](ob1.md#control-calibration).

## Conditions and evidence

The reference was VST3 version 1.0 in REAPER 7.82 on macOS arm64, with its demo explicitly enabled.
Processing was 48 kHz stereo float32, 2x oversampling and a maximum internal buffer setting of 32.
Output gain was -13.98 dB and track/master gains were unity. Vintage, effects, high-pass filtering,
keyboard tracking, filter envelope depth and filter LFO depth were off; filter fine tune was centered.
The voice was mono with one voice. Sources were the internal white noise or oscillator 1 saw, with
MIDI note 48 for saw captures. Source settings were identical within each response/reference pair.

The evidence comprises 118 measurement renders and four pilot renders. All 122 passed checks for
sample rate, stereo channels, exact expected duration, float32 format, finite samples and sample
peaks below clipping. The highest stereo sample peak was -7.29 dBFS. No normalization was applied.
Pitch and phase-tracking analyses passed synthetic sinusoid and chirp self-checks.

Local source records, resolved parameters, start/end readbacks, saved REAPER projects, raw WAVs,
analysis results and SHA-256 inventories are retained under the ignored
`research/reference-filter-mapping/` directory. The capture series are `pilot`, `static-and-onset`,
`refinement-and-motion` and `final-bracket`. Control observations are retained separately from audio.
These local artifacts are the primary measurement sources; they are not included in the repository.

## Cutoff position

Let `u` be normalized cutoff position from 0 to 1. The displayed frequency follows:

```text
f_display(u) = 10 + 20990 u^3 Hz
u(f_display) = ((f_display - 10) / 20990)^(1/3)
```

There were 2,050 display queries across both modes. Of these, 2,045 had matching requested and actual
parameter values; their maximum discrepancy from the formula was 0.500 Hz, consistent with integer-Hz
display rounding. Five queries were excluded because host automation changed the parameter between
setting and reading it. The rejected observations remain in the evidence.

This is a cubic control curve, not a constant-octaves-per-control-unit curve. At 25%, 50% and 75%
position, its unrounded display values are approximately 338 Hz, 2,634 Hz and 8,865 Hz. At the same
position, both modes share the displayed frequency and essentially the same full-resonance tone pitch.

A displayed cutoff, a self-oscillation pitch and a whole-filter -3 dB frequency are different quantities.
Settled full-resonance pitches measured with a small continuous noise seed were:

| Display target | OB4 tone | OB2 tone |
| --- | --- | --- |
| 10 Hz | 9.90 Hz | 9.90 Hz |
| 100 Hz | 99.12 Hz | 99.12 Hz |
| 250 Hz | 248.37 Hz | 248.37 Hz |
| 1,000 Hz | 1,004.39 Hz | 1,004.39 Hz |
| 4,000 Hz | 4,177.61 Hz | 4,177.61 Hz |
| 8,000 Hz | 8,484.64 Hz | 8,484.64 Hz |
| 16,000 Hz | 17,121.00 Hz | 17,121.01 Hz |
| 21,000 Hz | 22,508.74 Hz | 22,508.73 Hz |

Sixteen positions per mode were measured across the range. The maximum difference between corresponding
mode pitches was 0.015 Hz. The tone's offset from the display depends on frequency; matching the displayed
curve alone does not establish an audio match.

## Resonance

A short white-noise excitation was followed by source silence while the voice gate remained open.
At displayed cutoffs of 250 Hz, 1 kHz and 4 kHz, both modes decayed at normalized resonance 0.632 and
sustained at 0.634. The measured onset bracket is therefore **63.2–63.4%** under these conditions.
Near-threshold decay takes longer at low cutoff; these captures used a 12-second observation period.
The post-excitation floor is nonzero, so a residual trace near that floor is not itself oscillation.

Below onset, the low-frequency response relative to the same mode's fully-open, zero-resonance reference
is consistent with the following effective feedback model:

```text
k_effective(r) ≈ 10 r^2
low_frequency_gain(r) ≈ 1 / (1 + k_effective(r))
```

Here `r` is normalized resonance. This is an inference from the measured response, not an observation
of the reference's internal implementation. At nominal 1 kHz cutoff:

| Resonance | OB4 bass loss | OB2 bass loss | Predicted loss from the effective model |
| --- | --- | --- | --- |
| 25% | -4.19 dB | -4.15 dB | -4.22 dB |
| 50% | -10.83 dB | -10.91 dB | -10.88 dB |
| 62.5% | -13.77 dB | -13.78 dB | -13.82 dB |

Bass loss is the median relative response from 30 to 100 Hz. Repeating the 1 kHz, zero/62.5%-resonance
responses at a lower noise level changed the bass estimates by less than 0.1 dB. The inferred model's
`k = 4` point is 63.25%, consistent with the measured onset bracket. Its extrapolation above onset is
not verified: saturation, oscillation amplitude and internal feedback gain cannot be separated by this
bass-loss measurement once the filter oscillates.

At full resonance the modes differ in output level. For nominal 1 kHz, settled tone RMS was about
-16.8 dBFS in OB4 and -11.4 dBFS in OB2. These are reference-output observations, not gain targets for
a firmware implementation. Any later sound change must preserve existing maximum output headroom.

## Settled attenuation

White-noise spectra were averaged after settling and divided by each mode's own fully-open,
zero-resonance response at the same source level. Log-frequency averaging reduced random noise
variation. The resulting relative responses were measured at 250 Hz, 1 kHz and 4 kHz, with resonance
0%, 50% and 62.5%.

At zero resonance, attenuation at the displayed cutoff is approximately 12 dB for OB4 and 6 dB for
OB2. Estimated -3 dB frequencies relative to fully open were:

| Display target | OB4 relative -3 dB | OB2 relative -3 dB |
| --- | --- | --- |
| 250 Hz | 107 Hz | 159 Hz |
| 1,000 Hz | 428 Hz | 632 Hz |
| 4,000 Hz | 1,691 Hz | 2,541 Hz |

These estimates have stochastic and frequency-averaging uncertainty; their precision is lower than
the static tone estimates. The open reference is itself filtered, so these are not absolute bypass
responses. High-frequency attenuation must be compared with the complete measured response rather
than inferred from pole count or a single nominal cutoff. Sweep speed is a separate property.

## Motion and control resolution

Ten-second upward and downward sweeps were captured at 50% and 100% resonance for both modes.
Eight-second narrow sweeps from normalized position 0.49 to 0.51, and back, produced a predominantly
monotonic moving tone through roughly 2.54–2.88 kHz. These observations do not support imposing a
semitone grid on direct automation.

For a jump from position 0.49 to 0.51 at full resonance, the settled pitches were approximately
2,541.3 Hz and 2,875.7 Hz. Both modes reached and stayed within five cents of the final pitch after
about 18 ms. The pitch estimate uses a 10 ms phase-analysis window and band-limited processing;
this result is not an isolated internal smoothing time constant. Larger upward and downward jumps
were also captured, but no universal settling law was fitted.

A GUI drag with host cutoff automation bypassed produced arbitrary normalized positions. A one-pixel
movement from approximately 0.5716965 to 0.5757812 changed the display from 3,932 to 4,017 Hz, about
37 cents. This establishes a GUI control change smaller than a semitone; GUI gesture audio and its
continuous pointer trajectory were not recorded.

An explicitly learned 7-bit CC74 assignment was tested with values 0, 1, 31, 60–68 and 127, preserving
the repeated 64 in the sequence. Every observed normalized value matched `CC / 127` within 1e-7.
MIDI resolution therefore follows its 128 control values, with frequency spacing determined by the
cubic cutoff curve. Transport-relative readback timing was not calibrated, so this does not measure
MIDI-to-audio latency or smoothing. The temporary assignment was removed individually afterward.

## Boundaries of the measured target

The evidence establishes the dry cutoff control law, full-range resonant pitch, subthreshold resonance
curve and onset, relative response shape, selected motion behavior, and GUI/MIDI parameter resolution.
It does not establish an exact clone of the reference's nonlinear internals. Fine-tune extremes,
keyboard tracking, modulation depth laws, alternate oversampling settings, distortion versus drive,
GUI/MIDI gesture audio and physical hardware behavior were not characterized.

A future implementation should use these as separate calibration targets. Preserve stored parameter
formats and output headroom, and validate cutoff position, resonance and response together. There is
no evidence here requiring an additional discrete cutoff grid or programmer timing mechanism.
