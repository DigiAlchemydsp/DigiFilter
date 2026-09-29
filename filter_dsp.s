| Digi Filter: the state-variable filter for one voice, in place.
| digifilter_svf(int32 *buf, int frames, const int32 *coef, int32 *state)
|   buf    one voice's samples (32-bit), processed in place
|   frames number of samples
|   coef   struct fcoef { a1, a2, a3, c0, c1, c2 } (filter.c), Q31, as in Digi EQ's eq_dsp.s
|   state  int32[2]: ic1, ic2 (kept between calls)
| Per sample: v3 = v0 - ic2; v1 = a1*ic1 + a2*v3; v2 = ic2 + a2*ic1 + a3*v3;
|   ic1 = 2*v1 - ic1; ic2 = 2*v2 - ic2; out = v0 + 16*(c0*v0 + c1*v1 + c2*v2).
| All registers kept; the EMAC state (MACSR, ACC0, ACCEXT01) is saved and restored.
| The caller scales the block into the working range (see eq_dsp.s); the samples
| here are expected already at 24-bit x4, the same range Digi EQ uses.

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
        move.l  %d0, %acc0                      | start from an empty accumulator
        move.l  %d0, %accext01

        movea.l 80(%sp), %a0                    | buf
        move.l  84(%sp), %d7                    | frames
        movea.l 88(%sp), %a1                    | coef
        movea.l 0(%a1), %a2                     | a1
        movea.l 4(%a1), %a3                     | a2
        movea.l 8(%a1), %a4                     | a3
        movea.l 12(%a1), %a5                    | c0
        movea.l 16(%a1), %a6                    | c1
        move.l  20(%a1), %d6                    | c2
        movea.l 92(%sp), %a1                    | state
        move.l  (%a1), %d4                      | ic1
        move.l  4(%a1), %d5                     | ic2
        move.l  %a1, 72(%sp)                    | state ptr for the write-back

        tst.l   %d7
        beq.w   .Ldone
.Ls:    move.l  (%a0), %d0                      | v0
        move.l  %d0, %d1
        sub.l   %d5, %d1                        | v3 = v0 - ic2
        mac.l   %a2, %d4, %acc0                 | a1*ic1
        mac.l   %a3, %d1, %acc0                 | a2*v3
        movclr.l %acc0, %d2                     | v1
        mac.l   %a3, %d4, %acc0                 | a2*ic1
        mac.l   %a4, %d1, %acc0                 | a3*v3
        movclr.l %acc0, %d3
        add.l   %d5, %d3                        | v2 = ic2 + ...
        move.l  %d2, %d1
        add.l   %d1, %d1
        sub.l   %d4, %d1
        move.l  %d1, %d4                        | ic1 = 2*v1 - ic1
        move.l  %d3, %d1
        add.l   %d1, %d1
        sub.l   %d5, %d1
        move.l  %d1, %d5                        | ic2 = 2*v2 - ic2
        mac.l   %a5, %d0, %acc0                 | c0*v0
        mac.l   %a6, %d2, %acc0                 | c1*v1
        mac.l   %d6, %d3, %acc0                 | c2*v2
        movclr.l %acc0, %d1
        asl.l   #4, %d1
        add.l   %d1, %d0
        move.l  %d0, (%a0)
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
