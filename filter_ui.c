/* Digi Filter: the FLTR page's FREQ/RES response *curve* for the new modes.
 *
 * The stock page draws the curve itself, from UI-model state, so nothing the
 * DSP writes reaches it (see RE_NOTES.md). Patching the page's drawView vtable
 * word (0x401842a0) with an op:ptr site does not survive a multi-mod build:
 * that slot is the shared track-parameter page view class, and core's ev_draw
 * event trampoline owns it whenever a mod subscribes to ev_draw (see RE_NOTES
 * §11). So instead this mod subscribes to core's ev_draw: after the whole frame
 * has been drawn (stock curve included) digifilter_draw paints over it.
 *
 * The handler walks the view controller's view list (the same list drawAll
 * iterates), takes the top view, and when its page kind is the FLTR kind (6)
 * and the active track's TYPE is one of ours, paints the BP/BP2 band-pass bell
 * or the COMB/TRASH comb teeth over the graph area.
 *
 * The curve is the same shape the DSP makes (filter_tables.h): BP/BP2 a
 * state-variable band pass at FREQ with RESO, COMB/TRASH the harmonic peaks of a
 * comb at FREQ. It is drawn in the same graph box the stock page uses so it
 * reads as the same UI.
 */
typedef int int32;
typedef unsigned int uint32;

#include "filter_tables.h"

/* the firmware's drawing primitives (OS 1.53) */
typedef void (*fillrect_t)(void *bmp, int x0, int y0, int x1, int y1, int colour);
#define FILLRECT ((fillrect_t)0x400c19a6)    /* colour 0 clear, 1 set, -1 invert */
/* The page kind: the view's kind vector is at +124, its end at +128 and the
 * shown index at +144; kind = vector[index] (as digieq/digipoly read it). */
#define VIEW_KINDS(view) (*(int32 **)((char *)(view) + 124))
#define VIEW_KINDS_END(view) (*(int32 **)((char *)(view) + 128))
#define VIEW_INDEX(view) (*(int32 *)((char *)(view) + 144))

/* The view controller drawAll (0x400ca382) walks: a circular list of view nodes
 * whose sentinel is embedded at ctrl+0x14, with the first node at *(ctrl+0x1c).
 * A node's view object is at +8 and its next at +0. The controller is the
 * second argument of an ev_draw handler. */
#define CTRL_SENTINEL(ctrl) ((char *)(ctrl) + 0x14)
#define CTRL_HEAD(ctrl) (*(char **)((char *)(ctrl) + 0x1c))
#define NODE_VIEW(node) (*(void **)((char *)(node) + 8))
#define NODE_NEXT(node) (*(char **)(node))

/* the active track and the pattern's kit (RE_NOTES): kit + 0x20 + t*0xa2 is the
 * track's sound block, slot s a word at +0x14 + 2s. */
#define UI_KIT (*(unsigned char *volatile *)0x4199dc44)
#define ACTIVE_TRACK (*(int *volatile *)0x4197b6b4)
#define FSLOT(kit, t, s) ((int)(*(unsigned short *)((kit) + 0x20 + (t) * 0xa2 + 0x14 + 2 * (s))))
#define FS_TYPE 0x19
#define FS_FREQ 0x1a
#define FS_RESO 0x1b
/* COMB/TRASH controls on the second page: spare sound slots (47/48), driven by
 * two commandeered 'Error' descriptors (see page2_setup). They coexist with the
 * stock Base/Width/Env Delay/SRR knobs, which are left untouched; the comb
 * feedback is the RESO/GAIN knob (slot 0x1b). */
#define FS_HARM 0x2f
#define FS_DAMP 0x30

/* the FLTR page kind. The page-kind list is at view+124 (vector), the index at
 * view+144; kind -> layout is 0x400657b2 (20 x 44 bytes at RAM 0x4197cf88),
 * whose +8.. are the 8 knob descriptor ids. The FLTR page's layout is
 * {ATK, DEC, SUS, REL, FREQ, RESO, TYPE, ENV} = ids {34,35,36,37,30,32,33,38}
 * = kind 6 (confirmed from the gui.snap RAM layout table). The second FLTR
 * page (FLTR pressed again) is kind 7 = {EnvDelay, -, -, SRR, Base, Width, -,
 * Routing} = ids {39,0,0,42,40,41,0,43}; the '-' entries are empty dotted boxes
 * (descriptor id 0). */
#define FLTR_KIND 6
#define FLTR2_KIND 7

/* kind -> layout: 20 entries of 44 bytes at RAM 0x4197cf88 (function
 * 0x400657b2). Entry +8..+39 are the 8 encoder descriptor ids (32-bit). */
#define LAYOUT_TABLE 0x4197CF88UL
#define LAYOUT_STRIDE 44
#define LAYOUT_PAGE2 (LAYOUT_TABLE + FLTR2_KIND * LAYOUT_STRIDE)
#define LAYOUT_IDS ((volatile unsigned *)(LAYOUT_PAGE2 + 8))

/* The parameter descriptor table (0x401a9d9c, 0x34 bytes each). Descriptors 0..16
 * are unused 'Error' placeholders (group 0xffff); for COMB/TRASH we commandeer
 * 13/14/15 as real filter descriptors for the new knobs and restore them after.
 * Field offsets: +2 group, +6 slot, +14 range, +18 step, +0x30 short name. */
#define DESC_TABLE 0x401A9D9CUL
#define DESC_STRIDE 0x34
#define DESC_NEW0 14
#define DESC_NEW1 15
#define DESC_TEMPLATE 42                 /* copy SRR's fields (it draws a dial), override the rest */

static const char DF_L_HARM[] = "HARM";
static const char DF_L_DAMP[] = "DAMP";

enum { FM_BP, FM_BP2, FM_COMB, FM_TRASH, FM_NMODES };
#define FM_FIRST_TYPE 8

/* Graph box: the FLTR page's FREQ/RES response area (screen 128 x 64, firmware
 * bitmap row 0 = the bottom). Measured off the stock page: the box is x 20..71,
 * E.fb rows 40..56 (top-origin) = firmware rows 7..23. */
#define GX0 20
#define GX1 71
#define GY0 7
#define GY1 23

/* The small filter-type box to the right of the response graph (same rows as
 * the graph box); the stock page draws an "EQ n" glyph and name inside it. */
#define TBX0 78
#define TBX1 92
#define TBY0 8
#define TBY1 22

static int32 curve[128];                 /* raw response per frequency step */

static int clampi(int v, int lo, int hi)
{
    return v < lo ? lo : v > hi ? hi : v;
}

static int32 mulsh(int32 a, int32 b, int sh)
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

static uint32 udivq16(uint32 x, uint32 y)     /* floor(x * 65536 / y) */
{
    uint32 rem = x, q = 0;
    int i;
    for (i = 0; i < 16; i++) {
        rem <<= 1;
        q <<= 1;
        if (rem >= y) {
            rem -= y;
            q |= 1;
        }
    }
    return q;
}

/* log2(v) x 256, v > 0 (LOG2Q8 as Digi EQ) */
static const unsigned short LOG2Q8[256] = {
    0, 3, 6, 8, 11, 14, 16, 19, 22, 24, 27, 29, 32, 34, 37, 39,
    42, 45, 47, 50, 52, 54, 57, 59, 62, 64, 67, 69, 71, 74, 76, 78,
    81, 83, 85, 88, 90, 92, 94, 97, 99, 101, 103, 105, 108, 110, 112, 114,
    116, 119, 121, 123, 125, 127, 129, 131, 133, 135, 138, 140, 142, 144, 146, 148,
    150, 152, 154, 156, 158, 160, 162, 164, 166, 168, 169, 171, 173, 175, 177, 179,
    181, 183, 185, 186, 188, 190, 192, 194, 196, 197, 199, 201, 203, 205, 206, 208,
    210, 212, 213, 215, 217, 219, 220, 222, 224, 225, 227, 229, 231, 232, 234, 236,
    237, 239, 241, 242, 244, 246, 247, 249, 250, 252, 254, 255, 257, 259, 260, 262,
    263, 265, 267, 268, 270, 271, 273, 274, 276, 277, 279, 281, 282, 284, 285, 287,
    288, 290, 291, 293, 294, 296, 297, 299, 300, 302, 303, 305, 306, 308, 309, 311,
    312, 314, 315, 316, 318, 319, 321, 322, 324, 325, 326, 328, 329, 331, 332, 333,
    335, 336, 338, 339, 340, 342, 343, 345, 346, 347, 349, 350, 351, 353, 354, 355,
    357, 358, 359, 361, 362, 363, 365, 366, 367, 369, 370, 371, 373, 374, 375, 377,
    378, 379, 380, 382, 383, 384, 386, 387, 388, 389, 391, 392, 393, 394, 396, 397,
    398, 399, 401, 402, 403, 404, 406, 407, 408, 409, 411, 412, 413, 414, 415, 417,
    418, 419, 420, 421, 423, 424, 425, 426, 427, 429, 430, 431, 432, 433, 434, 436,
};

static int log2q8(uint32 v)
{
    int p = 31;
    uint32 m;
    while (!(v >> p))
        p--;
    m = p >= 8 ? v >> (p - 8) : v << (8 - p);
    return p * 256 + LOG2Q8[m & 255];
}

/* BP/BP2: the band-pass magnitude of the same trapezoidal SVF the DSP runs
 * (a1 = 1/(1+g(g+k)), c0 = -1, c1 = k, c2 = 0): at the frequency step x, with
 * r = g(x)/g(f): for r <= 1 the response is r*k / sqrt((1-r^2)^2 + (r k)^2)
 * (band gain), in half-dB. k is scaled down (narrow: *3/4, wide: *1/2) so the
 * bell is narrower than the DSP's as-drawn Q. */
static int bp_db2(int fi, int qi, int x, int wide)
{
    int32 g = wide ? G27[fi] << 1 : G27[fi];     /* BP2: roughly double the width */
    /* k in Q16 (k27 >> 11): the products below must stay under 2^32 (the old
     * Q27 k made num^2 wrap, which drew noise). */
    int32 k = (K27[wide ? (qi >> 1) : qi] >> 11) * (wide ? 1 : 3) / (wide ? 2 : 4);
    int32 G = G27[x], t, num, den, n, d;
    /* r = |g(x)/g(f)| in Q16, then the band gain is r*k / sqrt((1-r^2)^2+(r k)^2). */
    if (G <= g)
        t = udivq16(G, (uint32)g);
    else
        t = udivq16((uint32)g, G);
    num = mulsh(k, t, 16);                        /* r*k */
    den = (1 << 16) - mulsh(t, t, 16);            /* 1 - r^2 */
    if (den < 0)
        den = -den;
    n = mulsh(num, num, 16);
    d = mulsh(den, den, 16) + n;
    if (n <= 0)
        return -200;
    if (d <= 0)
        return 200;
    return ((log2q8(n) - log2q8(d)) * 1541 + 32768) >> 16;
}

/* Q15 cos(2*pi*i/256): the comb's phase cos(2*pi*f*D/fs) is looked up here. */
static const short COS15[256] = {
     32767,  32757,  32728,  32678,  32609,  32521,  32412,  32285,
     32137,  31971,  31785,  31580,  31356,  31113,  30852,  30571,
     30273,  29956,  29621,  29268,  28898,  28510,  28105,  27683,
     27245,  26790,  26319,  25832,  25329,  24811,  24279,  23731,
     23170,  22594,  22005,  21403,  20787,  20159,  19519,  18868,
     18204,  17530,  16846,  16151,  15446,  14732,  14010,  13279,
     12539,  11793,  11039,  10278,   9512,   8739,   7962,   7179,
      6393,   5602,   4808,   4011,   3212,   2410,   1608,    804,
         0,   -804,  -1608,  -2410,  -3212,  -4011,  -4808,  -5602,
     -6393,  -7179,  -7962,  -8739,  -9512, -10278, -11039, -11793,
    -12539, -13279, -14010, -14732, -15446, -16151, -16846, -17530,
    -18204, -18868, -19519, -20159, -20787, -21403, -22005, -22594,
    -23170, -23731, -24279, -24811, -25329, -25832, -26319, -26790,
    -27245, -27683, -28105, -28510, -28898, -29268, -29621, -29956,
    -30273, -30571, -30852, -31113, -31356, -31580, -31785, -31971,
    -32137, -32285, -32412, -32521, -32609, -32678, -32728, -32757,
    -32767, -32757, -32728, -32678, -32609, -32521, -32412, -32285,
    -32137, -31971, -31785, -31580, -31356, -31113, -30852, -30571,
    -30273, -29956, -29621, -29268, -28898, -28510, -28105, -27683,
    -27245, -26790, -26319, -25832, -25329, -24811, -24279, -23731,
    -23170, -22594, -22005, -21403, -20787, -20159, -19519, -18868,
    -18204, -17530, -16846, -16151, -15446, -14732, -14010, -13279,
    -12539, -11793, -11039, -10278,  -9512,  -8739,  -7962,  -7179,
     -6393,  -5602,  -4808,  -4011,  -3212,  -2410,  -1608,   -804,
         0,    804,   1608,   2410,   3212,   4011,   4808,   5602,
      6393,   7179,   7962,   8739,   9512,  10278,  11039,  11793,
     12539,  13279,  14010,  14732,  15446,  16151,  16846,  17530,
     18204,  18868,  19519,  20159,  20787,  21403,  22005,  22594,
     23170,  23731,  24279,  24811,  25329,  25832,  26319,  26790,
     27245,  27683,  28105,  28510,  28898,  29268,  29621,  29956,
     30273,  30571,  30852,  31113,  31356,  31580,  31785,  31971,
     32137,  32285,  32412,  32521,  32609,  32678,  32728,  32757,
};

/* Feedback-comb magnitude |1 / (1 - g e^-jwD)| from the cos of the phase wD
 * (Q15). log2q8(|den|^2) falls at the teeth (den -> 0) and rises between them,
 * so 4600 - log2q8(den) peaks at the teeth. g in Q15 (RESO). */
static int comb_mag(int c, int g)
{
    int gc = mulsh(g, c, 15);
    int den = (1 << 15) + mulsh(g, g, 15) - 2 * gc;   /* |1 - g e^-jwD|^2, Q15 */
    int l;
    if (den < 0)
        den = -den;
    if (den < 1)
        den = 1;
    l = log2q8((uint32)den);                          /* ~3840 quiet .. ~4480 */
    if (l > 4600)
        l = 4600;
    return 4600 - l;                                  /* quiet ~240, tooth ~1690 */
}

/* The tooth phase step per display column, so the teeth are laid out evenly (the
 * graph x-axis is logarithmic; a literal harmonic comb crams every tooth into the
 * top octave). FREQ (fi) sets the density across the whole range with no dead
 * zone, so turning FREQ sweeps the teeth from end to end; Q12 so it is
 * fractional. The box is only ~50 px, so the step is capped (< 64) to keep the
 * teeth at least a pixel apart and crisp. */
#define TOOTH_Q (5 << 12)                      /* step at fi = 0, Q12 */
#define comb_dstep(fi) (TOOTH_Q + (fi) * ((64 << 12) - TOOTH_Q) / 127)

/* COMB: sharp, evenly spaced teeth (depth from the Feedback knob, 0..127). */
static int comb_db2(int fi, int fb, int x)
{
    int idx = ((x * comb_dstep(fi)) >> 12) & 255;
    return comb_mag(COS15[idx], fb * 235);
}

/* TRASH: a denser comb (its own series) with a lower feedback, but the same
 * continuous sweep over FREQ. */
static int trash_db2(int fi, int fb, int x)
{
    int idx = ((x * comb_dstep(fi) * 3 / 2) >> 12) & 255;
    return comb_mag(COS15[idx], fb * 130);
}

static int col2step(int x)
{
    return (x - GX0 - 1) * 127 / (GX1 - GX0 - 2);
}

#define CH (GY1 - GY0 - 4)              /* the drawn curve's height, in rows */

/* build the logical per-column curve (0 = floor, +CH = peak) for the active
 * track's mode. The displayed depth scales with FREQ/RESO directly, so turning a
 * knob moves the curve instead of the normaliser flattening it; it clamps only
 * at the extreme ends. */
static void build_curve(int mode, int fi, int qi)
{
    int x, pass;
    if (mode == FM_COMB || mode == FM_TRASH) {
        /* the teeth sit above the quiet floor; the floor is the comb's own
         * minimum, so Feedback raises the teeth from it (clamps only at max). */
        int base = (mode == FM_COMB) ? 240 : 120;
        for (x = 0; x < 128; x++) {
            int v = (mode == FM_COMB) ? comb_db2(fi, qi, x)
                                      : trash_db2(fi, qi, x);
            int d = v - base;
            curve[x] = CH * (d < 0 ? 0 : d > 1500 ? 1500 : d) / 1500;
        }
    } else {
        /* BP/BP2: the peak height from Q (deeper with RESO), the shape from the
         * SVF magnitude, then smoothed (the integer ratio/log2 result steps). */
        int depth = CH * (5 + qi) / 20;
        for (x = 0; x < 128; x++) {
            int32 d = bp_db2(fi, qi, x, mode == FM_BP2);   /* ~ +50 .. -78 dB */
            if (d > 0)
                d = 0;
            curve[x] = (int32)depth * 50 / (50 - d);       /* 0 .. depth */
        }
        for (pass = 0; pass < 3; pass++) {
            int32 prev = curve[0];
            for (x = 1; x < 127; x++) {
                int32 cur = curve[x];
                curve[x] = (prev + 2 * cur + curve[x + 1]) / 4;
                prev = cur;
            }
        }
    }
}

/* Map the logical curve to a row, then taper it towards the floor at both box
 * edges so the curve never ends in a vertical "brickwall". */
static int curve_y(int s, int v)
{
    int w = (s < 8) ? s : (s > 119) ? (127 - s) : 8;
    return GY0 + 2 + v * w / 8;
}

/* The small type-box glyph: mask the stock "EQ n" artwork and draw a fixed mini
 * version of the mode -- a bell for BP, a wider bell for BP2, comb teeth for
 * COMB, and a small trash can for TRASH. Fits the stock box interior. */
static void type_glyph(void *bmp, int mode)
{
    int x, cx = (TBX0 + TBX1) / 2, h = TBY1 - (TBY0 + 1);
    FILLRECT(bmp, TBX0, TBY0, TBX1, TBY1, 0);
    if (mode == FM_TRASH) {
        int b0 = TBX0 + 2, b1 = TBX1 - 2, bb = TBY0 + 1;
        FILLRECT(bmp, b0, bb, b1, bb, 1);                    /* base */
        FILLRECT(bmp, b0, bb, b0, TBY1 - 3, 1);              /* left wall */
        FILLRECT(bmp, b1, bb, b1, TBY1 - 3, 1);              /* right wall */
        FILLRECT(bmp, b0 - 1, TBY1 - 3, b1 + 1, TBY1 - 3, 1);/* rim */
        FILLRECT(bmp, cx - 1, TBY1 - 2, cx + 1, TBY1 - 2, 1);/* lid handle */
        FILLRECT(bmp, cx - 2, bb + 1, cx - 2, TBY1 - 5, 1);  /* ribs */
        FILLRECT(bmp, cx + 2, bb + 1, cx + 2, TBY1 - 5, 1);
        return;
    }
    for (x = TBX0 + 1; x < TBX1; x++) {
        int v;
        if (mode == FM_COMB) {
            v = ((x - TBX0) % 3 == 1) ? h : h / 3;           /* comb teeth */
        } else {
            int half = (mode == FM_BP2) ? 7 : 4, dx = x - cx;
            v = (dx * dx >= half * half) ? 0
              : h * (half * half - dx * dx) / (half * half); /* bell */
        }
        FILLRECT(bmp, x, TBY0 + 1, x, TBY0 + 1 + v, 1);
    }
}

/* read the active track's TYPE/FREQ/RESO from the pattern's kit */
static int read_track(int *type, int *fi, int *qi)
{
    unsigned char *kit = UI_KIT;
    int t = ACTIVE_TRACK;
    int ty;
    if (!kit || t < 0 || t > 7)
        return 0;
    ty = FSLOT(kit, t, FS_TYPE) >> 8;      /* the slot word is the value << 8 */
    if (ty < FM_FIRST_TYPE || ty >= FM_FIRST_TYPE + FM_NMODES)
        return 0;
    *type = ty - FM_FIRST_TYPE;
    *fi = clampi((unsigned)FSLOT(kit, t, FS_FREQ) >> 8, 0, 127);
    /* COMB/TRASH: the feedback is the RESO/GAIN knob (slot 0x1b), 0..127.
     * BP/BP2: the DSP caps RESO at 13/15 (see filter.c) — match it so the
     * drawn curve shows the resonance the audio gets. */
    if (*type == FM_COMB || *type == FM_TRASH)
        *qi = clampi((unsigned)FSLOT(kit, t, FS_RESO) >> 8, 0, 127);
    else
        *qi = clampi((unsigned)FSLOT(kit, t, FS_RESO) >> 11, 0, 15) * 13 / 15;
    return 1;
}

/* the active track's TYPE, or -1 */
static int active_type(void)
{
    unsigned char *kit = UI_KIT;
    int t = ACTIVE_TRACK;
    if (!kit || t < 0 || t > 7)
        return -1;
    return FSLOT(kit, t, FS_TYPE) >> 8;
}

/* Write a filter parameter descriptor into a spare ('Error') descriptor entry:
 * copy the SRR descriptor's fields (so the knob draws the same round dial),
 * then set group 6, the sound slot, range 0x7f00 (0..127), step 1 and our own
 * short name. The generic knob path then draws and edits it like any stock
 * filter knob. */
static void df_desc(unsigned id, int slot, const char *name)
{
    volatile unsigned char *d = (volatile unsigned char *)(DESC_TABLE + id * DESC_STRIDE);
    const volatile unsigned char *t = (const volatile unsigned char *)(DESC_TABLE + DESC_TEMPLATE * DESC_STRIDE);
    int i;
    for (i = 0; i < DESC_STRIDE; i++)
        d[i] = t[i];
    *(volatile unsigned short *)(d + 2) = 6;            /* group = Filter */
    *(volatile unsigned short *)(d + 6) = (unsigned short)slot;
    *(volatile unsigned short *)(d + 14) = 0x7f00;      /* range 0..127 */
    *(volatile unsigned short *)(d + 18) = 0x0100;      /* step 1 */
    *(volatile unsigned *)(d + 0x30) = (unsigned)name;  /* short name */
}

/* The second FLTR page (kind 7) for COMB/TRASH: add the comb's Harmonics and
 * Damping controls on the free C/G encoders, leaving the stock Base/Width/Env
 * Delay/SRR knobs exactly as they are (and the comb feedback is the RESO/GAIN
 * knob on page 1). We commandeer two unused 'Error' descriptors (14/15) as
 * filter descriptors on spare sound slots, put them in C/G and restore the
 * stock layout/descriptors for every other TYPE. Called every UI tick (from
 * filter.c's digifilter_tick) before the page is drawn and before encoders
 * turn, so the stock input/display path does all the work.
 *
 * kind 7 stock = {39,0,0,42,40,41,0,43}; comb = {39,0,14,42,40,41,15,43}
 * (encoders A..H; 0 = the empty dotted box). */
static void page2_setup(void)
{
    static const unsigned stock[8] = { 39, 0, 0, 42, 40, 41, 0, 43 };
    static const unsigned combm[8] = { 39, 0, 14, 42, 40, 41, 15, 43 };
    static unsigned char orig[2][DESC_STRIDE];
    static int init, last = -1;
    int ty = active_type(), comb = ty == FM_FIRST_TYPE + FM_COMB ||
                                    ty == FM_FIRST_TYPE + FM_TRASH;
    const unsigned *m = comb ? combm : stock;
    int i;
    if (!init) {
        init = 1;
        for (i = 0; i < 2; i++) {
            const volatile unsigned char *s = (const volatile unsigned char *)(DESC_TABLE + (DESC_NEW0 + i) * DESC_STRIDE);
            int j;
            for (j = 0; j < DESC_STRIDE; j++)
                orig[i][j] = s[j];
        }
    }
    if (comb != last) {                          /* only rewrite on a state change */
        last = comb;
        if (comb) {
            df_desc(DESC_NEW0, FS_HARM, DF_L_HARM);
            df_desc(DESC_NEW1, FS_DAMP, DF_L_DAMP);
        } else {
            for (i = 0; i < 2; i++) {
                volatile unsigned char *d = (volatile unsigned char *)(DESC_TABLE + (DESC_NEW0 + i) * DESC_STRIDE);
                int j;
                for (j = 0; j < DESC_STRIDE; j++)
                    d[j] = orig[i][j];
            }
        }
    }
    for (i = 0; i < 8; i++)
        if (LAYOUT_IDS[i] != m[i])
            LAYOUT_IDS[i] = m[i];
}

void digifilter_page2_sync(void)
{
    page2_setup();
}

/* the page kind the view is showing (digieq/digipoly read the vector + index) */
static int view_kind(void *view)
{
    int32 *v = VIEW_KINDS(view), *e = VIEW_KINDS_END(view);
    int i = VIEW_INDEX(view);
    if (!v || i < 0 || i >= e - v)
        return -1;
    return v[i];
}

/* The track-parameter page view in the controller's list (drawAll iterates the
 * list and calls each view's drawView, so the view is present whenever its page
 * is shown). Its kind is the currently shown page, so we look for a FLTR kind
 * rather than assuming the view is the last one: other screens/overlays stay in
 * the list too. Returns the view and sets *kind to FLTR_KIND (page 1) or
 * FLTR2_KIND (page 2). */
static void *page_view(void *ctrl, int *kind)
{
    char *node, *sent;
    if (!ctrl)
        return 0;
    sent = CTRL_SENTINEL(ctrl);
    for (node = CTRL_HEAD(ctrl); node && node != sent; node = NODE_NEXT(node)) {
        void *view = NODE_VIEW(node);
        int k = view ? view_kind(view) : -1;
        if (k == FLTR_KIND || k == FLTR2_KIND) {
            if (kind)
                *kind = k;
            return view;
        }
    }
    return 0;
}

/* The comb controls' value (0..127) from the active track's spare slots. */
static int comb_val(int slot)
{
    unsigned char *kit = UI_KIT;
    int t = ACTIVE_TRACK;
    if (!kit || t < 0 || t > 7)
        return 0;
    return clampi((unsigned)FSLOT(kit, t, slot) >> 8, 0, 127);
}

static void dial_px(void *bmp, int x, int y)
{
    FILLRECT(bmp, x, y, x, y, 1);
}

/* A stock-style round dial (like SRR's): a circle with a needle, in the empty
 * cell the commandeered descriptors leave on the second FLTR page. The value
 * 0..127 sweeps the needle from lower-left to lower-right through straight up. */
#define DIAL_R 8
static void draw_dial(void *bmp, int cx, int cy, int v)
{
    int x = DIAL_R, y = 0, e = 0;
    while (x >= y) {
        dial_px(bmp, cx + x, cy + y); dial_px(bmp, cx + y, cy + x);
        dial_px(bmp, cx - y, cy + x); dial_px(bmp, cx - x, cy + y);
        dial_px(bmp, cx - x, cy - y); dial_px(bmp, cx - y, cy - x);
        dial_px(bmp, cx + y, cy - x); dial_px(bmp, cx + x, cy - y);
        y++;
        if (e <= 0)
            e += 2 * y + 1;
        if (e > 0) {
            x--;
            e -= 2 * x + 1;
        }
    }
    {
        int idx = (v - 64) * 200 / 127;
        int dx = (COS15[(idx - 64) & 255] * DIAL_R) >> 15;
        int dy = (COS15[idx & 255] * DIAL_R) >> 15;
        int k;
        for (k = 1; k <= DIAL_R; k++)
            dial_px(bmp, cx + dx * k / DIAL_R, cy + dy * k / DIAL_R);
    }
}

/* core's ev_draw handler: the frame (stock curve included) is already drawn, so
 * paint ours over it when the FLTR page is up and the active track uses a mode.
 * (bmp, ctrl): ctrl is the view controller drawAll walks. */
void digifilter_draw(void *bmp, void *ctrl)
{
    int kind = -1, mode, fi, qi, x;
    if (!bmp || !page_view(ctrl, &kind))
        return;
    if (!read_track(&mode, &fi, &qi))
        return;
    if (kind == FLTR2_KIND) {
        /* The commandeered descriptors draw the HARM/DAMP labels but no value
         * widget (their slot is past the model's range), so paint a stock round
         * dial in each of the two free cells. */
        if (mode == FM_COMB || mode == FM_TRASH) {
            draw_dial(bmp, 85, 41, comb_val(FS_HARM));
            draw_dial(bmp, 85, 15, comb_val(FS_DAMP));
        }
        return;
    }
    /* Page 1: the stock page drew its response for this (to it, unknown) TYPE,
     * so clear the graph interior before painting ours. */
    FILLRECT(bmp, GX0 + 1, GY0 + 1, GX1 - 1, GY1 - 1, 0);
    build_curve(mode, fi, qi);
    {
        int prev = -1;
        for (x = GX0 + 1; x < GX1; x++) {
            int s = col2step(x);
            int y = curve_y(s, curve[s]);
            if (prev < 0)
                prev = y;
            FILLRECT(bmp, x, prev < y ? prev : y, x, prev < y ? y : prev, 1);
            prev = y;
        }
    }
    type_glyph(bmp, mode);
}
