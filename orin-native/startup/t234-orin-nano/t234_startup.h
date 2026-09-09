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
 * The addresses below are shared with callout_debug_tcu.S, so everything
 * that is not a plain #define has to hide from the assembler.
 */
#ifndef __ASSEMBLER__
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

#ifndef __ASSEMBLER__
extern const _Uint64t t234_cpu_mpidr[T234_NUM_CPU];
extern _Uint64t       t234_ram_size_override;

/* ---- board pieces, defined across this directory ---- */
void         t234_init_raminfo(void);
void         t234_wdt_report(void);
void         t234_wdt_apply(const char *policy);
void         t234_probe_hv_timer(void);
void         init_tcu(unsigned channel, const char *init, const char *defaults);
void         put_tcu(int c);

extern struct callout_rtn display_char_tcu;
extern struct callout_rtn poll_key_tcu;
extern struct callout_rtn break_detect_tcu;

unsigned     tcu_drop_count(void);
#endif /* !__ASSEMBLER__ */

#endif /* T234_STARTUP_H_ */
