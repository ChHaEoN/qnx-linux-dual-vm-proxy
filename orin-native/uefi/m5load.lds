/* SPDX-License-Identifier: MIT
 *
 * m5load.lds - the link map for M5LOAD.EFI.
 *
 * Phase 3b, results/orin-native-port/20260909T1100Z/m5-design.md §3.4: one
 * .text section, read-write-execute, holding the code, the strings, the
 * embedded blob and a zero-filled pool, with file offsets equal to RVAs and
 * SizeOfHeaders 0x1000.
 *
 * The layout this produces, which objcopy -O binary then writes out flat, is
 * exactly the PE file:
 *
 *   0x0000  .head   the hand-written DOS and PE headers (m5load-head.S)
 *   0x1000  .text   entry, loader code, trampoline, exception table, strings
 *           .pool   a zero-filled scratch area, page-aligned
 *           .blob   the embedded payload, page-aligned, LAST (gate items 4, 8)
 *
 * IMAGE_BASE is a linker argument, not an edit: the build links once at 0 and
 * once at 0x100000 and the gate requires the two files to be byte-identical
 * (§3.4 gate item 6, §13 decision G). Nothing here may depend on IMAGE_BASE,
 * which is the point of the test.
 */

OUTPUT_FORMAT("elf64-littleaarch64")
OUTPUT_ARCH(aarch64)
ENTRY(m5_entry)

PROVIDE(IMAGE_BASE = 0);

SECTIONS
{
	. = IMAGE_BASE;

	.head : {
		KEEP(*(.head))
		. = ALIGN(0x1000);
	}

	m5_headers_end = .;

	.text : {
		m5_text_start = .;
		*(.text.entry)
		*(.text .text.*)
		*(.rodata .rodata.*)
		*(.data .data.*)
		. = ALIGN(16);
		m5_text_end = .;
	}

	.pool : ALIGN(0x1000) {
		m5_pool_start = .;
		*(.pool)
		. = ALIGN(0x1000);
		m5_pool_end = .;
	}

	.blob : ALIGN(0x1000) {
		m5_blob_start = .;
		KEEP(*(.blob))
		. = ALIGN(0x1000);
		m5_blob_end = .;
	}

	m5_image_end = .;

	/* The PE header's computed fields live here, not in the assembler: GNU as
	 * cannot subtract a linker-script symbol at assembly time. Each of these is
	 * an RVA or a size, so none depends on IMAGE_BASE and the two links agree
	 * byte for byte (§3.4 gate item 6). */
	PE_SIZE_OF_IMAGE = m5_image_end - IMAGE_BASE;
	PE_SIZE_OF_CODE  = m5_image_end - IMAGE_BASE - 0x1000;
	PE_TEXT_VSIZE    = m5_image_end - IMAGE_BASE - 0x1000;
	PE_ENTRY_RVA     = m5_entry - IMAGE_BASE;

	/* Nothing may reach the image through a relocation record: the gate
	 * rejects any .rela* content, and a stray .bss would make SizeOfImage
	 * disagree with the file (§3.4 gate item 3). */
	.bss (NOLOAD) : { *(.bss .bss.* COMMON) }
	ASSERT(SIZEOF(.bss) == 0, "m5load: .bss must be empty; put scratch in .pool")

	/DISCARD/ : {
		*(.comment)
		*(.note .note.*)
		*(.eh_frame .eh_frame_hdr)
		*(.interp .dynamic .dynsym .dynstr .hash .gnu.hash)
	}
}
