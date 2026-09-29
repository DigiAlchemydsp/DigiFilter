| Digi Filter: the raw site entry points.
| Firmware addresses are OS 1.53's (RE_NOTES.md).

        .section .run, "ax"

| ---------------- the FLTR page's type label formatter -------------------------------
| mod.json points the immediate at 0x401539b2 (stock: move.l #0x40065336,d0) at this.
| The stock formatter is called with its arguments as
|   (?, value<<8, char *dst)   -- value at 8(%sp), dst at 0xc(%sp)
| and prints "OFF"/"LP"/"HP" for values 0..2 and "EQ:%d" (value-2) for 3..7.
| We return our mode names for TYPE 8..11 and pass everything else to the stock
| formatter untouched.
        .balign 2
        .globl  digifilter_typefmt
digifilter_typefmt:
        move.l  8(%sp), %d0
        asr.l   #8, %d0
        cmpi.l  #8, %d0
        blt.s   .Lstock
        cmpi.l  #12, %d0
        bge.s   .Lstock
        subq.l  #8, %d0
        lsl.l   #3, %d0                 | 8-byte strides
        lea     nf_names, %a0
        adda.l  %d0, %a0
        move.l  0xc(%sp), %a1
.Lcopy: move.b  (%a0)+, %d1
        move.b  %d1, (%a1)+
        tst.b   %d1
        bne.s   .Lcopy
        rts
.Lstock:
        jmp     0x40065336

        .balign 8
nf_names:
        .asciz  "BP"
        .balign 8
        .asciz  "BP2"
        .balign 8
        .asciz  "COMB"
        .balign 8
        .asciz  "TRASH"
        .balign 8

| The per-voice filter call dispatcher.
|
| The render loops voices calling the per-voice filter through a3; a3 is set
| once before the loop by "lea <filter>,%a3" at 0x400780a4. digihealth 1.0
| rewrites that instruction for its profiling wrapper, so we must not touch it.
| Instead mod.json hooks the free 6-byte instruction just before the call,
|        0x400780ba   add.l #0x80001a18,%d0     (buffer = 0x80001a18 + voice*0x80)
| with a jsr here. We do that instruction's work, then, in the loop each voice,
| point a3 at our filter only for our TYPE values (8..11); for stock types we
| restore the original a3 (digihealth's wrapper, or the stock function), so
| digihealth keeps working. On entry d3 = this voice's params (byte 0 = TYPE),
| d0 = voice<<7.
        .balign 2
        .globl  digifilter_dispatch
digifilter_dispatch:
        move.l  %d1, -(%sp)                     | scratch regs we clobber
        move.l  %a1, -(%sp)
        add.l   #0x80001a18, %d0                | the displaced instruction
        tst.l   digifilter_disp_got:l
        bne.s   .Ldisp_have
        move.l  %a3, digifilter_disp_orig:l     | remember the stock/digihealth target
        move.l  #1, %d1
        move.l  %d1, digifilter_disp_got:l
.Ldisp_have:
        move.l  %d3, %a1
        move.b  (%a1), %d1
        cmpi.b  #8, %d1
        blt.s   .Ldisp_stock
        cmpi.b  #12, %d1
        bge.s   .Ldisp_stock
        lea     digifilter_filt, %a3            | our TYPE: run our filter (filter.c)
        bra.s   .Ldisp_out
.Ldisp_stock:
        move.l  digifilter_disp_orig:l, %a3     | stock TYPE: the original target
.Ldisp_out:
        move.l  (%sp)+, %a1
        move.l  (%sp)+, %d1
        rts
