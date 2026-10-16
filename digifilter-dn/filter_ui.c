/* SPDX-License-Identifier: GPL-2.0-or-later */
/* DigiFilter-DN UI + integration: FLTR curve/glyphs/dials + per-voice filter.
 *
 * Thin port (5 files, shared DSP via ../, no copies): this file holds DN
 * integration (digifilter_dn_filt: dispatcher globals + fw_voice_params slots
 * 54 TYPE/55 FREQ/56 RESO/65 HARM/26 DAMP, TYPE base 4, base FREQ only) plus UI
 * (FLTR p1 curve/glyphs, p2 HARM/DAMP dials, tick/enc/key). DSP lives in
 * ../df_dsp.c (SVF/comb) + ../filter_dsp.s (EMAC) + ../ob1_vcf.c (ladder);
 * tables via ../filter_tables.h/../ob1_tables.h.
 *
 * UI: p1 curve (bell/teeth/lowpass OB1_CURVE, no left taper for OB) in 20..71,
 * glyphs (bell/wider/teeth/can/lowpass) with full-outer clear in 78..92,
 * dials (86,42 C HARM / 86,15 G DAMP, ENV-style) for COMB/TRASH; p2 C/G tick
 * [35,0,182,0,36,37,183,0] for COMB/TRASH else stock (DEL/BASE/WIDTH stock
 * always). HARM/DAMP params 182/183 group Filter slots 65/26 (savable ASSUME).
 * BASE/WIDTH slots 62/63 stock always. Envelope TODO (base FREQ only). Slots
 * 65/26 + 48kHz ASSUME (verify on device).
 *
 * Gated on firmware state (active TYPE, FLTR p1 list[pos]==6, brain
 * bottom==top, toast yield 90 ticks on chorded RECORD/STOP/PLAY). Tick
 * re-arms only on change (track/TYPE/FREQ/RESO/page/enc highlight+expiry).
 * Never takes events.
 */
#include "digitone-mk1/core3.h"

#include "../df_dsp.h"
#include "../ob1_vcf.h"
#include "../filter_tables.h"
#include "../ob1_tables.h"

#define FLTR_P1 6
#define FLTR_P2 7

/* Wide FREQ/RESO curve cell (bottom row, FREQ+RESO share wide display) */
#define GX0 20
#define GX1 71
#define GY0 7
#define GY1 23
/* TYPE cell outer (15px, centre 86,15) + glyph interior */
#define TBX0 77
#define TBX1 93
#define TBY0 7
#define TBY1 23

#define K_FUNC 1
#define K_PTN 4
#define K_REC 10
#define K_PLAY 11
#define K_STOP 12
#define K_PAGE 19

#define VIEW_LIST(v) (*(int32_t **)((char *)(v) + 124))
#define VIEW_END(v) (*(int32_t **)((char *)(v) + 128))
#define VIEW_POS(v) (*(int32_t *)((char *)(v) + 144))
#define CTRL_SENT(ctrl) ((char *)(ctrl) + 0x14)
#define CTRL_HEAD(ctrl) (*(char **)((char *)(ctrl) + 0x1c))
#define NODE_VIEW(n) (*(void **)((char *)(n) + 8))
#define NODE_NEXT(n) (*(char **)(n))
#define BRAIN_BOT 0x54
#define BRAIN_TOP 0x5c

#define FS_TYPE 54
#define FS_FREQ 55
#define FS_RESO 56
#define FS_BASE 62
#define FS_WIDTH 63
#define FS_HARM 65
#define FS_DAMP 26

enum { FM_BP = 4, FM_BP2, FM_COMB, FM_TRASH, FM_OB4, FM_OB2 };

static void *df_brain;
static uint32_t df_ticks;
static uint32_t df_msg_until;
#define DF_MSG_HOLD 90u
static int32_t df_enc = -1;
static uint32_t df_enc_at;
static int32_t df_trigs;
static int32_t df_func, df_ptn, df_page, df_rec_down;
static int32_t tick_valid;
static int32_t tick_track, tick_type, tick_fi, tick_qi, tick_harm, tick_damp;
static int32_t tick_pos, tick_p2pos, tick_enc, tick_hl, tick_msg;

static int32_t msg_sup(void)
{
    return (int32_t)(df_ticks - df_msg_until) < 0;
}

static int32_t clampi_ui(int32_t v, int32_t lo, int32_t hi)
{
    return v < lo ? lo : v > hi ? hi : v;
}

/* ---- TYPE glyphs: user-supplied 17x17 bitmaps (SVG sources live outside
 * the repo in DigiFilter-ICONS/). Row 0 = bottom (screen y7).
 * Bit x = column x (screen 77+x). Art covers 77..93/7..23. */
static const unsigned BP_GLYPH[17] = {
    0x0FFFE, 0x10001, 0x17FFD, 0x10FE1, 0x10FE1, 0x10FE1, 0x10FE1, 0x10FE1, 0x107C1, 0x107C1, 0x107C1, 0x107C1, 0x10381, 0x10381, 0x10381, 0x10101, 0x0FFFE,
};
static const unsigned BP2_GLYPH[17] = {
    0x0FFFE, 0x10001, 0x17FFD, 0x17FFD, 0x17FFD, 0x17FFD, 0x13FF9, 0x13FF9, 0x13FF9, 0x11FF1, 0x11FF1, 0x10FE1, 0x10FE1, 0x107C1, 0x10381, 0x10101, 0x0FFFE,
};
static const unsigned COMB_GLYPH[17] = {
    0x0FFFE, 0x10001, 0x17FFD, 0x17FFD, 0x17FFD, 0x17FFD, 0x17FFD, 0x14925, 0x14925, 0x14925, 0x14925, 0x14925, 0x14925, 0x14925, 0x14925, 0x14925, 0x0FFFE,
};
static const unsigned TRASH_GLYPH[17] = {
    0x0FFFE, 0x10001, 0x13FF9, 0x12449, 0x12449, 0x12449, 0x12449, 0x12449, 0x12449, 0x12449, 0x12449, 0x12009, 0x17FFD, 0x10381, 0x10001, 0x10001, 0x0FFFE,
};
static const unsigned OB4_GLYPH[17] = {
    0x0FFFE, 0x10001, 0x10FFD, 0x10FFD, 0x10FFD, 0x107FD, 0x107FD, 0x107FD, 0x103FD, 0x103FD, 0x103FD, 0x10381, 0x10381, 0x10381, 0x10381, 0x10381, 0x0FFFE,
};
static const unsigned OB2_GLYPH[17] = {
    0x0FFFE, 0x10001, 0x17FFD, 0x17FFD, 0x17FFD, 0x17FFD, 0x13FFD, 0x11FFD, 0x10FFD, 0x107FD, 0x103FD, 0x10381, 0x10381, 0x10381, 0x10381, 0x10381, 0x0FFFE,
};
/* ---- TYPE glyphs (17x17 bitmaps, 77..93/7..23) ---- */
static void type_glyph(void *bmp, int32_t mode)
{
    const unsigned *g;
    int32_t r;
    if (mode == FM_BP) g = BP_GLYPH;
    else if (mode == FM_BP2) g = BP2_GLYPH;
    else if (mode == FM_COMB) g = COMB_GLYPH;
    else if (mode == FM_TRASH) g = TRASH_GLYPH;
    else if (mode == FM_OB4) g = OB4_GLYPH;
    else g = OB2_GLYPH;
    fw_fillrect(bmp, TBX0, TBY0, TBX1, TBY1, 0);
    for (r = 0; r < 17; r++) {
        unsigned rowbits = g[r];
        int32_t xx;
        for (xx = 0; xx < 17; xx++)
            if (rowbits & (1u << xx))
                fw_fillrect(bmp, TBX0 + xx, TBY0 + r, TBX0 + xx, TBY0 + r, 1);
    }
}


/* ---- FREQ/RESO curve (DT build_curve, DN wide cell 25..67) ---- */
static int32_t curve[128];

static int32_t mulsh_ui(int32_t a, int32_t b, int32_t sh)
{
    uint32_t ua = a < 0 ? -(uint32_t)a : (uint32_t)a, ub = b < 0 ? -(uint32_t)b : (uint32_t)b;
    uint32_t al = ua & 0xffff, ah = ua >> 16, bl = ub & 0xffff, bh = ub >> 16;
    uint32_t ll = al * bl, lh = al * bh, hl = ah * bl, hh = ah * bh;
    uint32_t mid = (ll >> 16) + (lh & 0xffff) + (hl & 0xffff);
    uint32_t lo = (ll & 0xffff) | (mid << 16);
    uint32_t hi = hh + (lh >> 16) + (hl >> 16) + (mid >> 16);
    if ((a < 0) != (b < 0)) {
        lo = ~lo + 1;
        hi = ~hi + (lo == 0);
    }
    return (int32_t)((hi << (32 - sh)) | (lo >> sh));
}

static uint32_t udivq16_ui(uint32_t x, uint32_t y)
{
    uint32_t rem = x, q = 0;
    int32_t i;
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

static const unsigned short LOG2Q8_UI[256] = {
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

static int32_t log2q8_ui(uint32_t v)
{
    int32_t p = 31;
    uint32_t m;
    while (!(v >> p))
        p--;
    m = p >= 8 ? v >> (p - 8) : v << (8 - p);
    return p * 256 + LOG2Q8_UI[m & 255];
}

static int32_t bp_db2_ui(int32_t fi, int32_t qi, int32_t x, int32_t wide)
{
    int32_t g = wide ? G27[fi] << 1 : G27[fi];
    int32_t k = (K27[wide ? (qi >> 1) : qi] >> 11) * (wide ? 1 : 3) / (wide ? 2 : 4);
    int32_t G = G27[x], t, num, den, n, d;
    if (G <= g)
        t = (int32_t)udivq16_ui((uint32_t)G, (uint32_t)g);
    else
        t = (int32_t)udivq16_ui((uint32_t)g, (uint32_t)G);
    num = mulsh_ui(k, t, 16);
    den = (1 << 16) - mulsh_ui(t, t, 16);
    if (den < 0)
        den = -den;
    n = mulsh_ui(num, num, 16);
    d = mulsh_ui(den, den, 16) + n;
    if (n <= 0)
        return -200;
    if (d <= 0)
        return 200;
    return ((log2q8_ui((uint32_t)n) - log2q8_ui((uint32_t)d)) * 1541 + 32768) >> 16;
}

static const short COS15_UI[256] = {
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

static int32_t comb_mag_ui(int32_t c, int32_t g)
{
    int32_t gc = mulsh_ui(g, c, 15);
    int32_t den = (1 << 15) + mulsh_ui(g, g, 15) - 2 * gc;
    int32_t l;
    if (den < 0)
        den = -den;
    if (den < 1)
        den = 1;
    l = log2q8_ui((uint32_t)den);
    if (l > 4600)
        l = 4600;
    return 4600 - l;
}

#define TOOTH_Q_UI (5 << 12)
#define comb_dstep_ui(fi) (TOOTH_Q_UI + (fi) * ((64 << 12) - TOOTH_Q_UI) / 127)

static int32_t comb_db2_ui(int32_t fi, int32_t fb, int32_t x)
{
    int32_t idx = ((x * comb_dstep_ui(fi)) >> 12) & 255;
    return comb_mag_ui(COS15_UI[idx], fb * 235);
}

static int32_t trash_db2_ui(int32_t fi, int32_t fb, int32_t x)
{
    int32_t idx = ((x * comb_dstep_ui(fi) * 3 / 2) >> 12) & 255;
    return comb_mag_ui(COS15_UI[idx], fb * 130);
}

static int32_t col2step_ui(int32_t x)
{
    return (x - GX0 - 1) * 127 / (GX1 - GX0 - 2);
}

#define CH_UI (GY1 - GY0 - 4)

static int32_t curve_lowpass_ui;

#define OB_FLOOR2_UI (-72)
#define OB_SPAN2_UI 108
static void ob_curve_ui(int32_t mode, int32_t fi, int32_t qi)
{
    const signed char (*c)[129] = OB1_CURVE[mode == FM_OB2];
    int32_t lvl = qi >> 4, span = lvl < 7 ? 16 : 15, frac = qi - 16 * lvl, x;
    for (x = 0; x < 128; x++) {
        int32_t d = clampi_ui(x - fi + 64, 0, 128);
        int32_t v = c[lvl][d] + (c[lvl + 1][d] - c[lvl][d]) * frac / span;
        curve[x] = CH_UI * clampi_ui(v - OB_FLOOR2_UI, 0, OB_SPAN2_UI) / OB_SPAN2_UI;
    }
}

static void build_curve_ui(int32_t mode, int32_t fi, int32_t qi)
{
    int32_t x, pass;
    curve_lowpass_ui = (mode == FM_OB4 || mode == FM_OB2);
    if (mode == FM_OB4 || mode == FM_OB2) {
        ob_curve_ui(mode, fi, qi);
        return;
    }
    if (mode == FM_COMB || mode == FM_TRASH) {
        int32_t base = (mode == FM_COMB) ? 240 : 120;
        for (x = 0; x < 128; x++) {
            int32_t v = (mode == FM_COMB) ? comb_db2_ui(fi, qi, x)
                                          : trash_db2_ui(fi, qi, x);
            int32_t d = v - base;
            curve[x] = CH_UI * (d < 0 ? 0 : d > 1500 ? 1500 : d) / 1500;
        }
    } else {
        int32_t depth = CH_UI * (5 + qi) / 20;
        for (x = 0; x < 128; x++) {
            int32_t d = bp_db2_ui(fi, qi, x, mode == FM_BP2);
            if (d > 0)
                d = 0;
            curve[x] = depth * 50 / (50 - d);
        }
        for (pass = 0; pass < 3; pass++) {
            int32_t prev = curve[0];
            for (x = 1; x < 127; x++) {
                int32_t cur = curve[x];
                curve[x] = (prev + 2 * cur + curve[x + 1]) / 4;
                prev = cur;
            }
        }
    }
}

static int32_t curve_y_ui(int32_t s, int32_t v)
{
    int32_t w = (s < 8 && !curve_lowpass_ui) ? s : (s > 119) ? (127 - s) : 8;
    return GY0 + 2 + v * w / 8;
}

static int32_t read_track_ui(int32_t *mode, int32_t *fi, int32_t *qi)
{
    uint8_t *kit = fw_kit;
    int32_t t = fw_active_track, ty;
    if (!kit || t < 0 || t > 3)
        return 0;
    ty = FW_SOUND_SLOT(kit, t, FS_TYPE) >> 8;
    if (ty < FM_BP || ty > FM_OB2)
        return 0;
    *mode = ty;
    *fi = clampi_ui((FW_SOUND_SLOT(kit, t, FS_FREQ) >> 8) & 0xff, 0, 127);
    if (*mode == FM_COMB || *mode == FM_TRASH || *mode == FM_OB4 || *mode == FM_OB2)
        *qi = clampi_ui((FW_SOUND_SLOT(kit, t, FS_RESO) >> 8) & 0xff, 0, 127);
    else
        *qi = clampi_ui(FW_SOUND_SLOT(kit, t, FS_RESO) >> 11, 0, 15) * 13 / 15;
    return 1;
}

/* ---- HARM/DAMP params (ids 182/183, slots 65/26, C/G on page-2) ----
 * BASE/WIDTH (ids 36/37 slots 62/63 E/F) stay stock always (base filter
 * always accessible). HARM/DAMP live on free C/G (blank squares) with stock
 * dial widgets (slots within model, unlike DT spare past range which needed
 * painted dials). Slots: 65 globally free (savable ASSUME), 26 free on synth
 * (Delay WID group 5 + MIDI CC group 11 use it elsewhere). No mirroring
 * needed if DN serializer saves 0..78 (ASSUME, verify on device like DT). */
static void harm_fmt(int32_t v, char *buf)
{
    int32_t r = v >> 8, d, i = 0;
    char t[4];
    int32_t n = 0;
    if (r < 0) r = 0;
    if (r > 127) r = 127;
    d = 1 + r * 3 / 127;
    do { t[n++] = (char)('0' + d % 10); d /= 10; } while (d && n < 3);
    while (n) buf[i++] = t[--n];
    buf[i] = 0;
}

static void damp_fmt(int32_t v, char *buf)
{
    int32_t r = v >> 8, i = 0;
    char t[4];
    int32_t n = 0;
    if (r < 0) r = 0;
    if (r > 127) r = 127;
    do { t[n++] = (char)('0' + r % 10); r /= 10; } while (r && n < 3);
    while (n) buf[i++] = t[--n];
    buf[i] = 0;
}

static const char df_harm_name[] = "Harmonics";
static const char df_harm_group[] = "Filter";
static const char df_harm_short[] = "HARM";
static const char df_damp_name[] = "Damping";
static const char df_damp_group[] = "Filter";
static const char df_damp_short[] = "DAMP";

const struct core_param digifilter_dn_harm = {
    182, 2, 65, 0, 0x7f00, 0, 0, -1, -1, -1, 0,
    df_harm_name, df_harm_group, df_harm_short,
    harm_fmt, fw_str_empty, 36,
};

const struct core_param digifilter_dn_damp = {
    183, 2, 26, 0, 0x7f00, 0, 0, -1, -1, -1, 0,
    df_damp_name, df_damp_group, df_damp_short,
    damp_fmt, fw_str_empty, 37,
};

/* Page-2 C/G addrs (RAM page record ids, per OS via -DPAGE2_C_AT/-DPAGE2_G_AT).
 * Stock [35,0,0,0,36,37,0,0] -> comb [35,0,182,0,36,37,183,0] (C=HARM,G=DAMP,
 * E/F BASE/WIDTH stock always). Tick rewrites C/G (no sites, like DT). */
#ifndef PAGE2_C_AT
#error "PAGE2_C_AT: page-2 C id addr (0x4136b69c 1.43, 0x4136c69c 1.44)"
#endif
#ifndef PAGE2_G_AT
#error "PAGE2_G_AT: page-2 G id addr (0x4136b6ac 1.43, 0x4136c6ac 1.44)"
#endif

static int32_t active_type(void)
{
    int32_t t = fw_active_track;
    uint8_t *kit = fw_kit;
    if (t < 0 || t > 3 || !kit)
        return -1;
    return FW_SOUND_SLOT(kit, t, FS_TYPE) >> 8;
}

static void page2_setup(void)
{
    int32_t ty = active_type();
    int32_t comb = (ty == FM_COMB || ty == FM_TRASH);
    volatile uint32_t *c = (volatile uint32_t *)PAGE2_C_AT;
    volatile uint32_t *g = (volatile uint32_t *)PAGE2_G_AT;
    if (*c != (uint32_t)(comb ? 182 : 0))
        *c = (uint32_t)(comb ? 182 : 0);
    if (*g != (uint32_t)(comb ? 183 : 0))
        *g = (uint32_t)(comb ? 183 : 0);
}

/* ---- per-voice filter (DN integration, no DSP state here) ----
 * The render calls the per-voice filter through a5; the dispatcher
 * (filter_glue.s) points a5 here for TYPE 4..9. Reads voice/buffer from
 * dispatcher globals and FREQ/RESO/HARM/DAMP from fw_voice_params (render's
 * copy, locks included). Ignores the stock stack args. Runs shared DSP
 * (../df_dsp.c + ../filter_dsp.s + ../ob1_vcf.c) in place; stock types never
 * reach here. Base FREQ only, no envelope (TODO for all new types). DSP state
 * lives in the shared core; this file keeps only the mode-change detector. */
extern int digifilter_dn_voice;
extern int digifilter_dn_buf;
static int dn_prev_type[8] = { -1, -1, -1, -1, -1, -1, -1, -1 };

void digifilter_dn_filt(void)
{
    int voice = digifilter_dn_voice;
    int32 *buf = (int32 *)digifilter_dn_buf;
    int type, fi;
    if (voice < 0 || voice >= 8 || !buf)
        return;
    type = (FW_VOICE_PARAM(voice, FS_TYPE) >> 8) & 0xff;
    if (type < FM_BP || type > FM_OB2)
        return;
    fi = df_clampi((FW_VOICE_PARAM(voice, FS_FREQ) >> 8) & 0xff, 0, 127);
    if (dn_prev_type[voice] != type) {
        df_reset(voice);
        ob1_vcf_reset(voice);
        dn_prev_type[voice] = type;
    }
    if (type <= FM_BP2) {
        int qi = df_clampi(FW_VOICE_PARAM(voice, FS_RESO) >> 11, 0, 15);
        df_svf_run(type - FM_BP, fi, qi, buf, voice);
    } else if (type <= FM_TRASH) {
        int fb = df_clampi((FW_VOICE_PARAM(voice, FS_RESO) >> 8) & 0xff, 0, 127);
        int harm = df_clampi((FW_VOICE_PARAM(voice, FS_HARM) >> 8) & 0xff, 0, 127);
        int damp = FW_VOICE_PARAM(voice, FS_DAMP);
        int hdiv = 1 + harm * 3 / 127;
        int div = (type == FM_COMB) ? 1 : 2;
        df_comb_run(buf, 32, fi, fb, voice, div, hdiv, damp);
    } else {
        int fi8 = FW_VOICE_PARAM(voice, FS_FREQ);
        int qio = df_clampi((FW_VOICE_PARAM(voice, FS_RESO) >> 8) & 0xff, 0, 127);
        ob1_vcf_run((type == FM_OB4) ? OB1_TAP4 : OB1_TAP2, fi8, qio, (int *)buf, voice);
    }
}

/* ---- view/page gating ---- */
static void *fltr_p1_view(void *ctrl)
{
    char *node, *sent;
    if (!ctrl)
        return 0;
    sent = CTRL_SENT(ctrl);
    for (node = CTRL_HEAD(ctrl); node && node != sent; node = NODE_NEXT(node)) {
        void *view = NODE_VIEW(node);
        int32_t *v, *e, pos;
        if (!view)
            continue;
        v = VIEW_LIST(view);
        e = VIEW_END(view);
        pos = VIEW_POS(view);
        if (!v || pos < 0 || pos >= e - v)
            continue;
        if (v[pos] == FLTR_P1)
            return view;
    }
    return 0;
}

/* ---- ev handlers ---- */
static void *fltr_p2_view(void *ctrl)
{
    char *node, *sent;
    if (!ctrl)
        return 0;
    sent = CTRL_SENT(ctrl);
    for (node = CTRL_HEAD(ctrl); node && node != sent; node = NODE_NEXT(node)) {
        void *view = NODE_VIEW(node);
        int32_t *v, *e, pos;
        if (!view)
            continue;
        v = VIEW_LIST(view);
        e = VIEW_END(view);
        pos = VIEW_POS(view);
        if (!v || pos < 0 || pos >= e - v)
            continue;
        if (v[pos] == FLTR_P2)
            return view;
    }
    return 0;
}

#define DIAL_R_UI 8
static void dial_px_ui(void *bmp, int32_t x, int32_t y)
{
    fw_fillrect(bmp, x, y, x, y, 1);
}

/* Stock-style round dial (like ENV on p1 H): circle + needle from 0..127
 * sweeping lower-left to lower-right through up. Centres (86,42) C top HARM,
 * (86,15) G bottom DAMP (17px cells, pedal col_x/ROW_Y bitmap bottom=0). */
static void draw_dial_ui(void *bmp, int32_t cx, int32_t cy, int32_t v)
{
    int32_t x = DIAL_R_UI, y = 0, e = 0;
    while (x >= y) {
        dial_px_ui(bmp, cx + x, cy + y); dial_px_ui(bmp, cx + y, cy + x);
        dial_px_ui(bmp, cx - y, cy + x); dial_px_ui(bmp, cx - x, cy + y);
        dial_px_ui(bmp, cx - x, cy - y); dial_px_ui(bmp, cx - y, cy - x);
        dial_px_ui(bmp, cx + y, cy - x); dial_px_ui(bmp, cx + x, cy - y);
        y++;
        if (e <= 0)
            e += 2 * y + 1;
        if (e > 0) {
            x--;
            e -= 2 * x + 1;
        }
    }
    {
        int32_t idx = (v - 64) * 200 / 127;
        int32_t dx = (COS15_UI[(idx - 64) & 255] * DIAL_R_UI) >> 15;
        int32_t dy = (COS15_UI[idx & 255] * DIAL_R_UI) >> 15;
        int32_t k;
        for (k = 1; k <= DIAL_R_UI; k++)
            dial_px_ui(bmp, cx + dx * k / DIAL_R_UI, cy + dy * k / DIAL_R_UI);
    }
}

void digifilter_dn_draw(void *bmp, void *ctrl)
{
    int32_t mode, fi, qi, x, t;
    uint8_t *kit;
    void *view, *bottom, *top;
    if (!bmp || !df_brain)
        return;
    bottom = *(void *volatile *)((uint8_t *)df_brain + BRAIN_BOT);
    top = *(void *volatile *)((uint8_t *)df_brain + BRAIN_TOP);
    if (!bottom || bottom != top)
        return;
    if (msg_sup())
        return;
    t = fw_active_track;
    if (t < 0 || t > 3 || !(kit = fw_kit))
        return;
    if (fltr_p1_view(ctrl)) {
        if (!read_track_ui(&mode, &fi, &qi))
            return;
        fw_fillrect(bmp, GX0 + 1, GY0 + 1, GX1 - 1, GY1 - 1, 0);
        build_curve_ui(mode, fi, qi);
        {
            int32_t prev = -1;
            for (x = GX0 + 1; x < GX1; x++) {
                int32_t s = col2step_ui(x);
                int32_t y = curve_y_ui(s, curve[s]);
                if (prev < 0)
                    prev = y;
                fw_fillrect(bmp, x, prev < y ? prev : y, x, prev < y ? y : prev, 1);
                prev = y;
            }
        }
        type_glyph(bmp, mode);
        if (df_enc == 6 && (int32_t)(df_ticks - df_enc_at) < 45) {
            fw_framerect(bmp, TBX0, TBY0, TBX1, TBY1, 1);
        }
        return;
    }
    if (fltr_p2_view(ctrl)) {
        int32_t ty = FW_SOUND_SLOT(kit, t, FS_TYPE) >> 8;
        int32_t harm, damp;
        if (ty != FM_COMB && ty != FM_TRASH)
            return;
        harm = clampi_ui((FW_SOUND_SLOT(kit, t, 65) >> 8) & 0xff, 0, 127);
        damp = clampi_ui((FW_SOUND_SLOT(kit, t, 26) >> 8) & 0xff, 0, 127);
        draw_dial_ui(bmp, 86, 42, harm);
        draw_dial_ui(bmp, 86, 15, damp);
        return;
    }
    (void)view;
    (void)bottom;
    (void)top;
}

int digifilter_dn_key(void *brain, void *ev)
{
    int32_t id, fl;
    if (brain)
        df_brain = brain;
    if (!ev)
        return 0;
    id = *(volatile int32_t *)((const uint8_t *)ev + 12);
    fl = *(volatile int32_t *)((const uint8_t *)ev + 16);
    if (id == K_FUNC)
        df_func = !(fl & 0x10);
    else if (id == K_PTN)
        df_ptn = !(fl & 0x10);
    else if (id == K_PAGE)
        df_page = !(fl & 0x10);
    if (id == K_REC)
        df_rec_down = !(fl & 0x10);
    if (id >= 26 && id <= 41) {
        if (fl & 0x10)
            df_trigs &= ~(1u << (uint32_t)(id - 26));
        else
            df_trigs |= 1u << (uint32_t)(id - 26);
    } else if (id >= 20 && id <= 25 && (fl & 1)) {
        df_trigs = 0;
    }
    if (id >= 42 && id <= 45 && (fl & 1)) {
        df_trigs = 0;
        df_func = df_ptn = df_page = df_rec_down = 0;
    }
    if ((id == K_REC || id == K_PLAY || id == K_STOP) && !(fl & 0x10)) {
        if (df_func || df_ptn || df_page || df_trigs ||
            ((id == K_PLAY || id == K_STOP) && df_rec_down))
            df_msg_until = df_ticks + DF_MSG_HOLD;
    }
    return 0;
}

int digifilter_dn_enc(void *brain, void *ev)
{
    int32_t enc;
    if (brain)
        df_brain = brain;
    if (!ev)
        return 0;
    enc = *(volatile int32_t *)((const uint8_t *)ev + 12);
    if (enc < 1 || enc > 8)
        return 0;
    df_enc = enc - 1;
    df_enc_at = df_ticks;
    return 0;
}

void digifilter_dn_tick(void *ctrl)
{
    int32_t t = fw_active_track, ty = active_type(), hl, msg, dirty = 0;
    int32_t pos = -1, p2pos = -1, fi = 0, qi = 0, harm = 0, damp = 0;
    void *view, *view2;
    uint8_t *kit;
    df_ticks++;
    if (!ctrl)
        return;
    if (df_brain) {
        void *b = *(void *volatile *)((uint8_t *)df_brain + BRAIN_BOT);
        void *tp = *(void *volatile *)((uint8_t *)df_brain + BRAIN_TOP);
        if (!b || b != tp) {
            df_trigs = 0;
            df_func = df_ptn = df_page = df_rec_down = 0;
        }
    }
    page2_setup();
    if (t < 0 || t > 3 || !(kit = fw_kit)) {
        tick_valid = 0;
        return;
    }
    if (ty >= FM_BP && ty <= FM_OB2) {
        fi = clampi_ui((FW_SOUND_SLOT(kit, t, FS_FREQ) >> 8) & 0xff, 0, 127);
        if (ty == FM_COMB || ty == FM_TRASH || ty == FM_OB4 || ty == FM_OB2) {
            qi = clampi_ui((FW_SOUND_SLOT(kit, t, FS_RESO) >> 8) & 0xff, 0, 127);
            if (ty == FM_COMB || ty == FM_TRASH) {
                harm = clampi_ui((FW_SOUND_SLOT(kit, t, 65) >> 8) & 0xff, 0, 127);
                damp = clampi_ui((FW_SOUND_SLOT(kit, t, 26) >> 8) & 0xff, 0, 127);
            }
        } else {
            qi = clampi_ui(FW_SOUND_SLOT(kit, t, FS_RESO) >> 11, 0, 15);
        }
    }
    view = fltr_p1_view(ctrl);
    if (view)
        pos = VIEW_POS(view);
    view2 = fltr_p2_view(ctrl);
    if (view2)
        p2pos = VIEW_POS(view2);
    hl = df_enc >= 0 && (int32_t)(df_ticks - df_enc_at) < 45;
    msg = msg_sup();
    if (!tick_valid || t != tick_track || ty != tick_type || fi != tick_fi ||
        qi != tick_qi || harm != tick_harm || damp != tick_damp ||
        pos != tick_pos || p2pos != tick_p2pos || df_enc != tick_enc ||
        hl != tick_hl || msg != tick_msg)
        dirty = 1;
    if (!dirty)
        return;
    tick_valid = 1;
    tick_track = t;
    tick_type = ty;
    tick_fi = fi;
    tick_qi = qi;
    tick_harm = harm;
    tick_damp = damp;
    tick_pos = pos;
    tick_p2pos = p2pos;
    tick_enc = df_enc;
    tick_hl = hl;
    tick_msg = msg;
    *((volatile uint8_t *)ctrl + 0x20) = 1;
}
