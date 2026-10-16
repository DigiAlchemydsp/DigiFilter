/* SPDX-License-Identifier: GPL-2.0-or-later */
/* DigiFilter shared DSP core: firmware-free SVF/comb math + per-voice state.
 *
 * Digitakt 1.1a verbatim (copy-paste, no logic changes): mulsh/div55/clamping,
 * mode coefficients (Q capped, BP2 halves, c1=k exactly), feedback comb
 * (fractional, smoothed, saturated) and SVF runner (cached coefficients,
 * single call when still, 4x ramp when sweeping). No kit/engine/firmware:
 * callers pass m/fi/qi/fb/hdiv/damp/div + buf/voice. Host tests cover it.
 */
#ifndef DF_DSP_H
#define DF_DSP_H

typedef int int32;
typedef unsigned int uint32;

struct df_coef {
    int32 a1, a2, a3, c0, c1, c2;
};

int32 df_mulsh(int32 a, int32 b, int sh);
int32 df_div55(uint32 d);
int df_clampi(int v, int lo, int hi);
void df_mode_coef(int m, int fi, int qi, struct df_coef *c);
void df_comb_run(int32 *buf, int frames, int fi, int fb, int v, int div,
                 int hdiv, int damp);
void df_svf_run(int m, int fi, int qi, int32 *buf, int v);
void df_reset(int v);

#endif
