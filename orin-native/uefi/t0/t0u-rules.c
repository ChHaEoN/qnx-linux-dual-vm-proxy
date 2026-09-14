/* SPDX-License-Identifier: MIT
 *
 * t0u-rules.c - T0u: the pure J7a rules of m5load-rules.h, compiled for the
 * host and run on synthetic maps and trees. No firmware, no board, no QNX byte.
 *
 * Phase 3b, results/orin-native-port/20260909T1100Z/s1-design.md §15.13.4, the
 * T0u row: a tree in window 2 or over c1, an RT attribute in window 2, a gap,
 * BootServicesData over a canary, a canary claim that failed, a final map that
 * fails, a reserved-memory node over c2 at window 2's base, a malformed
 * property (form=unparsed) - each gives its named result, and a clean map
 * passes. A few edge cases are added (descriptor size above the structure's,
 * page-count overflow, cell counts, truncated trees).
 *
 * Every address here is a design constant or a synthetic value; nothing comes
 * from a run. Built and run by t0/run-t0u.ps1. Prints one line per check and a
 * final "T0U RESULT PASS|FAIL passed/total"; exit 0 only on PASS.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../efi-min.h"
#include "../m5load-rules.h"

static int g_total, g_failed;

static void check(const char *name, int cond)
{
	g_total++;
	if (!cond)
		g_failed++;
	printf("T0U %s %s\n", cond ? "PASS" : "FAIL", name);
}

/* ---------------------------------------------------------------- maps */

#define MAXD 64

struct map {
	EFI_MEMORY_DESCRIPTOR d[MAXD];
	UINTN n;
};

static void add(struct map *m, UINT32 type, UINT64 start, UINT64 end, UINT64 attr)
{
	EFI_MEMORY_DESCRIPTOR *d = &m->d[m->n++];

	memset(d, 0, sizeof(*d));
	d->Type = type;
	d->PhysicalStart = start;
	d->NumberOfPages = (end - start) / M5R_PAGE;
	d->Attribute = attr;
}

#define C1 M5L_CANARY_C1
#define C2 M5L_CANARY_C2
#define C3 M5L_CANARY_C3
#define CS M5L_CANARY_SIZE
#define W2S M5L_W2_START
#define W2E M5L_W2_END
#define MAPSZ(m) ((m)->n * sizeof(EFI_MEMORY_DESCRIPTOR))

/* A clean map in shuffled order: the three canaries claimed (LoaderData), the
 * rest of window 2 free, BootServicesData above it. */
static void clean_map(struct map *m)
{
	m->n = 0;
	add(m, EfiConventionalMemory, C2 + CS, C3, 1);
	add(m, EfiBootServicesData, W2E, 0x200000000ull, 1);
	add(m, EfiLoaderData, C1, C1 + CS, 1);
	add(m, EfiConventionalMemory, 0x80000000ull, C1, 1);
	add(m, EfiLoaderData, C3, C3 + CS, 1);
	add(m, EfiConventionalMemory, C1 + CS, W2S, 1);
	add(m, EfiLoaderData, C2, C2 + CS, 1);
}

/* Replace [lo, hi) of the Conventional descriptor between c2 and c3 with the
 * given descriptor (type, attr), keeping the rest; hi == lo removes nothing. */
static void punch(struct map *m, UINT64 lo, UINT64 hi, UINT32 type, UINT64 attr, int gap)
{
	UINTN i;

	for (i = 0; i < m->n; i++)
		if (m->d[i].PhysicalStart == C2 + CS)
			break;
	add(m, EfiConventionalMemory, hi, C3, 1);
	m->d[i].NumberOfPages = (lo - (C2 + CS)) / M5R_PAGE;
	if (!gap)
		add(m, type, lo, hi, attr);
}

static void test_maps(void)
{
	struct map m;
	UINT64 at;
	int r;

	clean_map(&m);
	r = m5r_sweep(m.d, MAPSZ(&m), sizeof(EFI_MEMORY_DESCRIPTOR), W2S, W2E, M5R_SWEEP_W2, &at);
	check("clean map: window-2 sweep passes", r == M5R_OK);
	check("clean map: canary c1 passes", m5r_canary(m.d, MAPSZ(&m), sizeof(m.d[0]), 0, 7, &at) == M5R_OK);
	check("clean map: canary c2 passes", m5r_canary(m.d, MAPSZ(&m), sizeof(m.d[0]), 1, 7, &at) == M5R_OK);
	check("clean map: canary c3 passes", m5r_canary(m.d, MAPSZ(&m), sizeof(m.d[0]), 2, 7, &at) == M5R_OK);
	check("clean map: final map passes", m5r_final_ok(m.d, MAPSZ(&m), sizeof(m.d[0]), 7) == 1);

	/* RT attribute in window 2 */
	clean_map(&m);
	punch(&m, 0x120000000ull, 0x120010000ull, EfiConventionalMemory, 1 | M5R_ATTR_RUNTIME, 0);
	r = m5r_sweep(m.d, MAPSZ(&m), sizeof(m.d[0]), W2S, W2E, M5R_SWEEP_W2, &at);
	check("RT attribute in window 2: reason rt at its start", r == M5R_RT && at == 0x120000000ull);
	check("RT attribute in window 2: final map fails", m5r_final_ok(m.d, MAPSZ(&m), sizeof(m.d[0]), 7) == 0);

	/* RuntimeServicesData with RT: rt; MMIO and Reserved without RT: type */
	clean_map(&m);
	punch(&m, 0x130000000ull, 0x130004000ull, EfiRuntimeServicesData, M5R_ATTR_RUNTIME, 0);
	r = m5r_sweep(m.d, MAPSZ(&m), sizeof(m.d[0]), W2S, W2E, M5R_SWEEP_W2, &at);
	check("RuntimeServicesData+RT in window 2: reason rt", r == M5R_RT && at == 0x130000000ull);
	clean_map(&m);
	punch(&m, 0x140000000ull, 0x140001000ull, EfiMemoryMappedIO, 0, 0);
	r = m5r_sweep(m.d, MAPSZ(&m), sizeof(m.d[0]), W2S, W2E, M5R_SWEEP_W2, &at);
	check("MMIO in window 2: reason type", r == M5R_TYPE && at == 0x140000000ull);
	clean_map(&m);
	punch(&m, 0x140000000ull, 0x140001000ull, EfiReservedMemoryType, 0, 0);
	r = m5r_sweep(m.d, MAPSZ(&m), sizeof(m.d[0]), W2S, W2E, M5R_SWEEP_W2, &at);
	check("Reserved in window 2: reason type", r == M5R_TYPE && at == 0x140000000ull);
	clean_map(&m);
	punch(&m, 0x140000000ull, 0x140001000ull, EfiACPIReclaimMemory, 0, 0);
	r = m5r_sweep(m.d, MAPSZ(&m), sizeof(m.d[0]), W2S, W2E, M5R_SWEEP_W2, &at);
	check("ACPIReclaim in window 2: reason type", r == M5R_TYPE);
	clean_map(&m);
	punch(&m, 0x140000000ull, 0x140001000ull, EfiBootServicesCode, 0, 0);
	r = m5r_sweep(m.d, MAPSZ(&m), sizeof(m.d[0]), W2S, W2E, M5R_SWEEP_W2, &at);
	check("BootServicesCode in window 2 (not over a canary): passes", r == M5R_OK);

	/* A gap */
	clean_map(&m);
	punch(&m, 0x150000000ull, 0x150010000ull, 0, 0, 1);
	r = m5r_sweep(m.d, MAPSZ(&m), sizeof(m.d[0]), W2S, W2E, M5R_SWEEP_W2, &at);
	check("gap in window 2: reason gap at its start", r == M5R_GAP && at == 0x150000000ull);
	check("gap in window 2: final map fails", m5r_final_ok(m.d, MAPSZ(&m), sizeof(m.d[0]), 7) == 0);

	/* A gap at window 2's end (c3 descriptor shortened) */
	clean_map(&m);
	{
		UINTN i;
		for (i = 0; i < m.n; i++)
			if (m.d[i].PhysicalStart == C3)
				m.d[i].NumberOfPages -= 1;
	}
	r = m5r_sweep(m.d, MAPSZ(&m), sizeof(m.d[0]), W2S, W2E, M5R_SWEEP_W2, &at);
	check("gap at window 2's last page: reason gap", r == M5R_GAP && at == W2E - M5R_PAGE);
	check("gap at window 2's last page: canary c3 fails", m5r_canary(m.d, MAPSZ(&m), sizeof(m.d[0]), 2, 7, &at) == M5R_TYPE);

	/* The lowest failure wins: a gap below an RT descriptor */
	clean_map(&m);
	punch(&m, 0x150000000ull, 0x150010000ull, 0, 0, 1);
	{
		UINTN i;
		for (i = 0; i < m.n; i++)
			if (m.d[i].PhysicalStart == 0x150010000ull)
				m.d[i].Attribute |= M5R_ATTR_RUNTIME;
	}
	r = m5r_sweep(m.d, MAPSZ(&m), sizeof(m.d[0]), W2S, W2E, M5R_SWEEP_W2, &at);
	check("gap below an RT descriptor: gap reported first", r == M5R_GAP && at == 0x150000000ull);

	/* An RT descriptor hidden under an overlapping good one */
	clean_map(&m);
	add(&m, EfiRuntimeServicesCode, 0x160000000ull, 0x160001000ull, M5R_ATTR_RUNTIME);
	r = m5r_sweep(m.d, MAPSZ(&m), sizeof(m.d[0]), W2S, W2E, M5R_SWEEP_W2, &at);
	check("RT descriptor overlapped by a free one: still rt", r == M5R_RT && at == 0x160000000ull);

	/* BootServicesData over a canary */
	clean_map(&m);
	{
		UINTN i;
		for (i = 0; i < m.n; i++)
			if (m.d[i].PhysicalStart == C2)
				m.d[i].Type = EfiBootServicesData;
	}
	r = m5r_sweep(m.d, MAPSZ(&m), sizeof(m.d[0]), W2S, W2E, M5R_SWEEP_W2, &at);
	check("BootServicesData over c2: window-2 sweep still passes", r == M5R_OK);
	check("BootServicesData over c2: canary rule type at c2",
	      m5r_canary(m.d, MAPSZ(&m), sizeof(m.d[0]), 1, 7, &at) == M5R_TYPE && at == C2);
	check("BootServicesData over c2: final map fails", m5r_final_ok(m.d, MAPSZ(&m), sizeof(m.d[0]), 7) == 0);

	/* A canary partly LoaderData, partly Conventional */
	clean_map(&m);
	{
		UINTN i;
		for (i = 0; i < m.n; i++)
			if (m.d[i].PhysicalStart == C1)
				m.d[i].NumberOfPages = 0x800;
		add(&m, EfiConventionalMemory, C1 + 0x800000ull, C1 + CS, 1);
	}
	check("c1 half claimed: canary rule type at the free half",
	      m5r_canary(m.d, MAPSZ(&m), sizeof(m.d[0]), 0, 7, &at) == M5R_TYPE && at == C1 + 0x800000ull);

	/* A canary claim that failed */
	clean_map(&m);
	check("claim of c2 failed: canary rule type at c2",
	      m5r_canary(m.d, MAPSZ(&m), sizeof(m.d[0]), 1, 5, &at) == M5R_TYPE && at == C2);
	check("claim of c2 failed: c1 and c3 still pass",
	      m5r_canary(m.d, MAPSZ(&m), sizeof(m.d[0]), 0, 5, &at) == M5R_OK &&
	      m5r_canary(m.d, MAPSZ(&m), sizeof(m.d[0]), 2, 5, &at) == M5R_OK);
	check("claim of c2 failed: final map fails", m5r_final_ok(m.d, MAPSZ(&m), sizeof(m.d[0]), 5) == 0);
	check("no claim at all: final map fails", m5r_final_ok(m.d, MAPSZ(&m), sizeof(m.d[0]), 0) == 0);

	/* A descriptor size above the structure's (the map's DescriptorSize rules) */
	{
		UINT64 buf[MAXD * 7];
		UINTN dsz = 56, i;
		struct map c;

		clean_map(&c);
		memset(buf, 0xA5, sizeof(buf));
		for (i = 0; i < c.n; i++)
			memcpy((UINT8 *)buf + i * dsz, &c.d[i], sizeof(c.d[i]));
		check("descriptor size 56: clean map passes",
		      m5r_final_ok((EFI_MEMORY_DESCRIPTOR *)buf, c.n * dsz, dsz, 7) == 1);
		check("descriptor size below the structure: gap",
		      m5r_sweep((EFI_MEMORY_DESCRIPTOR *)buf, c.n * dsz, 16, W2S, W2E, M5R_SWEEP_W2, &at) == M5R_GAP);
	}

	/* Page-count overflow saturates and does not wrap */
	m.n = 0;
	add(&m, EfiConventionalMemory, 0x80000000ull, 0x80001000ull, 1);
	m.d[0].NumberOfPages = 0xFFFFFFFFFFFFFull;
	r = m5r_sweep(m.d, MAPSZ(&m), sizeof(m.d[0]), W2S, W2E, M5R_SWEEP_W2, &at);
	check("huge page count: saturates, covers window 2", r == M5R_OK);
	check("m5r_stop saturates", m5r_stop(0xFFFFFFFFFFFFF000ull, 2) == ~0ull);

	/* An empty map */
	check("empty map: gap at window 2's base",
	      m5r_sweep(m.d, 0, sizeof(m.d[0]), W2S, W2E, M5R_SWEEP_W2, &at) == M5R_GAP && at == W2S);
}

/* ---------------------------------------------------------------- tree rule */

static void test_fdt_rule(void)
{
	check("tree straddling window 2's base: w2", m5r_fdt_rule(W2S - 0x100, 0x200) == M5R_FDT_W2);
	check("tree inside window 2: w2", m5r_fdt_rule(0x150000000ull, 0x10000) == M5R_FDT_W2);
	check("tree straddling window 2's end: w2", m5r_fdt_rule(W2E - 0x100, 0x2000) == M5R_FDT_W2);
	check("tree at window 2's end: ok", m5r_fdt_rule(W2E, 0x10000) == M5R_FDT_OK);
	check("tree ending at window 2's base: ok", m5r_fdt_rule(W2S - 0x10000, 0x10000) == M5R_FDT_OK);
	check("tree over c1: canary", m5r_fdt_rule(C1 - 0x100, 0x200) == M5R_FDT_CANARY);
	check("tree inside c1: canary", m5r_fdt_rule(C1 + 0x1000, 0x1000) == M5R_FDT_CANARY);
	check("tree just above c1: ok", m5r_fdt_rule(C1 + CS, 0x10000) == M5R_FDT_OK);
	check("tree high above both: ok", m5r_fdt_rule(0x270000000ull, 0x10000) == M5R_FDT_OK);
	check("zero-size tree: ok", m5r_fdt_rule(W2S, 0) == M5R_FDT_OK);
}

static void test_self(void)
{
	UINT32 w2 = 9, c;

	c = m5r_self_class(C2 + 0x1000, 0x100000, &w2);
	check("self inside c2: w2=yes canary=c2", w2 == 1 && c == 2);
	c = m5r_self_class(0x160000000ull, 0x100000, &w2);
	check("self in window 2, no canary: w2=yes canary=none", w2 == 1 && c == 0);
	c = m5r_self_class(C1 - 0x1000, 0x2000, &w2);
	check("self over c1: w2=no canary=c1", w2 == 0 && c == 1);
	c = m5r_self_class(0x27F000000ull, 0x3000000, &w2);
	check("self high: w2=no canary=none", w2 == 0 && c == 0);
	c = m5r_self_class(0, 0, &w2);
	check("self unknown (0+0): w2=no canary=none", w2 == 0 && c == 0);
}

/* ---------------------------------------------------------------- trees */

struct fdtb {
	UINT8 st[8192];
	UINT32 stn;
	char str[1024];
	UINT32 strn;
	UINT8 out[16384];
	UINT32 outn;
};

static void put32(UINT8 *p, UINT32 v)
{
	p[0] = (UINT8)(v >> 24);
	p[1] = (UINT8)(v >> 16);
	p[2] = (UINT8)(v >> 8);
	p[3] = (UINT8)v;
}

static void st32(struct fdtb *b, UINT32 v)
{
	put32(b->st + b->stn, v);
	b->stn += 4;
}

static void st_bytes(struct fdtb *b, const void *p, UINT32 n)
{
	memcpy(b->st + b->stn, p, n);
	b->stn += n;
	while (b->stn & 3)
		b->st[b->stn++] = 0;
}

static void begin(struct fdtb *b, const char *name)
{
	st32(b, 1);
	st_bytes(b, name, (UINT32)strlen(name) + 1);
}

static void end(struct fdtb *b)
{
	st32(b, 2);
}

static void prop(struct fdtb *b, const char *name, const void *val, UINT32 len)
{
	UINT32 off = b->strn;

	memcpy(b->str + b->strn, name, strlen(name) + 1);
	b->strn += (UINT32)strlen(name) + 1;
	st32(b, 3);
	st32(b, len);
	st32(b, off);
	if (len)
		st_bytes(b, val, len);
}

static void prop_cells(struct fdtb *b, const char *name, const UINT32 *cells, UINT32 n)
{
	UINT8 tmp[256];
	UINT32 i;

	for (i = 0; i < n; i++)
		put32(tmp + 4 * i, cells[i]);
	prop(b, name, tmp, 4 * n);
}

static void prop_str(struct fdtb *b, const char *name, const char *s)
{
	prop(b, name, s, (UINT32)strlen(s) + 1);
}

static UINT32 finish(struct fdtb *b)
{
	UINT32 off_struct = 40 + 16, off_strings, total;

	st32(b, 9);
	memset(b->out, 0, sizeof(b->out));
	memcpy(b->out + off_struct, b->st, b->stn);
	off_strings = off_struct + b->stn;
	memcpy(b->out + off_strings, b->str, b->strn);
	total = off_strings + b->strn;
	put32(b->out + 0, 0xd00dfeedu);
	put32(b->out + 4, total);
	put32(b->out + 8, off_struct);
	put32(b->out + 12, off_strings);
	put32(b->out + 16, 40);
	put32(b->out + 20, 17);
	put32(b->out + 24, 16);
	put32(b->out + 28, 0);
	put32(b->out + 32, b->strn);
	put32(b->out + 36, b->stn);
	return total;
}

/* Functions, not casts of constants: MSVC /W4 warns (C4310) on a cast that
 * truncates a constant, and the truncation is the point here. */
static UINT32 hi32(UINT64 v) { return (UINT32)(v >> 32); }
static UINT32 lo32(UINT64 v) { return (UINT32)(v & 0xFFFFFFFFull); }
#define HI(v) hi32(v)
#define LO(v) lo32(v)

static void build_tree(struct fdtb *b)
{
	memset(b, 0, sizeof(*b));
	begin(b, "");
	{ UINT32 c[] = { 2 }; prop_cells(b, "#address-cells", c, 1); }
	{ UINT32 c[] = { 2 }; prop_cells(b, "#size-cells", c, 1); }
	prop_str(b, "compatible", "synthetic,board");

	/* a node outside /reserved-memory with a reg over c2: never reported */
	begin(b, "memory@80000000");
	{ UINT32 c[] = { 0, 0x80000000u, 2, 0 }; prop_cells(b, "reg", c, 4); }
	end(b);

	begin(b, "reserved-memory");
	{ UINT32 c[] = { 2 }; prop_cells(b, "#address-cells", c, 1); }
	{ UINT32 c[] = { 2 }; prop_cells(b, "#size-cells", c, 1); }
	prop(b, "ranges", 0, 0);

	/* 1: over c2 at window 2's base, alloc-ranges, disabled */
	begin(b, "carve_a@100000000");
	{ UINT32 c[] = { HI(W2S), LO(W2S), 0, 0x08000000u }; prop_cells(b, "alloc-ranges", c, 4); }
	prop_str(b, "status", "disabled");
	end(b);

	/* 2: high, outside everything; okay */
	begin(b, "ramoops_x@272770000");
	{ UINT32 c[] = { 2, 0x72770000u, 0, 0x10000u }; prop_cells(b, "reg", c, 4); }
	prop_str(b, "status", "okay");
	end(b);

	/* 3: no-map and reusable, reg over c3 (not at base) */
	begin(b, "fb_y");
	{ UINT32 c[] = { HI(C3), LO(C3) + 0x1000u, 0, 0x100000u }; prop_cells(b, "reg", c, 4); }
	prop(b, "reusable", 0, 0);
	prop(b, "no-map", 0, 0);
	end(b);

	/* 4: a malformed reg (12 bytes, not a multiple of 16) */
	begin(b, "broken@1");
	{ UINT32 c[] = { 0, 1, 2 }; prop_cells(b, "reg", c, 3); }
	end(b);

	/* 5: iommu-addresses over c1 (phandle, addr, size); reusable */
	begin(b, "dma_z");
	{ UINT32 c[] = { 0x55, HI(C1), LO(C1), 0, 0x1000u }; prop_cells(b, "iommu-addresses", c, 5); }
	prop(b, "reusable", 0, 0);
	prop_str(b, "status", "ok");
	end(b);

	/* 6: two reg entries, one over window 2 only, one over c2 and c3 */
	begin(b, "wide*node");
	{
		UINT32 c[] = { HI(0x150000000ull), LO(0x150000000ull), 0, 0x1000u,
		               HI(W2S), LO(W2S), 0, (UINT32)(W2E - W2S) };
		prop_cells(b, "reg", c, 8);
	}
	/* a grandchild whose props must be ignored */
	begin(b, "sub");
	prop_str(b, "status", "disabled");
	{ UINT32 c[] = { 0, 0x1000, 0, 0x1000 }; prop_cells(b, "reg", c, 4); }
	end(b);
	end(b);

	/* 7: window 2 only, not over a canary */
	begin(b, "mid");
	{ UINT32 c[] = { HI(0x160000000ull), LO(0x160000000ull), 0, 0x200000u }; prop_cells(b, "reg", c, 4); }
	end(b);

	end(b);                 /* /reserved-memory */

	begin(b, "after");      /* never reached: the walk ends with /reserved-memory */
	end(b);
	end(b);                 /* root */
}

static void test_resmem(void)
{
	struct fdtb *b = (struct fdtb *)calloc(1, sizeof(struct fdtb));
	struct m5r_rm_iter it;
	struct m5r_rm_node node;
	UINT32 total;
	int r, count = 0;

	build_tree(b);
	total = finish(b);
	m5r_rm_init(b->out, total, &it);
	check("resmem: tree accepted", it.state == 0);

	r = m5r_rm_next(b->out, &it, &node); count += r == 1;
	check("node 1: name cut at @", r == 1 && strcmp(node.name, "carve_a") == 0);
	check("node 1: status disabled, map plain", node.status == M5R_ST_DISABLED && node.map == M5R_MAP_PLAIN);
	check("node 1: alloc-ranges over c2 and w2, at window 2's base",
	      node.prop[M5R_PROP_ALLOC].form == M5R_FORM_OK &&
	      node.prop[M5R_PROP_ALLOC].over == (M5R_OVER_C2 | M5R_OVER_W2) &&
	      node.prop[M5R_PROP_ALLOC].base == 1);
	check("node 1: reg absent", node.prop[M5R_PROP_REG].form == M5R_FORM_ABSENT);

	r = m5r_rm_next(b->out, &it, &node); count += r == 1;
	check("node 2: okay, reg parsed, over nothing",
	      r == 1 && strcmp(node.name, "ramoops_x") == 0 && node.status == M5R_ST_OKAY &&
	      node.prop[M5R_PROP_REG].form == M5R_FORM_OK && node.prop[M5R_PROP_REG].over == 0);

	r = m5r_rm_next(b->out, &it, &node); count += r == 1;
	check("node 3: no-map wins over reusable, status absent",
	      r == 1 && node.map == M5R_MAP_NOMAP && node.status == M5R_ST_ABSENT);
	check("node 3: reg over c3 and w2, base=no",
	      node.prop[M5R_PROP_REG].over == (M5R_OVER_C3 | M5R_OVER_W2) && node.prop[M5R_PROP_REG].base == 0);

	r = m5r_rm_next(b->out, &it, &node); count += r == 1;
	check("node 4: malformed reg is form=unparsed",
	      r == 1 && strcmp(node.name, "broken") == 0 && node.prop[M5R_PROP_REG].form == M5R_FORM_UNPARSED);

	r = m5r_rm_next(b->out, &it, &node); count += r == 1;
	check("node 5: iommu-addresses over c1 only; reusable; status ok is okay",
	      r == 1 && node.prop[M5R_PROP_IOMMU].form == M5R_FORM_OK &&
	      node.prop[M5R_PROP_IOMMU].over == M5R_OVER_C1 && node.map == M5R_MAP_REUSABLE &&
	      node.status == M5R_ST_OKAY);

	r = m5r_rm_next(b->out, &it, &node); count += r == 1;
	check("node 6: name sanitised",
	      r == 1 && strcmp(node.name, "wide_node") == 0);
	check("node 6: two entries: c2, c3 and w2, base=yes; grandchild ignored",
	      node.prop[M5R_PROP_REG].over == (M5R_OVER_C2 | M5R_OVER_C3 | M5R_OVER_W2) &&
	      node.prop[M5R_PROP_REG].base == 1 && node.status == M5R_ST_ABSENT);

	r = m5r_rm_next(b->out, &it, &node); count += r == 1;
	check("node 7: window 2 only", r == 1 && node.prop[M5R_PROP_REG].over == M5R_OVER_W2);

	r = m5r_rm_next(b->out, &it, &node);
	check("walk ends after /reserved-memory, memory node never reported", r == 0 && count == 7);
	check("a finished walk stays finished", m5r_rm_next(b->out, &it, &node) == 0);

	/* size-cells 0 and address-cells 3 are unparsed */
	memset(b, 0, sizeof(*b));
	begin(b, "");
	begin(b, "reserved-memory");
	{ UINT32 c[] = { 3 }; prop_cells(b, "#address-cells", c, 1); }
	{ UINT32 c[] = { 1 }; prop_cells(b, "#size-cells", c, 1); }
	begin(b, "three");
	{ UINT32 c[] = { 0, 1, 0, 16 }; prop_cells(b, "reg", c, 4); }
	end(b);
	end(b);
	end(b);
	total = finish(b);
	m5r_rm_init(b->out, total, &it);
	r = m5r_rm_next(b->out, &it, &node);
	check("#address-cells 3: form=unparsed", r == 1 && node.prop[M5R_PROP_REG].form == M5R_FORM_UNPARSED);

	/* default cells (root absent): 2 and 1 */
	memset(b, 0, sizeof(*b));
	begin(b, "");
	begin(b, "reserved-memory");
	begin(b, "dflt");
	{ UINT32 c[] = { HI(C2), LO(C2), 0x1000 }; prop_cells(b, "reg", c, 3); }
	end(b);
	end(b);
	end(b);
	total = finish(b);
	m5r_rm_init(b->out, total, &it);
	r = m5r_rm_next(b->out, &it, &node);
	check("default cells 2 and 1: reg over c2 at base",
	      r == 1 && node.prop[M5R_PROP_REG].form == M5R_FORM_OK &&
	      node.prop[M5R_PROP_REG].over == (M5R_OVER_C2 | M5R_OVER_W2) && node.prop[M5R_PROP_REG].base == 1);

	/* no /reserved-memory at all */
	memset(b, 0, sizeof(*b));
	begin(b, "");
	begin(b, "chosen");
	end(b);
	end(b);
	total = finish(b);
	m5r_rm_init(b->out, total, &it);
	check("no /reserved-memory: walk ends cleanly", m5r_rm_next(b->out, &it, &node) == 0);

	/* malformed trees */
	build_tree(b);
	total = finish(b);
	b->out[0] = 0;
	m5r_rm_init(b->out, total, &it);
	check("bad magic: unwalkable", m5r_rm_next(b->out, &it, &node) == -1);

	build_tree(b);
	total = finish(b);
	put32(b->out + 36, 200);        /* structure block cut inside the tree */
	m5r_rm_init(b->out, total, &it);
	r = m5r_rm_next(b->out, &it, &node);
	check("truncated structure block: unwalkable, no node", r == -1);

	build_tree(b);
	total = finish(b);
	put32(b->out + 36, 0x100000);   /* structure size past totalsize */
	m5r_rm_init(b->out, total, &it);
	check("structure size past totalsize: unwalkable", m5r_rm_next(b->out, &it, &node) == -1);

	build_tree(b);
	total = finish(b);
	put32(b->out + 20, 16);         /* version below 17 */
	m5r_rm_init(b->out, total, &it);
	check("version 16: unwalkable", m5r_rm_next(b->out, &it, &node) == -1);

	build_tree(b);
	total = finish(b);
	/* an unknown token right after the root's name */
	put32(b->out + 40 + 16 + 8, 0x77);
	m5r_rm_init(b->out, total, &it);
	check("unknown token: unwalkable", m5r_rm_next(b->out, &it, &node) == -1);

	check("m5r_overlaps: empty ranges overlap nothing",
	      !m5r_overlaps(W2S, 0, W2S, 1) && !m5r_overlaps(W2S, 1, W2S, 0));
	check("m5r_overlaps: touching ranges do not overlap", !m5r_overlaps(0, 0x1000, 0x1000, 0x1000));
	check("m5r_overlaps: saturated end", m5r_overlaps(0xFFFFFFFFFFFFF000ull, 0x10000, 0xFFFFFFFFFFFFF800ull, 1));

	free(b);
}

int main(void)
{
	check("constants: window 2 is [RAM2_BASE, RAM2_BASE + RAM2_SIZE)",
	      M5L_W2_START == 0x100000000ull && M5L_W2_END == 0x100000000ull + 0x8A000000ull);
	check("constants: canary pages cover the canary size", M5L_CANARY_PAGES * M5R_PAGE == M5L_CANARY_SIZE);
	test_maps();
	test_fdt_rule();
	test_self();
	test_resmem();
	printf("T0U RESULT %s %d/%d\n", g_failed ? "FAIL" : "PASS", g_total - g_failed, g_total);
	return g_failed ? 1 : 0;
}
