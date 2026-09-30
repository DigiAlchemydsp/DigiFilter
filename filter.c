/* Digi Filter: extra per-track filter modes for the Digitakt mk1 (OS 1.53).
 *
 * The stock filter keeps running for every stock TYPE value: nothing here
 * reimplements a stock mode, so stock sounds are untouched. TYPE values above
 * the stock range (FM_FIRST_TYPE + mode) select an extra mode. BP/BP2 run a
 * trapezoidal state-variable filter (Simper / Zavalishin, the same kernel as
 * Digi EQ's eq_dsp.s) with the track's own FREQ, RESO and filter envelope;
 * COMB/TRASH run a feedback comb, with the second FLTR page's Base / Width /
 * Env Delay / SRR knobs reused as delay, harmonics, damping and feedback trim.
 *
 * The filter envelope (FLTR slot 0x1c, params@6) is applied exactly as the
 * stock filter does (see cutoff_index): the engine writes a per-voice envelope
 * level at 0x4199df58 + v*12, and the modulated cutoff is
 *   (FREQ<<16) + (((-env) * ((ENVword-0x4000)<<17)) >> 31).
 *
 * 32-bit integer arithmetic only: no FPU, no libgcc (mulsh / div55 by hand).
 *
 * Open: the FLTR page's FREQ/RES response *curve* still draws the stock shapes
 * for TYPE 8..11 (cosmetic; it is drawn by the page UI from UI-model state, not
 * from this DSP's RAM). See RE_NOTES.md / HANDOFF.md.
 */
typedef int int32;
typedef unsigned int uint32;

#include "filter_tables.h"

/* ---- firmware (OS 1.53) ---- */
#define UI_KIT (*(unsigned char *volatile *)0x4199dc44)  /* the kit of the pattern being edited */

/* a track's sound block in the kit: 0xa2 bytes at kit + 0x20 + t*0xa2, the 53
 * parameter slots as words at +0x14 + 2*s (TECHNICAL_NOTES, v3e). */
#define SOUND(kit, t)   ((kit) + 0x20 + (t) * 0xa2)
#define FSLOT(kit, t, s) ((int)(*(unsigned short *)(SOUND(kit, t) + 0x14 + 2 * (s))))

/* Confirmed from the filter parameter descriptors at 0x401aa3b4.. (OS 1.53):
 *   Frequency  slot 0x1a  long "Frequency"  short "FREQ"  CC 74
 *   Resonance  slot 0x1b  long "Resonance"  short "RESO"  CC 75
 *   FilterType slot 0x19  long "Filter Type" short "TYPE" CC 76  (display max 7)
 *   Env Depth 0x1c, Attack 0x1d, Decay 0x1e, Sustain 0x1f, Release 0x20,
 *   Base 0x21, Width 0x22, Env Delay 0x23, SRR 0x24. */
#define FS_TYPE 0x19
#define FS_FREQ 0x1a
#define FS_RESO 0x1b
#define FS_BASE 0x21
#define FS_WIDTH 0x22
#define FS_ENVDELAY 0x23
#define FS_SRR 0x24

/* ---- the extra modes (TYPE = FM_FIRST_TYPE + mode) ----
 * Notch/all-pass/peak are already covered by the stock filter types, so the
 * new slots are: band pass, a wider band pass, and two combs. TRASH is the
 * second comb with a different (higher) harmonic series. */
enum { FM_BP, FM_BP2, FM_COMB, FM_TRASH, FM_NMODES };
static const char *const FM_NAME[FM_NMODES] = { "BP", "BP2", "COMB", "TRASH" };
/* The multimode dispatch (0x40075184) compares the mode against 3/2/1 = 4
 * paths (LP2/LP4/HP2/HP4); the FilterType descriptor's range byte (0x0700)
 * hints at 0..7. The real stock TYPE maximum is still to be confirmed in the
 * emulator, so this base is a placeholder. New modes start at FM_FIRST_TYPE;
 * the FLTR page's bound must be widened (Phase 3) and the sanitizer at
 * 0x40079a60 must not clamp the value away. */
#define FM_STOCK_TYPES 8
#define FM_FIRST_TYPE  FM_STOCK_TYPES

/* ---- the coefficient set the DSP reads (filter_dsp.s) ---- */
struct fcoef { int32 a1, a2, a3, c0, c1, c2; };
struct fset { int32 run; int32 mode[8]; struct fcoef v[8]; };
static struct fset sets[2];
static int cur;
struct fset *digifilter_live;                       /* one 32-bit store switches the audio side */
static int32 dsp_st[8][2];                          /* per voice: ic1, ic2 */
static int prev_mode[8] = { -1, -1, -1, -1, -1, -1, -1, -1 };

extern void digifilter_svf(int32 *buf, int frames, const int32 *coef, int32 *state);

/* floor(a * b / 2^sh) for 16 <= sh <= 31, when the result fits 32 bits */
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

/* floor(2^55 / d), d > 2^24 */
static int32 div55(uint32 d)
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

static int clampi(int v, int lo, int hi)
{
    return v < lo ? lo : v > hi ? hi : v;
}

/* the SVF coefficients and the mode's output mix (A = 1: no band gain) */
static void mode_coef(int m, int fi, int qi, struct fcoef *c)
{
    /* BP2 is the same band-pass but with ~half the resonance (a wider band):
     * take k from a lower Q step. */
    int32 g = G27[fi], k = K27[m == FM_BP2 ? (qi >> 1) : qi], d24;
    /* band-pass output mix: out = c1 * band  (c0 cancels the input's v0 term) */
    c->c0 = -ONE27;
    c->c1 = mulsh(k, ONE27, 27);
    c->c2 = 0;
    d24 = (1 << 24) + mulsh(g, g + k, 30);
    c->a1 = div55((uint32)d24);
    c->a2 = mulsh(g, c->a1, 27);
    c->a3 = mulsh(g, c->a2, 27);
}

/* rebuild the set from the pattern's kit; called each UI frame (cheap: 8 voices) */
static void commit(void)
{
    struct fset *s = &sets[cur ^ 1];
    unsigned char *kit = UI_KIT;
    int t, run = 0;
    for (t = 0; t < 8; t++) {
        struct fcoef *c = &s->v[t];
        int type, m, fi, qi, j;
        for (j = 0; j < 6; j++)
            ((int32 *)c)[j] = 0;
        s->mode[t] = -1;
        if (!kit)
            continue;
        type = FSLOT(kit, t, FS_TYPE);
        m = type - FM_FIRST_TYPE;
        if (m < 0 || m >= FM_NMODES)
            continue;
        /* TODO(RE): decode the stock FREQ/RESO words into the 0..127 / 0..15
         * indices. The shift below is a placeholder (the words are 0..32512). */
        fi = clampi((unsigned)FSLOT(kit, t, FS_FREQ) >> 8, 0, 127);
        qi = clampi((unsigned)FSLOT(kit, t, FS_RESO) >> 8, 0, 15);
        mode_coef(m, fi, qi, c);
        s->mode[t] = m;
        run = 1;
    }
    s->run = run;
    cur ^= 1;
    digifilter_live = s;
    for (t = 0; t < 8; t++)
        if (s->mode[t] != prev_mode[t]) {           /* a mode change restarts the filter */
            dsp_st[t][0] = 0;
            dsp_st[t][1] = 0;
            prev_mode[t] = s->mode[t];
        }
}

/* ---- integration points ---- */

/* The render calls, per voice, the stock per-voice filter
 *   0x40072844(params, buffer, active, voice)
 * at 0x400780c4, through a3. mod.json hooks the instruction just before the
 * call, 0x400780ba (`addil #0x80001a18,%d0`), with digifilter_dispatch
 * (filter_glue.s); the dispatcher points a3 at digifilter_filt for our TYPE
 * values and restores the original target otherwise, so a profiling wrapper
 * another mod installed (e.g. digihealth) keeps working.
 *
 *   params  per-voice record, byte 0 = the track's Filter Type
 *           (0x800027a4 + voice*0x6a; raw, unclamped)
 *   buffer  this voice's 32 audio frames (int32), filtered in place
 *           (0x80001a18 + voice*0x80)
 *   active  voice-sounding mask bit (0/1) — the stock function ignores it
 *   voice   0..7
 *
 * For a stock TYPE we tail-call the stock function, so stock sounds are
 * untouched; for our TYPE values (>= FM_FIRST_TYPE) we run our DSP. */
/* CUTOFF comes from params@2, the field the stock per-voice filter 0x40072844
 * reads (word = FREQ index<<8). It tracks FLTR encoder E (FREQ) exactly like
 * the stock types (verified live). RESO comes from the engine's per-voice
 * settings slot 0x1b (FLTR encoder F), value<<8 -> qi 0..15.
 *
 * The filter ENVELOPE (FLTR encoder H, slot 0x1c) is at params@6. The stock
 * filter adds an envelope modulation to FREQ before filtering; we do the same
 * (RE_NOTES, "filter envelope"):
 *
 *   envmod = ((-env_level) * ((ENV_word - 0x4000) << 17)) >> 31   (32-bit, floor)
 *   cutoff = (FREQ_word << 16) + envmod        (clamped 0..0x7f000000)
 *
 * where env_level = *(int *)(0x4199df58 + v*12) is the per-voice filter
 * envelope output the engine's envelope stage (0x40073304) writes every block,
 * read by the stock filter through 0x40073412. ENV_word is biased: 0x4000 = 0.
 * Since FREQ_word is (index<<8), cutoff>>16 = FREQ_word + envmod>>16, so the
 * modulated index is (FREQ_word + (envmod>>16)) >> 8. */
#define ENGINE(v) (0x80001502 + 106 * (v))
#define PARAM_CUTOFF(params) (*(volatile unsigned short *)((params) + 2))
#define PARAM_ENV(params) (*(volatile unsigned short *)((params) + 6))
#define SET_RESO(v) (*(volatile unsigned short *)(ENGINE(v) + 2 * FS_RESO))
#define ENV_LEVEL(v) (*(volatile int *)(0x4199DF58 + 12 * (v)))

/* Every sound slot is a word in the render record; slot s is at
 * params + 2s - 0x32 (TYPE s=0x19 is at +0; FREQ 0x1a at +2; ...; the second
 * FLTR page's Base/Width/Env Delay/SRR slots 0x21..0x24 are at +0x10..+0x16).
 * Verified live: turning the second-page knobs moves these words. */
#define PARAM_SLOT(params, s) (*(volatile unsigned short *)((params) + 2 * (s) - 0x32))

/* ---- COMB second FLTR page (slots 0x21..0x24) ----
 * COMB/TRASH reuse the second page, which the stock filter uses as Base / Width
 * / Env Delay / SRR while it runs — but it does not run for our types, so those
 * knobs are free. Defaults (Base 0, Width max, Env Delay 0, SRR 0) leave the
 * comb exactly as it was:
 *   Base 0x21   delay offset (coarse), 0..127 samples added to the FREQ delay
 *   Width 0x22  harmonics: divider multiplier 1..4 (max width = 1 = no change)
 *   EnvDelay 0x23  damping: 0 = off, else a one-pole on the feedback
 *   SRR 0x24    feedback trim: pushes the RESO feedback toward self-oscillation
 */

/* ---- COMB state (per voice) ---- */
#define COMB_N 256                   /* power of two: delay wraps with a mask */
#define COMB_MASK (COMB_N - 1)
static int32 comb_buf[8][COMB_N];
static int comb_pos[8];
static int comb_init[8];
static int32 comb_dly[8];            /* Q16 smoothed delay in samples */
static int32 comb_g[8];              /* Q27 smoothed feedback */
static int32 comb_lp[8];             /* Q27 one-pole state for the damping */
static int prev_filt_type[8];        /* reset state when the mode changes */

/* Per-sample smoothing shifts. The delay is smoothed so changing the cutoff
 * (or the filter envelope) glides instead of clicking; the feedback is smoothed
 * for the same reason. */
#define COMB_DSHIFT 6                /* ~64 samples (1.3 ms) */
#define COMB_GSHIFT 7

/* Feedback comb, fractional and smoothed: y = x + g*y[n-D]. D = COMB_DELAY[fi]
 * / div (clamped 3..255), g from RESO. COMB uses div 1; TRASH uses div 2 for a
 * higher (different) harmonic series. The delay is interpolated (linear) so it
 * can move continuously; the output is saturated so high feedback cannot run
 * away at the extreme cutoffs. */
static void comb_run(int32 *buf, int frames, int fi, int qi, int v, int div,
                     int dly_off, int hdiv, int damp, int fbtrim)
{
    /* Harmonics: an extra divider on top of the mode's own (COMB 1 / TRASH 2).
     * Width 0x22 at max (the default) -> 1 (no change). */
    int32 target = COMB_DELAY[fi] / (div * hdiv) + dly_off;
    int32 tdq, gt, *b = comb_buf[v];
    int p, i;
    if (target < 3)
        target = 3;                  /* taper: no near-Nyquist comb */
    if (target > COMB_MASK)
        target = COMB_MASK;
    tdq = target << 16;
    gt = (int32)qi * (ONE27 / 16);   /* 0 .. 0.9375 */
    if (fbtrim) {
        gt += mulsh(ONE27 - gt, fbtrim, 15);     /* up toward full feedback */
        if (gt > 0x7c000000)
            gt = 0x7c000000;         /* stay short of runaway */
    }
    if (!comb_init[v]) {
        comb_init[v] = 1;
        comb_dly[v] = tdq;           /* start at the target, no glide-in */
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
        /* Linear interpolation, but with one 32x32 multiply instead of mulsh:
         * (fp*diff)>>16 == ((fp>>1)*((diff)>>13))>>2, both factors < 2^15. */
        fa = fp >> 1;
        da = (b[i1] - b[i0]) >> 13;
        val = b[i0] + ((fa * da) >> 2);
        if (damp) {                  /* Env Delay 0x23: darken the tail */
            comb_lp[v] += (val - comb_lp[v]) >> 4;
            val += mulsh(comb_lp[v] - val, damp, 15);
        }
        /* Feedback: (comb_g*val)>>27 == ((comb_g>>12)*(val>>11))>>4. */
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

/* The render's smoothed cutoff moves continuously; we sample it once per 32
 * frame block, which steps the SVF coefficients. Ramp the cutoff and resonance
 * indices from the previous block's values across four 8-frame sub-blocks so
 * the coefficients glide (as the stock filter does). */
static int svf_fi[8], svf_qi[8];
static int svf_have[8];

/* filter_glue.s: digifilter_dispatch remembers the a3 the render set (the
 * stock filter, or digihealth's wrapper) so stock types keep their target. */
int digifilter_disp_got;
int digifilter_disp_orig;

/* The envelope-modulated cutoff index: FREQ (params@2) plus the stock filter's
 * envelope term (params@6 * the engine's per-voice envelope level), 0..127. */
static int cutoff_index(unsigned char *params, int v)
{
    int base = (int)(unsigned)PARAM_CUTOFF(params);       /* index<<8 */
    int depth = ((int)(unsigned)PARAM_ENV(params) - 0x4000) << 17;
    if (depth) {
        int32 env = ENV_LEVEL(v);
        int32 envmod = mulsh((int32)(0u - (uint32)env), depth, 31);  /* (-env)*depth>>31 */
        base += envmod >> 16;                             /* to FREQ-word units */
    }
    return clampi(base >> 8, 0, 127);
}

static void svf_run(int m, int fi, int qi, int32 *buf, int v)
{
    int fi0 = svf_have[v] ? svf_fi[v] : fi;
    int qi0 = svf_have[v] ? svf_qi[v] : qi;
    struct fcoef c0, c1;
    int k;
    /* Compute the coefficients only at this block's start and end and ramp
     * between them (2 mode_coef calls, each with its div55) instead of
     * recomputing them at 4 ramped index points (4 calls). The coefficients
     * move smoothly with the indices, so a linear ramp is as smooth. */
    mode_coef(m, fi0, qi0, &c0);
    mode_coef(m, fi, qi, &c1);
    for (k = 0; k < 4; k++) {
        int w = k + 1;                               /* 1..4, ends exactly at c1 */
        int32 *d = (int32 *)&c0, *e = (int32 *)&c1;
        struct fcoef c;
        int32 *o = (int32 *)&c;
        int j;
        for (j = 0; j < 6; j++) {
            /* Lerp d..e by w/4 without overflowing on a large jump: split the
             * delta so no intermediate exceeds 32 bits. */
            int32 delta = e[j] - d[j];
            o[j] = d[j] + (delta >> 2) * w + (((delta & 3) * w) >> 2);
        }
        digifilter_svf(buf + 8 * k, 8, (const int32 *)&c, dsp_st[v]);
    }
    svf_fi[v] = fi;
    svf_qi[v] = qi;
    svf_have[v] = 1;
}

int digifilter_filt(unsigned char *params, int *buf, int active, int voice)
{
    /* NOTE: the stock function 0x40072844 never reads this `active` argument;
     * it is a per-voice mask from the render and is 0 in normal playback, so we
     * must not gate on it. Process whenever this voice's TYPE is ours. */
    (void)active;
    if (voice >= 0 && voice < 8) {
        int type = params[0];
        int m = type - FM_FIRST_TYPE;
        if (m >= 0 && m < FM_NMODES) {
            /* CUTOFF: params@2 (index<<8) plus the params@6 filter-envelope
             * modulation (cutoff_index), RESO: the engine's slot 0x1b — the
             * same fields the stock per-voice filter reads, so the FLTR knobs
             * and the filter envelope track. */
            int fi = cutoff_index(params, voice);
            int qi = clampi((unsigned)SET_RESO(voice) >> 11, 0, 15);
            if (prev_filt_type[voice] != type) {         /* mode change: fresh state */
                comb_init[voice] = 0;
                svf_have[voice] = 0;
                dsp_st[voice][0] = 0;
                dsp_st[voice][1] = 0;
                prev_filt_type[voice] = type;
            }
            if (m <= FM_BP2) {
                svf_run(m, fi, qi, buf, voice);
            } else {
                /* Second FLTR page (slots 0x21..0x24): delay offset, harmonics,
                 * damping, feedback trim. Defaults leave the comb unchanged. */
                int width = (int)(unsigned)PARAM_SLOT(params, FS_WIDTH);
                int dly_off = (int)(unsigned)PARAM_SLOT(params, FS_BASE) >> 8;
                int hdiv = 1 + ((32512 - width) * 3) / 32512;    /* 1..4 */
                int damp = (int)(unsigned)PARAM_SLOT(params, FS_ENVDELAY);
                int fbtrim = (int)(unsigned)PARAM_SLOT(params, FS_SRR);
                int div = (m == FM_COMB) ? 1 : 2;                /* TRASH = div 2 */
                comb_run(buf, 32, fi, qi, voice, div, dly_off, hdiv, damp, fbtrim);
            }
            return 1;
        }
    }
    ((void (*)(unsigned char *, int *, int, int))0x40072844)(params, buf, active, voice);
    return 0;
}

/* Run the extra filter on one voice's block, in place. TODO(RE): call this
 * from the site that owns the per-voice audio, with the voice index. */
void digifilter_voice(int v, int32 *buf, int frames)
{
    struct fset *s = digifilter_live;
    if (!s || !s->run || v < 0 || v >= 8 || s->mode[v] < 0)
        return;
    digifilter_svf(buf, frames, (const int32 *)&s->v[v], dsp_st[v]);
}

/* Every UI frame: pick up the pattern's settings. */
void digifilter_tick(void *ctrl)
{
    (void)ctrl;
    commit();
}

/* FLTR view knob listener. TODO(RE): needs the view kind, the current track and
 * the stock handler to chain to. Returns 0 (not taken) until then. */
int digifilter_enc(void *view, void *ev)
{
    (void)view;
    (void)ev;
    return 0;
}
