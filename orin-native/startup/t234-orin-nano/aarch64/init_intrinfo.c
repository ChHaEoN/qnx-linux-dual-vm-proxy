/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * Interrupt controller: GIC-600, a plain GICv3.
 *
 * This file is short because the library does the work. gic_v3_initialize()
 * registers the PPI entry itself and synthesises a default SPI entry when the
 * board has not added one, so there are no startup_intrinfo structures to
 * build here — which is the opposite of what the plan assumed, and worth
 * knowing before someone writes two hundred lines that are already written.
 *
 * What the board must get right is the geometry, and there is exactly one trap
 * in it. The redistributor frames are 0x20000 apart in a 2 MiB region, so
 * sixteen fit, but this SKU populates only six and not contiguously: CPUs 0-3
 * in frames 0-3, the two cluster-1 cores in frames 6 and 7. The library derives
 * its frame limit from the region size when one is given, and from the CPU
 * count when it is not. Six is not enough to reach frame 7. So the size is
 * passed explicitly, and the wrapper that omits it — gic_v3_set_paddr — must
 * not be used here, however much simpler it looks.
 *
 * The failure mode of getting that wrong is at least loud: the affinity walk
 * asserts and crashes with a named file and line, rather than hanging. On a
 * board with no console that distinction is most of the debugging budget.
 *
 * M2 adds two things, both there to turn a silent secondary-core failure into a
 * named one: a probe of the redistributor frames on CPU0 before any core
 * depends on them, and a wrapper around the library's per-CPU GIC routine that
 * wakes the redistributor first and checks the result afterwards. M2 ran both
 * on six cores under -Q disable.
 *
 * M1b adds a step 8 to the wrapper, under -Q enable,el2-host only: a check that
 * the core is the VHE host procnto will run on, and the INTID 28 probe
 * (hvtimer.c). Step 8 has not run on the board.
 */

#include "t234_startup.h"
#include <aarch64/gic_v3.h>

/*
 * Frame base from a frame index. Shift 17 is the library's stride on a v3.0
 * GIC (lib/aarch64/gic_v3.c:325-326); M1 logged "arch v3.0" on this part.
 */
#define T234_GICR_FRAME(idx)    ((paddr_t)T234_GICR_BASE + ((paddr_t)(idx) << 17))

/* GICR_WAKER bits, as the library tests them (lib/aarch64/gic_v3.c:1360, :1364). */
#define WAKER_PROCESSOR_SLEEP   (1u << 1)
#define WAKER_CHILDREN_ASLEEP   (1u << 2)

/* The library's per-CPU routine, saved when the board wrapper replaces it. */
static void (*t234_lib_gic_cpu_init)(unsigned);

/* Which CPU the board table puts in frame f, or -1 for an unpopulated frame. */
static int
t234_frame_owner(unsigned const f)
{
	unsigned k;

	for (k = 0; k < T234_NUM_CPU; ++k) {
		if (t234_cpu_gicr_idx[k] == f) {
			return (int)k;
		}
	}
	return -1;
}

/*
 * Read the redistributor frames the library's walk is about to read, on CPU0,
 * before any secondary depends on them.
 *
 * The walk for the highest-numbered CPU the image starts reads frames 0 up to
 * that CPU's frame (lib/aarch64/gic_v3.c:1343-1354), so that is the range read
 * here: frame 0 at -P1, 0-1 at -P2, 0-3 at -P4, 0-6 at -P5, 0-7 at -P6.
 *
 * It settles whether the 32-bit read of TYPER's upper half returns the affinity
 * at all — M1 could not tell, because CPU0's affinity 0 also matches a register
 * that reads as zero — and shows the WAKER state firmware leaves on offlined
 * cores before any CPU_ON. What it cannot settle: an asynchronous SError from
 * frames 4 or 5 would stay pending under DAIF and not be reported here.
 *
 * Runs before init_qtime, so t234_cps() may be the board constant here.
 * num_cpu is 1 from init_syspage_memory (lib/syspage_memory.c:119) or at most
 * T234_NUM_CPU from init_smp (lib/init_smp.c:107-109), so num - 1 indexes the
 * table.
 */
void
t234_gicr_probe(void)
{
	unsigned const num  = lsp.syspage.p->num_cpu;
	unsigned const last = t234_cpu_gicr_idx[num - 1];
	unsigned       f;

	if (debug_flag > 1) {
		kprintf("t234: fdt cpus=%d num_cpu=%d cntvct=%L cps=%L\n",
		        fdt_num_cpu(), num, (_Uint64t)aa64_sr_rd64(cntvct_el0),
		        t234_cps());
	}

	for (f = 0; f <= last; ++f) {
		paddr_t const  frame    = T234_GICR_FRAME(f);
		int const      owner    = t234_frame_owner(f);
		_Uint32t const typer_lo = in32(frame + ARM_GICR_TYPER);
		_Uint32t const typer_hi = in32(frame + ARM_GICR_TYPER + 4);

		if (owner >= 0) {
			_Uint32t const waker = in32(frame + ARM_GICR_WAKER);

			kprintf("t234: gicr frame %d @%P TYPER_hi=%x TYPER_lo=%x WAKER=%x\n",
			        f, frame, typer_hi, typer_lo, waker);

			if ((unsigned)owner < num && (_Uint64t)typer_hi != t234_cpu_mpidr[owner]) {
				crash("t234: gicr frame %d affinity %x != cpu%d %x\n",
				      f, typer_hi, owner, (unsigned)t234_cpu_mpidr[owner]);
			}
		} else {
			/*
			 * Frames 4 and 5: only the two TYPER halves, the same access
			 * upstream Linux already makes on this board with its 64-bit
			 * TYPER read. Neither Linux nor the QNX library reads WAKER on
			 * an unpopulated frame, so neither does this.
			 */
			kprintf("t234: gicr frame %d @%P TYPER_hi=%x TYPER_lo=%x WAKER=-\n",
			        f, frame, typer_hi, typer_lo);

			/*
			 * A cluster-1 affinity here would be matched by the walk before
			 * its real frame, and that core would bind the wrong
			 * redistributor.
			 */
			if ((_Uint64t)typer_hi == t234_cpu_mpidr[4] ||
			    (_Uint64t)typer_hi == t234_cpu_mpidr[5]) {
				crash("t234: gicr frame %d is unpopulated but reads affinity %x: the library walk would bind it for a cluster-1 core\n",
				      f, typer_hi);
			}
		}
	}
}

/*
 * The per-CPU GIC routine as the library calls it: from init_one_cpuinfo
 * (lib/aarch64/init_cpuinfo.c:306-308), on CPU0 during init_cpuinfo and on each
 * secondary itself — at EL1 under -Q disable, or at EL2 with E2H and TGE set
 * under el2-host, MMU off in both — before that secondary clears cpu_starting
 * (lib/aarch64/smp_start.S:83-90). On a secondary CPU0 is silent, so printing
 * here is safe.
 *
 * On CPU0 the final check also confirms that kexec handed over on affinity 0,
 * before any CPU_ON is issued.
 */
void
t234_gic_cpu_init(unsigned const cpu)
{
	volatile struct t234_ap_diag *const d = &t234_ap_diag[cpu];
	_Uint64t const mpidr  = aa64_sr_rd64(mpidr_el1);
	_Uint32t const aff32  = (_Uint32t)((mpidr & 0xFFFFFFull) |
	                                   ((mpidr >> 8) & 0xFF000000ull));
	unsigned const tidx   = t234_cpu_gicr_idx[cpu];
	paddr_t const  tframe = T234_GICR_FRAME(tidx);
	unsigned       idx;
	paddr_t        frame;
	paddr_t        sgi;
	_Uint64t       sgi1r;
	_Uint32t       waker;
	_Uint32t       act;
	_Uint32t       isen;
	const char    *act_state;

	/*
	 * 1. Wake the redistributor before the library looks at it.
	 *
	 * The library's own WAKER code (lib/aarch64/gic_v3.c:1358-1370), run right
	 * after its walk, waits up to 1000 reads for ChildrenAsleep to become 1
	 * under an ASSERT, then clears ProcessorSleep and never waits for
	 * ChildrenAsleep to return to 0. Upstream Linux (gic_enable_redist) and
	 * TF-A (mark_core_awake) do the opposite order: clear ProcessorSleep, then
	 * wait for ChildrenAsleep to clear. The board does that first, against a
	 * real deadline, so when it has run the library sees ProcessorSleep clear
	 * and skips its branch. Its ASSERT stays reachable only when this step was
	 * skipped. Whether WAKER is writable from Non-secure EL1 or EL2 on this GIC
	 * is unknown; if it is RAZ/WI, this reads 0 and does nothing.
	 *
	 * The affinity formula is the library's (gic_v3.c:1340). The frame comes
	 * from the board table, and is used only if it really holds this core.
	 */
	d->stage = T234_STAGE_GIC_WAKE;
	{
		_Uint32t const typer_hi = in32(tframe + ARM_GICR_TYPER + 4);

		if (typer_hi != aff32) {
			kprintf("t234: cpu %d table frame %d TYPER_hi=%x != aff %x, wake step skipped\n",
			        cpu, tidx, typer_hi, aff32);
		} else {
			_Uint32t const fw = in32(tframe + ARM_GICR_WAKER);

			d->waker_fw = fw;
			if ((fw & WAKER_PROCESSOR_SLEEP) != 0) {
				_Uint64t dl;

				out32(tframe + ARM_GICR_WAKER, fw & ~WAKER_PROCESSOR_SLEEP);
				dl = t234_deadline(T234_GICR_WAKE_TIMEOUT_S);
				while ((in32(tframe + ARM_GICR_WAKER) & WAKER_CHILDREN_ASLEEP) != 0) {
					if (t234_expired(dl)) {
						crash("t234: cpu %d redistributor wake timeout WAKER=%x fw=%x\n",
						      cpu, in32(tframe + ARM_GICR_WAKER), fw);
					}
				}
			}
		}
	}

	/* 2. The library's routine, unchanged. */
	d->stage = T234_STAGE_GIC_LIB;
	t234_lib_gic_cpu_init(cpu);
	d->stage = T234_STAGE_GIC_CHECK;

	/*
	 * 3. What the library decided: the frame its walk bound (low 16 bits of
	 * the map entry, gic_v3.c:1356) and the IPI value it built (:1542).
	 */
	idx   = lsp.cpu.aarch64_gicr_map.p->gicr_idx[cpu] & 0xffffu;
	frame = T234_GICR_FRAME(idx);
	sgi   = frame + ARM_GICR_SGI_BASE_OFFSET;
	sgi1r = lsp.cpu.aarch64_gic_map.p->gic_cpu[cpu];

	/* 4. The redistributor must be awake by now, whichever code woke it. */
	if ((in32(frame + ARM_GICR_WAKER) & (WAKER_PROCESSOR_SLEEP | WAKER_CHILDREN_ASLEEP)) != 0) {
		_Uint64t const dl = t234_deadline(T234_GICR_WAKE_TIMEOUT_S);

		while ((in32(frame + ARM_GICR_WAKER) & (WAKER_PROCESSOR_SLEEP | WAKER_CHILDREN_ASLEEP)) != 0) {
			if (t234_expired(dl)) {
				crash("t234: cpu %d redistributor not awake after gicc_init WAKER=%x\n",
				      cpu, in32(frame + ARM_GICR_WAKER));
			}
		}
	}
	waker = in32(frame + ARM_GICR_WAKER);

	/*
	 * 5. Leftover active state. Linux ran split EOI/deactivate, and the library
	 * clears neither ISACTIVER0 nor the active-priority registers, so an SGI or
	 * PPI Linux left active would stay active under procnto. Clear it and say
	 * what was found: "0" nothing was active, "cleared" it was and the clear
	 * took, "stuck" it was and the clear did not take.
	 */
	act = in32(sgi + ARM_GICR_ISACTIVER0);
	if (act == 0) {
		act_state = "0";
	} else {
		out32(sgi + ARM_GICR_ICACTIVER0, act);
		act_state = (in32(sgi + ARM_GICR_ISACTIVER0) == 0) ? "cleared" : "stuck";
	}

	/*
	 * 6. The board's expectation against the library's result. MPIDR is
	 * compared on its affinity fields only: bits 31 (RES1) and 24 (MT) are set
	 * on this part (M1 black-box log:32) and are not in the table.
	 */
	isen = in32(sgi + ARM_GICR_ISENABLER0);
	if ((mpidr & 0xff00ffffffull) != t234_cpu_mpidr[cpu] ||
	    idx != tidx ||
	    sgi1r != t234_cpu_sgi1r[cpu] ||
	    (isen & 1u) == 0) {
		crash("t234: cpu %d MISMATCH MPIDR=%L/%L idx=%d/%d SGI1R=%L/%L ISENABLER0=%x\n",
		      cpu, mpidr, t234_cpu_mpidr[cpu], idx, tidx,
		      sgi1r, t234_cpu_sgi1r[cpu], isen);
	}

	/* 7. The pass-criterion line. */
	kprintf("t234: cpu %d up MPIDR=%L GICR=%P idx=%d SGI1R=%L WAKER=%x fw=%x ISENABLER0=%x ISACTIVER0=%x(%s) AP1R0=%x\n",
	        cpu, mpidr, frame, idx, sgi1r, waker, (unsigned)d->waker_fw, isen,
	        act, act_state, (unsigned)aa64_sr_rd32(S3_0_C12_C9_0));
	d->stage = T234_STAGE_UP;

	/*
	 * 8. el2-host only: prove this core is the VHE host procnto will run on,
	 * and that the clock interrupt the library gave procnto is wired to it.
	 * Runs after this core's own hypervisor_init (CPU0: main.c; a secondary:
	 * lib/aarch64/smp_start.S:73 before :84), so E2H and TGE are set and every
	 * CNTV_* access procnto makes lands on CNTHV_*_EL2, whose PPI the library
	 * named INTID 28 (lib/aarch64/init_qtime_v8gt.c:56-57) without checking it.
	 *
	 * Placed after the up line, so that 0x43 keeps M2's meaning and the stages
	 * stay in time order. Under -Q disable and el1-host nothing here runs or
	 * prints. lsp.qtime is allocated: init_qtime runs before init_cpuinfo on
	 * CPU0 (main.c), long before any secondary starts.
	 */
	if (hypervisor_get_required_flags() == (HYP_FLAG_ENABLED | HYP_FLAG_EL2_HOST)) {
		unsigned const el = (unsigned)(aa64_sr_rd64(CurrentEL) >> 2) & 3u;
		_Uint64t       hcr;
		int            v;

		if (el != 2) {
			crash("t234: cpu %d el2-host requested but running at EL%d, stopping\n", cpu, el);
		}
		hcr = aa64_sr_rd64(hcr_el2);
		if ((hcr & T234_HCR_E2H) == 0 || (hcr & T234_HCR_TGE) == 0) {
			crash("t234: cpu %d el2-host requested but HCR_EL2=%L: E2H and TGE must both be set, stopping\n", cpu, hcr);
		}
		kprintf("t234: cpu %d el2-host EL2 HCR_EL2=%L\n", cpu, hcr);

		d->stage = T234_STAGE_HVT;
		if (t234_hvt_policy == T234_HVT_OFF) {
			kprintf("t234: hvtimer cpu %d probe off (-toff): clock INTID %d not checked\n",
			        cpu, (int)lsp.qtime.p->intr);
		} else {
			/*
			 * Under -tstop the probe crashes itself on anything but wired, so
			 * that the crash text can carry its reason (hvtimer.c). Only
			 * -tcontinue comes back here with another verdict.
			 */
			v = t234_hvt_probe(cpu, sgi);
			if (v != T234_HVT_WIRED && t234_hvt_policy == T234_HVT_CONTINUE) {
				kprintf("t234: hvtimer cpu %d continuing despite verdict=%s (-tcontinue)\n",
				        cpu, t234_hvt_verdict_name(v));
			}
		}
		d->stage = T234_STAGE_HVT_DONE;
	}
}

void
init_intrinfo(void)
{
	/*
	 * Bases and the full region size. No ITS on this part: the device tree
	 * has no ITS child and Linux logs no LPI support, so NULL_PADDR rather
	 * than an address — and NULL_PADDR is all-ones, not zero. A literal 0
	 * would be taken for a real physical address and mapped.
	 */
	gic_v3_set_paddr_range(T234_GICD_BASE, T234_GICR_BASE, T234_GICR_SIZE,
	                       NULL_PADDR);

	/*
	 * System-register callouts, which are already the default. This call is a
	 * no-op as written — the library guards its body on a non-null GICC and
	 * ignores a zero second argument — and it is here for what it documents
	 * rather than what it does: this part has no GICC MMIO aperture, and if
	 * the CPU ever reported no system-register GIC interface the library would
	 * force memory-mapped callouts and then assert, because no aperture was
	 * ever supplied. On A78AE that field is non-zero; Linux logs the
	 * system-register interface at boot.
	 */
	gic_v3_use_mm_reg_callouts(NULL_PADDR, 0);

	/*
	 * Before the library touches a frame. CPU0's fault vectors are live: the
	 * board EL1 table under -Q disable, the board EL2 table under el2-host
	 * (main.c).
	 */
	t234_gicr_probe();

	gic_v3_initialize();

	/*
	 * Wrap the per-CPU routine. gic_cpu_init is a public pointer
	 * (lib/public/aarch64/cpu_startup.h:181) that gic_v3_initialize has just
	 * set (lib/aarch64/gic_v3.c:1096), and its only caller is init_one_cpuinfo,
	 * which has not run yet on any CPU.
	 */
	t234_lib_gic_cpu_init = gic_cpu_init;
	gic_cpu_init          = t234_gic_cpu_init;

	/*
	 * The IPI routine could not be chosen before the GIC version was known.
	 * board_smp_init set it too, so this is belt and braces rather than the
	 * only assignment — cheap insurance against an ordering change leaving the
	 * field null, which would be a silent SMP failure rather than a loud one.
	 */
	{
		struct smp_entry *const smp = lsp.smp.p;

		if (smp != NULL) {
			smp->send_ipi = (void *)gic_sendipi;
		}
	}
}
