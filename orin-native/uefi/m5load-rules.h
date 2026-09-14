/* SPDX-License-Identifier: MIT
 *
 * m5load-rules.h - J7a's pure rules for M5LOAD.EFI: the window-2 sweep, the
 * canary rule, the tree-overlap rule and the reserved-memory walk.
 *
 * Phase 3b, results/orin-native-port/20260909T1100Z/s1-design.md §15.13.3
 * (UM1-UM10) and §15.13.4 (the loader source change, T0u).
 *
 * m5load.c includes this file only under M5L_J7A, so the switch-off object is
 * the M5 loader byte for byte (UM8, D0b). Every function here is pure:
 *   - it takes the map or tree bytes and the constants as arguments;
 *   - it defines no static data and stores no pointer (gate item 6: the two
 *     link bases must give identical files);
 *   - it allocates nothing and calls no boot service (m5load.lds refuses .bss,
 *     and UM6 runs these between GetMemoryMap and ExitBootServices);
 *   - it prints nothing: m5load.c does the printing.
 * The same functions compile for the host in T0u (t0/t0u-rules.c).
 *
 * The types come from efi-min.h, which the includer provides.
 */

#ifndef M5LOAD_RULES_H
#define M5LOAD_RULES_H

#ifdef _MSC_VER
#define M5R_FN static __inline
#else
#define M5R_FN static inline
#endif

/* UM1. Window 2 and the three canaries (s1-design §3.3). Gate item 11 parses
 * these lines and requires equality with board/t234_startup.h's T234_RAM2_*
 * and T234_CANARY* defines: W2_START = RAM2_BASE, W2_END = RAM2_BASE +
 * RAM2_SIZE, each canary base, CANARY_SIZE, and CANARY_PAGES * 0x1000 =
 * CANARY_SIZE. Keep one define per line in this form. */
#define M5L_W2_START      0x100000000ull
#define M5L_W2_END        0x18A000000ull
#define M5L_CANARY_C1     0xBD000000ull
#define M5L_CANARY_C2     0x100000000ull
#define M5L_CANARY_C3     0x189000000ull
#define M5L_CANARY_SIZE   0x1000000ull
#define M5L_CANARY_PAGES  0x1000ull

#define M5R_PAGE          0x1000ull
#define M5R_ATTR_RUNTIME  0x8000000000000000ull

/* Rule results. */
#define M5R_OK    0
#define M5R_GAP   1
#define M5R_TYPE  2
#define M5R_RT    3

/* Tree-overlap results (UM3). */
#define M5R_FDT_OK      0
#define M5R_FDT_W2      1
#define M5R_FDT_CANARY  2

/* Sweep modes. */
#define M5R_SWEEP_W2      0   /* window 1's allowed types, no RT attribute  */
#define M5R_SWEEP_CANARY  1   /* LoaderData only, no RT attribute           */

/* The canary base by index 0..2 (c1..c3). A switch, not a table: a table of
 * constants would be fine, but a switch keeps "no static data" literal. */
M5R_FN UINT64 m5r_canary_base(UINT32 i)
{
	switch (i) {
	case 0: return M5L_CANARY_C1;
	case 1: return M5L_CANARY_C2;
	default: return M5L_CANARY_C3;
	}
}

/* start + pages * PAGE, saturated at the top of the address space. */
M5R_FN UINT64 m5r_stop(UINT64 start, UINT64 pages)
{
	UINT64 room = ~start;

	if (pages > room / M5R_PAGE)
		return ~0ull;
	return start + pages * M5R_PAGE;
}

/* [a, a+alen) overlaps [b, b+blen), with saturated ends. Empty ranges overlap
 * nothing. */
M5R_FN int m5r_overlaps(UINT64 a, UINT64 alen, UINT64 b, UINT64 blen)
{
	UINT64 aend = (alen > ~a) ? ~0ull : a + alen;
	UINT64 bend = (blen > ~b) ? ~0ull : b + blen;

	if (alen == 0 || blen == 0)
		return 0;
	return a < bend && b < aend;
}

M5R_FN int m5r_type_ok(UINT32 mode, UINT32 t)
{
	if (mode == M5R_SWEEP_CANARY)
		return t == EfiLoaderData;
	return t == EfiLoaderCode || t == EfiLoaderData || t == EfiBootServicesCode ||
	       t == EfiBootServicesData || t == EfiConventionalMemory;
}

/* The descriptor at index i. The map's DescriptorSize is authoritative. */
M5R_FN const EFI_MEMORY_DESCRIPTOR *m5r_desc(const EFI_MEMORY_DESCRIPTOR *map,
                                             UINTN desc_size, UINTN i)
{
	return (const EFI_MEMORY_DESCRIPTOR *)((const UINT8 *)map + i * desc_size);
}

/* UM5's sweep over [lo, hi): every byte covered by a descriptor of an allowed
 * type with no RT attribute. Returns M5R_OK, or the reason at the lowest
 * failing address (*at):
 *   M5R_RT    a descriptor over the range carries EFI_MEMORY_RUNTIME;
 *   M5R_TYPE  a descriptor over the range has a type the mode does not allow;
 *   M5R_GAP   a byte of the range has no descriptor.
 * A bad descriptor is found even when another descriptor overlaps it. A map
 * whose descriptor size is below the structure's reads as a gap at lo. */
M5R_FN int m5r_sweep(const EFI_MEMORY_DESCRIPTOR *map, UINTN map_size, UINTN desc_size,
                     UINT64 lo, UINT64 hi, UINT32 mode, UINT64 *at)
{
	UINTN n, i, pass;
	UINT64 bad_at = ~0ull, covered = lo, gap_at = ~0ull;
	int bad = M5R_OK, gap = 0;

	*at = lo;
	if (lo >= hi)
		return M5R_OK;
	if (map == 0 || desc_size < sizeof(EFI_MEMORY_DESCRIPTOR))
		return M5R_GAP;
	n = map_size / desc_size;

	for (i = 0; i < n; i++) {
		const EFI_MEMORY_DESCRIPTOR *d = m5r_desc(map, desc_size, i);
		UINT64 start = d->PhysicalStart;
		UINT64 stop = m5r_stop(start, d->NumberOfPages);
		UINT64 here;
		int why = M5R_OK;

		if (!(start < hi && stop > lo))
			continue;
		if (d->Attribute & M5R_ATTR_RUNTIME)
			why = M5R_RT;
		else if (!m5r_type_ok(mode, d->Type))
			why = M5R_TYPE;
		if (why == M5R_OK)
			continue;
		here = start > lo ? start : lo;
		if (here < bad_at) {
			bad_at = here;
			bad = why;
		}
	}

	for (pass = 0; pass < n + 1 && covered < hi; pass++) {
		UINT64 best_stop = covered;

		for (i = 0; i < n; i++) {
			const EFI_MEMORY_DESCRIPTOR *d = m5r_desc(map, desc_size, i);
			UINT64 start = d->PhysicalStart;
			UINT64 stop = m5r_stop(start, d->NumberOfPages);

			if (start <= covered && stop > covered && stop > best_stop)
				best_stop = stop;
		}
		if (best_stop == covered) {
			gap = 1;
			gap_at = covered;
			break;
		}
		covered = best_stop;
	}

	if (gap && gap_at < bad_at) {
		*at = gap_at;
		return M5R_GAP;
	}
	if (bad != M5R_OK) {
		*at = bad_at;
		return bad;
	}
	return M5R_OK;
}

/* UM5's canary rule for canary i (0..2): its claim returned success (bit i of
 * claimed) and it is covered only by LoaderData with no RT attribute. Returns
 * M5R_OK or M5R_TYPE (a gap, another type, RT, or no successful claim), with
 * the lowest failing address in *at (the base when the claim is missing). */
M5R_FN int m5r_canary(const EFI_MEMORY_DESCRIPTOR *map, UINTN map_size, UINTN desc_size,
                      UINT32 i, UINT32 claimed, UINT64 *at)
{
	UINT64 base = m5r_canary_base(i);

	if (!(claimed & (1u << i))) {
		*at = base;
		return M5R_TYPE;
	}
	if (m5r_sweep(map, map_size, desc_size, base, base + M5L_CANARY_SIZE,
	              M5R_SWEEP_CANARY, at) != M5R_OK)
		return M5R_TYPE;
	return M5R_OK;
}

/* UM6: UM5's sweep and canary rule over the exact buffer handed to
 * ExitBootServices. 1 when every rule holds and all three claims succeeded. */
M5R_FN int m5r_final_ok(const EFI_MEMORY_DESCRIPTOR *map, UINTN map_size, UINTN desc_size,
                        UINT32 claimed)
{
	UINT64 at;
	UINT32 i;

	if (m5r_sweep(map, map_size, desc_size, M5L_W2_START, M5L_W2_END, M5R_SWEEP_W2, &at) != M5R_OK)
		return 0;
	for (i = 0; i < 3; i++)
		if (m5r_canary(map, map_size, desc_size, i, claimed, &at) != M5R_OK)
			return 0;
	return 1;
}

/* UM3: the tree's [fdt, fdt + totalsize) against window 2, then c1. */
M5R_FN int m5r_fdt_rule(UINT64 fdt, UINT64 size)
{
	if (m5r_overlaps(fdt, size, M5L_W2_START, M5L_W2_END - M5L_W2_START))
		return M5R_FDT_W2;
	if (m5r_overlaps(fdt, size, M5L_CANARY_C1, M5L_CANARY_SIZE))
		return M5R_FDT_CANARY;
	return M5R_FDT_OK;
}

/* UM2: the loader's own LoadedImage range. *w2 is 1 when it overlaps window 2;
 * the return value is 0 for no canary, else 1..3 for the first canary it
 * overlaps (c1, c2, c3). */
M5R_FN UINT32 m5r_self_class(UINT64 base, UINT64 size, UINT32 *w2)
{
	UINT32 i;

	*w2 = (UINT32)m5r_overlaps(base, size, M5L_W2_START, M5L_W2_END - M5L_W2_START);
	for (i = 0; i < 3; i++)
		if (m5r_overlaps(base, size, m5r_canary_base(i), M5L_CANARY_SIZE))
			return i + 1;
	return 0;
}

/* ---------------------------------------------------------------- UM9
 *
 * A read-only walk of /reserved-memory in the x0 tree. Class only: node names
 * (cut at '@', so no unit address), status, mapping kind, and for each of
 * reg, alloc-ranges and iommu-addresses whether it parsed and which of c1, c2,
 * c3 and window 2 it overlaps. No address or size leaves this walk.
 *
 * Readings fixed here (s1-design §15.13.3 UM9 leaves them to the code):
 *   - cells: a child's ranges use /reserved-memory's #address-cells and
 *     #size-cells, which default to the root's (and those to 2 and 1);
 *   - iommu-addresses entries are one phandle cell, then an address and a size
 *     in those same cells (HYPOTHESIS for the firmware tree; the values are
 *     IOVAs, so an overlap there is a class, not a physical claim);
 *   - a property whose length is zero or does not divide by its entry size,
 *     or whose cells are address 0 or above 2, or size 0 or above 2, is
 *     form=unparsed;
 *   - status "okay" or "ok" is okay, any other value disabled, none absent;
 *   - no-map wins over reusable when both are present.
 */

#define M5R_RM_NAME       32
#define M5R_PROP_REG      0
#define M5R_PROP_ALLOC    1
#define M5R_PROP_IOMMU    2
#define M5R_ST_ABSENT     0
#define M5R_ST_OKAY       1
#define M5R_ST_DISABLED   2
#define M5R_MAP_PLAIN     0
#define M5R_MAP_NOMAP     1
#define M5R_MAP_REUSABLE  2
#define M5R_FORM_ABSENT   0
#define M5R_FORM_OK       1
#define M5R_FORM_UNPARSED 2
#define M5R_OVER_C1       1u
#define M5R_OVER_C2       2u
#define M5R_OVER_C3       4u
#define M5R_OVER_W2       8u

struct m5r_rm_prop {
	UINT32 form;
	UINT32 over;      /* M5R_OVER_* bits                                   */
	UINT32 base;      /* 1 when a range of this property starts at W2_START */
};

struct m5r_rm_node {
	char name[M5R_RM_NAME];
	UINT32 status;
	UINT32 map;
	struct m5r_rm_prop prop[3];
};

struct m5r_rm_iter {
	UINT64 pos;        /* offset of the next token, from the tree's start */
	UINT64 end;        /* offset of the end of the structure block        */
	UINT64 strings;    /* offset of the strings block                     */
	UINT64 strings_end;
	UINT32 depth;
	UINT32 in_rm;      /* inside /reserved-memory (depth 2)               */
	UINT32 in_child;   /* inside one of its children (depth 3)            */
	UINT32 root_ac, root_sc, ac, sc;
	int state;         /* 0 walking, 1 done, -1 malformed                 */
};

M5R_FN UINT32 m5r_be32(const UINT8 *p)
{
	return ((UINT32)p[0] << 24) | ((UINT32)p[1] << 16) | ((UINT32)p[2] << 8) | (UINT32)p[3];
}

/* Big-endian cells, at most two, into 64 bits. */
M5R_FN UINT64 m5r_cells(const UINT8 *p, UINT32 cells)
{
	UINT64 v = 0;
	UINT32 i;

	for (i = 0; i < cells; i++)
		v = (v << 32) | m5r_be32(p + 4 * i);
	return v;
}

/* NUL-terminated string at [off, lim) equals s exactly. */
M5R_FN int m5r_str_is(const UINT8 *t, UINT64 off, UINT64 lim, const char *s)
{
	UINT64 k = 0;

	while (off + k < lim && s[k] != '\0') {
		if (t[off + k] != (UINT8)s[k])
			return 0;
		k++;
	}
	return s[k] == '\0' && off + k < lim && t[off + k] == '\0';
}

/* The node name at [off, lim) equals s up to a '@' or its NUL. */
M5R_FN int m5r_name_is(const UINT8 *t, UINT64 off, UINT64 lim, const char *s)
{
	UINT64 k = 0;

	while (off + k < lim && s[k] != '\0') {
		if (t[off + k] != (UINT8)s[k])
			return 0;
		k++;
	}
	return s[k] == '\0' && off + k < lim && (t[off + k] == '\0' || t[off + k] == '@');
}

M5R_FN void m5r_rm_init(const UINT8 *fdt, UINT64 totalsize, struct m5r_rm_iter *it)
{
	UINT64 off_struct, size_struct, off_strings, size_strings;

	it->pos = 0;
	it->end = 0;
	it->strings = 0;
	it->strings_end = 0;
	it->depth = 0;
	it->in_rm = 0;
	it->in_child = 0;
	it->root_ac = 2;
	it->root_sc = 1;
	it->ac = 2;
	it->sc = 1;
	it->state = -1;

	if (fdt == 0 || totalsize < 40 || m5r_be32(fdt) != 0xd00dfeedu)
		return;
	if ((UINT64)m5r_be32(fdt + 4) < totalsize)
		totalsize = m5r_be32(fdt + 4);
	off_struct = m5r_be32(fdt + 8);
	off_strings = m5r_be32(fdt + 12);
	size_strings = m5r_be32(fdt + 32);
	size_struct = m5r_be32(fdt + 36);
	if (m5r_be32(fdt + 20) < 17)            /* size_dt_struct needs v17 */
		return;
	if (off_struct > totalsize || size_struct > totalsize - off_struct)
		return;
	if (off_strings > totalsize || size_strings > totalsize - off_strings)
		return;
	it->pos = off_struct;
	it->end = off_struct + size_struct;
	it->strings = off_strings;
	it->strings_end = off_strings + size_strings;
	it->state = 0;
}

/* One property of a child: reg (0), alloc-ranges (1) or iommu-addresses (2). */
M5R_FN void m5r_rm_prop_eval(const UINT8 *val, UINT32 len, UINT32 which,
                             UINT32 ac, UINT32 sc, struct m5r_rm_prop *p)
{
	UINT32 extra = (which == M5R_PROP_IOMMU) ? 1u : 0u;
	UINT32 cells = extra + ac + sc;
	UINT32 k, n;

	p->over = 0;
	p->base = 0;
	if (ac == 0 || ac > 2 || sc == 0 || sc > 2 || len == 0 || (len % (4 * cells)) != 0) {
		p->form = M5R_FORM_UNPARSED;
		return;
	}
	p->form = M5R_FORM_OK;
	n = len / (4 * cells);
	for (k = 0; k < n; k++) {
		const UINT8 *e = val + 4 * cells * k;
		UINT64 addr = m5r_cells(e + 4 * extra, ac);
		UINT64 size = m5r_cells(e + 4 * (extra + ac), sc);
		UINT32 i;

		for (i = 0; i < 3; i++)
			if (m5r_overlaps(addr, size, m5r_canary_base(i), M5L_CANARY_SIZE))
				p->over |= (1u << i);
		if (m5r_overlaps(addr, size, M5L_W2_START, M5L_W2_END - M5L_W2_START))
			p->over |= M5R_OVER_W2;
		if (addr == M5L_W2_START && size != 0)
			p->base = 1;
	}
}

/* The next child of /reserved-memory. Returns 1 with *node filled, 0 when the
 * walk is over, -1 when the tree cannot be walked (never a refusal). */
M5R_FN int m5r_rm_next(const UINT8 *fdt, struct m5r_rm_iter *it, struct m5r_rm_node *node)
{
	if (it->state == 1)
		return 0;                       /* a finished walk stays finished */
	if (it->state != 0)
		return -1;

	while (it->pos + 4 <= it->end) {
		UINT32 tok = m5r_be32(fdt + it->pos);

		it->pos += 4;
		if (tok == 1u) {                                /* FDT_BEGIN_NODE */
			UINT64 q = it->pos;

			while (q < it->end && fdt[q] != '\0')
				q++;
			if (q >= it->end)
				break;
			it->depth++;
			if (it->depth == 2 && m5r_name_is(fdt, it->pos, it->end, "reserved-memory")) {
				it->in_rm = 1;
				it->ac = it->root_ac;
				it->sc = it->root_sc;
			}
			if (it->in_rm && it->depth == 3) {
				UINT64 k = 0;
				UINT32 j = 0, i;

				it->in_child = 1;
				while (it->pos + k < q && fdt[it->pos + k] != '@' && j < M5R_RM_NAME - 1) {
					UINT8 c = fdt[it->pos + k];
					int okc = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
					          (c >= '0' && c <= '9') || c == '_' || c == '-' ||
					          c == ',' || c == '.' || c == '+';
					node->name[j++] = okc ? (char)c : '_';
					k++;
				}
				if (j == 0)
					node->name[j++] = '-';
				node->name[j] = '\0';
				node->status = M5R_ST_ABSENT;
				node->map = M5R_MAP_PLAIN;
				for (i = 0; i < 3; i++) {
					node->prop[i].form = M5R_FORM_ABSENT;
					node->prop[i].over = 0;
					node->prop[i].base = 0;
				}
			}
			it->pos = (q + 1 + 3) & ~3ull;
			continue;
		}
		if (tok == 2u) {                                /* FDT_END_NODE */
			if (it->depth == 0)
				break;
			if (it->in_child && it->depth == 3) {
				it->in_child = 0;
				it->depth--;
				return 1;
			}
			if (it->in_rm && it->depth == 2) {
				it->in_rm = 0;
				it->state = 1;          /* one /reserved-memory: done */
				return 0;
			}
			it->depth--;
			continue;
		}
		if (tok == 3u) {                                /* FDT_PROP */
			UINT32 len, nameoff;
			UINT64 val, nm;

			if (it->pos + 8 > it->end)
				break;
			len = m5r_be32(fdt + it->pos);
			nameoff = m5r_be32(fdt + it->pos + 4);
			val = it->pos + 8;
			if ((UINT64)len > it->end - val)
				break;
			it->pos = (val + len + 3) & ~3ull;
			nm = it->strings + nameoff;
			if (nm >= it->strings_end)
				break;

			if (it->depth == 1 && len == 4) {
				if (m5r_str_is(fdt, nm, it->strings_end, "#address-cells"))
					it->root_ac = m5r_be32(fdt + val);
				else if (m5r_str_is(fdt, nm, it->strings_end, "#size-cells"))
					it->root_sc = m5r_be32(fdt + val);
			} else if (it->in_rm && it->depth == 2 && len == 4) {
				if (m5r_str_is(fdt, nm, it->strings_end, "#address-cells"))
					it->ac = m5r_be32(fdt + val);
				else if (m5r_str_is(fdt, nm, it->strings_end, "#size-cells"))
					it->sc = m5r_be32(fdt + val);
			} else if (it->in_child && it->depth == 3) {
				if (m5r_str_is(fdt, nm, it->strings_end, "status")) {
					int okay = (len >= 5 && fdt[val] == 'o' && fdt[val + 1] == 'k' &&
					            fdt[val + 2] == 'a' && fdt[val + 3] == 'y' && fdt[val + 4] == '\0') ||
					           (len >= 3 && fdt[val] == 'o' && fdt[val + 1] == 'k' &&
					            fdt[val + 2] == '\0');
					node->status = okay ? M5R_ST_OKAY : M5R_ST_DISABLED;
				} else if (m5r_str_is(fdt, nm, it->strings_end, "no-map")) {
					node->map = M5R_MAP_NOMAP;
				} else if (m5r_str_is(fdt, nm, it->strings_end, "reusable")) {
					if (node->map != M5R_MAP_NOMAP)
						node->map = M5R_MAP_REUSABLE;
				} else if (m5r_str_is(fdt, nm, it->strings_end, "reg")) {
					m5r_rm_prop_eval(fdt + val, len, M5R_PROP_REG, it->ac, it->sc,
					                 &node->prop[M5R_PROP_REG]);
				} else if (m5r_str_is(fdt, nm, it->strings_end, "alloc-ranges")) {
					m5r_rm_prop_eval(fdt + val, len, M5R_PROP_ALLOC, it->ac, it->sc,
					                 &node->prop[M5R_PROP_ALLOC]);
				} else if (m5r_str_is(fdt, nm, it->strings_end, "iommu-addresses")) {
					m5r_rm_prop_eval(fdt + val, len, M5R_PROP_IOMMU, it->ac, it->sc,
					                 &node->prop[M5R_PROP_IOMMU]);
				}
			}
			continue;
		}
		if (tok == 4u)                                  /* FDT_NOP */
			continue;
		if (tok == 9u) {                                /* FDT_END */
			it->state = 1;
			return 0;
		}
		break;                                          /* unknown token */
	}
	it->state = -1;
	return -1;
}

#endif /* M5LOAD_RULES_H */
