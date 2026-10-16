/* Private OB4/OB2 cutoff control; docs/ob1-programmer.md derives the DAC and clock. */
#ifndef OB1_CONTROL_H
#define OB1_CONTROL_H

struct ob1_control {
    unsigned int phase;
    int cutoff8, fresh;
};

/* Digitakt FREQ -> 64 DAC words, nominal semitones, keeping FREQ 64 at 327 Hz.
 * Q24 stock indices: 10.57 indices/octave; the low bits retain the 301K DAC correction. */
static inline int ob1_knob_cutoff8(int word)
{
    int code;
    word = word < 0 ? 0 : word > 0x7f00 ? 0x7f00 : word;
    code = (word * 63 + 0x3f80) / 0x7f00;
    return ((64 << 24) + (code - 32) * 14777931 - (code & 7) * 4605 + 32768) >> 16;
}

static inline int ob1_control_run(struct ob1_control *s, int word)
{
    if (s->fresh) {
        s->phase = 0;
        s->cutoff8 = ob1_knob_cutoff8(word);
        s->fresh = 0;
    } else {
        /* 32 audio frames at 48 kHz; 22 slots x 89 C4 periods at measured C4 126660 Hz. */
        /* shortcut: scans land at block boundaries; split blocks if measured timing requires finer edges. */
        s->phase += 32u * 126660u;
        if (s->phase >= 22u * 89u * 48000u) {
            s->phase -= 22u * 89u * 48000u;
            s->cutoff8 = ob1_knob_cutoff8(word);
        }
    }
    return s->cutoff8;
}

#endif
