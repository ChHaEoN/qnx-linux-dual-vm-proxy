/* SPDX-License-Identifier: MIT
 *
 * contract-probe.lds - link map for the T0 payload.
 *
 * It is linked where the loader puts it, 0x80080000, because it reports the PC
 * it actually landed on and that number is only meaningful against a known
 * link address (m5-design.md §6.1, case T0c).
 *
 * PROBE_IMAGE_SIZE is the image_size the arm64 header advertises. The loader
 * allocates that many bytes, copies the file and zeroes the tail (§13 decision
 * D), so it only has to be a page multiple at least as large as the file.
 */

OUTPUT_FORMAT("elf64-littleaarch64")
OUTPUT_ARCH(aarch64)
ENTRY(_start)

PROBE_IMAGE_SIZE = 0x2000;

SECTIONS
{
	. = 0x80080000;

	.text : {
		KEEP(*(.text.head))
		*(.text .text.*)
		*(.rodata .rodata.*)
		. = ALIGN(8);
	}

	probe_end = .;

	ASSERT(probe_end - 0x80080000 <= PROBE_IMAGE_SIZE,
	       "contract-probe: the image outgrew PROBE_IMAGE_SIZE")

	.bss (NOLOAD) : { *(.bss .bss.* COMMON) }
	ASSERT(SIZEOF(.bss) == 0, "contract-probe: no .bss")

	/DISCARD/ : {
		*(.comment)
		*(.note .note.*)
		*(.eh_frame .eh_frame_hdr)
	}
}
