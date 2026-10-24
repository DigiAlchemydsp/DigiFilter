/* Filter+FX shared DSP core: VOWEL/BANK/FOLD/CRUSH/RING/PHASER/FLANGER.
 * Firmware-free; the DN adapter passes mode/fi/qi/aux1/aux2, buf and voice.
 */
#ifndef FX_DSP_C
#define FX_DSP_C

typedef int int32;
typedef unsigned int uint32;

#include "fx_dsp.h"
#include "biquad_tables.h"
#include "analog_tables.h"
#include "mod_tables.h"

enum { FM_VOWEL, FM_BANK, FM_FOLD, FM_CRUSH, FM_RING, FM_PHASER, FM_FLANGER, FM_NMODES };

#define MAX_BANDS 4

/* Full-scale sample (the biquad kernel saturates here too). */
#define FM_FULL (1 << 27)

static inline int32 sat_full(int32 v)
{
    return v > FM_FULL ? FM_FULL : v < -FM_FULL ? -FM_FULL : v;
}

/* Q30 b0, b2, n1 = -a1, n2 = -a2. The bands are the same size for both modes. */
struct bcoef { int32 b0, b2, n1, n2; };

extern void digifilter_biq(int32 *buf, const int32 *coef, int32 *state);
extern void digifilter_biq4(int32 *buf, const int32 *coef4, int32 *state);

static inline __attribute__((always_inline)) int32 mulsh(int32 a, int32 b, int sh)
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

static int clampi(int v, int lo, int hi)
{
    return v < lo ? lo : v > hi ? hi : v;
}

/* RESO 0..127 -> K27 row 8..15 (Q 1.7 .. 8). */
static int q_row(int qi)
{
    return 8 + qi * 7 / 127;
}

/* One band's biquad: the (Q row, FREQ) table entry with the band gain folded
 * into b0/b2 (Q30 in, Q30 out). */
static void band_coef(int fi8, int ek, int32 gain_q30, struct bcoef *c)
{
    const int *t;
    int i = (fi8 + 128) >> 8;
    i = clampi(i, 0, 127);
    t = BIQ_Q30[ek - 8][i];
    /* b0/b2/n2 are Q31; n1 can reach +-2, so it stays Q30 and the kernel
     * applies it twice. */
    c->b0 = mulsh(t[0], gain_q30, 30) << 1;
    c->b2 = mulsh(t[1], gain_q30, 30) << 1;
    c->n1 = t[2];
    c->n2 = t[3] << 1;
}

static void build_target(int m, int fi, int qi, int a1, int a2, struct bcoef *c)
{
    int b, ek = q_row(qi);
    if (m == FM_VOWEL) {
        int off = a1 * 12 * 256 / 127;              /* SIZE: 0..+1 octave */
        int32 g4 = mulsh(VOWEL_GAIN[3], (127 + a2) * 258, 15) << 3; /* F4: 1..2x */
        for (b = 0; b < VOWEL_N - 1; b++)
            band_coef(VOWEL_FI8[b][fi] + off, ek, VOWEL_GAIN[b] << 3, &c[b]);
        band_coef(VOWEL_FI8[3][fi] + off, ek, g4, &c[3]);
    } else {
        int shift = (fi - 64) * 12 * 256 / 64;      /* +-12 FREQ steps, ~1 octave */
        int spread = a1 * 12 * 256 / 127;           /* SPREAD: top band +1 octave */
        for (b = 0; b < BANK_N; b++) {
            int off = spread * b / 3;
            int tilt = a2 * (2 * b - 3) / 3;        /* TILT: 0 = flat */
            int32 g = mulsh(BANK_GAIN[b], (127 + tilt) * 258, 15) << 3;
            band_coef(BANK_BASE_FI8[b] + shift + off, ek, g, &c[b]);
        }
    }
}

/* filter_glue.s remembers the render's original a3 target here. */

/* per voice: z1[0..3] then z2[0..3], and the last block's coefficient target */
static int32 biq_st[8][8];
static struct bcoef prev_c[8][MAX_BANDS];
static int prev_type[8] = { -1, -1, -1, -1, -1, -1, -1, -1 };
static int prev_fi[8], prev_qi[8], prev_a1[8], prev_a2[8];
static int crush_hold[8];
static int32 crush_last[8];

/* FOLD: triangle wavefolder. The input is shifted to Q27 and driven 1..8x,
 * then folded around +-1 (2^27) with a bias from RESO. No state. */
#define FOLD_F FM_FULL
static inline int32 fold_sample(int32 x, int drive, int32 bias)
{
    int32 v = (x >> 4) * drive + bias;
    uint32 u = (uint32)v & (4u * FOLD_F - 1);
    if (u > 2u * FOLD_F)
        u = 4u * FOLD_F - u;
    return (int32)u - FOLD_F;
}

static void run_fold(int fi, int qi, int32 *buf)
{
    int drive = 1 + fi * 7 / 127;
    int32 bias = (int32)(qi - 64) << 21;
    int i;
    for (i = 0; i < 32; i++)
        buf[i] = fold_sample(buf[i], drive, bias);
}

/* CRUSH: sample-rate hold (FREQ) plus bit-depth quantisation (RESO). */
static void run_crush(int fi, int qi, int32 *buf, int v)
{
    int rate = 1 + fi * 31 / 127;
    int bits = 16 - qi * 15 / 127;
    int shift = 31 - bits;
    int hold = crush_hold[v];
    int32 last = crush_last[v];
    int i;
    for (i = 0; i < 32; i++) {
        if (hold <= 0) {
            last = buf[i];
            hold = rate;
        }
        hold--;
        buf[i] = (last >> shift) << shift;
    }
    crush_hold[v] = hold;
    crush_last[v] = last;
}

static inline int32 mulq31(int32 a, int32 b)
{
#ifdef __mcoldfire__
    int32 r;
    __asm__ volatile("mac.l %1,%2,%%acc0\n\tmovclr.l %%acc0,%0"
                     : "=d"(r) : "d"(a), "d"(b));
    return r;
#else
    return (int32)(((long long)a * b) >> 31);
#endif
}

/* ---- RING: carrier sine at FREQ, depth from RESO ---- */
static uint32 ring_phase[8];

static void run_ring(int fi, int qi, int32 *buf, int v)
{
    uint32 ph = ring_phase[v], inc = RING_INC[fi];
    int32 depth31 = ((int32)qi * 258) << 16;    /* Q15 -> Q31 */
    int i;
#ifdef __mcoldfire__
    int32 macsr, acc0, ext;
    __asm__ volatile("move.l %%macsr,%0\n\tmove.l %%acc0,%1\n\tmove.l %%accext01,%2"
                     : "=d"(macsr), "=d"(acc0), "=d"(ext));
    __asm__ volatile("move.l #0x20,%%d1\n\tmove.l %%d1,%%macsr" ::: "d1");
#endif
    for (i = 0; i < 32; i++) {
        int32 x = buf[i], s31, ring;
        ph += inc;
        s31 = (int32)SINE_Q15[ph >> 24] << 16;
        ring = mulq31(s31, x);
        buf[i] = x + mulq31(depth31, ring - x);
    }
    ring_phase[v] = ph;
#ifdef __mcoldfire__
    __asm__ volatile("move.l %0,%%acc0\n\tmove.l %1,%%accext01\n\tmove.l %2,%%macsr"
                     :: "d"(acc0), "d"(ext), "d"(macsr));
#endif
}

/* ---- PHASER: four cascaded first-order allpasses, LFO on the coefficient ---- */
static int32 ph_x1[8][4], ph_y1[8][4];
static uint32 ph_phase[8];

static void run_phaser(int fi, int qi, int32 *buf, int v)
{
    uint32 ph = ph_phase[v], inc = LFO_INC[fi];
    int32 depth = (int32)qi * 258;              /* Q15 */
    int32 x1[4], y1[4];
    int i, k;
#ifdef __mcoldfire__
    int32 macsr, acc0, ext;
    __asm__ volatile("move.l %%macsr,%0\n\tmove.l %%acc0,%1\n\tmove.l %%accext01,%2"
                     : "=d"(macsr), "=d"(acc0), "=d"(ext));
    __asm__ volatile("move.l #0x20,%%d1\n\tmove.l %%d1,%%macsr" ::: "d1");
#endif
    for (k = 0; k < 4; k++) {
        x1[k] = ph_x1[v][k];
        y1[k] = ph_y1[v][k];
    }
    for (i = 0; i < 32; i++) {
        int32 dry = buf[i], x = dry, a15, a31;
        int32 lfo = SINE_Q15[ph >> 24];
        ph += inc;
        a15 = 16384 + (((lfo * depth) >> 15) >> 1);
        if (a15 < 2000)
            a15 = 2000;
        else if (a15 > 30000)
            a15 = 30000;
        a31 = a15 << 16;
        for (k = 0; k < 4; k++) {
            int32 y = x1[k] + mulq31(a31, y1[k]) - mulq31(a31, x);
            x1[k] = x;
            y1[k] = y;
            x = y;
        }
        /* A first-order allpass passes a step with overshoot; four in series
         * can push the dry+wet sum past full scale on transients. Saturate the
         * output so it clips cleanly instead of wrapping the 32-bit sample. */
        buf[i] = sat_full((x + dry) >> 1);
    }
    for (k = 0; k < 4; k++) {
        ph_x1[v][k] = x1[k];
        ph_y1[v][k] = y1[k];
    }
    ph_phase[v] = ph;
#ifdef __mcoldfire__
    __asm__ volatile("move.l %0,%%acc0\n\tmove.l %1,%%accext01\n\tmove.l %2,%%macsr"
                     :: "d"(acc0), "d"(ext), "d"(macsr));
#endif
}

/* ---- FLANGER: LFO-modulated fractional delay with feedback ---- */
#define FL_N 256
#define FL_MASK (FL_N - 1)
/* 16-bit line: Q15 per entry (1.0 = 32768), converted to/from Q27 at the
 * edges. 256 entries hold the 2..255-sample sweep (max 5.3 ms). */
static short fl_buf[8][FL_N];
static int fl_pos[8];
static uint32 fl_phase[8];

static void run_flanger(int fi, int qi, int32 *buf, int v)
{
    uint32 ph = fl_phase[v], inc = LFO_INC[fi];
    short *b = fl_buf[v];
    int p = fl_pos[v];
    int32 base = 128 << 16;                     /* 2.7 ms centre */
    int32 depth = qi;                           /* up to +-127 samples */
    int32 g = (int32)qi * (FOLD_F * 4 / 5 / 127);
    int i;
    for (i = 0; i < 32; i++) {
        int32 x = buf[i], lfo = SINE_Q15[ph >> 24];
        int32 dq = base + lfo * depth * 2;      /* Q16 samples, +-depth */
        int32 ip, fp, i0, i1, val, fb, fa, ga, va;
        ph += inc;
        if (dq < (2 << 16))                     /* centre 128 > depth 127 */
            dq = 2 << 16;
        else if (dq > (FL_MASK << 16))
            dq = FL_MASK << 16;
        ip = dq >> 16;
        fp = dq & 0xffff;
        i0 = (p - ip) & FL_MASK;
        i1 = (i0 - 1) & FL_MASK;
        fa = fp >> 1;
        val = ((int32)b[i0] + ((fa * (b[i1] - b[i0])) >> 15)) << 12;
        /* Feedback goes into the line; the output is the usual dry + delayed
         * mix, so RESO 0 still gives a comb and RESO only adds regeneration. */
        ga = g >> 12;
        va = val >> 11;
        fb = sat_full(x + ((ga * va) >> 4));
        b[p] = (short)clampi((fb + 2048) >> 12, -32768, 32767);
        p = (p + 1) & FL_MASK;
        buf[i] = (x + val) >> 1;
    }
    fl_phase[v] = ph;
    fl_pos[v] = p;
}


static void run_mode(int m, int fi, int qi, int a1, int a2, int32 *buf, int v)
{
    struct bcoef target[MAX_BANDS], *pc = prev_c[v];
    int32 coef[MAX_BANDS * 4], coef4[4 * MAX_BANDS * 4];
    int b, k, j;
    int reset = prev_type[v] != m;
    int same = !reset && prev_fi[v] == fi && prev_qi[v] == qi &&
               prev_a1[v] == a1 && prev_a2[v] == a2;

    if (!same)
        build_target(m, fi, qi, a1, a2, target);
    if (reset) {
        for (b = 0; b < 8; b++)
            biq_st[v][b] = 0;
        for (b = 0; b < MAX_BANDS; b++)
            pc[b] = target[b];
    }
    if (same) {
        for (b = 0; b < MAX_BANDS; b++) {
            coef[b * 4 + 0] = pc[b].b0;
            coef[b * 4 + 1] = pc[b].b2;
            coef[b * 4 + 2] = pc[b].n1;
            coef[b * 4 + 3] = pc[b].n2;
        }
        digifilter_biq(buf, coef, biq_st[v]);
    } else {
        for (k = 0; k < 4; k++) {
            int w = k + 1;
            for (b = 0; b < MAX_BANDS; b++) {
                int32 *o = &coef4[k * 16 + b * 4];
                int32 *a = (int32 *)&pc[b], *z = (int32 *)&target[b];
                for (j = 0; j < 4; j++) {
                    int32 d = z[j] - a[j];
                    o[j] = a[j] + (d >> 2) * w + (((d & 3) * w) >> 2);
                }
            }
        }
        digifilter_biq4(buf, coef4, biq_st[v]);
    }
    if (!same)
        for (b = 0; b < MAX_BANDS; b++)
            pc[b] = target[b];
    prev_type[v] = m;
    prev_fi[v] = fi;
    prev_qi[v] = qi;
    prev_a1[v] = a1;
    prev_a2[v] = a2;
}


void fx_reset(int v)
{
    int b, k;
    if (v < 0 || v >= 8)
        return;
    for (b = 0; b < 8; b++)
        biq_st[v][b] = 0;
    for (b = 0; b < MAX_BANDS; b++) {
        prev_c[v][b].b0 = prev_c[v][b].b2 = 0;
        prev_c[v][b].n1 = prev_c[v][b].n2 = 0;
    }
    prev_type[v] = -1;
    prev_fi[v] = prev_qi[v] = prev_a1[v] = prev_a2[v] = 0;
    crush_hold[v] = 0;
    crush_last[v] = 0;
    ring_phase[v] = 0;
    ph_phase[v] = 0;
    for (k = 0; k < 4; k++)
        ph_x1[v][k] = ph_y1[v][k] = 0;
    fl_phase[v] = 0;
    fl_pos[v] = 0;
    for (k = 0; k < FL_N; k++)
        fl_buf[v][k] = 0;
}

void fx_run(int m, int fi, int qi, int a1, int a2, int32 *buf, int v)
{
    if (m < 0 || m >= FM_NMODES || v < 0 || v >= 8)
        return;
    if (m == FM_FOLD) {
        prev_type[v] = m;
        run_fold(fi, qi, buf);
    } else if (m == FM_CRUSH) {
        if (prev_type[v] != m) {
            crush_hold[v] = 0;
            crush_last[v] = 0;
            prev_type[v] = m;
        }
        run_crush(fi, qi, buf, v);
    } else if (m == FM_RING) {
        if (prev_type[v] != m) {
            ring_phase[v] = 0;
            prev_type[v] = m;
        }
        run_ring(fi, qi, buf, v);
    } else if (m == FM_PHASER) {
        if (prev_type[v] != m) {
            int k;
            ph_phase[v] = 0;
            for (k = 0; k < 4; k++)
                ph_x1[v][k] = ph_y1[v][k] = 0;
            prev_type[v] = m;
        }
        run_phaser(fi, qi, buf, v);
    } else if (m == FM_FLANGER) {
        if (prev_type[v] != m) {
            int k;
            fl_phase[v] = 0;
            fl_pos[v] = 0;
            for (k = 0; k < FL_N; k++)
                fl_buf[v][k] = 0;
            prev_type[v] = m;
        }
        run_flanger(fi, qi, buf, v);
    } else {
        run_mode(m, fi, qi, a1, a2, buf, v);
    }
}

#endif
