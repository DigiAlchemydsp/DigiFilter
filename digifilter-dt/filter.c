/* Digi Filter: extra per-track filter modes for the Digitakt mk1 (OS 1.54).
 *
 * The stock filter keeps running for every stock TYPE value: nothing here
 * reimplements a stock mode, so stock sounds are untouched. TYPE values above
 * the stock range (FM_FIRST_TYPE + mode) select an extra mode. BP/BP2 run a
 * trapezoidal state-variable filter (Simper / Zavalishin, the same kernel as
 * Digi EQ's eq_dsp.s) with the track's own FREQ, RESO and filter envelope;
 * COMB/TRASH run a feedback comb: the RESO/GAIN knob is the comb feedback, and
 * the second FLTR page's free encoders C / G add Harmonics / Damping
 * (filter_ui.c commandeers unused descriptors for them), alongside the stock
 * Base / Width / Env Delay / SRR knobs, which keep working. Those two values
 * live in spare sound slots (0x2f/0x30).
 *
 * The filter envelope (FLTR slot 0x1c, params@6) is applied exactly as the
 * stock filter does (see cutoff_index): the engine writes a per-voice envelope
 * level at 0x4199df58 + v*12, and the modulated cutoff is
 *   (FREQ<<16) + (((-env) * ((ENVword-0x4000)<<17)) >> 31).
 *
 * DSP lives in ../shared/df_dsp.c (firmware-free, shared with the Digitone
 * port): this file is the Digitakt adapter (kit slots, envelope, dispatch).
 *
 * The FLTR page's FREQ/RES response *curve* and TYPE-box icon are drawn by
 * filter_ui.c, from a core ev_draw handler (digifilter_draw) for TYPE 8..13.
 * See RE_NOTES.md.
 */

/* ---- firmware addresses (OS 1.54) ---- */
#define F_4199dc44 0x4199ec44
#define F_4199df58 0x4199ef58
/* ---- end of the firmware addresses ---- */

#include "../shared/df_dsp.h"
#include "../shared/ob1_vcf.h"

/* ---- firmware (OS 1.54) ---- */
#define UI_KIT (*(unsigned char *volatile *)F_4199dc44)  /* the kit of the pattern being edited */

/* a track's sound block in the kit: 0xa2 bytes at kit + 0x20 + t*0xa2, the 53
 * parameter slots as words at +0x14 + 2*s (TECHNICAL_NOTES, v3e). */
#define SOUND(kit, t)   ((kit) + 0x20 + (t) * 0xa2)
#define FSLOT(kit, t, s) ((int)(*(unsigned short *)(SOUND(kit, t) + 0x14 + 2 * (s))))

/* Confirmed from the filter parameter descriptors at 0x401aa3b4.. (OS 1.54):
 *   Frequency  slot 0x1a  long "Frequency"  short "FREQ"  CC 74
 *   Resonance  slot 0x1b  long "Resonance"  short "RESO"  CC 75
 *   FilterType slot 0x19  long "Filter Type" short "TYPE" CC 76  (display max 7)
 *   Env Depth 0x1c, Attack 0x1d, Decay 0x1e, Sustain 0x1f, Release 0x20,
 *   Base 0x21, Width 0x22, Env Delay 0x23, SRR 0x24. */
#define FS_TYPE 0x19
#define FS_FREQ 0x1a
#define FS_RESO 0x1b
/* COMB/TRASH second-page storage: two spare sound slots, driven by the free
 * encoders C/G (filter_ui.c commandeers unused descriptors for them). The
 * stock Base/Width/Env Delay/SRR slots are left to their own controls, and the
 * comb feedback is the RESO/GAIN knob (slot 0x1b) itself. */
#define FS_HARM 0x2f            /* C: harmonics (delay divider 1..4) */
#define FS_DAMP 0x30            /* G: damping on the feedback */

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
/* The OB-1 modes (ob1_vcf.c, docs/ob1.md) after ours: TYPE 12 OB4, 13 OB2. Kept out of FM_NMODES, so the SVF and
 * comb code never sees them. */
#define OB_FIRST_TYPE  (FM_FIRST_TYPE + FM_NMODES)
#define OB_NTYPES      2

/* ---- the coefficient set the DSP reads (filter_dsp.s) ---- */
struct fset { int32 run; int32 mode[8]; struct df_coef v[8]; };
static struct fset sets[2];
static int cur;
struct fset *digifilter_live;                       /* one 32-bit store switches the audio side */
static int32 voice_st[8][2];                        /* legacy digifilter_voice path only */
static int prev_mode[8] = { -1, -1, -1, -1, -1, -1, -1, -1 };

extern void digifilter_svf(int32 *buf, int frames, const int32 *coef, int32 *state);

/* rebuild the set from the pattern's kit; called each UI frame (cheap: 8 voices) */
static void commit(void)
{
    struct fset *s = &sets[cur ^ 1];
    unsigned char *kit = UI_KIT;
    int t, run = 0;
    for (t = 0; t < 8; t++) {
        struct df_coef *c = &s->v[t];
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
        fi = df_clampi((unsigned)FSLOT(kit, t, FS_FREQ) >> 8, 0, 127);
        qi = df_clampi((unsigned)FSLOT(kit, t, FS_RESO) >> 8, 0, 15);
        df_mode_coef(m, fi, qi, c);
        s->mode[t] = m;
        run = 1;
    }
    s->run = run;
    cur ^= 1;
    digifilter_live = s;
    for (t = 0; t < 8; t++)
        if (s->mode[t] != prev_mode[t]) {           /* a mode change restarts the filter */
            voice_st[t][0] = 0;
            voice_st[t][1] = 0;
            prev_mode[t] = s->mode[t];
        }
}

/* Best-effort kit persistence for the new comb controls. The two values live in
 * the spare sound slots 0x2f/0x30, which the sound serializer (a permutation of
 * the 46 savable slots 0..45) does not carry. So we also mirror each value
 * (0..127, stored as value+1 so 0 means "empty") into the low byte of two
 * savable filter words we keep — Base (0x21), Width (0x22) — whose low byte is
 * otherwise always 0. A loaded kit restores the spare slots from those low
 * bytes. The stock high bytes are untouched. */
static void df_persist(void)
{
    unsigned char *kit = UI_KIT;
    static const int spare[2] = { FS_HARM, FS_DAMP };
    static const int donor[2] = { 0x21, 0x22 };
    int t, i;
    if (!kit)
        return;
    for (t = 0; t < 8; t++) {
        unsigned char *b = SOUND(kit, t) + 0x14;
        for (i = 0; i < 2; i++) {
            volatile unsigned short *sp = (volatile unsigned short *)(b + 2 * spare[i]);
            volatile unsigned short *dc = (volatile unsigned short *)(b + 2 * donor[i]);
            unsigned v = *sp >> 8;
            unsigned lo = *dc & 0xff;
            if (v == 0 && lo != 0)
                *sp = (unsigned short)((lo - 1) << 8);            /* after a kit load */
            else if (lo != v + 1)
                *dc = (unsigned short)((*dc & 0xff00) | (v + 1)); /* keep it saved */
        }
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
#define ENV_LEVEL(v) (*(volatile int *)(F_4199df58 + 12 * (v)))

/* Every sound slot is a word in the render record; slot s is at
 * params + 2s - 0x32 (TYPE s=0x19 is at +0; FREQ 0x1a at +2; ...; the second
 * FLTR page's Base/Width/Env Delay/SRR slots 0x21..0x24 are at +0x10..+0x16).
 * Verified live: turning the second-page knobs moves these words. */
#define PARAM_SLOT(params, s) (*(volatile unsigned short *)((params) + 2 * (s) - 0x32))

/* ---- COMB second FLTR page ----
 * The comb feedback is the RESO/GAIN knob on page 1 (slot 0x1b): it combines
 * the stock resonance/gain control and the comb feedback, 0..127. On the
 * second FLTR page filter_ui.c commandeers two unused descriptors for Harmonics
 * / Damping on the free C/G encoders, leaving the stock Base/Width/Env Delay/
 * SRR knobs untouched. The DSP reads those two spare sound slots:
 *   Harmonics 0x2f (C)  0..127 -> delay divider 1 + h*3/127 (1..4)
 *   Damping   0x30 (G)  raw word -> one-pole on the feedback (0 = off)
 * Their defaults (0) leave the plain comb. */

/* Reset shared DSP state when the mode changes (df_dsp.c holds the state). */
static int prev_filt_type[8];        /* zero-initialised: first block resets */

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
        int32 envmod = df_mulsh((int32)(0u - (uint32)env), depth, 31);
        base += envmod >> 16;                             /* to FREQ-word units */
    }
    return df_clampi(base >> 8, 0, 127);
}

/* cutoff_index() without the rounding: 8.8, 0..127 << 8, for the OB-1 modes' fractional cutoff */
static int cutoff_index8(unsigned char *params, int v)
{
    int base = (int)(unsigned)PARAM_CUTOFF(params);       /* index<<8 */
    int depth = ((int)(unsigned)PARAM_ENV(params) - 0x4000) << 17;
    if (depth) {
        int32 env = ENV_LEVEL(v);
        int32 envmod = df_mulsh((int32)(0u - (uint32)env), depth, 31);
        base += envmod >> 16;                             /* to FREQ-word units */
    }
    return df_clampi(base, 0, 127 << 8);
}

int digifilter_filt(unsigned char *params, int *buf, int active, int voice)
{
    /* NOTE: the stock function 0x40072844 never reads this `active` argument;
     * it is a per-voice mask from the render and is 0 in normal playback, so we
     * must not gate on it. Process whenever this voice's TYPE is ours. */
    (void)active;
    if (voice >= 0 && voice < 8) {
        int type = params[0];
        int m = type - FM_FIRST_TYPE, ob = type - OB_FIRST_TYPE;
        if (ob >= 0 && ob < OB_NTYPES) {
            /* OB4/OB2: the same cutoff (FREQ + the filter envelope) and RESO (0..127) as the combs read */
            if (prev_filt_type[voice] != type) {
                if (prev_filt_type[voice] < OB_FIRST_TYPE)
                    ob1_vcf_reset(voice);
                prev_filt_type[voice] = type;
            }
            ob1_vcf_run(ob ? OB1_TAP2 : OB1_TAP4, cutoff_index8(params, voice),
                        ob1_reso_depth((int)(unsigned)SET_RESO(voice) >> 8), buf, voice);
            return 1;
        }
        if (m >= 0 && m < FM_NMODES) {
            /* CUTOFF: params@2 (index<<8) plus the params@6 filter-envelope
             * modulation (cutoff_index), RESO: the engine's slot 0x1b — the
             * same fields the stock per-voice filter reads, so the FLTR knobs
             * and the filter envelope track. */
            int fi = cutoff_index(params, voice);
            int qi = (unsigned)SET_RESO(voice) >> 11;
            if (qi > 15)
                qi = 15;
            if (prev_filt_type[voice] != type) {
                df_reset(voice);
                prev_filt_type[voice] = type;
            }
            if (m <= FM_BP2) {
                df_svf_run(m, fi, qi, buf, voice);
            } else {
                /* Comb feedback is the RESO/GAIN knob (engine slot 0x1b, 0..127);
                 * C/G on the second FLTR page add Harmonics / Damping. */
                int fb = (int)(unsigned)SET_RESO(voice) >> 8;
                int harm = (int)(unsigned)PARAM_SLOT(params, FS_HARM) >> 8;
                int damp = (int)(unsigned)PARAM_SLOT(params, FS_DAMP);
                int hdiv, div;
                if (fb > 127)
                    fb = 127;
                if (harm > 127)
                    harm = 127;
                if (damp > 0x7f00)
                    damp = 0x7f00;
                hdiv = 1 + harm * 3 / 127;
                div = (m == FM_COMB) ? 1 : 2;
                df_comb_run(buf, 32, fi, fb, voice, div, hdiv, damp);
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
    digifilter_svf(buf, frames, (const int32 *)&s->v[v], voice_st[v]);
}

/* filter_ui.c: re-map the second FLTR page (kind 7) for COMB/TRASH. */
extern void digifilter_page2_sync(void);

/* Every UI frame: pick up the pattern's settings and keep the second FLTR
 * page's controls (the free C/G encoders) in step with the active track. */
void digifilter_tick(void *ctrl)
{
    (void)ctrl;
    commit();
    digifilter_page2_sync();
    df_persist();
}
