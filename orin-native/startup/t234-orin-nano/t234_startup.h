/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * Board constants for startup-t234-orin-nano (Jetson Orin Nano Developer Kit,
 * Tegra234, six Cortex-A78AE).
 *
 * Every address here was read off the running board or out of the upstream
 * device tree, not out of a datasheet we do not have — the Tegra234 TRM is
 * login-gated and was never consulted. Where a value came from a live read it
 * says so, because a constant whose provenance is forgotten is the thing that
 * quietly breaks a port six months later.
 *
 * Provenance: results/orin-native-port/20260909T1100Z/harvest-orin.md,
 * research-tegra234.md, blackbox-verified.md.
 */

#ifndef T234_STARTUP_H_
#define T234_STARTUP_H_

/*
 * The addresses below are shared with callout_debug_tcu.S and ap_entry.S, so
 * everything that is not a plain #define has to hide from the assembler.
 */
#ifndef __ASSEMBLER__
#include <stddef.h>
#include <startup.h>
#include <aarch64/gic.h>
#endif

/* ---- GIC-600, a plain GICv3: no ITS, no GICV, system-register CPU interface.
 * GICD and GICR bases and the region size are from the live device tree and
 * from Linux's own probe messages ("GICv3: CPU0: found redistributor 0 region
 * 0:0x000000000f440000", and 960 SPIs).
 *
 * The region size matters more than it looks. Frames are 0x20000 apart, so the
 * 2 MiB region holds 16 of them, but only six are populated and not
 * contiguously: CPUs 0-3 in frames 0-3, and the two cluster-1 cores in frames
 * 6 and 7. Passing the size explicitly makes the library's frame limit 16;
 * letting it default ties the limit to the CPU count, which is 6, and the
 * affinity walk then asserts before it ever reaches frame 7. */
#define T234_GICD_BASE      0x0F400000u
#define T234_GICR_BASE      0x0F440000u
#define T234_GICR_SIZE      0x00200000u      /* 16 frames of 0x20000 */
#define T234_GIC_NUM_SPI    960u

/* ---- Tegra Combined UART. Not a UART: a pair of HSP shared mailboxes that
 * the SPE demultiplexes onto the physical debug port. Transmit and receive
 * live in different HSP blocks, so they are two separate mappings.
 *
 * Word layout, identical in both directions: bytes in 23:0, count in 25:24,
 * Flush 26, HwFlush 27, FULL 31. The writer sets FULL; the consumer clears it
 * by writing the whole word as zero. */
#define T234_TCU_TX         0x0C168000u      /* AON HSP, shared mailbox 1  */
#define T234_TCU_RX         0x03C10000u      /* TOP0 HSP, shared mailbox 0 */

#define TCU_FULL            (1u << 31)
#define TCU_HWFLUSH         (1u << 27)
#define TCU_FLUSH           (1u << 26)
#define TCU_COUNT_SHIFT     24
#define TCU_COUNT_MASK      0x3u

/* ---- Alternative debug ports, both 16550-class at a 4-byte register stride.
 * uarta is the one Linux exposes as ttyTHS1 and the one the 40-pin header
 * carries; uarti is the SBSA-style port. Neither is on the critical path —
 * they exist so that -D can move the console if the TCU turns out to be dead
 * once Linux is gone, which is the one thing about the console that no amount
 * of reading could settle in advance. */
#define T234_UARTA_BASE     0x03100000u
#define T234_UARTA_SHIFT    2
#define T234_UARTA_IRQ      144u             /* SPI 112 */
#define T234_UARTI_BASE     0x031D0000u
#define T234_UARTI_SHIFT    2

/* ---- TKE watchdogs. WDT0 is armed by systemd at two minutes and is counting
 * when the payload takes over — verified by reading WDTCR/WDTSR on the running
 * board, not inferred from the device tree, whose watchdog node is disabled and
 * is a different node from the one the driver actually binds.
 *
 * That is free unattended recovery and a hard two-minute budget at the same
 * time, which is why -W exists. */
#define T234_WDT0_BASE      0x02190000u
#define T234_WDT1_BASE      0x021A0000u
#define T234_WDT_CR         0x00u
#define T234_WDT_SR         0x04u
#define T234_WDT_CMDR       0x08u
#define T234_WDT_UR         0x0Cu
#define T234_WDT_UNLOCK     0xC45Au
#define T234_WDT_CMD_DISABLE 0x02u

/* ---- Memory. The firmware device tree has no /memory node and kexec does not
 * add one, so this cannot be read from anywhere: it is the lowest System RAM
 * range as /proc/iomem reports it on the running kernel. It is the lowest of
 * about seven disjoint fragments, not the whole 8 GB, and exclusive ownership
 * of it after Linux is gone is an assumption this port has not yet tested. */
#define T234_RAM_BASE       0x80000000ull
#define T234_RAM_SIZE       0x3E000000ull     /* 992 MiB */

/* ---- The RAM black box: the ramoops console zone, at the carveout base plus
 * the dump area the kernel puts ahead of it. Located and its format read
 * directly out of memory on the running board, not inferred.
 *
 * This is the only output channel that does not depend on a wire nobody has
 * attached yet. It survives a PSCI reset and an exception the shim's vectors
 * turn into one; it does NOT survive a power cycle, so anything that hangs
 * takes its own evidence with it.
 *
 * Header is three little-endian words — signature, write cursor, length —
 * followed by the data. startup appends after whatever the shim left rather
 * than starting again, so one recovered zone holds both. */
#define T234_BB_BASE        0x272770000ull
#define T234_BB_SIG         0x43474244u      /* 'D','B','G','C' in memory order */
#define T234_BB_MAP         0x10000u         /* map 64 KiB: -vvv and the syspage fit */
#define T234_BB_LIMIT       (T234_BB_MAP - 16u)

/* ---- The shim. kexec places our 8 KiB page here and the vectors it installs
 * stay live through startup, so this range must never be handed to the RAM
 * allocator. */
#define T234_SHIM_BASE      0x80080000ull
#define T234_SHIM_SIZE      0x2000ull

/* ---- The six cores' MPIDR affinities, from the live device tree's cpu@ reg
 * cells. They are not the linear indices 0..5 — cluster 1 starts at 0x10200 —
 * and the library's default PSCI id mapping returns the index verbatim, so a
 * board override is not optional here. */
#define T234_NUM_CPU        6

/* ---- M2: one diagnostic record per core, written by the secondary itself.
 *
 * Why it exists: a core that dies before the library's handshake is silent
 * until an uncalibrated 2^32-iteration counter wraps (lib/init_smp.c:73-76),
 * and then says only "CPU N start failure" — the same words a refused CPU_ON
 * produces (lib/ap_fail.c:30). A stage number and the register values the
 * core found at entry turn that into "which step it never finished, and what
 * firmware left behind".
 *
 * aarch64/ap_entry.S writes this record with the MMU off and no stack, so the
 * layout is spelled out here as plain offsets (no C suffixes: the assembler
 * reads these too). The C view below asserts every one of them at compile
 * time, so the two cannot drift apart without the build failing. */
#define T234_DIAG_STAGE         0
#define T234_DIAG_ENTRY_EL      4
#define T234_DIAG_MPIDR         8
#define T234_DIAG_HCR_EL2       16
#define T234_DIAG_SCTLR_EL2     24
#define T234_DIAG_MDCR_EL2      32
#define T234_DIAG_HSTR_EL2      40
#define T234_DIAG_ICH_HCR_EL2   48
#define T234_DIAG_CNTHP_CTL     56
#define T234_DIAG_CNTP_CTL      64
#define T234_DIAG_CNTV_CTL      72
#define T234_DIAG_CNTFRQ        80
#define T234_DIAG_WAKER_FW      88
#define T234_DIAG_SIZE          96

/* Stages, in the order a healthy secondary passes them. The owner of each
 * write is the CPU in the comment; a timeout prints the last one reached. */
#define T234_STAGE_CPU_ON       0x10    /* CPU0: CPU_ON issued                       */
#define T234_STAGE_TRAMP_IN     0x20    /* AP:   t234_ap_entry reached               */
#define T234_STAGE_TRAMP_NORM   0x21    /* AP:   EL2 state normalised (EL2 entry)    */
#define T234_STAGE_EL1_VECTORS  0x30    /* AP:   board_smp_adjust_num, vectors in    */
#define T234_STAGE_GIC_WAKE     0x40    /* AP:   GIC wrapper entered, wake step      */
#define T234_STAGE_GIC_LIB      0x41    /* AP:   library gicc_init called            */
#define T234_STAGE_GIC_CHECK    0x42    /* AP:   library returned, board checks      */
#define T234_STAGE_UP           0x43    /* AP:   "cpu N up" printed                  */
#define T234_STAGE_HANDSHAKE    0x50    /* CPU0: saw cpu_starting == 0               */
#define T234_STAGE_RELEASED     0x60    /* CPU0: released towards smp_spin          */
#define T234_STAGE_PARKED       0x70    /* CPU0: saw smp.pending == 0                */

/* Real-time bounds, in seconds of CPU0's generic counter. 15 s for a start
 * because a secondary's -vvv output is about 1 KB through a throttled mailbox;
 * a timeout that fires while it is still printing shows as stage 0x43 not
 * reached, with its partial lines just ahead of the crash text. */
#define T234_AP_START_TIMEOUT_S     15
#define T234_AP_PARK_TIMEOUT_S      5
#define T234_GICR_WAKE_TIMEOUT_S    1

/* CPU0's CNTFRQ_EL0 on this board, 31.25 MHz: the shim's register bank and
 * M1's qtime section both read it (logs/sample-boot/
 * orin-native-m1-reboot-blackbox.log:18 and :50). Used when the syspage value
 * does not exist yet; a secondary's own CNTFRQ_EL0 is never trusted for a
 * deadline, because nothing has shown what firmware leaves in it. */
#define T234_CNTFRQ_FALLBACK    0x1dcd650

#ifndef __ASSEMBLER__
extern const _Uint64t t234_cpu_mpidr[T234_NUM_CPU];
extern const unsigned t234_cpu_gicr_idx[T234_NUM_CPU];
extern const _Uint64t t234_cpu_sgi1r[T234_NUM_CPU];
extern _Uint64t       t234_ram_size_override;

struct t234_ap_diag {
	_Uint32t	stage;
	_Uint32t	entry_el;
	_Uint64t	mpidr;
	_Uint64t	hcr_el2;
	_Uint64t	sctlr_el2;
	_Uint64t	mdcr_el2;
	_Uint64t	hstr_el2;
	_Uint64t	ich_hcr_el2;
	_Uint64t	cnthp_ctl;
	_Uint64t	cntp_ctl;
	_Uint64t	cntv_ctl;
	_Uint64t	cntfrq;
	_Uint64t	waker_fw;
};

#define T234_DIAG_CHECK(field, off)                                           \
	_Static_assert(offsetof(struct t234_ap_diag, field) == (off),         \
	               "struct t234_ap_diag." #field " is not at " #off       \
	               ": ap_entry.S would write the wrong field")
T234_DIAG_CHECK(stage,       T234_DIAG_STAGE);
T234_DIAG_CHECK(entry_el,    T234_DIAG_ENTRY_EL);
T234_DIAG_CHECK(mpidr,       T234_DIAG_MPIDR);
T234_DIAG_CHECK(hcr_el2,     T234_DIAG_HCR_EL2);
T234_DIAG_CHECK(sctlr_el2,   T234_DIAG_SCTLR_EL2);
T234_DIAG_CHECK(mdcr_el2,    T234_DIAG_MDCR_EL2);
T234_DIAG_CHECK(hstr_el2,    T234_DIAG_HSTR_EL2);
T234_DIAG_CHECK(ich_hcr_el2, T234_DIAG_ICH_HCR_EL2);
T234_DIAG_CHECK(cnthp_ctl,   T234_DIAG_CNTHP_CTL);
T234_DIAG_CHECK(cntp_ctl,    T234_DIAG_CNTP_CTL);
T234_DIAG_CHECK(cntv_ctl,    T234_DIAG_CNTV_CTL);
T234_DIAG_CHECK(cntfrq,      T234_DIAG_CNTFRQ);
T234_DIAG_CHECK(waker_fw,    T234_DIAG_WAKER_FW);
_Static_assert(sizeof(struct t234_ap_diag) == T234_DIAG_SIZE,
               "struct t234_ap_diag is not T234_DIAG_SIZE: ap_entry.S indexes by it");
#undef T234_DIAG_CHECK

/*
 * volatile because two CPUs share it: CPU0 reads a stage an AP wrote, inside a
 * wait loop that itself writes nothing, and must not be allowed to hoist that
 * read out of the loop.
 */
extern volatile struct t234_ap_diag t234_ap_diag[T234_NUM_CPU];

/*
 * Counts per second for startup-time deadlines: CPU0's CNTFRQ as init_qtime
 * recorded it (lib/aarch64/init_qtime_v8gt.c:55), or the board constant.
 *
 * A NULL test alone is not enough. Before init_qtime runs — and main() calls
 * init_intrinfo, hence t234_gicr_probe, first — lsp.qtime.p is not NULL:
 * init_syspage_memory points every unallocated section at the end of the
 * syspage header with size 0 (lib/syspage_memory.c:97-100), and later
 * sections slide along with it, so the pointer would read some other
 * section's bytes. A zero size is the library's own test for "not yet
 * allocated" (lib/alloc_qtime.c:36).
 */
static __inline__ _Uint64t
t234_cps(void)
{
	const struct qtime_entry *const qt = lsp.qtime.p;

	if (qt == NULL || lsp.qtime.size == 0 || qt->cycles_per_sec == 0) {
		return T234_CNTFRQ_FALLBACK;
	}
	return qt->cycles_per_sec;
}

/*
 * A deadline on the virtual counter. at_el2 zeroes CNTVOFF_EL2
 * (lib/aarch64/_start_el1.S:180) and sets CNTHCTL_EL2 to 3 (:167-168), so at
 * EL1 this reads the physical count without a trap, on CPU0 and on every
 * secondary. 64 bits at 31.25 MHz do not wrap in any run this port will make.
 */
static __inline__ _Uint64t
t234_deadline(unsigned const secs)
{
	return aa64_sr_rd64(cntvct_el0) + (t234_cps() * (_Uint64t)secs);
}

static __inline__ int
t234_expired(_Uint64t const dl)
{
	return aa64_sr_rd64(cntvct_el0) >= dl;
}

/* ---- board pieces, defined across this directory ---- */
void         t234_init_raminfo(void);
void         t234_wdt_report(void);
void         t234_wdt_apply(const char *policy);
void         t234_probe_hv_timer(void);
void         t234_install_el1_vectors(void);
void         init_tcu(unsigned channel, const char *init, const char *defaults);
void         put_tcu(int c);

/* M2: SMP bring-up. t234_ap_entry is a CPU_ON entry point, never called. */
void         t234_ap_entry(void);
void         t234_transfer_aps(void);
void         t234_gicr_probe(void);
void         t234_gic_cpu_init(unsigned cpu);
void         t234_el2_fault(unsigned long idx, unsigned long esr,
                            unsigned long elr, unsigned long far,
                            unsigned long spsr);

extern struct callout_rtn display_char_tcu;
extern struct callout_rtn poll_key_tcu;
extern struct callout_rtn break_detect_tcu;

unsigned     tcu_drop_count(void);
#endif /* !__ASSEMBLER__ */

#endif /* T234_STARTUP_H_ */
