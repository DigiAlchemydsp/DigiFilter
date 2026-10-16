| DigiFilter-DN: raw site entry points (Digitone mk1, OS 1.43/1.44).
| Firmware addresses are per-OS via defsym FILTER/FMT (mod.json).
| Uses core-dn1 exports fw_voice_params/fw_voices (core 3.1) for TYPE.

        .section .run, "ax"
        .include "digitone-mk1/core3.inc"

| ---------------- TYPE label formatter -------------------------------
| mod.json points the fmt pointer (param 29 record +0x34) at this.
| Stock formatter (FMT, 0x40014b6c both versions) is called as
|   f(value<<8, char *dst) -- value at 4(%sp), dst at 8(%sp)
| and prints OFF/LP2/HP/LP4 for 0..3 (clamped). We return our names for
| 4..7 and tail-jump to stock otherwise.
        .balign 2
        .globl  digifilter_dn_typefmt
digifilter_dn_typefmt:
        move.l  4(%sp), %d0
        asr.l   #8, %d0
        cmpi.l  #4, %d0
        blt.s   .Lstock_dn
        cmpi.l  #10, %d0
        bge.s   .Lstock_dn
        subq.l  #4, %d0
        lsl.l   #3, %d0                 | 8-byte strides
        lea     digifilter_dn_names, %a0
        adda.l  %d0, %a0
        move.l  8(%sp), %a1
.Lcopy_dn:
        move.b  (%a0)+, %d1
        move.b  %d1, (%a1)+
        tst.b   %d1
        bne.s   .Lcopy_dn
        rts
.Lstock_dn:
        jmp     FMT

        .balign 8
        .globl  digifilter_dn_names
digifilter_dn_names:
        .asciz  "BP"
        .balign 8
        .asciz  "BP2"
        .balign 8
        .asciz  "COMB"
        .balign 8
        .asciz  "TRASH"
        .balign 8
        .asciz  "OB4"
        .balign 8
        .asciz  "OB2"
        .balign 8

| Value-text table with our modes appended (stock OFF/LP2/HP/LP4 via
| OFF_STR/LP2_STR/HP_STR/LP4_STR defsym per OS, ours via names above).
| The value-text delegate (max sites + table site in mod.json) uses this
| instead of the stock 4-entry table, so G shows BP/BP2/COMB/TRASH for 4..7.
        .balign 4
        .globl  digifilter_dn_types
digifilter_dn_types:
        .long   OFF_STR
        .long   LP2_STR
        .long   HP_STR
        .long   LP4_STR
        .long   digifilter_dn_names
        .long   digifilter_dn_names+8
        .long   digifilter_dn_names+16
        .long   digifilter_dn_names+24
        .long   digifilter_dn_names+32
        .long   digifilter_dn_names+40

| ---------------- per-voice filter dispatcher ------------------------
| mod.json hooks the buffer computation inside the voices' filter loop:
|   1.43 0x4009e0b2 / 1.44 0x4009e0d2: addil #0x80004110,%d0 (6 bytes)
| (buffer = fw_voices + voice*128; d0 before = voice*128, voice 0..7).
| We do that work, read the voice's TYPE from fw_voice_params (slot 54),
| point a5 at our filter for 4..7 and at FILTER (stock) otherwise, and
| stash voice/buffer for our C filter (which ignores the stock stack).
| On entry d0 = voice*128, d2 = voice (pre-inc), a3 = this voice's 16-byte
| filter block (TYPE long at +8, but we read TYPE from fw_voice_params
| instead so locks/smoothing are included as the render sees them).
| Keeps d0 (= buffer) for the caller; saves/restores d1/a0/a1.
        .balign 2
        .globl  digifilter_dn_dispatch
digifilter_dn_dispatch:
        move.l  %d1, -(%sp)
        move.l  %a0, -(%sp)
        move.l  %a1, -(%sp)
        move.l  %d0, %d1
        lsr.l   #7, %d1                 | voice 0..7
        add.l   #0x80004110, %d0        | displaced: buffer
        move.l  %d1, digifilter_dn_voice:l
        move.l  %d0, digifilter_dn_buf:l
        | TYPE from fw_voice_params: slot 54 at +18+158*v+108 = +126+158*v
        lea     fw_voice_params, %a0
        mulu.w  #158, %d1               | 158*voice (0..1106, fits 16-bit)
        adda.l  %d1, %a0
        move.w  126(%a0), %d1
        lsr.l   #8, %d1
        andi.l  #0xff, %d1              | TYPE 0..7
        cmpi.l  #4, %d1
        blt.s   .Ldn_stock
        cmpi.l  #10, %d1
        bge.s   .Ldn_stock
        lea     digifilter_dn_filt, %a5 | our TYPE: run our DSP
        bra.s   .Ldn_out
.Ldn_stock:
        lea     FILTER, %a5             | stock TYPE: original target
.Ldn_out:
        move.l  (%sp)+, %a1
        move.l  (%sp)+, %a0
        move.l  (%sp)+, %d1
        rts

        .section .bss
        .balign 4
        .globl  digifilter_dn_voice
digifilter_dn_voice:
        .skip   4
        .globl  digifilter_dn_buf
digifilter_dn_buf:
        .skip   4
