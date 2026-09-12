/* SPDX-License-Identifier: MIT
 *
 * m5load-head.S - M5LOAD.EFI's PE headers, entry, exception table, post-exit
 * console writers and the trampoline that takes the CPU and branches.
 *
 * Phase 3b, results/orin-native-port/20260909T1100Z/m5-design.md sections 3.3
 * (steps 11-14), 3.4 (the PE layout and the gate), 13 decision C (the post-exit
 * console comes from the device tree) and 13 decision L (two sections).
 *
 * Two sections, not one: the first T0b run faulted on `str x20, [x19, #512]`,
 * the first write to an in-image static, because the firmware maps a section's
 * pages from its characteristics and our single read-write-execute section came
 * out non-writable. Code is read and execute; the statics and the payload live
 * in a data section that is read and write, with no execute.
 *
 * Nothing here is copied from Linux's arm64 header or from edk2. The PE header
 * is written from the PE/COFF specification; the TCU writer follows our own
 * shim (shim/t234-shim.S), which is where the mailbox protocol and its deadline
 * come from.
 *
 * Position independence is a hard requirement (section 3.4 item 6): every
 * reference below is PC-relative, and the header's computed fields come from
 * m5load.lds as ready-made RVAs and sizes, because GNU as cannot subtract a
 * linker-script symbol at assembly time.
 */

	.set	PE_SECTION_ALIGN,  0x1000
	.set	PE_FILE_ALIGN,     0x1000
	.set	PE_HEADERS_SIZE,   0x1000

	/* Section characteristics, PE/COFF. */
	.set	SCN_CNT_CODE,      0x00000020
	.set	SCN_CNT_INIT_DATA, 0x00000040
	.set	SCN_MEM_EXECUTE,   0x20000000
	.set	SCN_MEM_READ,      0x40000000
	.set	SCN_MEM_WRITE,     0x80000000

	/* Post-exit console kinds, shared with m5load.c. */
	.set	CON_NONE,  0
	.set	CON_TCU,   1
	.set	CON_PL011, 2

	/* Trampoline modes. */
	.set	MODE_JUMP,     0
	.set	MODE_EBS_FAIL, 1

	/* PSCI function ids (SMC Calling Convention, 32-bit ids). They are
	 * built from masked halves: :lo12: is for add and ldr, never movz. */
	.set	PSCI_SYSTEM_OFF,   0x84000008
	.set	PSCI_SYSTEM_RESET, 0x84000009

/* ------------------------------------------------------------------ *
 * .head - the DOS and PE headers.  SizeOfHeaders is 0x1000, so this
 * whole section is the first page of the file and of the image, and
 * file offsets equal RVAs from here on.
 * ------------------------------------------------------------------ */
	.section .head, "a"
	.align	12
m5_dos_header:
	.ascii	"MZ"
	.fill	0x3a, 1, 0			/* to e_lfanew at 0x3c          */
	.long	m5_pe_header - m5_dos_header	/* 0x40                         */

m5_pe_header:
	.ascii	"PE\0\0"

	/* COFF header, 20 bytes. */
	.short	0xaa64				/* Machine: AArch64             */
	.short	2				/* NumberOfSections: text, data */
	.long	0				/* TimeDateStamp                */
	.long	0				/* PointerToSymbolTable         */
	.long	0				/* NumberOfSymbols              */
	.short	m5_dirs_end - m5_opt_header	/* SizeOfOptionalHeader = 0xa0  */
	.short	0x0206				/* EXECUTABLE | LINE_NUMS_STRIPPED
						 * | DEBUG_STRIPPED.  Never
						 * RELOCS_STRIPPED (gate item 2) */

m5_opt_header:
	/* PE32+ standard fields. */
	.short	0x020b				/* Magic: PE32+                 */
	.byte	0				/* MajorLinkerVersion           */
	.byte	0				/* MinorLinkerVersion           */
	.long	PE_SIZE_OF_CODE			/* SizeOfCode (from m5load.lds) */
	.long	PE_SIZE_OF_DATA			/* SizeOfInitializedData        */
	.long	0				/* SizeOfUninitializedData      */
	.long	PE_ENTRY_RVA			/* AddressOfEntryPoint          */
	.long	PE_TEXT_RVA			/* BaseOfCode                   */

	/* PE32+ Windows-specific fields. */
	.quad	0				/* ImageBase: 0 (gate item 2)   */
	.long	PE_SECTION_ALIGN		/* SectionAlignment             */
	.long	PE_FILE_ALIGN			/* FileAlignment                */
	.short	0				/* MajorOperatingSystemVersion  */
	.short	0				/* MinorOperatingSystemVersion  */
	.short	0				/* MajorImageVersion            */
	.short	0				/* MinorImageVersion            */
	.short	0				/* MajorSubsystemVersion        */
	.short	0				/* MinorSubsystemVersion        */
	.long	0				/* Win32VersionValue            */
	.long	PE_SIZE_OF_IMAGE		/* SizeOfImage                  */
	.long	PE_HEADERS_SIZE			/* SizeOfHeaders                */
	.long	0				/* CheckSum: unused by edk2     */
	.short	10				/* Subsystem: EFI application   */
	.short	0				/* DllCharacteristics           */
	.quad	0				/* SizeOfStackReserve           */
	.quad	0				/* SizeOfStackCommit            */
	.quad	0				/* SizeOfHeapReserve            */
	.quad	0				/* SizeOfHeapCommit             */
	.long	0				/* LoaderFlags                  */
	.long	6				/* NumberOfRvaAndSizes          */

	/* Six data directories, every one zero (gate item 5). */
	.quad	0, 0, 0
	.quad	0, 0, 0
m5_dirs_end:

	/* Section 1: code. Read and execute, never writable - a writable code
	 * section is what the firmware refused to map writable at all. */
	.ascii	".text\0\0\0"
	.long	PE_TEXT_VSIZE			/* VirtualSize                  */
	.long	PE_TEXT_RVA			/* VirtualAddress               */
	.long	PE_TEXT_VSIZE			/* SizeOfRawData                */
	.long	PE_TEXT_RVA			/* PointerToRawData             */
	.long	0				/* PointerToRelocations         */
	.long	0				/* PointerToLinenumbers         */
	.short	0				/* NumberOfRelocations          */
	.short	0				/* NumberOfLinenumbers          */
	.long	SCN_CNT_CODE | SCN_MEM_EXECUTE | SCN_MEM_READ

	/* Section 2: data. The writable statics and the embedded payload.
	 * Read and write, never executable. */
	.ascii	".data\0\0\0"
	.long	PE_DATA_VSIZE			/* VirtualSize                  */
	.long	PE_DATA_RVA			/* VirtualAddress               */
	.long	PE_DATA_VSIZE			/* SizeOfRawData                */
	.long	PE_DATA_RVA			/* PointerToRawData             */
	.long	0				/* PointerToRelocations         */
	.long	0				/* PointerToLinenumbers         */
	.short	0				/* NumberOfRelocations          */
	.short	0				/* NumberOfLinenumbers          */
	.long	SCN_CNT_INIT_DATA | SCN_MEM_READ | SCN_MEM_WRITE

/* ------------------------------------------------------------------ *
 * The entry the firmware calls: x0 = ImageHandle, x1 = SystemTable,
 * AAPCS64 (the AArch64 UEFI binding), on a stack the firmware owns.
 * ------------------------------------------------------------------ */
	.section .text.entry, "ax"
	.globl	m5_entry
m5_entry:
	b	m5_main				/* returns EFI_STATUS in x0     */

	.section .text, "ax"

/* ------------------------------------------------------------------ *
 * Post-exit console.  Both writers live in both builds, so the T0 and
 * board images still differ only in the blob (section 3.4 item 8).
 * The base and the kind are latched in .pool before the exit, so the
 * exception handlers can print without arguments.
 * ------------------------------------------------------------------ */
	.globl	m5_con_latch
/* void m5_con_latch(unsigned long base, unsigned long kind) */
m5_con_latch:
	adr	x9, m5_con_base
	str	x0, [x9]
	str	x1, [x9, #8]
	ret

/* putc: w0 = byte.  Clobbers x9-x15.  Never faults on CON_NONE. */
m5_putc:
	adr	x9, m5_con_base
	ldr	x10, [x9]			/* base                         */
	ldr	x11, [x9, #8]			/* kind                         */
	cmp	x11, #CON_TCU
	b.eq	m5_putc_tcu
	cmp	x11, #CON_PL011
	b.eq	m5_putc_pl011
	ret					/* CON_NONE: drop it            */

/* TCU TX mailbox, the AON HSP shared mailbox the shim uses.  Bit 31 set
 * means the SPE has not drained the last byte; wait, but only to a real
 * deadline read off the system counter, never an instruction count. */
m5_putc_tcu:
	mrs	x13, cntfrq_el0
	lsr	x13, x13, #6			/* about 15 ms                  */
	mrs	x14, cntpct_el0
	add	x13, x13, x14
1:	ldr	w11, [x10]
	tbz	w11, #31, 2f
	mrs	x14, cntpct_el0
	cmp	x14, x13
	b.lo	1b
	ret					/* not draining: drop the byte  */
2:	and	w11, w0, #0xff
	movz	w12, #0x8500, lsl #16		/* FULL | Flush | count = 1     */
	orr	w11, w11, w12
	str	w11, [x10]
	ret

/* PL011: FR at +0x18, TXFF is bit 5; DR at +0x00.  QEMU's virt board
 * only, reached when the device tree is not Tegra (section 13 C). */
m5_putc_pl011:
	mrs	x13, cntfrq_el0
	lsr	x13, x13, #6
	mrs	x14, cntpct_el0
	add	x13, x13, x14
3:	ldr	w11, [x10, #0x18]
	tbz	w11, #5, 4f
	mrs	x14, cntpct_el0
	cmp	x14, x13
	b.lo	3b
	ret
4:	and	w11, w0, #0xff
	str	w11, [x10]
	ret

/* puts: x1 = NUL-terminated string.  Returns through x28. */
m5_puts:
	mov	x28, x30
5:	ldrb	w0, [x1], #1
	cbz	w0, 6f
	bl	m5_putc
	b	5b
6:	ret	x28

/* puthex64: x2 = value, sixteen nibbles.  Returns through x27. */
m5_puthex64:
	mov	x27, x30
	mov	x26, #60
7:	lsr	x0, x2, x26
	and	w0, w0, #0xf
	cmp	w0, #9
	b.hi	8f
	add	w0, w0, #'0'
	b	9f
8:	add	w0, w0, #('a' - 10)
9:	bl	m5_putc
	subs	x26, x26, #4
	b.ge	7b
	ret	x27

/* ------------------------------------------------------------------ *
 * The trampoline.  The gate disassembles exactly this symbol range and
 * requires, in order: the dc civac loop, dsb sy, ic iallu, dsb sy, isb,
 * the sctlr_el2 write, isb, then the branch (section 3.4 item 9).  It
 * never disassembles anything else, and never the blob.
 *
 * void m5_tramp(x0 = target, x1 = image_size, x2 = fdt, x3 = mode)
 * The console is already latched.  Does not return.
 * ------------------------------------------------------------------ */
	.globl	m5_tramp_start
	.globl	m5_tramp
	.globl	m5_tramp_end
	.align	6
m5_tramp_start:
m5_tramp:
	mov	x19, x0				/* target                       */
	mov	x20, x1				/* image_size                   */
	mov	x21, x2				/* fdt                          */
	mov	x22, x3				/* mode                         */

	/* Step 11: take the CPU.  Interrupts stay masked from here on, and
	 * every fault lands in our own table, which prints and resets. */
	msr	daifset, #0xf
	adr	x9, m5_vectors
	msr	vbar_el2, x9
	isb

	/* Step 12(a): clean and invalidate the copied image and this
	 * trampoline, stepping by the data-cache line size in CTR_EL0.
	 * The image was written as data and is about to be fetched as code. */
	mrs	x9, ctr_el0
	ubfx	x9, x9, #16, #4			/* DminLine, in words           */
	mov	x10, #4
	lsl	x10, x10, x9			/* line size in bytes           */

	mov	x11, x19
	add	x12, x19, x20
10:	dc	civac, x11
	add	x11, x11, x10
	cmp	x11, x12
	b.lo	10b

	adr	x11, m5_tramp_start
	adr	x12, m5_tramp_end
	bic	x11, x11, #63
11:	dc	civac, x11
	add	x11, x11, x10
	cmp	x11, x12
	b.lo	11b

	dsb	sy

	/* Step 12(b): no stale instruction-cache line may cover the image. */
	ic	iallu
	dsb	sy
	isb

	/* Step 13: MMU off.  We run identity-mapped, so the next instruction
	 * fetch is from the same address either way. */
	mrs	x9, sctlr_el2
	mov	x10, #1				/* M                            */
	orr	x10, x10, #(1 << 2)		/* C                            */
	orr	x10, x10, #(1 << 12)		/* I                            */
	bic	x9, x9, x10
	msr	sctlr_el2, x9
	isb

	/* Step 14: the last two tokens, then the branch.  Device accesses
	 * with the MMU off; the console was latched before the exit. */
	cmp	x22, #MODE_EBS_FAIL
	b.eq	12f

	adr	x1, m5_str_ebs_ok
	bl	m5_puts
	adr	x1, m5_str_jump
	bl	m5_puts

	mov	x0, x21				/* x0 = FDT                     */
	mov	x1, xzr
	mov	x2, xzr
	mov	x3, xzr
	br	x19

	/* ExitBootServices never succeeded: say so and reset. */
12:	adr	x1, m5_str_ebs_fail
	bl	m5_puts
	b	m5_reset
m5_tramp_end:

/* ------------------------------------------------------------------ *
 * PSCI.  SMC first, which is the board's conduit; if it returns (QEMU
 * with no EL3 answers HVC instead), try HVC, then park.
 * ------------------------------------------------------------------ */
	.globl	m5_reset
m5_reset:
	movz	w0, #(PSCI_SYSTEM_RESET & 0xffff)
	movk	w0, #(PSCI_SYSTEM_RESET >> 16), lsl #16
	smc	#0
	movz	w0, #(PSCI_SYSTEM_RESET & 0xffff)
	movk	w0, #(PSCI_SYSTEM_RESET >> 16), lsl #16
	hvc	#0
13:	wfi
	b	13b

	.globl	m5_power_off
m5_power_off:
	movz	w0, #(PSCI_SYSTEM_OFF & 0xffff)
	movk	w0, #(PSCI_SYSTEM_OFF >> 16), lsl #16
	hvc	#0
	movz	w0, #(PSCI_SYSTEM_OFF & 0xffff)
	movk	w0, #(PSCI_SYSTEM_OFF >> 16), lsl #16
	smc	#0
14:	wfi
	b	14b

/* ------------------------------------------------------------------ *
 * The EL2 exception table installed at step 11.  Every entry prints
 * ESR and ELR and resets.  Section 13 decision J: this is a diagnostic,
 * not a control - if the console is unreachable the handler can fault
 * again, and that is accepted.
 * ------------------------------------------------------------------ */
	.align	11
m5_vectors:
	.rept	16
	b	m5_exc
	.align	7
	.endr

m5_exc:
	adr	x1, m5_str_exc
	bl	m5_puts
	mrs	x2, esr_el2
	bl	m5_puthex64
	adr	x1, m5_str_elr
	bl	m5_puts
	mrs	x2, elr_el2
	bl	m5_puthex64
	adr	x1, m5_str_crlf
	bl	m5_puts
	b	m5_reset

/* ------------------------------------------------------------------ *
 * Post-exit strings.  Pre-exit text goes through ConOut from C.
 * ------------------------------------------------------------------ */
	.align	3
m5_str_ebs_ok:		.asciz	"M5L-EBS ok\r\n"
m5_str_jump:		.asciz	"M5L-JUMP\r\n"
m5_str_ebs_fail:	.asciz	"M5L-EBS FAIL\r\n"
m5_str_exc:		.asciz	"M5L-EXC ESR="
m5_str_elr:		.asciz	" ELR="
m5_str_crlf:		.asciz	"\r\n"

/* ------------------------------------------------------------------ *
 * .pool - the writable statics, routed into the PE data section by
 * m5load.lds.  Not .bss: the linker script refuses one, so that
 * SizeOfImage and the file always agree.
 * ------------------------------------------------------------------ */
	.section .pool, "aw"
	.align	3
	.globl	m5_con_base
m5_con_base:	.quad	0
	.globl	m5_con_kind
m5_con_kind:	.quad	0
