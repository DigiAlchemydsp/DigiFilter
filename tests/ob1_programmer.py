#!/usr/bin/env python3
"""Nominal OB-1 programmer DC networks and scan timing; not used by the firmware.

See docs/ob1-programmer.md for the schematic, calibration and timing limits.
Run directly for the numerical self-check (requires ngspice). No measured reference voltage is assumed.
"""
import math
from pathlib import Path
import subprocess


def adc_ramp(code, vr):
    """1341: ideal buffer outputs, drawn resistor values, unloaded LM301 input."""
    if not isinstance(code, int) or not 0 <= code <= 63:
        raise ValueError('code must be an integer from 0 to 63')
    if not math.isfinite(vr) or vr <= 0:
        raise ValueError('vr must be a finite positive voltage')
    voltage, resistance = vr * (code & 1) / 2, 50000.0
    for bit in range(1, 6):
        lower = 49900.0 + resistance
        conductance = 1 / 100000.0 + 1 / lower
        voltage = (vr * ((code >> bit) & 1) / 100000.0 + voltage / lower) / conductance
        resistance = 1 / conductance
    return (voltage / resistance - 15 / 10000000.0) / (1 / resistance + 1 / 10000000.0)


def adc_boundary(code, vr, comparator_high):
    """MUX voltage at comparator equality on the ascending ramp, before clock timing."""
    if not math.isfinite(comparator_high):
        raise ValueError('comparator_high must be finite')
    return (101 * adc_ramp(code, vr) - comparator_high) / 100


def dac_voltage(code, vr, trim):
    """1342/3 U48 output, volts; trim is T17's effective resistance, 0..1000 ohms."""
    if not isinstance(code, int) or not 0 <= code <= 63:
        raise ValueError('code must be an integer from 0 to 63')
    if not math.isfinite(vr) or vr <= 0:
        raise ValueError('vr must be a finite positive voltage')
    if not math.isfinite(trim) or not 0 <= trim <= 1000:
        raise ValueError('trim must be a finite resistance from 0 to 1000 ohms')
    link = 1 / (1 / 301000.0 + 1 / 100000.0)
    current = vr * ((code & 7) / (8 * (25000.0 + link + 100000.0)) + (code >> 3) / 200000.0)
    return (11500.0 + trim) * (current - 15 / 1000000.0)


def scan_slot():
    """U21/U10 settled states before each C4 falling edge; excludes gate delays.

    Each tuple is (counter, T1 reset, TS strobe request). This does not model the
    U4/U45 serial clock or the analog switch's acquisition window.
    """
    counter, t1, ts = 0, False, False
    states = []
    for _ in range(89):
        states.append((counter, t1, ts))
        next_t1 = counter & 87 == 87       # S1 S2 S3 S5 S7, U10 J; K is T1
        next_ts = not next_t1 and (ts or counter & 71 == 71)
        counter = 0 if t1 or next_t1 else counter + 1
        t1, ts = next_t1, next_ts
    assert (counter, t1, ts) == (0, False, False)
    return states


def knob_cutoff8(word):
    """Nominal encoder mapping, distinct from the original pot ADC's unresolved edge behavior."""
    code = math.floor(max(0, min(0x7f00, word)) * 63 / 0x7f00 + 0.5)
    # VR and T17 cancel when DAC intervals are normalized to nominal semitones.
    semitones = (dac_voltage(code, 10.0, 500.0) - dac_voltage(32, 10.0, 500.0)) / 0.075
    return (64 + semitones * 10.57 / 12) * 256


def self_check():
    # The voltages here are algebraic fixtures, not an OB-1 calibration.
    vr, trim = 10.0, 500.0
    ramp = [adc_ramp(code, vr) for code in range(64)]
    dac = [dac_voltage(code, vr, trim) for code in range(64)]
    assert all(a < b for a, b in zip(ramp, ramp[1:]))
    assert all(a < b for a, b in zip(dac, dac[1:]))
    assert math.isclose(dac[0], -0.18, abs_tol=1e-12)
    for code in range(64):
        # Both resistor networks are linear in the six bit-driving voltages.
        for values in (ramp, dac):
            expected = values[0] + sum(values[1 << bit] - values[0]
                                       for bit in range(6) if code & (1 << bit))
            assert math.isclose(values[code], expected, abs_tol=1e-12)
        mux = adc_boundary(code, vr, 12.0)
        assert math.isclose((100 * mux + 12) / 101, ramp[code], abs_tol=1e-12)
    # R271/R272 cancel; D4, D5 and D6 carry binary weights through their branches.
    step = vr * (11500 + trim) / 1600000
    for code in range(56):
        assert math.isclose(dac[code + 8] - dac[code], 8 * step, abs_tol=1e-12)
    # The 301K branch makes a low-bit step slightly smaller than a perfect binary step.
    assert 0 < dac[1] - dac[0] < step < dac[8] - dac[7]
    # Comparator high-state variation changes thresholds; it cannot be silently omitted.
    assert math.isclose(adc_boundary(32, vr, 12) - adc_boundary(32, vr, 10), -0.02,
                        abs_tol=1e-12)
    for bad in (-1, 64, 0.5):
        for function, args in ((adc_ramp, (bad, vr)), (dac_voltage, (bad, vr, trim))):
            try:
                function(*args)
            except ValueError:
                pass
            else:
                raise AssertionError('invalid code accepted')
    for args in ((0, 0, trim), (0, math.nan, trim), (0, vr, -1), (0, vr, 1001)):
        try:
            dac_voltage(*args)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid calibration accepted')

    states = scan_slot()
    assert [n for n, reset, _ in states if not reset] == list(range(88))
    assert states[88] == (0, True, False)
    assert [n for n, _, ts in states if ts] == list(range(72, 88))
    transfer = [n for n, _, ts in states if n & 64 and not ts and n & 6 != 6]
    assert transfer == list(range(64, 70))
    # Slot counter U17 resets at PE PB PC = 1, producing 22 slots, not 32.
    assert next(n for n in range(32) if n & 22 == 22) == 22
    # FF is U57 channel 2 in group 2: slot 10. FR is channel 3: slot 11.
    assert 10 & 7 == 2 and 11 & 7 == 3
    c4_hz = 126660.0                 # Grieb's measured C4; not 505000 / 4
    slot_seconds = len(states) / c4_hz
    frame_seconds = 22 * slot_seconds
    assert math.isclose(1 / frame_seconds, 64.68845760980592)
    assert not math.isclose(slot_seconds, 707.6e-6, rel_tol=1e-3)
    circuit = Path(__file__).parent / 'spice' / 'ob1_programmer.cir'
    result = subprocess.run(['ngspice', '-b', str(circuit)], check=True, text=True,
                            capture_output=True)
    rows = [line.split() for line in result.stdout.splitlines()
            if line.split() and line.split()[0].isdigit()]
    assert len(rows) == 64, result.stdout
    for code, row in enumerate(rows):
        assert len(row) == 4 and int(row[0]) == code, row
        assert float(row[1]) == code
        assert math.isclose(float(row[2]), ramp[code], abs_tol=1e-7), row
        assert math.isclose(float(row[3]), dac[code], abs_tol=1e-7), row
    print('PASS: ADC/DAC monotonicity, superposition, comparator feedback and input validation')
    print('PASS: 89-cycle slot, six-count transfer decode, TS request and 22-slot frame')
    print('PASS: all 64 ADC and DAC voltages match the SPICE netlist within 0.1 uV')
    print('Measured-clock example: %.3f us/slot, %.6f ms/frame, %.6f Hz' %
          (slot_seconds * 1e6, frame_seconds * 1e3, 1 / frame_seconds))
    print('Calibration fixture only (VR=10 V, T17=500 ohms): DAC %.9f..%.9f V' %
          (dac[0], dac[-1]))


if __name__ == '__main__':
    self_check()
