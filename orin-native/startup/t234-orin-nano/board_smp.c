/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * Secondary-CPU bring-up: PSCI CPU_ON over SMC, six cores, two clusters.
 *
 * There is no spin table here and no firmware handshake to discover. TF-A
 * started all six cores for Linux at EL2, and CPU_ON is how it hands them back.
 * The geometry is the library's; what this file adds is failure handling,
 * because on this board a hang costs a power cycle and a power cycle wipes the
 * black box that would have explained it.
 *
 * The library's own path has three silent endings, all read in source:
 *
 *   - psci_smp_start throws away CPU_ON's return code
 *     (lib/common_arm/psci_smp.c:37-41), so a refused start and a core that
 *     died later both end as the same "CPU N start failure"
 *     (lib/ap_fail.c:30);
 *   - start_aps waits for the handshake on an uncalibrated 2^32-iteration
 *     counter (lib/init_smp.c:73-76), printing nothing until it wraps;
 *   - transfer_aps waits for each core to park with no bound at all
 *     (lib/init_smp.c:54-56).
 *
 * Here the return code is named, and both waits have a real-time deadline that
 * ends in a crash() naming the core and how far it got. None of it patches the
 * library: board_smp_start replaces the CPU_ON entry point with t234_ap_entry,
 * and main() swaps smp_hook_rtn for t234_transfer_aps at the one moment that
 * is safe. The part that is not failure handling is psci_cpu_id.c next door:
 * the affinities are not the linear indices.
 *
 * Nothing in this file has run on the board with more than one CPU.
 */

#include "t234_startup.h"

#include <hw/inout.h>          /* mem_barrier(), as lib/init_smp.c uses it */
#include <aarch64/psci.h>

/* Both are plain globals in lib/init_smp.c:30-31; no header declares them. */
extern volatile int cpu_starting;
extern volatile int syspage_available;

/*
 * MPIDR affinities from the live device tree's cpu@ reg cells. Cluster 0 holds
 * four cores at 0x0, 0x100, 0x200, 0x300; cluster 1 holds two at 0x10200 and
 * 0x10300. The gap is real — this SKU is floor-swept, and the missing cores'
 * redistributor frames (4 and 5) sit unoccupied in the middle of the region.
 */
const _Uint64t t234_cpu_mpidr[T234_NUM_CPU] = {
	0x00000ull, 0x00100ull, 0x00200ull, 0x00300ull, 0x10200ull, 0x10300ull,
};

/*
 * Redistributor frame index per CPU: Linux's own frame bases (0x0f440000 for
 * CPU0, then 0x20000 apart, with cluster 1 at 0x0f500000 and 0x0f520000)
 * divided by the library's stride (lib/aarch64/gic_v3.c:325, shift 17 on a v3.0
 * GIC). CPU0's index 0 is what M1 recorded (M1 black-box log:103); the other
 * five are what this port expects and have not been observed yet.
 */
const unsigned t234_cpu_gicr_idx[T234_NUM_CPU] = { 0, 1, 2, 3, 6, 7 };

/*
 * ICC_SGI1R_EL1 value per CPU, as the library builds it for its IPI callout
 * (lib/aarch64/gic_v3.c:1523-1531): target-list bit Aff0, Aff1 at 16, Aff2 at
 * 32. CPU0's 0x1 is M1's recorded gic_map (M1 black-box log:101); the rest are
 * the formula applied to the table above, not yet observed.
 */
const _Uint64t t234_cpu_sgi1r[T234_NUM_CPU] = {
	0x000000001ull, 0x000010001ull, 0x000020001ull, 0x000030001ull,
	0x100020001ull, 0x100030001ull,
};

/*
 * One diagnostic record per core (layout in t234_startup.h). Placed in .data
 * next to where the library keeps its own AP stack (lib/aarch64/smp_start.S:
 * 112-115), so its zero contents are part of the loaded image itself rather
 * than something cstart's .bss clear has to have provided.
 */
volatile struct t234_ap_diag t234_ap_diag[T234_NUM_CPU]
	__attribute__((__section__(".data")));

unsigned
board_smp_num_cpu(void)
{
	unsigned num = fdt_num_cpu();

	if (num == 0 || num > T234_NUM_CPU) {
		/*
		 * No device tree, or one describing a machine this file was not
		 * written for. Six is what this SKU has; -P caps it below that and
		 * the library applies that cap itself.
		 */
		num = T234_NUM_CPU;
	}
	return num;
}

void
board_smp_init(struct smp_entry *smp, unsigned num_cpus)
{
	(void)num_cpus;

	/*
	 * The IPI routine is set again in init_intrinfo once the GIC is up, which
	 * is where the correct one is finally known. Setting it here as well keeps
	 * the field from being left null if the order ever changes.
	 */
	smp->send_ipi = (void *)gic_sendipi;
}

/*
 * PSCI error codes by name (lib/public/aarch64/psci.h:67-76), so a refused
 * CPU_ON reads as a reason rather than a negative number in hex.
 */
static const char *
t234_psci_name(int32_t const r)
{
	switch (r) {
	case PSCI_NOT_SUPPORTED:      return "NOT_SUPPORTED";
	case PSCI_INVALID_PARAMETERS: return "INVALID_PARAMETERS";
	case PSCI_DENIED:             return "DENIED";
	case PSCI_ALREADY_ON:         return "ALREADY_ON";
	case PSCI_ON_PENDING:         return "ON_PENDING";
	case PSCI_INTERNAL_FAILURE:   return "INTERNAL_FAILURE";
	case PSCI_NOT_PRESENT:        return "NOT_PRESENT";
	case PSCI_DISABLED:           return "DISABLED";
	case PSCI_INVALID_ADDRESS:    return "INVALID_ADDRESS";
	default:                      break;
	}
	return "unknown";
}

/*
 * Start one secondary and wait until it has finished its own startup.
 *
 * On entry cpu_starting == cpu + 1, set by start_aps just before this call
 * (lib/init_smp.c:70-72). The secondary clears it only after init_one_cpuinfo,
 * which includes the GIC wrapper and its "cpu N up" line
 * (lib/aarch64/smp_start.S:83-91).
 *
 * `start` is smp_start; it is deliberately not used. The core enters at
 * t234_ap_entry, which normalises EL2 state and records what firmware left,
 * and then branches to smp_start itself.
 *
 * Returning 1 only after cpu_starting has been seen 0 makes the library's own
 * counter loop run exactly one iteration (lib/init_smp.c:73-76), so its
 * uncalibrated ap_fail path stays as an unreachable backstop.
 */
int
board_smp_start(unsigned cpu, void (*start)(void))
{
	_Uint64t const aff   = psci_cpu_id(cpu);
	paddr_t const  entry = (paddr_t)(uintptr_t)t234_ap_entry;
	int32_t const  ai    = psci_affinity_info(aff, 0);
	int32_t        r;

	(void)start;

	/*
	 * Safe to print: the previous secondary has already cleared its handshake
	 * and is in a silent loop waiting for syspage_available
	 * (lib/aarch64/smp_start.S:96-99).
	 */
	if (debug_flag > 1) {
		kprintf("t234: cpu %d CPU_ON aff=%L entry=%P affinity_info=%x\n",
		        cpu, aff, entry, (unsigned)ai);
	}

	t234_ap_diag[cpu].stage = T234_STAGE_CPU_ON;
	r = psci_cpu_on(aff, (uintptr_t)t234_ap_entry, 0);
	if (r != PSCI_SUCCESS) {
		crash("t234: cpu %d CPU_ON aff=%L entry=%P returned %x (%s)\n",
		      cpu, aff, entry, (unsigned)r, t234_psci_name(r));
	}

	/*
	 * From here until cpu_starting reads 0 the secondary owns the console, so
	 * CPU0 prints nothing unless the deadline expires — and that path is a
	 * crash anyway. The polarity is the whole point: success is the secondary
	 * writing 0 (lib/aarch64/smp_start.S:90), so the loop runs while it is
	 * still non-zero.
	 */
	{
		_Uint64t const dl = t234_deadline(T234_AP_START_TIMEOUT_S);

		while (cpu_starting != 0) {
			if (t234_expired(dl)) {
				int32_t const ai2 = psci_affinity_info(aff, 0);

				crash("t234: cpu %d start timeout %d s: stage=%x affinity_info=%x\n",
				      cpu, T234_AP_START_TIMEOUT_S,
				      t234_ap_diag[cpu].stage, (unsigned)ai2);
			}
		}
	}

	t234_ap_diag[cpu].stage = T234_STAGE_HANDSHAKE;
	return 1;
}

/*
 * Runs on the secondary, at its entry EL, on the library stack, before
 * hypervisor_init (lib/aarch64/smp_start.S:57-73). CPU0 is in board_smp_start's
 * silent wait, so printing here cannot interleave.
 */
unsigned
board_smp_adjust_num(unsigned cpu)
{
	volatile struct t234_ap_diag *const d = &t234_ap_diag[cpu];

	/*
	 * The same table main() gives CPU0, and for the same reason: smp_start has
	 * just installed vbar_default (smp_start.S:44-45), and everything this core
	 * does at EL1 until procnto takes over would otherwise fault silently.
	 */
	t234_install_el1_vectors();
	d->stage = T234_STAGE_EL1_VECTORS;

	/*
	 * What t234_ap_entry found, printed now that there is a stack. The EL2
	 * fields read 0 when the core entered at EL1.
	 */
	if (debug_flag > 0) {
		kprintf("t234: cpu %d entry EL%d MPIDR=%L HCR_EL2=%L SCTLR_EL2=%L CNTFRQ=%x\n",
		        cpu, d->entry_el, d->mpidr, d->hcr_el2, d->sctlr_el2,
		        (unsigned)d->cntfrq);
		kprintf("t234: cpu %d fw MDCR_EL2=%L HSTR_EL2=%L ICH_HCR_EL2=%L CNTHP_CTL=%x CNTP_CTL=%x CNTV_CTL=%x -> normalised\n",
		        cpu, d->mdcr_el2, d->hstr_el2, d->ich_hcr_el2,
		        (unsigned)d->cnthp_ctl, (unsigned)d->cntp_ctl,
		        (unsigned)d->cntv_ctl);
	}

	/*
	 * Fail closed on EL1 entry. At EL1, _start_el2_or_el1 returns without a
	 * single write (lib/aarch64/_start_el1.S:64-66), and under -Q disable the
	 * hypervisor code does nothing either (lib/aarch64/hypervisor.c:38-44,
	 * :80-87). Whatever HCR_EL2 routing, trap bits and VBAR_EL2 firmware left
	 * would persist unseen. Linux on this board reports all CPUs starting at
	 * EL2, so EL1 here would itself be the finding; allowing it would first
	 * need NVIDIA's T234 TF-A read, and a rebuild.
	 */
	if (d->entry_el != 2) {
		crash("t234: cpu %d entered at EL%d: EL2 trap and vector state cannot be read or normalised from EL1, stopping\n",
		      cpu, d->entry_el);
	}

	return cpu;
}

/*
 * The library's transfer_aps (lib/init_smp.c:39-58), with a deadline.
 *
 * Installed by main() as smp_hook_rtn after init_system_private() returns, so
 * it runs from _main after write_syspage_memory (lib/_main.c:151-156). CPU0 is
 * still in startup with the MMU off; the secondaries print nothing in this
 * phase (their next output is procnto's).
 */
void
t234_transfer_aps(void)
{
	unsigned const        num = lsp.syspage.p->num_cpu;
	volatile uint32_t    *pending;
	unsigned              i;

	/*
	 * Ordering precheck, before anything is released. If this hook were
	 * installed early enough to be the first smp_hook_rtn call, no CPU_ON
	 * would ever have been issued, and the failure would surface below as a
	 * misleading "released but pending" timeout. Every secondary that
	 * start_aps handled has stage 0x50; anything else means start_aps never
	 * ran.
	 */
	for (i = 1; i < num; ++i) {
		if (t234_ap_diag[i].stage != T234_STAGE_HANDSHAKE) {
			crash("t234: transfer hook ran before cpu %d handshake (stage=%x): smp_hook_rtn installed too early\n",
			      i, t234_ap_diag[i].stage);
		}
	}

	/* The same expression as the library, so the semantics are identical. */
	pending = &SYSPAGE_ENTRY(smp)->pending;

	for (i = 1; i < num; ++i) {
		/* Get one AP into the syspage spin callout. */
		*pending = 1;
		mem_barrier();
		t234_ap_diag[i].stage = T234_STAGE_RELEASED;

		/*
		 * Printed before the release: core i is still in its silent
		 * syspage_available loop and the earlier ones are in smp_spin. If a
		 * core dies with the MMU on, its fault handler resets without
		 * printing, and this is the line that names it.
		 */
		if (debug_flag > 1) {
			kprintf("t234: cpu %d -> smp_spin\n", i);
		}
		syspage_available = i;

		{
			_Uint64t const dl = t234_deadline(T234_AP_PARK_TIMEOUT_S);

			while (*pending != 0) {
				if (t234_expired(dl)) {
					int32_t const ai = psci_affinity_info(psci_cpu_id(i), 0);

					crash("t234: cpu %d released but smp.pending still set after %d s (cpu_startnext/vstart/smp_spin) affinity_info=%x\n",
					      i, T234_AP_PARK_TIMEOUT_S, (unsigned)ai);
				}
				mem_barrier();   /* give the bus a break, as the library does */
			}
		}
		t234_ap_diag[i].stage = T234_STAGE_PARKED;
	}

	kprintf("t234: all %d cpus parked in smp_spin\n", num);
}
