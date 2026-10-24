/* SPDX-License-Identifier: GPL-2.0-or-later */
/* DigiFilter shared DSP core: firmware-free SVF/comb math + per-voice state.
 *
 * Digitakt 1.1b verbatim (copy-paste, no logic changes). Cached SVF
 * coefficients when still (one digifilter_svf call for the whole block), a
 * linear ramp run in one digifilter_svf4 call when sweeping, precomputed a1
 * (no software division per block), and a damping-free comb fast path.
 * Sound identical, cost lower. No kit/engine/firmware here.
 */
#include "df_dsp.h"
#include "filter_tables.h"
#ifndef SVF_A1_GEN
#include "svf_a1_tables.h"          /* a1 per (resonance, cutoff), from tools/gen_svf_a1.py */
#endif

extern void digifilter_svf(int32 *buf, int frames, const int32 *coef, int32 *state);
extern void digifilter_svf4(int32 *buf, const int32 *coef4, int32 *state);

static int32 dsp_st[8][2];
static int32 comb_buf[8][256];
static int comb_pos[8];
static int comb_init[8];
static int32 comb_dly[8];
static int32 comb_g[8];
static int32 comb_lp[8];
static int svf_fi[8], svf_qi[8];
static int svf_have[8];
static struct df_coef svf_c[8];

#define COMB_N 256
#define COMB_MASK (COMB_N - 1)
#define COMB_DSHIFT 6
#define COMB_GSHIFT 7

/* floor(2^16 / d) for d = 1..8; ceil() is exact for COMB_DELAY <= 255, so the
 * comb's delay divisor needs no software division. */
static const uint32 COMB_RECIP[9] = {
    0, 65536, 32768, 21846, 16384, 13108, 10923, 9363, 8192
};

/* floor(a * b / 2^sh) for 16 <= sh <= 31, when the result fits 32 bits. */
int32 df_mulsh(int32 a, int32 b, int sh)
{
    uint32 ua = a < 0 ? -(uint32)a : (uint32)a, ub = b < 0 ? -(uint32)b : (uint32)b;
    uint32 al = ua & 0xffff, ah = ua >> 16, bl = ub & 0xffff, bh = ub >> 16;
    uint32 ll = al * bl, lh = al * bh, hl = ah * bl, hh = ah * bh;
    uint32 mid = (ll >> 16) + (lh & 0xffff) + (hl & 0xffff);
    uint32 lo = (ll & 0xffff) | (mid << 16);
    uint32 hi = hh + (lh >> 16) + (hl >> 16) + (mid >> 16);
    if ((a < 0) != (b < 0)) {
        lo = ~lo + 1;
        hi = ~hi + (lo == 0);
    }
    return (int32)((hi << (32 - sh)) | (lo >> sh));
}

/* floor(2^55 / d), d > 2^24. Only tools/gen_svf_a1.py compiles this: the
 * shipped build reads the precomputed SVF_A1 table instead. */
#ifdef SVF_A1_GEN
int32 df_div55(uint32 d)
{
    uint32 rem = 1u << 23, q = 0;
    int i;
    for (i = 0; i < 32; i++) {
        uint32 carry = rem >> 31;
        rem <<= 1;
        q <<= 1;
        if (carry || rem >= d) {
            rem -= d;
            q |= 1;
        }
    }
    return (int32)q;
}
#endif

int df_clampi(int v, int lo, int hi)
{
    return v < lo ? lo : v > hi ? hi : v;
}

/* SVF coefficients and band-pass mix (c0=-1 cancels v0, c1=k, c2=0).
 * Q is capped (top of K27 overshoots); m==1 is BP2 and halves Q. */
void df_mode_coef(int m, int fi, int qi, struct df_coef *c)
{
    int qk = qi * 13 / 15;
    int ek = (m == 1) ? (qk >> 1) : qk;      /* the index into K27 the mode uses */
    int32 g = G27[fi], k = K27[ek];
    c->c0 = -ONE27;
    c->c1 = k;
    c->c2 = 0;
#ifdef SVF_A1_GEN
    c->a1 = df_div55((uint32)((1 << 24) + df_mulsh(g, g + k, 30)));
#else
    /* a1 = floor(2^55 / ((1 << 24) + mulsh(g, g + k, 30))): precomputed for every
     * (ek, fi) by tools/gen_svf_a1.py, so a block needs no software division. */
    c->a1 = SVF_A1[ek][fi];
#endif
    c->a2 = df_mulsh(g, c->a1, 27);
    c->a3 = df_mulsh(g, c->a2, 27);
}

/* Damping-free comb: same math, but without the per-sample damp branch or
 * comb_lp update. Used when the damping knob is at zero, which is common. */
static inline __attribute__((always_inline)) void df_comb_nodamp(int32 *buf, int frames,
                                                  int32 tdq, int32 gt, int32 *b, int *pos,
                                                  int32 *dly, int32 *g)
{
    int p = *pos, i;
    int32 d = *dly, gg = *g;
    for (i = 0; i < frames; i++) {
        int32 ds, ip, fp, i0, i1, x, val, y, fa, da, ga, va;
        d += (tdq - d) >> COMB_DSHIFT;
        gg += (gt - gg) >> COMB_GSHIFT;
        ds = d;
        ip = ds >> 16;
        fp = ds & 0xffff;
        i0 = (p - ip) & COMB_MASK;
        i1 = (i0 - 1) & COMB_MASK;
        x = buf[i];
        fa = fp >> 1;
        da = (b[i1] - b[i0]) >> 13;
        val = b[i0] + ((fa * da) >> 2);
        ga = gg >> 12;
        va = val >> 11;
        y = x + ((ga * va) >> 4);
        if (y > (1 << 27))
            y = 1 << 27;
        else if (y < -(1 << 27))
            y = -(1 << 27);
        b[p] = y;
        p = (p + 1) & COMB_MASK;
        buf[i] = y;
    }
    *pos = p;
    *dly = d;
    *g = gg;
}

/* Feedback comb, fractional and smoothed: y = x + g*y[n-D].
 * D = COMB_DELAY[fi] / (div * hdiv), clamped 3..255; g from fb 0..127.
 * Delay and feedback glide per sample; output saturates at +-2^27. */
void df_comb_run(int32 *buf, int frames, int fi, int fb, int v, int div,
                 int hdiv, int damp)
{
    int32 target = (int32)(((uint32)COMB_DELAY[fi] * COMB_RECIP[div * hdiv]) >> 16);
    int32 tdq, gt, *b = comb_buf[v];
    int p, i;
    if (target < 3)
        target = 3;
    if (target > COMB_MASK)
        target = COMB_MASK;
    tdq = target << 16;
    gt = (int32)fb * ((ONE27 / 32) * 31 / 127);
    if (!comb_init[v]) {
        comb_init[v] = 1;
        comb_dly[v] = tdq;
        comb_g[v] = gt;
        comb_lp[v] = 0;
        comb_pos[v] = 0;
        for (i = 0; i < COMB_N; i++)
            b[i] = 0;
    }
    if (!damp) {
        df_comb_nodamp(buf, frames, tdq, gt, b, &comb_pos[v], &comb_dly[v], &comb_g[v]);
        return;
    }
    p = comb_pos[v];
    for (i = 0; i < frames; i++) {
        int32 ds, ip, fp, i0, i1, x, val, y, fa, da, ga, va;
        comb_dly[v] += (tdq - comb_dly[v]) >> COMB_DSHIFT;
        comb_g[v] += (gt - comb_g[v]) >> COMB_GSHIFT;
        ds = comb_dly[v];
        ip = ds >> 16;
        fp = ds & 0xffff;
        i0 = (p - ip) & COMB_MASK;
        i1 = (i0 - 1) & COMB_MASK;
        x = buf[i];
        fa = fp >> 1;
        da = (b[i1] - b[i0]) >> 13;
        val = b[i0] + ((fa * da) >> 2);
        if (damp) {
            comb_lp[v] += (val - comb_lp[v]) >> 4;
            val += df_mulsh(comb_lp[v] - val, damp, 15);
        }
        ga = comb_g[v] >> 12;
        va = val >> 11;
        y = x + ((ga * va) >> 4);
        if (y > (1 << 27))
            y = 1 << 27;
        else if (y < -(1 << 27))
            y = -(1 << 27);
        b[p] = y;
        p = (p + 1) & COMB_MASK;
        buf[i] = y;
    }
    comb_pos[v] = p;
}

/* SVF runner: cached coefficients when still, 4x ramp when sweeping. */
void df_svf_run(int m, int fi, int qi, int32 *buf, int v)
{
    struct df_coef c0, c1;
    int k, same;
    if (svf_have[v]) {
        c0 = svf_c[v];
        if (svf_fi[v] == fi && svf_qi[v] == qi) {
            same = 1;
            c1 = c0;
        } else {
            same = 0;
            df_mode_coef(m, fi, qi, &c1);
            svf_c[v] = c1;
            svf_fi[v] = fi;
            svf_qi[v] = qi;
        }
    } else {
        df_mode_coef(m, fi, qi, &c1);
        svf_c[v] = c1;
        svf_fi[v] = fi;
        svf_qi[v] = qi;
        svf_have[v] = 1;
        c0 = c1;
        same = 1;
    }
    if (same) {
        digifilter_svf(buf, 32, (const int32 *)&c1, dsp_st[v]);
        return;
    }
    {
        /* Build the four sub-block sets and run them in one call: the prologue/
         * epilogue and the EMAC save/restore happen once, not four times. */
        struct df_coef c4[4];
        for (k = 0; k < 4; k++) {
            int w = k + 1;                           /* 1..4, ends exactly at c1 */
            int32 *d = (int32 *)&c0, *e = (int32 *)&c1;
            int32 *o = (int32 *)&c4[k];
            int j;
            for (j = 0; j < 6; j++) {
                /* Lerp d..e by w/4 without overflowing on a large jump: split the
                 * delta so no intermediate exceeds 32 bits. */
                int32 delta = e[j] - d[j];
                o[j] = d[j] + (delta >> 2) * w + (((delta & 3) * w) >> 2);
            }
        }
        digifilter_svf4(buf, (const int32 *)c4, dsp_st[v]);
    }
}

void df_reset(int v)
{
    if (v < 0 || v >= 8)
        return;
    comb_init[v] = 0;
    svf_have[v] = 0;
    dsp_st[v][0] = 0;
    dsp_st[v][1] = 0;
}
