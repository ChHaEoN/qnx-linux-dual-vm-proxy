/* SPDX-License-Identifier: MIT
 *
 * contract-probe.S - the T0 payload.
 *
 * Phase 3b, results/orin-native-port/20260909T1100Z/m5-design.md §4.2 and §6.1:
 * an arm64-headered image that stands in for the kimg under QEMU, so that no
 * QNX byte ever runs there (§6.1's "No QNX byte runs in QEMU").
 *
 * It prints what the loader promised to hand over, then powers off:
 *
 *   PROBE EL=<n> X0=<hex> X1=<hex> X2=<hex> X3=<hex> MAGIC=<ok|bad>
 *         SCTLR_EL2=<hex> DAIF=<hex> PC=<hex>
 *
 * MAGIC is ok when x0 points at a flattened device tree, the same d00dfeed the
 * shim checks. PC is where this code actually landed, which is what catches a
 * loader that branched to the wrong place.
 *
 * Console: QEMU virt's PL011 at its fixed base. This payload runs only under
 * T0, never on the board, so it needs no device-tree walk to find it.
 */

	.set	PL011_BASE, 0x09000000
	.set	PL011_DR,   0x00
	.set	PL011_FR,   0x18
	.set	FR_TXFF,    (1 << 5)

	.set	PSCI_SYSTEM_OFF, 0x84000008

	.section .text.head, "ax"
	.globl	_start

/* 0x00: the arm64 image header the loader checks at its step 4. */
_start:
	b	probe_body			/* code0: entry                */
	.long	0				/* code1                       */
	.quad	0x80000				/* text_offset                 */
	.quad	PROBE_IMAGE_SIZE		/* image_size (linker script)  */
	.quad	0				/* flags: LE, 4K, anywhere     */
	.quad	0				/* res2                        */
	.quad	0				/* res3                        */
	.quad	0				/* res4                        */
	.ascii	"ARM\x64"			/* magic, offset 0x38          */
	.long	0				/* res5                        */

probe_body:
	mov	x19, x0				/* x0 as handed over           */
	mov	x20, x1
	mov	x21, x2
	mov	x22, x3
	adr	x23, _start			/* where we really landed      */

	movz	x24, #(PL011_BASE >> 16), lsl #16	/* 0x09000000          */

	adr	x1, s_probe
	bl	puts

	/* EL */
	mrs	x2, CurrentEL
	lsr	x2, x2, #2
	add	w0, w2, #'0'
	bl	putc

	adr	x1, s_x0
	bl	puts
	mov	x2, x19
	bl	puthex64
	adr	x1, s_x1
	bl	puts
	mov	x2, x20
	bl	puthex64
	adr	x1, s_x2
	bl	puts
	mov	x2, x21
	bl	puthex64
	adr	x1, s_x3
	bl	puts
	mov	x2, x22
	bl	puthex64

	/* MAGIC: is x0 a device tree? */
	adr	x1, s_magic
	bl	puts
	mov	x9, #0
	cbz	x19, 1f
	ldr	w10, [x19]
	movz	w11, #0xfeed
	movk	w11, #0xd00d, lsl #16		/* d00dfeed, big-endian on disk */
	rev	w10, w10
	cmp	w10, w11
	cset	w9, eq
1:	cbz	w9, 2f
	adr	x1, s_ok
	b	3f
2:	adr	x1, s_bad
3:	bl	puts

	adr	x1, s_sctlr
	bl	puts
	mrs	x2, sctlr_el2
	bl	puthex64

	adr	x1, s_daif
	bl	puts
	mrs	x2, daif
	bl	puthex64

	adr	x1, s_pc
	bl	puts
	mov	x2, x23
	bl	puthex64

	adr	x1, s_crlf
	bl	puts

	/* §13 decision H: ask for PSCI SYSTEM_OFF over HVC, then SMC, then park
	 * and let run-t0.ps1's timeout end the case. */
	movz	w0, #(PSCI_SYSTEM_OFF & 0xffff)
	movk	w0, #(PSCI_SYSTEM_OFF >> 16), lsl #16
	hvc	#0
	movz	w0, #(PSCI_SYSTEM_OFF & 0xffff)
	movk	w0, #(PSCI_SYSTEM_OFF >> 16), lsl #16
	smc	#0
4:	wfi
	b	4b

/* putc: w0 = byte. Bounded by the transmit-full flag, never by a spin count. */
putc:
	mov	x12, #0x10000
5:	ldr	w11, [x24, #PL011_FR]
	tbz	w11, #5, 6f
	subs	x12, x12, #1
	b.ne	5b
	ret
6:	and	w11, w0, #0xff
	str	w11, [x24, #PL011_DR]
	ret

/* puts: x1 = NUL-terminated. Returns through x28. */
puts:
	mov	x28, x30
7:	ldrb	w0, [x1], #1
	cbz	w0, 8f
	bl	putc
	b	7b
8:	ret	x28

/* puthex64: x2 = value. Returns through x27. */
puthex64:
	mov	x27, x30
	mov	x26, #60
9:	lsr	x0, x2, x26
	and	w0, w0, #0xf
	cmp	w0, #9
	b.hi	10f
	add	w0, w0, #'0'
	b	11f
10:	add	w0, w0, #('a' - 10)
11:	bl	putc
	subs	x26, x26, #4
	b.ge	9b
	ret	x27

	.section .rodata, "a"
	.align	3
s_probe:	.asciz	"\r\nPROBE EL="
s_x0:		.asciz	" X0="
s_x1:		.asciz	" X1="
s_x2:		.asciz	" X2="
s_x3:		.asciz	" X3="
s_magic:	.asciz	" MAGIC="
s_ok:		.asciz	"ok"
s_bad:		.asciz	"bad"
s_sctlr:	.asciz	" SCTLR_EL2="
s_daif:		.asciz	" DAIF="
s_pc:		.asciz	" PC="
s_crlf:		.asciz	"\r\n"
