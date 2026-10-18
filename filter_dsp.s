| Digi Filter: the state-variable filter for one voice, in place.
| digifilter_svf(int32 *buf, int frames, const int32 *coef, int32 *state)
|   buf    one voice's samples (32-bit), processed in place
|   frames number of samples
|   coef   struct fcoef { a1, a2, a3, c0, c1, c2 } (filter.c), Q31, as in Digi EQ's eq_dsp.s
|   state  int32[2]: ic1, ic2 (kept between calls)
| Per sample: v3 = v0 - ic2; v1 = a1*ic1 + a2*v3; v2 = ic2 + a2*ic1 + a3*v3;
|   ic1 = 2*v1 - ic1; ic2 = 2*v2 - ic2; out = v0 + 16*(c0*v0 + c1*v1 + c2*v2).
| c2 is always 0 for this filter (a band pass), so it is not accumulated. The two
| multiplies that make v1 and the two that make v2 accumulate in ACC0 and ACC1 and
| interleave, so a movclr.l read does not stall behind a serial pair (the eMAC
| method of DSPLIBUM 2.2.1.6). All registers kept; the EMAC state (MACSR, ACC0,
| ACCEXT01) is saved and restored. The caller scales the block into the working
| range (see eq_dsp.s); the samples here are expected already at 24-bit x4, the
| same range Digi EQ uses.

        .text
        .globl  digifilter_svf
digifilter_svf:
        lea     -76(%sp), %sp
        movem.l %d0-%d7/%a0-%a6, (%sp)          | 0..59
        move.l  %macsr, %d0
        move.l  %d0, 60(%sp)
        move.l  %acc0, %d0
        move.l  %d0, 64(%sp)
        move.l  %accext01, %d0
        move.l  %d0, 68(%sp)
        move.l  #0x20, %macsr                   | signed, fractional, truncating, no saturation
        moveq   #0, %d0
        move.l  %d0, %acc0                      | start from empty accumulators
        move.l  %d0, %acc1
        move.l  %d0, %accext01

        movea.l 80(%sp), %a0                    | buf
        move.l  84(%sp), %d7                    | frames
        movea.l 88(%sp), %a1                    | coef
        movea.l 0(%a1), %a2                     | a1
        movea.l 4(%a1), %a3                     | a2
        movea.l 8(%a1), %a4                     | a3
        movea.l 12(%a1), %a5                    | c0
        movea.l 16(%a1), %a6                    | c1
        movea.l 92(%sp), %a1                    | state
        move.l  (%a1), %d4                      | ic1
        move.l  4(%a1), %d5                     | ic2
        move.l  %a1, 72(%sp)                    | state ptr for the write-back

        tst.l   %d7
        beq.w   .Ldone
        move.l  #0x08000000, %d6                | +2^27 for the output clamp (c2 was 0)
        move.l  #-134217728, %d1
        movea.l %d1, %a1                        | -2^27, for the clamp (a1 is free in the loop)
.Ls:    move.l  (%a0), %d0                      | v0
        move.l  %d0, %d1
        sub.l   %d5, %d1                        | v3 = v0 - ic2
        mac.l   %a2, %d4, %acc0                 | v1 += a1*ic1
        mac.l   %a3, %d4, %acc1                 | v2 += a2*ic1
        mac.l   %a3, %d1, %acc0                 | v1 += a2*v3
        mac.l   %a4, %d1, %acc1                 | v2 += a3*v3
        movclr.l %acc0, %d2                     | v1
        movclr.l %acc1, %d3
        add.l   %d5, %d3                        | v2 = ic2 + ...
        | band-pass output: out = v0 + 16*(c0*v0 + c1*v1)  (c2*v2 term is 0)
        mac.l   %a5, %d0, %acc0                 | c0*v0
        mac.l   %a6, %d2, %acc0                 | c1*v1
        movclr.l %acc0, %d1
        asl.l   #4, %d1
        add.l   %d1, %d0
        | ic1 = 2*v1 - ic1, ic2 = 2*v2 - ic2: v1/v2 are dead after the output, so
        | the doublings update the state in place (no copies)
        add.l   %d2, %d2
        sub.l   %d4, %d2
        move.l  %d2, %d4
        add.l   %d3, %d3
        sub.l   %d5, %d3
        move.l  %d3, %d5
        | saturate the output to +-2^27 (as the comb does): a high-Q peak clips
        | there instead of wrapping the 32-bit sample (BP distortion fix)
        cmp.l   %d6, %d0
        ble.s   .Lc1
        move.l  %d6, %d0
        bra.s   .Lc2
.Lc1:   cmp.l   %a1, %d0
        bge.s   .Lc2
        move.l  %a1, %d0
.Lc2:   move.l  %d0, (%a0)
        addq.l  #4, %a0
        subq.l  #1, %d7
        bne.b   .Ls

        movea.l 72(%sp), %a1
        move.l  %d4, (%a1)                      | ic1
        move.l  %d5, 4(%a1)                     | ic2
.Ldone:
        move.l  64(%sp), %d0
        move.l  %d0, %acc0
        move.l  68(%sp), %d0
        move.l  %d0, %accext01
        move.l  60(%sp), %d0
        move.l  %d0, %macsr
        movem.l (%sp), %d0-%d7/%a0-%a6
        lea     76(%sp), %sp
        rts

| The ramp path: one 32-frame block with the coefficients reloaded for each of the
| four 8-frame sub-blocks (svf_run lerps them in C), so the block costs one
| prologue/epilogue instead of four. Same inner loop as digifilter_svf, so the
| output is identical; c2 is 0 and omitted, and the clamp constants are immediate
| (the a-registers all hold coefficients).
| digifilter_svf4(int32 *buf, const int32 *coef4, int32 *state)
|   coef4  four struct fcoef (24 ints): frames 0-7, 8-15, 16-23, 24-31
        .balign 2
        .globl  digifilter_svf4
digifilter_svf4:
        lea     -80(%sp), %sp
        movem.l %d0-%d7/%a0-%a6, (%sp)          | 0..59
        move.l  %macsr, %d0
        move.l  %d0, 60(%sp)
        move.l  %acc0, %d0
        move.l  %d0, 64(%sp)
        move.l  %accext01, %d0
        move.l  %d0, 68(%sp)
        move.l  #0x20, %macsr                   | signed, fractional, truncating, no saturation
        moveq   #0, %d0
        move.l  %d0, %acc0
        move.l  %d0, %acc1
        move.l  %d0, %accext01

        movea.l 84(%sp), %a0                    | buf
        movea.l 88(%sp), %a1                    | coef4
        movea.l 92(%sp), %a5                    | state
        move.l  (%a5), %d4                      | ic1
        move.l  4(%a5), %d5                     | ic2
        move.l  %a5, 72(%sp)                    | state ptr for the write-back
        lea     128(%a0), %a5
        move.l  %a5, 76(%sp)                    | buf end

.L4blk: movea.l 0(%a1), %a2                     | a1
        movea.l 4(%a1), %a3                     | a2
        movea.l 8(%a1), %a4                     | a3
        movea.l 12(%a1), %a5                    | c0
        movea.l 16(%a1), %a6                    | c1
        lea     24(%a1), %a1                    | the next sub-block's set
        moveq   #8, %d7
.L4s:   move.l  (%a0), %d0                      | v0
        move.l  %d0, %d1
        sub.l   %d5, %d1                        | v3 = v0 - ic2
        mac.l   %a2, %d4, %acc0                 | v1 += a1*ic1
        mac.l   %a3, %d4, %acc1                 | v2 += a2*ic1
        mac.l   %a3, %d1, %acc0                 | v1 += a2*v3
        mac.l   %a4, %d1, %acc1                 | v2 += a3*v3
        movclr.l %acc0, %d2                     | v1
        movclr.l %acc1, %d3
        add.l   %d5, %d3                        | v2 = ic2 + ...
        mac.l   %a5, %d0, %acc0                 | c0*v0
        mac.l   %a6, %d2, %acc0                 | c1*v1
        movclr.l %acc0, %d1
        asl.l   #4, %d1
        add.l   %d1, %d0
        add.l   %d2, %d2                        | ic1 = 2*v1 - ic1
        sub.l   %d4, %d2
        move.l  %d2, %d4
        add.l   %d3, %d3                        | ic2 = 2*v2 - ic2
        sub.l   %d5, %d3
        move.l  %d3, %d5
        cmp.l   #0x08000000, %d0                | saturate the output to +-2^27
        ble.s   .L4c1
        move.l  #0x08000000, %d0
        bra.s   .L4c2
.L4c1:  cmp.l   #-134217728, %d0
        bge.s   .L4c2
        move.l  #-134217728, %d0
.L4c2:  move.l  %d0, (%a0)
        addq.l  #4, %a0
        subq.l  #1, %d7
        bne.b   .L4s
        movea.l 76(%sp), %a5
        cmpa.l  %a5, %a0
        bne.b   .L4blk

        movea.l 72(%sp), %a1
        move.l  %d4, (%a1)                      | ic1
        move.l  %d5, 4(%a1)                     | ic2
        move.l  64(%sp), %d0
        move.l  %d0, %acc0
        move.l  68(%sp), %d0
        move.l  %d0, %accext01
        move.l  60(%sp), %d0
        move.l  %d0, %macsr
        movem.l (%sp), %d0-%d7/%a0-%a6
        lea     80(%sp), %sp
        rts
