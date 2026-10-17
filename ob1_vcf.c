/* The OB-1 filter modes: a zero-delay-feedback 4-pole ladder of trapezoidal one-poles, Q31 fixed point, as
 * tests/ob1_model.py's Ladder (the reference). Integer only, no libgcc: on the ColdFire every multiply is an
 * EMAC fractional mac.l, rounding (the MACSR is set and restored here); on the host (the tests) the same in C.
 *
 * Per sample: the stages' states carried through the loop, S = G^3 (1-G) s0 + G^2 (1-G) s1 + G (1-G) s2
 * + (1-G) s3 (in Horner's form); the linear loop's u = (x - k S) / (1 + k G^4), and y4's estimate from it,
 * G^4 u + S; the feedback through U28's saturation, u = x - k T(that); the four one-poles, v = G (in - s),
 * y = v + s, s' = y + v. Per block: G from the table (interpolated), G^4, 1 / (1 + k G^4) and
 * G^4 / (1 + k G^4), ramped from the last block's across four sub-blocks. The stages' own saturation (the
 * model's KS) is left out: it only shows without resonance, about 0.03 % THD at twice a VCO's level in SPICE.
 *
 * Cubic cutoff and quadratic subthreshold resonance follow the measured reference controls. */
#include "ob1_vcf.h"
#include "ob1_tables.h"

typedef int int32;
typedef unsigned int uint32;

/* U28's knee on y4: the model's KF = 1.61, with one VCO = 2^27 internally. */
#define INV_KF      325645      /* 2^46 / (1.61 * 2^27): fmul(y, INV_KF) = y / KF in Q15 */
#define KF4_5       172872434   /* 4/5 KF: the polynomial at y = KF, its ceiling */
/* The render's blocks are Q31 (a full-scale sample 2^31); inside, one OB-1 VCO at ON is 2^27, the model's unit.
 * A full-scale sample is two VCOs: it saturates as a hot OB-1 mix does, and leaves the states headroom. */
#define IN_SHIFT    3
/* No clamp on the loop's input: |x| <= 2^28 and U28's saturated feedback adds at most k 4/5 KF = 7.3e8, so
 * |u| < 2^30 by construction (the linear path, for the tests only, is fed small signals). The output is
 * clamped before it is scaled back, so a resonant peak on a full-scale input saturates rather than wraps. */
#define Y_MAX       ((1 << (33 - IN_SHIFT)) - 1)
#define SEED        1024        /* nudged into stage 1 each block with a random sign, -102 dB of a VCO: an analog
                                   filter's own noise, so self-oscillation starts from silence. Smaller ones
                                   round away in the stages (a stage passes nothing under ~0.5 / G LSBs). A sign
                                   that only alternated (a 750 Hz pattern) never started a low cutoff; the
                                   random one has the low frequencies */
#define SEED_K8     1057635697  /* k / 8 = 3.94 / 8, Q31: only near oscillation, otherwise it would leak to the
                                   output and silence in would not give silence out */

#ifdef __mcoldfire__
static inline __attribute__((always_inline)) int32 fmul(int32 a, int32 b)  /* (a * b) >> 31, rounded */
{
    int32 r;
    __asm__ volatile("mac.l %1,%2,%%acc0\n\tmovclr.l %%acc0,%0" : "=d"(r) : "r"(a), "r"(b));
    return r;
}
#else
static inline int32 fmul(int32 a, int32 b)
{
    return (int32)(((long long)a * b + (1LL << 30)) >> 31);
}
#endif

struct ob1_coef {
    int32 G, k8, r, g4r;        /* G; k / 8; 1 / (1 + k G^4), Q30; G^4 / (1 + k G^4) */
};

struct ob1_state {
    int32 s[4];
    struct ob1_coef c;          /* the coefficients at the end of the last block: this block ramps from them */
    int fresh;                  /* no last block: don't ramp */
};

static struct ob1_state st[8] = {[0 ... 7] = {.fresh = 1}};
static int32 seed = SEED;                       /* SEED with a random sign, new each block */
static uint32 lcg = 1;

void ob1_vcf_reset(int v)
{
    st[v].s[0] = st[v].s[1] = st[v].s[2] = st[v].s[3] = 0;
    st[v].fresh = 1;
}

/* The coefficients for a cutoff index (8.8: 0..127 << 8, between the table's whole indices linearly) and
 * RESO 0..127. One division. */
static void coef(int fi8, int qi, struct ob1_coef *c)
{
    int32 G, G4, i = fi8 >> 8;
    uint32 den16, k24;
    G = OB1_G[i] + ((OB1_G[i + 1] - OB1_G[i]) >> 8) * (fi8 & 0xff);
    G4 = fmul(G, G);
    G4 = fmul(G4, G4);
    c->G = G;
    k24 = (10u * (1u << 24) / (127 * 127)) * (uint32)(qi * qi);
    /* Compress above-onset drive to match the measured amplitude rise with the retained saturation. */
    if (k24 > (4u << 24)) {
        uint32 d12 = (k24 >> 12) - (5u << 11);                        /* k - 2.5, Q12 */
        k24 = ((17u << 14) - (3u << 25) / d12) << 8;                  /* 4.25 - 0.375/(k - 2.5), Q24 */
    }
    c->k8 = (int32)(k24 << 4);                                       /* k / 8, Q31 */
    den16 = 65536u + ((uint32)fmul(c->k8, G4) >> 12);                  /* 1 + k G^4, Q16 */
    c->r = (int32)((0x80000000u / den16) << 15);                        /* its reciprocal, Q30 */
    c->g4r = fmul(G4, c->r) << 1;                                      /* G^4 / (1 + k G^4), Q31 */
}

/* U28's saturation, KF tanh(y / KF), as tanh's series to the fifth power, z - z^3/3 + 2 z^5/15 (z = y / KF),
 * up to the knee and its value there, 4/5 KF, past it: the linear part exact, only the correction quantised.
 * The cubic alone over-compresses from z ~ 0.5 (2.1 dB too much THD at 4x a VCO with k 3.3). */
static inline int32 fbsat(int32 y)
{
    int32 z = fmul(y, INV_KF), z2;              /* y / KF, Q15 */
    if (z >= 32768)
        return KF4_5;
    if (z <= -32768)
        return -KF4_5;
    z2 = (z * z) >> 15;                         /* z^2, Q15 */
    /* Both integer weights share 4369; factor after the existing Q15 truncation. */
    return y - fmul(y, (5 * z2 - 2 * ((z2 * z2) >> 15)) * 4369);
}

/* The sample loop, inlined into one copy per (linear, two): gcc then tests neither per sample. Four sub-blocks of
 * 8 samples, each with the coefficients at its middle on the line from a (the last block's end) to b (this
 * one's), as svf_run ramps: a cutoff moving each block doesn't step. */
static inline __attribute__((always_inline)) void loop(int32 *s, int32 *buf, const struct ob1_coef *a,
                                                         const struct ob1_coef *b, const int linear, const int two)
{
    int32 s0 = s[0] + (linear || b->k8 < SEED_K8 ? 0 : seed), s1 = s[1], s2 = s[2], s3 = s[3];
    int32 dG = (b->G - a->G) >> 3, dk = (b->k8 - a->k8) >> 3, dr = (b->r - a->r) >> 3, dg = (b->g4r - a->g4r) >> 3;
    int j, i;
    for (j = 0; j < 4; j++) {
        int32 G = a->G + dG * (2 * j + 1), k8 = a->k8 + dk * (2 * j + 1);
        int32 r = a->r + dr * (2 * j + 1), g4r = a->g4r + dg * (2 * j + 1), omg = 0x7fffffff - G;
        for (i = 8 * j; i < 8 * j + 8; i++) {
            int32 S, e, u, w, x = buf[i] >> IN_SHIFT, y1, y2, y3, y4, y;
            S = fmul(omg, fmul(G, fmul(G, fmul(G, s0) + s1) + s2) + s3);  /* Horner: 4 multiplies, not 7 */
            e = x - (fmul(k8, S) << 3);                              /* x - k S */
            if (linear)
                u = fmul(e, r) << 1;                                 /* the loop's input, (x - k S) / (1 + k G^4) */
            else                                                     /* y4's linear estimate through U28 */
                u = x - (fmul(k8, fbsat(fmul(g4r, e) + S)) << 3);
            w = fmul(G, u - s0); y1 = w + s0; s0 = y1 + w;
            w = fmul(G, y1 - s1); y2 = w + s1; s1 = y2 + w;
            w = fmul(G, y2 - s2); y3 = w + s2; s2 = y3 + w;
            w = fmul(G, y3 - s3); y4 = w + s3; s3 = y4 + w;
            y = two ? y2 : y4;                                       /* x 0.25, as every stock TYPE, back to Q31 */
            y = y > Y_MAX ? Y_MAX : y < -Y_MAX ? -Y_MAX : y;
            buf[i] = y << (IN_SHIFT - 2);
        }
    }
    s[0] = s0; s[1] = s1; s[2] = s2; s[3] = s3;
}

void ob1_vcf_run(int tap, int fi8, int qi, int *buf, int v)
{
    struct ob1_state *p = &st[v];
    struct ob1_coef a, b;
    int linear = tap & OB1_LINEAR, two = (tap & 0xff) == OB1_TAP2;
#ifdef __mcoldfire__
    int32 macsr;
    __asm__ volatile("move.l %%macsr,%0\n\tmove.l #0x30,%%d0\n\tmove.l %%d0,%%macsr" : "=d"(macsr) :: "d0");
#endif
    fi8 = fi8 < 0 ? 0 : fi8 > (127 << 8) ? 127 << 8 : fi8;
    qi = qi < 0 ? 0 : qi > 127 ? 127 : qi;
    coef(fi8, qi, &b);
    a = p->fresh ? b : p->c;
    p->c = b;
    p->fresh = 0;
    lcg = lcg * 1664525u + 1013904223u;                          /* a random sign each block */
    seed = lcg & 0x80000000u ? -SEED : SEED;
    if (linear)
        two ? loop(p->s, buf, &a, &b, 1, 1) : loop(p->s, buf, &a, &b, 1, 0);
    else
        two ? loop(p->s, buf, &a, &b, 0, 1) : loop(p->s, buf, &a, &b, 0, 0);
#ifdef __mcoldfire__
    __asm__ volatile("move.l %0,%%macsr" :: "d"(macsr));
#endif
}
