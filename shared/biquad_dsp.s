| Four independent RBJ band-pass biquads in transposed direct form II, one
| eMAC accumulator per band. b0/b2/n2 are Q31, n1 = -a1 is Q30 (it can reach
| +-2), samples/state Q27. One `mac.l` on a Q31 coefficient gives Q27; n1 is
| applied twice, which is the same Q27 product.
|
| Memory layout (coef):
|   band 0: b0  0, b2  4, n1  8, n2 12
|   band 1:    16,    20,    24,    28
|   band 2:    32,    36,    40,    44
|   band 3:    48,    52,    56,    60
| state: z1[0..3] at 0,4,8,12; z2[0..3] at 16,20,24,28
|
| digifilter_biq(buf, coef, state)      one 32-frame block, one coefficient set
| digifilter_biq4(buf, coef4, state)    four 8-frame sub-blocks; coef4 is
|                                        four sets of the 64 bytes above

        .text

| The per-sample body. Uses d0-d7, a0 (buf), a1 (coef), a2 (state), a3 (the
| fourth lane); leaves a4/a5/a6 to the loop.
        .macro BIQ_SAMPLE
        move.l  (%a0), %d4                      | x

        | y = b0*x + z1
        move.l  0(%a2), %d0
        move.l  4(%a2), %d1
        move.l  8(%a2), %d2
        move.l  12(%a2), %d3
        move.l  %d0, %acc0
        move.l  %d1, %acc1
        move.l  %d2, %acc2
        move.l  %d3, %acc3
        move.l  0(%a1), %d5
        move.l  16(%a1), %d6
        move.l  32(%a1), %d7
        move.l  48(%a1), %a3
        mac.l   %d5, %d4, %acc0
        mac.l   %d6, %d4, %acc1
        mac.l   %d7, %d4, %acc2
        mac.l   %a3, %d4, %acc3
        movclr.l %acc0, %d0
        movclr.l %acc1, %d1
        movclr.l %acc2, %d2
        movclr.l %acc3, %d3                     | y[0..3]

        | z1' = n1*y + z2
        move.l  16(%a2), %d5
        move.l  20(%a2), %d6
        move.l  24(%a2), %d7
        move.l  28(%a2), %a3
        move.l  %d5, %acc0
        move.l  %d6, %acc1
        move.l  %d7, %acc2
        move.l  %a3, %acc3
        move.l  8(%a1), %d5
        move.l  24(%a1), %d6
        move.l  40(%a1), %d7
        move.l  56(%a1), %a3
        mac.l   %d5, %d0, %acc0
        mac.l   %d5, %d0, %acc0                 | n1 is Q30: two MACs = one Q27 product
        mac.l   %d6, %d1, %acc1
        mac.l   %d6, %d1, %acc1
        mac.l   %d7, %d2, %acc2
        mac.l   %d7, %d2, %acc2
        mac.l   %a3, %d3, %acc3
        mac.l   %a3, %d3, %acc3
        movclr.l %acc0, %d5
        movclr.l %acc1, %d6
        movclr.l %acc2, %d7
        movclr.l %acc3, %a3
        move.l  %d5, 0(%a2)
        move.l  %d6, 4(%a2)
        move.l  %d7, 8(%a2)
        move.l  %a3, 12(%a2)

        | z2' = b2*x + n2*y
        moveq   #0, %d5
        move.l  %d5, %acc0
        move.l  %d5, %acc1
        move.l  %d5, %acc2
        move.l  %d5, %acc3
        move.l  4(%a1), %d5
        move.l  20(%a1), %d6
        move.l  36(%a1), %d7
        move.l  52(%a1), %a3
        mac.l   %d5, %d4, %acc0
        mac.l   %d6, %d4, %acc1
        mac.l   %d7, %d4, %acc2
        mac.l   %a3, %d4, %acc3
        move.l  12(%a1), %d5
        move.l  28(%a1), %d6
        move.l  44(%a1), %d7
        move.l  60(%a1), %a3
        mac.l   %d5, %d0, %acc0
        mac.l   %d6, %d1, %acc1
        mac.l   %d7, %d2, %acc2
        mac.l   %a3, %d3, %acc3
        movclr.l %acc0, %d5
        movclr.l %acc1, %d6
        movclr.l %acc2, %d7
        movclr.l %acc3, %a3
        move.l  %d5, 16(%a2)
        move.l  %d6, 20(%a2)
        move.l  %d7, 24(%a2)
        move.l  %a3, 28(%a2)

        | sum the (already gained) bands and saturate
        add.l   %d1, %d0
        add.l   %d2, %d0
        add.l   %d3, %d0
        cmp.l   #0x08000000, %d0
        ble.s   1f
        move.l  #0x08000000, %d0
        bra.s   2f
1:      cmp.l   #-134217728, %d0
        bge.s   2f
        move.l  #-134217728, %d0
2:      move.l  %d0, (%a0)+
        .endm

        .macro BIQ_PROLOGUE
        lea     -88(%sp), %sp
        movem.l %d0-%d7/%a0-%a6, (%sp)
        move.l  %macsr, %d0
        move.l  %d0, 60(%sp)
        move.l  %acc0, %d0
        move.l  %d0, 64(%sp)
        move.l  %acc1, %d0
        move.l  %d0, 68(%sp)
        move.l  %acc2, %d0
        move.l  %d0, 72(%sp)
        move.l  %acc3, %d0
        move.l  %d0, 76(%sp)
        move.l  %accext01, %d0
        move.l  %d0, 80(%sp)
        move.l  %accext23, %d0
        move.l  %d0, 84(%sp)
        move.l  #0x20, %macsr
        moveq   #0, %d0
        move.l  %d0, %acc0
        move.l  %d0, %acc1
        move.l  %d0, %acc2
        move.l  %d0, %acc3
        move.l  %d0, %accext01
        move.l  %d0, %accext23
        movea.l 92(%sp), %a0
        movea.l 96(%sp), %a1
        movea.l 100(%sp), %a2
        .endm

        .macro BIQ_EPILOGUE
        move.l  64(%sp), %d0
        move.l  %d0, %acc0
        move.l  68(%sp), %d0
        move.l  %d0, %acc1
        move.l  72(%sp), %d0
        move.l  %d0, %acc2
        move.l  76(%sp), %d0
        move.l  %d0, %acc3
        move.l  80(%sp), %d0
        move.l  %d0, %accext01
        move.l  84(%sp), %d0
        move.l  %d0, %accext23
        move.l  60(%sp), %d0
        move.l  %d0, %macsr
        movem.l (%sp), %d0-%d7/%a0-%a6
        lea     88(%sp), %sp
        rts
        .endm

        .balign 2
        .globl  digifilter_biq
digifilter_biq:
        BIQ_PROLOGUE
        movea.l #32, %a5
.Lbs:   BIQ_SAMPLE
        subq.l  #1, %a5
        tst.l   %a5
        bne.w   .Lbs
        BIQ_EPILOGUE

        .balign 2
        .globl  digifilter_biq4
digifilter_biq4:
        BIQ_PROLOGUE
        movea.l #4, %a4
.Lbo:   movea.l #8, %a5
.Lbi:   BIQ_SAMPLE
        subq.l  #1, %a5
        tst.l   %a5
        bne.w   .Lbi
        lea     64(%a1), %a1
        subq.l  #1, %a4
        tst.l   %a4
        bne.w   .Lbo
        BIQ_EPILOGUE
