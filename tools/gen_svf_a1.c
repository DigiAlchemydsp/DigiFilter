/* Build-time table generator for the SVF's a1 coefficient. Compiles the shared
 * DSP core's own df_mode_coef()/df_div55()/df_mulsh() (no reimplementation) and
 * fills
 *   a1table[qk][fi] = div55((1 << 24) + mulsh(g, g + K27[qk], 30)),  g = G27[fi]
 * for the 14 resonance indices qk = qi * 13 / 15 (BP) that the SVF actually uses
 * (BP2 uses qk >> 1, a subset). Driven by tools/gen_svf_a1.py; do not edit the
 * header it writes. */
#define SVF_A1_GEN 1
#include "../shared/df_dsp.c"

int a1table[14][128];

void gen(void)
{
    int qi, fi, qk;
    for (qi = 0; qi < 16; qi++) {
        qk = qi * 13 / 15;
        for (fi = 0; fi < 128; fi++) {
            struct df_coef c;
            df_mode_coef(0, fi, qi, &c);
            a1table[qk][fi] = c.a1;
        }
    }
}
