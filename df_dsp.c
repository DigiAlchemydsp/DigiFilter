/* SPDX-License-Identifier: GPL-2.0-or-later */
/* DigiFilter shared DSP core: firmware-free SVF/comb math + per-voice state.
 *
 * Digitakt 1.1a verbatim (copy-paste, no logic changes). 1.1a keeps cached
 * SVF coefficients when still (one digifilter_svf call for the whole block)
 * and ramps from the cached set when sweeping; c1=k exactly (one mulsh saved).
 * Sound identical, cost lower when still. No kit/engine/firmware here.
 */
#include "df_dsp.h"
#include "filter_tables.h"

extern void digifilter_svf(int32 *buf, int frames, const int32 *coef, int32 *state);

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

/* floor(2^55 / d), d > 2^24. */
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

int df_clampi(int v, int lo, int hi)
{
    return v < lo ? lo : v > hi ? hi : v;
}

/* SVF coefficients and band-pass mix (c0=-1 cancels v0, c1=k, c2=0).
 * Q is capped (top of K27 overshoots); m==1 is BP2 and halves Q. */
void df_mode_coef(int m, int fi, int qi, struct df_coef *c)
{
    int qk = qi * 13 / 15;
    int32 g = G27[fi], k = K27[(m == 1) ? (qk >> 1) : qk], d24;
    c->c0 = -ONE27;
    c->c1 = k;
    c->c2 = 0;
    d24 = (1 << 24) + df_mulsh(g, g + k, 30);
    c->a1 = df_div55((uint32)d24);
    c->a2 = df_mulsh(g, c->a1, 27);
    c->a3 = df_mulsh(g, c->a2, 27);
}

/* Feedback comb, fractional and smoothed: y = x + g*y[n-D].
 * D = COMB_DELAY[fi] / (div * hdiv), clamped 3..255; g from fb 0..127.
 * Delay and feedback glide per sample; output saturates at +-2^27. */
void df_comb_run(int32 *buf, int frames, int fi, int fb, int v, int div,
                 int hdiv, int damp)
{
    int32 target = COMB_DELAY[fi] / (div * hdiv);
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
    for (k = 0; k < 4; k++) {
        int w = k + 1;
        int32 *d = (int32 *)&c0, *e = (int32 *)&c1;
        struct df_coef c;
        int32 *o = (int32 *)&c;
        int j;
        for (j = 0; j < 6; j++) {
            int32 delta = e[j] - d[j];
            o[j] = d[j] + (delta >> 2) * w + (((delta & 3) * w) >> 2);
        }
        digifilter_svf(buf + 8 * k, 8, (const int32 *)&c, dsp_st[v]);
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
