/* Filter+FX shared DSP modes. */
#ifndef FX_DSP_H
#define FX_DSP_H

#define FX_VOWEL   0
#define FX_BANK    1
#define FX_FOLD    2
#define FX_CRUSH   3
#define FX_RING    4
#define FX_PHASER  5
#define FX_FLANGER 6
#define FX_NMODES  7

/* One 32-frame block in place. fi/qi/aux1/aux2 are 0..127; voice 0..7. */
void fx_run(int mode, int fi, int qi, int aux1, int aux2, int *buf, int voice);

/* Clear a voice's state (silent voice / mode change). */
void fx_reset(int voice);

#endif
