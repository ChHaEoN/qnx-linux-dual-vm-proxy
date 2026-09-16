/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * RAM discovery, which on this board is not discovery at all.
 *
 * The library ships two ways to find memory: walk a /memory node in the device
 * tree, or walk the UEFI memory map. Neither is available here. The firmware
 * device tree has no /memory node — checked on the running board — and kexec
 * does not synthesise one, so init_raminfo_fdt would find nothing. The UEFI map
 * is long gone by the time Linux has booted and kexec'd away.
 *
 * So the range is stated. It is the lowest System RAM range /proc/iomem
 * reports, and it is deliberately the only one claimed at first:
 *
 *   - it is the lowest of roughly seven disjoint System RAM fragments, not the
 *     whole 8 GB. The rest are above 4 GB with firmware carve-outs between
 *     them, and claiming a carve-out would corrupt something belonging to a
 *     coprocessor that is still running.
 *   - even this range already contains a third child besides kernel code and
 *     data, so "empty once Linux is gone" is an assumption, not an observation.
 *   - 992 MiB is far more than M1 needs and enough for M3's guest at 512 MiB.
 *
 * A second window is claimed only under -b (S1, s1-design.md §3.3). It does not
 * come from re-reading /proc/iomem after the DMA masters were quiesced: plan
 * checklist 11c did that and found that the quiesce frees no RAM window, because
 * the map is fixed at boot. It comes from comparing /proc/iomem across three
 * boots, on all of which 0x1_0000_0000-0x2_49FF_FFFF held no reservation.
 * Window 2 is the bottom 2,208 MiB of that range and the rest is kept out as the
 * provisional GPU range (t234_startup.h). That no firmware or BPMP user of the
 * range exists which /proc/iomem does not show is still a hypothesis (K5).
 */

#include "t234_startup.h"

_Uint64t t234_ram_size_override;

/*
 * -b, set by main.c after select_debug: T234_RAMOPT_* bits, 0 when -b is absent,
 * which is the path M1 to M5 ran. In .data like t234_hvt_policy (main.c), so an
 * absent -b reads the image's own zero rather than whatever bss holds.
 */
unsigned t234_ram_opts __attribute__((__section__(".data"))) = 0;

/* "0x", at most 16 digits and the NUL. */
#define T234_HEX_LEN 19

/*
 * The constants against each other, at compile time.
 *
 * alloc_ram's overlap test also matches a ram_list entry that starts exactly
 * where the allocated range ends (lib/ram.c:297-299), so no canary may end at
 * the start of another entry. When the canaries are allocated, the entries
 * start at 0x80000000, at the image's end (add_ram's own alloc_ram,
 * lib/ram.c:377-379), at window 2's base and, once c2 is out, at c2's end.
 * The window starts are covered here and by the containment refusal below; a
 * canary that ended at the image's end would overlap the image, which is
 * refused; and c3 starts above c2's end.
 */
#define T234_CANARY_IN(b, wb, ws) \
	((b) >= (wb) && (b) + T234_CANARY_SIZE <= (wb) + (ws))
_Static_assert(T234_RAM_BASE + T234_RAM_SIZE < T234_RAM2_BASE,
               "window 1 must end below window 2, or c1 would end where window 2's entry starts");
_Static_assert(T234_RAM2_BASE + T234_RAM2_SIZE == T234_GPU_BASE,
               "the GPU range must be the rest of 11c's candidate above window 2");
_Static_assert(T234_GPU_BASE + T234_GPU_SIZE == 0x24A000000ull,
               "the GPU range must end where 11c's candidate ends, below the CMA pool");
_Static_assert(T234_CANARY_IN(T234_CANARY1_BASE, T234_RAM_BASE, T234_RAM_SIZE),
               "c1 must lie inside window 1 at its default size");
_Static_assert(T234_CANARY_IN(T234_CANARY2_BASE, T234_RAM2_BASE, T234_RAM2_SIZE),
               "c2 must lie inside window 2");
_Static_assert(T234_CANARY_IN(T234_CANARY3_BASE, T234_RAM2_BASE, T234_RAM2_SIZE),
               "c3 must lie inside window 2");
_Static_assert(T234_CANARY2_BASE + T234_CANARY_SIZE < T234_CANARY3_BASE,
               "c2 and c3 must not overlap or touch");
#undef T234_CANARY_IN

/*
 * The two ranges t234_dcache_clean_va cleans under -b (s1-design.md §16.3.2):
 * window 2 whole, and c1's range. Neither may reach the black box, whose first
 * page the shim has already cleaned and written; c1's range must lie in window 1
 * below window 2. Page alignment of every base and size covers any DminLine the
 * architecture allows (a line is at most 2 KiB), so the loop's last line ends
 * exactly at the range's end.
 */
#define T234_PAGE_ALIGNED(v) (((v) & 0xFFFull) == 0)
_Static_assert(T234_RAM2_BASE + T234_RAM2_SIZE <= T234_BB_BASE ||
               T234_BB_BASE + T234_BB_MAP <= T234_RAM2_BASE,
               "window 2 must not overlap the black box: its clean would come after the shim's writes");
_Static_assert(T234_CANARY1_BASE >= T234_RAM_BASE &&
               T234_CANARY1_BASE + T234_CANARY_SIZE <= T234_RAM_BASE + T234_RAM_SIZE &&
               T234_CANARY1_BASE + T234_CANARY_SIZE < T234_RAM2_BASE,
               "c1's range must lie inside window 1 and below window 2");
_Static_assert(T234_PAGE_ALIGNED(T234_RAM2_BASE) && T234_PAGE_ALIGNED(T234_RAM2_SIZE),
               "window 2's base and size must be page-aligned for the line-stride clean");
_Static_assert(T234_PAGE_ALIGNED(T234_CANARY1_BASE) && T234_PAGE_ALIGNED(T234_CANARY_SIZE),
               "c1's base and the canary size must be page-aligned for the line-stride clean");
#undef T234_PAGE_ALIGNED

/* In the order they are checked, allocated and filled. */
static const struct {
	const char *name;
	_Uint64t    base;
} t234_canaries[] = {
	{ "c1", T234_CANARY1_BASE },
	{ "c2", T234_CANARY2_BASE },
	{ "c3", T234_CANARY3_BASE },
};

/*
 * kprintf pads every hex conversion to its full width (lib/kprintf.c), so %L
 * would print base=0x0000000100000000. The S1 lines are unpadded, and the
 * parsers match them as text, so the digits are formatted here from the same
 * constants the code uses.
 */
static const char *
t234_hex(char *buf, _Uint64t v)
{
	char *p = &buf[T234_HEX_LEN - 1];

	*p = '\0';
	do {
		*--p = "0123456789abcdef"[v & 0xf];
		v >>= 4;
	} while (v != 0);
	*--p = 'x';
	*--p = '0';
	return p;
}

static int
t234_overlaps(_Uint64t base, _Uint64t size, _Uint64t rbase, _Uint64t rsize)
{
	return rsize != 0 && base < rbase + rsize && rbase < base + size;
}

static int
t234_inside(_Uint64t base, _Uint64t size, _Uint64t wbase, _Uint64t wsize)
{
	return base >= wbase && base + size <= wbase + wsize;
}

/*
 * SplitMix64's output for state x: one step of the generator, x plus the golden
 * gamma, then its mix. Word k of a canary at base holds this of base + 8k,
 * little-endian; memcanary verify recomputes it.
 */
static _Uint64t
t234_splitmix64(_Uint64t x)
{
	_Uint64t z = x + 0x9E3779B97F4A7C15ull;

	z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
	z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
	return z ^ (z >> 31);
}

/*
 * Clean and invalidate the data cache by VA over [base, base + size), to the
 * point of coherency (s1-design.md §16.3.3). Called under -b only, before
 * startup's first MMU-off write into the range, so that no agent's stale or
 * dirty Write-Back copy of it can later land over the canaries or over memory
 * procnto is handed.
 *
 * CPU0 is at EL2 with its MMU and caches off, so the VA operand is the PA and
 * the operation has Outer Shareable scope. dc civac rather than dc cvau (the
 * wrong level) or dc ivac (an implementation may clean a dirty line anyway).
 * The stride is CTR_EL0.DminLine's line size, as the library's own
 * aarch64_dcache_flush_va computes it, read from the register rather than
 * assumed. No print, no option, no MMIO and no library call.
 */
static void
t234_dcache_clean_va(_Uint64t const base, _Uint64t const size)
{
	_Uint64t const line = (_Uint64t)4u << ((aa64_sr_rd32(ctr_el0) >> 16) & 0xfu);
	_Uint64t const end = base + size;
	_Uint64t       va;

	if (line == 0) {
		crash("t234: dcache line size is zero\n");
	}
	for (va = base; va < end; va += line) {
		__asm__ __volatile__("dc civac, %0" :: "r"(va) : "memory");
	}
	__asm__ __volatile__("dsb sy" ::: "memory");
}

/*
 * One canary, s1-design.md §3.3 steps 1-5. Every refusal comes before the
 * range is allocated or written, and resets through crash_done with the black
 * box intact.
 *
 * The shim page and the tree are checked here rather than trusted to main.c's
 * avoid_ram calls, which run only after this function returns. Neither
 * avoid_ram would keep a canary away anyway: nothing here searches for memory.
 */
static void
t234_canary(const char *name, _Uint64t base, _Uint64t w1_size)
{
	const _Uint64t size = T234_CANARY_SIZE;
	char           hb[T234_HEX_LEN];
	char           hs[T234_HEX_LEN];
	_Uint64t      *w;
	_Uint64t       i;
	uintptr_t      p;

	if (t234_overlaps(base, size, shdr->ram_paddr, shdr->ram_size) ||
	    t234_overlaps(base, size, shdr->image_paddr, shdr->stored_size)) {
		crash("t234: canary %s overlaps image\n", name);
	}
	if (boot_regs[0] != 0 && t234_overlaps(base, size, boot_regs[0], fdt_size)) {
		crash("t234: canary %s overlaps fdt\n", name);
	}
	if (t234_overlaps(base, size, T234_SHIM_BASE, T234_SHIM_SIZE)) {
		crash("t234: canary %s overlaps shim\n", name);
	}
	if (t234_overlaps(base, size, T234_BB_BASE, T234_BB_MAP)) {
		crash("t234: canary %s overlaps blackbox\n", name);
	}
	if (t234_overlaps(base, size, T234_GPU_BASE, T234_GPU_SIZE)) {
		crash("t234: canary %s overlaps gpu\n", name);
	}
	if (!t234_inside(base, size, T234_RAM_BASE, w1_size) &&
	    !t234_inside(base, size, T234_RAM2_BASE, T234_RAM2_SIZE)) {
		/* Partly outside both windows: -m shrank window 1, or a constant moved. */
		crash("t234: canary %s overlaps unclaimed\n", name);
	}

	/*
	 * Out of ram_list, so add_sysram never hands it to procnto
	 * (lib/ram.c:275-316, :427-440); then named, as reserve_ram names what it
	 * takes (lib/ram.c:507-515).
	 */
	alloc_ram(base, size, 1);
	as_add_containing(base, base + size - 1, AS_ATTR_RAM, "s1canary", "ram");

	/*
	 * startup_io_map is the identity on AArch64 (lib/aarch64/map_startup_io.c),
	 * and the MMU is still off: the same access the black box makes above 4 GB
	 * (hw_sertcu.c).
	 */
	p = startup_io_map((unsigned)size, base);
	w = (_Uint64t *)p;
	for (i = 0; i < size / sizeof(*w); i++) {
		w[i] = t234_splitmix64(base + i * sizeof(*w));
	}
	startup_io_unmap(p);

	kprintf("t234: canary %s base=%s size=%s filled\n",
	        name, t234_hex(hb, base), t234_hex(hs, size));
}

void
t234_init_raminfo(void)
{
	_Uint64t size = (t234_ram_size_override != 0)
	              ? t234_ram_size_override
	              : T234_RAM_SIZE;
	unsigned i;

	add_ram(T234_RAM_BASE, size);

	/*
	 * Deliberately not added, and each for its own reason:
	 *
	 *   0x40000000  SysRAM, which the BPMP uses for inter-processor channels.
	 *   0xBE000000  a range whose owner we could not establish.
	 *   above 4 GB  every System RAM fragment except window 2 under -b, once
	 *               their carve-outs are mapped out properly rather than
	 *               guessed at; and the GPU range, which -b leaves out on
	 *               purpose.
	 *   the ramoops carveout at 0x2_725F0000, which is where startup and the
	 *               shim write their black-box output. It is above 4 GB and
	 *               outside both windows anyway, but it is named here so
	 *               that whoever widens the range does not silently reclaim
	 *               the one output channel this port has before it has a
	 *               console.
	 */

	/*
	 * -b w2: window 2 after window 1, so both are in ram_list before
	 * init_system_private's add_sysram (main.c). add_ram repeats its
	 * alloc_ram of the image (lib/ram.c:377-379); the image is already out
	 * of ram_list, and an entry that only touches the range is left as it is.
	 */
	if ((t234_ram_opts & T234_RAMOPT_W2) != 0) {
		char hb[T234_HEX_LEN];
		char hs[T234_HEX_LEN];

		add_ram(T234_RAM2_BASE, T234_RAM2_SIZE);

		/*
		 * s1-design.md §16.3.1, site B: nothing has written window 2 or c1's
		 * range yet, and every CPU_ON comes after the fills. Window 2 whole
		 * under w2 (c2, c3 and everything add_sysram later hands to
		 * procnto), then c1's range under canary; each line says it ran.
		 */
		t234_dcache_clean_va(T234_RAM2_BASE, T234_RAM2_SIZE);
		kprintf("t234: dcache w2 base=%s size=%s cleaned\n",
		        t234_hex(hb, T234_RAM2_BASE), t234_hex(hs, T234_RAM2_SIZE));
		if ((t234_ram_opts & T234_RAMOPT_CANARY) != 0) {
			t234_dcache_clean_va(T234_CANARY1_BASE, T234_CANARY_SIZE);
			kprintf("t234: dcache c1 base=%s size=%s cleaned\n",
			        t234_hex(hb, T234_CANARY1_BASE), t234_hex(hs, T234_CANARY_SIZE));
		}

		kprintf("t234: ram w2 base=%s size=%s\n",
		        t234_hex(hb, T234_RAM2_BASE), t234_hex(hs, T234_RAM2_SIZE));
		kprintf("t234: gpu range base=%s size=%s not added\n",
		        t234_hex(hb, T234_GPU_BASE), t234_hex(hs, T234_GPU_SIZE));
	}

	/* -b w2,canary: after both add_ram calls, in table order. */
	if ((t234_ram_opts & T234_RAMOPT_CANARY) != 0) {
		for (i = 0; i < sizeof(t234_canaries) / sizeof(t234_canaries[0]); i++) {
			t234_canary(t234_canaries[i].name, t234_canaries[i].base, size);
		}
	}
}
