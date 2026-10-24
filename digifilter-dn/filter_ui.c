/* Filter+FX-DN: FLTR graph/icons and per-voice filter integration. */
#include "digitone-mk1/core3.h"

#include "../shared/fx_dsp.h"
#include "../shared/filter_tables.h"   /* G27/K27 for the response graph */
#include "../shared/analog_tables.h"
#include "../shared/mod_tables.h"

#define FILLRECT fw_fillrect

#define FLTR_P1 6
#define FLTR_P2 7

#define GX0 20
#define GX1 71
#define GY0 7
#define GY1 23
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
#define FS_AUX1 65
#define FS_AUX2 26

#define FM_FIRST_TYPE 4
#define FM_VOWEL  4
#define FM_BANK   5
#define FM_FOLD   6
#define FM_CRUSH  7
#define FM_RING   8
#define FM_PHASER 9
#define FM_FLANGER 10
#define FM_LAST   10

typedef int int32;
typedef unsigned int uint32;

static void *df_brain;
static uint32_t df_ticks;
static uint32_t df_msg_until;
#define DF_MSG_HOLD 90u
static int32_t df_enc = -1;
static uint32_t df_enc_at;
static int32_t df_trigs;
static int32_t df_func, df_ptn, df_page, df_rec_down;
static int32_t tick_valid;
static int32_t tick_track, tick_type, tick_fi, tick_qi, tick_aux1, tick_aux2;
static int32_t tick_pos, tick_p2pos, tick_enc, tick_hl, tick_msg;

static int32_t msg_sup(void)
{
    return (int32_t)(df_ticks - df_msg_until) < 0;
}

static int32_t curve[128];
static int curve_transfer;

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

/* One SVF band's magnitude at frequency step x, in half-dB, for centre fi and
 * K27 row ek (same formula as DigiFilter's BP curve). */
static int bp_db2(int fi, int qi, int x)
{
    int32 g = G27[fi];
    int32 k = K27[qi] >> 11;
    int32 G = G27[x], t, num, den, n, d;
    if (G <= g)
        t = udivq16(G, (uint32)g);
    else
        t = udivq16((uint32)g, G);
    num = mulsh(k, t, 16);
    den = (1 << 16) - mulsh(t, t, 16);
    if (den < 0)
        den = -den;
    n = mulsh(num, num, 16);
    d = mulsh(den, den, 16) + n;
    if (d <= 0)
        return 0;
    /* half-dB, 0 at the band centre: the Q16 ratio has a 16-bit (160
     * half-dB) offset that must come off before combining bands. */
    return (int)((log2q8((uint32)(num * num)) - log2q8((uint32)d)) * 10 / 256) - 160;
}

#define CH (GY1 - GY0 - 4)

/* FOLD: the triangle transfer curve, drive from FREQ and bias from RESO. */
static void build_fold_curve(int fi, int qi)
{
    const int32 F = 1 << 27;
    int drive = 1 + fi * 7 / 127;
    int32 bias = (int32)(qi - 64) << 21;
    int x;
    for (x = 0; x < 128; x++) {
        int32 in = (int32)(x - 64) << 21;
        int32 v = in * drive + bias;
        uint32 u = (uint32)v & (4u * F - 1);
        if (u > 2u * F)
            u = 4u * F - u;
        curve[x] = ((int32)u >> 22) * CH / 128;
    }
}

/* CRUSH: the quantisation staircase, bit depth from RESO. */
static void build_crush_curve(int qi)
{
    int bits = 16 - qi * 15 / 127;
    int shift = 30 - bits;
    int x;
    for (x = 0; x < 128; x++) {
        int32 in = (int32)(x - 64) << 24;
        int32 q = (in >> shift) << shift;
        curve[x] = ((q >> 24) + 64) * CH / 128;
    }
}

/* RING: the carrier * modulator waveform. PHASER: a chirped sine (the swirl).
 * FLANGER: a rectified sine (the jet/comb). These are pictures, not responses. */
static void build_mod_curve(int mode, int fi, int qi)
{
    int x, depth = qi * 258;
    for (x = 0; x < 128; x++) {
        int v;
        if (mode == FM_RING) {
            int c = SINE_Q15[(x * 4) & 255];
            int m = SINE_Q15[(x * (2 + fi / 16)) & 255];
            int r = mulsh(c, m, 15);
            v = c + mulsh(r - c, depth, 15);
            curve[x] = (v + 32768) * CH / 65536;
        } else if (mode == FM_PHASER) {
            v = SINE_Q15[((x * x) / 3 + fi * 2) & 255];
            curve[x] = CH / 2 + (v * (CH / 2)) / 32768;
        } else {
            int s = SINE_Q15[(x * 4 + fi * 2) & 255];
            if (s < 0)
                s = -s;
            curve[x] = s * CH / 32768;
        }
    }
}

/* VOWEL: formant bells; BANK: four shifted bells; FOLD/CRUSH: transfer curves. */
static void build_curve(int mode, int fi, int qi)
{
    static const int vdb2[4] = { 0, -4, -9, -20 };
    curve_transfer = 0;
    if (mode >= FM_RING) {
        curve_transfer = 1;
        build_mod_curve(mode, fi, qi);
        return;
    }
    if (mode == FM_FOLD) {
        curve_transfer = 1;
        build_fold_curve(fi, qi);
        return;
    }
    if (mode == FM_CRUSH) {
        curve_transfer = 1;
        build_crush_curve(qi);
        return;
    }
    int ek = 8 + qi * 7 / 127;
    int banks = (mode == FM_FIRST_TYPE) ? VOWEL_N : BANK_N;
    int pos[4], db[4], b, x, pass;
    if (mode == FM_FIRST_TYPE) {
        for (b = 0; b < VOWEL_N; b++) {
            pos[b] = VOWEL_FI8[b][fi] >> 8;
            db[b] = vdb2[b];
        }
    } else {
        int shift = (fi - 64) * 12 / 64;
        for (b = 0; b < BANK_N; b++) {
            pos[b] = clampi((BANK_BASE_FI8[b] >> 8) + shift, 0, 127);
            db[b] = 0;
        }
    }
    for (x = 0; x < 128; x++) {
        int best = -0x7fff;
        for (b = 0; b < banks; b++) {
            int d = bp_db2(pos[b], ek, x) + db[b];
            if (d > best)
                best = d;
        }
        if (best > 0)
            best = 0;
        curve[x] = CH * 50 / (50 - best);
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

static int curve_y(int s, int v)
{
    int w;
    if (curve_transfer)
        return GY0 + 2 + v;
    w = (s < 8) ? s : (s > 119) ? (127 - s) : 8;
    return GY0 + 2 + v * w / 8;
}

static void type_glyph(void *bmp, int mode)
{
    int x, cx = (TBX0 + TBX1) / 2, top = TBY0 + 1, bot = TBY1 - 1, h = bot - top;
    FILLRECT(bmp, TBX0, TBY0, TBX1, TBY1, 0);
    if (mode == FM_FIRST_TYPE) {                 /* a mouth */
        int y0 = top + 3, y1 = bot - 2;
        FILLRECT(bmp, cx - 5, y0, cx + 5, y0, 1);
        FILLRECT(bmp, cx - 6, y0 + 1, cx + 6, y0 + 1, 1);
        FILLRECT(bmp, cx - 5, y1, cx + 5, y1, 1);
        FILLRECT(bmp, cx - 4, y1 + 1, cx + 4, y1 + 1, 1);
        FILLRECT(bmp, cx - 4, y0 + 2, cx + 4, y1 - 1, 0);
        for (x = cx - 3; x <= cx + 3; x += 2)
            FILLRECT(bmp, x, y0 + 2, x, y0 + 3, 1);
    } else if (mode == FM_FIRST_TYPE + 1) {      /* a robot */
        FILLRECT(bmp, cx, top, cx, top + 1, 1);
        FILLRECT(bmp, cx - 1, top + 2, cx + 1, top + 2, 1);
        FILLRECT(bmp, cx - 5, top + 3, cx + 5, top + 3, 1);
        FILLRECT(bmp, cx - 6, top + 4, cx - 6, bot - 1, 1);
        FILLRECT(bmp, cx + 6, top + 4, cx + 6, bot - 1, 1);
        FILLRECT(bmp, cx - 5, bot, cx + 5, bot, 1);
        FILLRECT(bmp, cx - 4, top + 5, cx - 3, top + 6, 1);
        FILLRECT(bmp, cx + 3, top + 5, cx + 4, top + 6, 1);
        for (x = cx - 4; x <= cx + 4; x += 2)
            FILLRECT(bmp, x, bot - 2, x, bot - 1, 1);
    } else if (mode == FM_FOLD) {                /* a folded wave */
        for (x = TBX0 + 1; x < TBX1; x++) {
            int t = (x - TBX0 - 1) % 8, v = t < 4 ? t : 8 - t;
            int y = top + v * h / 4;
            FILLRECT(bmp, x, y, x, y + 1, 1);
        }
    } else if (mode == FM_RING) {                /* a ringed planet */
        static const unsigned char half[7] = { 1, 2, 3, 3, 3, 2, 1 };
        int cy = (top + bot) / 2, dy;
        for (dy = -3; dy <= 3; dy++)
            FILLRECT(bmp, cx - half[dy + 3], cy + dy, cx + half[dy + 3], cy + dy, 1);
        for (dy = -1; dy <= 1; dy += 2) {
            FILLRECT(bmp, cx - 6, cy + dy, cx - 3, cy + dy, 1);
            FILLRECT(bmp, cx + 3, cy + dy, cx + 6, cy + dy, 1);
        }
    } else if (mode == FM_PHASER) {              /* an open square spiral */
        static const signed char sx[10] = { 0, 2, 2, -2, -2, 4, 4, -4, -4, 6 };
        static const signed char sy[10] = { 0, 0, 2, 2, -2, -2, 4, 4, -4, -4 };
        int i, py = (top + bot) / 2;
        for (i = 1; i < 10; i++) {
            int x0 = cx + sx[i - 1], y0 = py + sy[i - 1];
            int x1 = cx + sx[i], y1 = py + sy[i];
            if (x0 == x1) {
                int lo = y0 < y1 ? y0 : y1, hi = y0 < y1 ? y1 : y0, y;
                for (y = lo; y <= hi; y++)
                    if (y >= top && y <= bot)
                        FILLRECT(bmp, x0, y, x0, y, 1);
            } else {
                int lo = x0 < x1 ? x0 : x1, hi = x0 < x1 ? x1 : x0, xx;
                for (xx = lo; xx <= hi; xx++)
                    if (xx >= TBX0 + 1 && xx <= TBX1 - 1)
                        FILLRECT(bmp, xx, y0, xx, y0, 1);
            }
        }
    } else if (mode == FM_FLANGER) {             /* three waves / jet */
        int row;
        for (row = 0; row < 3; row++)
            for (x = TBX0 + 1; x < TBX1; x++) {
                int s = SINE_Q15[(x * 9 + row * 80) & 255];
                int y = top + 3 + row * 3 + (s * 3) / 32768;
                FILLRECT(bmp, x, y, x, y + 1, 1);
            }
    } else {                                     /* Pac-Man */
        static const unsigned char half[11] = { 2, 4, 5, 5, 6, 6, 6, 5, 5, 4, 2 };
        int cy = (top + bot) / 2, dy;
        for (dy = -5; dy <= 5; dy++)
            FILLRECT(bmp, cx - half[dy + 5], cy + dy, cx + half[dy + 5], cy + dy, 1);
        for (dy = -1; dy <= 1; dy++)
            FILLRECT(bmp, cx, cy + dy, cx + 6, cy + dy, 0);
        FILLRECT(bmp, cx - 2, cy - 3, cx - 1, cy - 3, 0);   /* eye */
    }
}



static int32_t active_type(void)
{
    int32_t t = fw_active_track;
    uint8_t *kit = fw_kit;
    if (t < 0 || t > 3 || !kit)
        return -1;
    return FW_SOUND_SLOT(kit, t, FS_TYPE) >> 8;
}

static int32_t aux_val(int32_t slot)
{
    int32_t t = fw_active_track;
    uint8_t *kit = fw_kit;
    if (t < 0 || t > 3 || !kit)
        return 0;
    return clampi((FW_SOUND_SLOT(kit, t, slot) >> 8) & 0xff, 0, 127);
}

static int32_t read_track_ui(int32_t *mode, int32_t *fi, int32_t *qi)
{
    uint8_t *kit = fw_kit;
    int32_t t = fw_active_track, ty;
    if (!kit || t < 0 || t > 3)
        return 0;
    ty = FW_SOUND_SLOT(kit, t, FS_TYPE) >> 8;
    if (ty < FM_FIRST_TYPE || ty > FM_LAST)
        return 0;
    *mode = ty;
    *fi = clampi((FW_SOUND_SLOT(kit, t, FS_FREQ) >> 8) & 0xff, 0, 127);
    *qi = clampi((FW_SOUND_SLOT(kit, t, FS_RESO) >> 8) & 0xff, 0, 127);
    return 1;
}

/* ---- second page: AUX1/AUX2 (params 182/183) for VOWEL/BANK ---- */
static void aux_fmt(int32_t v, char *buf)
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

static const char df_aux1_name[] = "Aux 1";
static const char df_aux2_name[] = "Aux 2";
static const char df_aux_group[] = "Filter";
static const char df_aux1_short[] = "AUX1";
static const char df_aux2_short[] = "AUX2";

const struct core_param digifilter_dn_aux1 = {
    182, 2, FS_AUX1, 0, 0x7f00, 0, 0, -1, -1, -1, 0,
    df_aux1_name, df_aux_group, df_aux1_short,
    aux_fmt, fw_str_empty, 36,
};

const struct core_param digifilter_dn_aux2 = {
    183, 2, FS_AUX2, 0, 0x7f00, 0, 0, -1, -1, -1, 0,
    df_aux2_name, df_aux_group, df_aux2_short,
    aux_fmt, fw_str_empty, 37,
};

static const char df_size_short[] = "SIZE";
static const char df_f4_short[] = "F4";
static const char df_sprd_short[] = "SPRD";
static const char df_tilt_short[] = "TILT";

static const char *aux_name(int32_t id, int32_t field)
{
    int32_t ty;
    if (field != 0x30)
        return 0;
    ty = active_type();
    if (id == 182) {
        if (ty == FM_VOWEL) return df_size_short;
        if (ty == FM_BANK) return df_sprd_short;
    } else if (id == 183) {
        if (ty == FM_VOWEL) return df_f4_short;
        if (ty == FM_BANK) return df_tilt_short;
    }
    return 0;
}

const struct core_param_override df_aux_override = { 0, aux_name };

#ifndef PAGE2_C_AT
#error "PAGE2_C_AT: page-2 C id addr (0x4136c69c on 1.44)"
#endif
#ifndef PAGE2_G_AT
#error "PAGE2_G_AT: page-2 G id addr (0x4136c6ac on 1.44)"
#endif

static void page2_setup(void)
{
    int32_t ty = active_type();
    int32_t own = (ty == FM_VOWEL || ty == FM_BANK);
    volatile uint32_t *c = (volatile uint32_t *)PAGE2_C_AT;
    volatile uint32_t *g = (volatile uint32_t *)PAGE2_G_AT;
    if (*c != (uint32_t)(own ? 182 : 0))
        *c = (uint32_t)(own ? 182 : 0);
    if (*g != (uint32_t)(own ? 183 : 0))
        *g = (uint32_t)(own ? 183 : 0);
}

/* ---- view gating: find both FLTR pages in one walk ---- */
static void fltr_views(void *ctrl, void **p1, void **p2)
{
    char *node, *sent;
    *p1 = *p2 = 0;
    if (!ctrl)
        return;
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
            *p1 = view;
        else if (v[pos] == FLTR_P2)
            *p2 = view;
    }
}

/* ---- per-voice filter (dispatcher globals + fw_voice_params) ---- */
extern int digifilter_dn_voice;
extern int digifilter_dn_buf;
extern int digifilter_dn_cut;
static int dn_sounding[8];

void digifilter_dn_filt(void)
{
    int voice = digifilter_dn_voice;
    int32 *buf = (int32 *)digifilter_dn_buf;
    volatile int16_t *vp;
    int cut, type, fi, qi, a1, a2, i;
    if (voice < 0 || voice >= 8 || !buf)
        return;
    vp = &fw_voice_params[9 + 79 * voice];
    for (i = 0; i < 32; i++)
        if (buf[i])
            break;
    if (i == 32) {
        if (dn_sounding[voice]) {
            fx_reset(voice);
            dn_sounding[voice] = 0;
        }
        return;
    }
    dn_sounding[voice] = 1;
    type = (vp[FS_TYPE] >> 8) & 0xff;
    if (type < FM_FIRST_TYPE || type > FM_LAST)
        return;
    cut = digifilter_dn_cut;
    fi = (cut >> 24) & 0xff;
    qi = (unsigned short)vp[FS_RESO] >> 8;
    a1 = (unsigned short)vp[FS_AUX1] >> 8;
    a2 = (unsigned short)vp[FS_AUX2] >> 8;
    if (qi > 127) qi = 127;
    if (a1 > 127) a1 = 127;
    if (a2 > 127) a2 = 127;
    fx_run(type - FM_FIRST_TYPE, fi, qi, a1, a2, (int *)buf, voice);
}

/* ---- TYPE persistence (stock temp save resets TYPE > 3) ---- */
static int dn_type_enc;
static int32_t dn_last_type[4] = { -1, -1, -1, -1 };

static void dn_persist_type(void)
{
    uint8_t *kit = fw_kit;
    int32_t t;
    if (!kit)
        return;
    for (t = 0; t < 4; t++) {
        int32_t type = (FW_SOUND_SLOT(kit, t, FS_TYPE) >> 8) & 0xff;
        int32_t base = FW_SOUND_SLOT(kit, t, 62);
        int32_t lo = base & 0xff;
        if (dn_type_enc) {
            core_sound_set(t, 62, (base & 0xff00) | type);
        } else if (type <= 3 && lo >= 4 && lo <= 10) {
            core_sound_set(t, 54, lo << 8);
            type = lo;
        } else if (type != dn_last_type[t]) {
            core_sound_set(t, 62, (base & 0xff00) | type);
        }
        dn_last_type[t] = type;
    }
    dn_type_enc = 0;
}

/* ---- dials on page 2 ---- */
static void dial_px(void *bmp, int32_t x, int32_t y)
{
    fw_fillrect(bmp, x, y, x, y, 1);
}

#define DIAL_R_UI 8
static void draw_dial(void *bmp, int32_t cx, int32_t cy, int32_t v)
{
    int32_t x = DIAL_R_UI, y = 0, e = 0;
    while (x >= y) {
        dial_px(bmp, cx + x, cy + y); dial_px(bmp, cx + y, cy + x);
        dial_px(bmp, cx - y, cy + x); dial_px(bmp, cx - x, cy + y);
        dial_px(bmp, cx - x, cy - y); dial_px(bmp, cx - y, cy - x);
        dial_px(bmp, cx + y, cy - x); dial_px(bmp, cx + x, cy - y);
        y++;
        if (e <= 0) e += 2 * y + 1;
        if (e > 0) { x--; e -= 2 * x + 1; }
    }
    {
        int32_t idx = 192 + v * 213 / 127;
        int32_t dx = (SINE_Q15[idx & 255] * DIAL_R_UI) >> 15;
        int32_t dy = (SINE_Q15[(idx + 64) & 255] * DIAL_R_UI) >> 15;
        int32_t k;
        for (k = 1; k <= DIAL_R_UI; k++)
            dial_px(bmp, cx + dx * k / DIAL_R_UI, cy + dy * k / DIAL_R_UI);
    }
}

void digifilter_dn_draw(void *bmp, void *ctrl)
{
    static int32_t curve_mode = -1, curve_fi = -1, curve_qi = -1;
    int32_t mode, fi, qi, x, t;
    uint8_t *kit;
    void *p1, *p2, *bottom, *top;
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
    fltr_views(ctrl, &p1, &p2);
    if (p1) {
        if (!read_track_ui(&mode, &fi, &qi))
            return;
        fw_fillrect(bmp, GX0 + 1, GY0 + 1, GX1 - 1, GY1 - 1, 0);
        if (mode != curve_mode || fi != curve_fi || qi != curve_qi) {
            build_curve(mode, fi, qi);
            curve_mode = mode;
            curve_fi = fi;
            curve_qi = qi;
        }
        {
            int32_t prev = -1;
            for (x = GX0 + 1; x < GX1; x++) {
                int32_t s = (x - GX0 - 1) * 127 / (GX1 - GX0 - 2);
                int32_t y = curve_y(s, curve[s]);
                if (prev < 0)
                    prev = y;
                fw_fillrect(bmp, x, prev < y ? prev : y, x, prev < y ? y : prev, 1);
                prev = y;
            }
        }
        type_glyph(bmp, mode);
        if (df_enc == 6 && (int32_t)(df_ticks - df_enc_at) < 45)
            fw_framerect(bmp, TBX0, TBY0, TBX1, TBY1, 1);
        return;
    }
    if (p2) {
        int32_t ty = FW_SOUND_SLOT(kit, t, FS_TYPE) >> 8;
        if (ty != FM_VOWEL && ty != FM_BANK)
            return;
        draw_dial(bmp, 86, 42, aux_val(FS_AUX1));
        draw_dial(bmp, 86, 15, aux_val(FS_AUX2));
    }
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
    if (id == K_FUNC) df_func = !(fl & 0x10);
    else if (id == K_PTN) df_ptn = !(fl & 0x10);
    else if (id == K_PAGE) df_page = !(fl & 0x10);
    if (id == K_REC) df_rec_down = !(fl & 0x10);
    if (id >= 26 && id <= 41) {
        if (fl & 0x10) df_trigs &= ~(1u << (uint32_t)(id - 26));
        else df_trigs |= 1u << (uint32_t)(id - 26);
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
    if (enc == 7)                       /* G: the page-1 TYPE encoder */
        dn_type_enc = 1;
    return 0;
}

void digifilter_dn_tick(void *ctrl)
{
    int32_t t = fw_active_track, ty, hl, msg, dirty = 0;
    int32_t pos = -1, p2pos = -1, fi = 0, qi = 0, a1 = 0, a2 = 0;
    void *view, *view2;
    uint8_t *kit;
    df_ticks++;
    if (!ctrl)
        return;
    dn_persist_type();
    ty = active_type();
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
    if (ty >= FM_FIRST_TYPE && ty <= FM_LAST) {
        fi = clampi((FW_SOUND_SLOT(kit, t, FS_FREQ) >> 8) & 0xff, 0, 127);
        qi = clampi((FW_SOUND_SLOT(kit, t, FS_RESO) >> 8) & 0xff, 0, 127);
        a1 = clampi((FW_SOUND_SLOT(kit, t, FS_AUX1) >> 8) & 0xff, 0, 127);
        a2 = clampi((FW_SOUND_SLOT(kit, t, FS_AUX2) >> 8) & 0xff, 0, 127);
    }
    fltr_views(ctrl, &view, &view2);
    if (view)
        pos = VIEW_POS(view);
    if (view2)
        p2pos = VIEW_POS(view2);
    hl = df_enc >= 0 && (int32_t)(df_ticks - df_enc_at) < 45;
    msg = msg_sup();
    if (!tick_valid || t != tick_track || ty != tick_type || fi != tick_fi ||
        qi != tick_qi || a1 != tick_aux1 || a2 != tick_aux2 ||
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
    tick_aux1 = a1;
    tick_aux2 = a2;
    tick_pos = pos;
    tick_p2pos = p2pos;
    tick_enc = df_enc;
    tick_hl = hl;
    tick_msg = msg;
    *((volatile uint8_t *)ctrl + 0x20) = 1;
}
