/* The OB-1 filter modes, TYPE 12 and 13 (filter.c's digifilter_filt): the Oberheim OB-1's VCF as a
 * 4-pole ladder, output from stage 4 (OB4) or stage 2 (OB2). See tests/ob1_model.py (the reference) and
 * docs/ob1.md. */
#ifndef OB1_VCF_H
#define OB1_VCF_H

#define OB1_TAP4    4           /* OB4: the 4-pole output */
#define OB1_TAP2    2           /* OB2: stage 2, the loop still closed from stage 4 */
#define OB1_LINEAR  0x100       /* or'ed into tap: no saturation (for the tests against the linear model) */

/* One 32-sample block of voice v (0..7) in place: fi8 the cutoff index in 8.8 (0..127 << 8, cubic frequency
 * curve), qi RESO 0..127; the coefficients ramp from the last block's. Output at x 0.25, as every stock TYPE. */
void ob1_vcf_run(int tap, int fi8, int qi, int *buf, int v);

/* Forget voice v's state and its last coefficients (a new note need not: the OB-1's filter runs on). */
void ob1_vcf_reset(int v);

#endif
