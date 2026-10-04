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

/* the FLTR page kind. The page-kind list is at view+124 (vector), the index at
 * view+144; kind -> layout is 0x400657b2 (20 x 44 bytes at RAM 0x4197cf88),
 * whose +8.. are the 8 knob descriptor ids. The FLTR page's layout is
 * {ATK, DEC, SUS, REL, FREQ, RESO, TYPE, ENV} = ids {34,35,36,37,30,32,33,38}
 * = kind 6 (confirmed from the gui.snap RAM layout table). */
#define FLTR_KIND 6

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
 * (band gain) -- enough for a UI curve, in half-dB. */
static int bp_db2(int fi, int qi, int x, int wide)
{
    int32 g = wide ? G27[fi] << 1 : G27[fi];     /* BP2: roughly double the width */
    /* k in Q16 (k27 >> 11): the products below must stay under 2^32 (the old
     * Q27 k made num^2 wrap, which drew noise). */
    int32 k = K27[wide ? (qi >> 1) : qi] >> 11;
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

/* TRASH: the second comb, kept as the earlier envelope curve (full at the
 * harmonics, dipping between them, RESO raising the peaks); div picks the
 * harmonic series. */
static int trash_db2(int fi, int qi, int x, int div)
{
    int32 D = COMB_DELAY[fi] / div;
    int32 f = HZ[x], peak;
    if (D < 2)
        D = 2;
    /* nearest harmonic index of f to the comb's spacing (fs/D ~ 48000/D) */
    peak = (int32)((f * D + 24000) / 48000);
    if (peak < 0)
        peak = 0;
    /* distance of f from that harmonic, as a fraction of the spacing */
    {
        int32 hz = peak * (48000 / D);
        int32 off = f > hz ? f - hz : hz - f;
        int32 span = 48000 / D;
        int32 lift;
        if (span < 1)
            span = 1;
        lift = (qi * 16) - (off * (qi * 16)) / span;      /* peaks up with RESO */
        return clampi(lift - 24, -100, 100);
    }
}

/* COMB: the feedback comb's evenly spaced teeth, sharpening with RESO (g). The
 * device's graph x-axis is logarithmic, so a true harmonic comb crams every
 * tooth into the top octave; the teeth are laid out evenly across the display
 * (their count from FREQ: the harmonics in the audio band, capped so they stay
 * readable). Returned as a -log2 proxy; the draw normalises the curve to the box. */
static int comb_db2(int fi, int qi, int x)
{
    int n = 20000 / HZ[fi];                /* harmonics across 20 Hz .. 20 kHz */
    int idx, c, g, gc, den;
    if (n < 3)
        n = 3;
    if (n > 8)
        n = 8;
    idx = (x * n * 2) % 256;               /* evenly spaced teeth */
    c = COS15[idx & 255];                  /* cos(wD) in Q15 */
    g = qi * 2000;                         /* feedback in Q15 (0 .. ~0.92) */
    gc = mulsh(g, c, 15);
    den = (1 << 15) + mulsh(g, g, 15) - 2 * gc;
    if (den < 1)
        den = 1;
    return -(int)log2q8((uint32)den);      /* shape only */
}

static int col2step(int x)
{
    return (x - GX0 - 1) * 127 / (GX1 - GX0 - 2);
}

static int curve_mn, curve_mx;          /* the built curve's value range */

/* Map the built curve into the graph box: its maximum to the top row, its
 * minimum to the bottom. The modes' raw values use different scales (BP is a
 * real half-dB magnitude, the comb's "lift" is arbitrary), so normalising keeps
 * every mode's shape visible in the small box. */
static int curve_y(int v)
{
    int span = curve_mx - curve_mn;
    int h = GY1 - GY0 - 4;
    if (span < 1)
        span = 1;
    return GY0 + 2 + (v - curve_mn) * h / span;
}

/* build the 128-step curve for the active track's mode */
static void build_curve(int mode, int fi, int qi)
{
    int x, pass;
    for (x = 0; x < 128; x++) {
        if (mode <= FM_BP2)
            curve[x] = bp_db2(fi, qi, x, mode == FM_BP2);
        else if (mode == FM_COMB)
            curve[x] = comb_db2(fi, qi, x);
        else
            curve[x] = trash_db2(fi, qi, x, 2);
    }
    if (mode <= FM_BP2) {
        /* the integer ratio/log2 quantisation steps the BP magnitude; smooth
         * the wobble (a [1,2,1]/4 pass, in place, three times). */
        for (pass = 0; pass < 3; pass++) {
            int32 prev = curve[0];
            for (x = 1; x < 127; x++) {
                int32 cur = curve[x];
                curve[x] = (prev + 2 * cur + curve[x + 1]) / 4;
                prev = cur;
            }
        }
    }
    curve_mn = 1 << 30;
    curve_mx = -(1 << 30);
    for (x = 0; x < 128; x++) {
        if (curve[x] < curve_mn)
            curve_mn = curve[x];
        if (curve[x] > curve_mx)
            curve_mx = curve[x];
    }
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
    *qi = clampi((unsigned)FSLOT(kit, t, FS_RESO) >> 11, 0, 15);
    return 1;
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
 * is shown). Its kind is the currently shown page, so we look for the FLTR kind
 * rather than assuming the view is the last one: other screens/overlays stay in
 * the list too. */
static void *fltr_view(void *ctrl)
{
    char *node, *sent;
    if (!ctrl)
        return 0;
    sent = CTRL_SENTINEL(ctrl);
    for (node = CTRL_HEAD(ctrl); node && node != sent; node = NODE_NEXT(node)) {
        void *view = NODE_VIEW(node);
        if (view && view_kind(view) == FLTR_KIND)
            return view;
    }
    return 0;
}

/* core's ev_draw handler: the frame (stock curve included) is already drawn, so
 * paint ours over it when the FLTR page is up and the active track uses a mode.
 * (bmp, ctrl): ctrl is the view controller drawAll walks. */
void digifilter_draw(void *bmp, void *ctrl)
{
    int mode, fi, qi, x;
    if (!bmp || !fltr_view(ctrl))
        return;
    if (!read_track(&mode, &fi, &qi))
        return;
    /* The stock page also drew its response for this (to it, unknown) TYPE, so
     * clear the graph interior before painting ours. */
    FILLRECT(bmp, GX0 + 1, GY0 + 1, GX1 - 1, GY1 - 1, 0);
    build_curve(mode, fi, qi);
    {
        int prev = -1;
        for (x = GX0 + 1; x < GX1; x++) {
            int y = curve_y(curve[col2step(x)]);
            if (prev < 0)
                prev = y;
            FILLRECT(bmp, x, prev < y ? prev : y, x, prev < y ? y : prev, 1);
            prev = y;
        }
    }
    type_glyph(bmp, mode);
}
