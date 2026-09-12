/* SPDX-License-Identifier: MIT
 *
 * m5load.lds - the link map for M5LOAD.EFI.
 *
 * Phase 3b, results/orin-native-port/20260909T1100Z/m5-design.md §3.4, as
 * amended by §13 decision L: two sections, not one.
 *
 * The layout, which objcopy -O binary then writes out flat, is the PE file:
 *
 *   0x0000  .head   the hand-written DOS and PE headers (m5load-head.S)
 *   0x1000  .text   entry, loader code, trampoline, exception table, strings
 *           .data   the writable statics, page-aligned
 *           .blob   the embedded payload, page-aligned, LAST (gate items 4, 8)
 *
 * .text is read and execute; .data and .blob are read and write, with no
 * execute, and the PE header describes them as one data section. Why: the
 * first T0b run faulted on the first write to an in-image static, because the
 * firmware mapped our single read-write-execute section non-writable. UEFI
 * image protection sets a section's page attributes from its characteristics,
 * so the writable data has to live in its own section.
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
		. = ALIGN(0x1000);
		m5_text_end = .;
	}

	/* Everything the loader writes to, and the payload it carries. One PE
	 * data section covers both, so the firmware may map it writable and
	 * non-executable. */
	.data : ALIGN(0x1000) {
		m5_data_start = .;
		*(.data .data.*)
		*(.pool)
		. = ALIGN(0x1000);
	}

	.blob : ALIGN(0x1000) {
		m5_blob_start = .;
		KEEP(*(.blob))
		. = ALIGN(0x1000);
		m5_blob_end = .;
	}

	m5_data_end = .;
	m5_image_end = .;

	/* The PE header's computed fields live here, not in the assembler: GNU as
	 * cannot subtract a linker-script symbol at assembly time. Each of these is
	 * an RVA or a size, so none depends on IMAGE_BASE and the two links agree
	 * byte for byte (§3.4 gate item 6). */
	PE_SIZE_OF_IMAGE = m5_image_end - IMAGE_BASE;
	PE_SIZE_OF_CODE  = m5_text_end - m5_text_start;
	PE_SIZE_OF_DATA  = m5_data_end - m5_data_start;
	PE_TEXT_RVA      = m5_text_start - IMAGE_BASE;
	PE_TEXT_VSIZE    = m5_text_end - m5_text_start;
	PE_DATA_RVA      = m5_data_start - IMAGE_BASE;
	PE_DATA_VSIZE    = m5_data_end - m5_data_start;
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
