/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * Board constants for the QEMU `virt` machine, aarch64, as a KVM guest.
 *
 * Every address below was read from the device tree QEMU itself generates for
 * the exact failing invocation, not taken from documentation or from the ARMv8
 * Foundation Model board this directory is skeletoned from:
 *
 *   qemu-system-aarch64 -machine virt,gic-version=3,dumpdtb=... \
 *                       -cpu host -enable-kvm -smp 2 -m 1G
 *
 * captured 2026-09-18 on the Orin under both QEMU 6.2.0 and 11.1.0, which
 * produce an identical layout. The Foundation Model's addresses differ in
 * every case (its PL011 is at 0x1c090000, its GICD at 0x2f000000), so nothing
 * here may be inherited from that skeleton.
 *
 * Cross-check that the numbers are the right ones: the image that boots today
 * starts its console with `devc-serpl011 -e -F 0x9000000,33`, and the device
 * tree gives pl011@9000000 with `interrupts = <0 1 4>` — SPI 1, so INTID
 * 32 + 1 = 33. The two agree.
 */

#ifndef QEMU_VIRT_STARTUP_H_
#define QEMU_VIRT_STARTUP_H_

#ifndef __ASSEMBLER__
#include <stddef.h>
#include <startup.h>
#include <aarch64/gic.h>
#endif

/*
 * GICv3. GICD is one 64 KiB frame; the redistributor region is sized for many
 * cores (0xf60000 = 123 frames of 0x20000), and the library walks it to find
 * the frame whose TYPER affinity matches each CPU, so the whole region is what
 * it must be given rather than the two frames this guest will use.
 */
#define QV_GICD_BASE        0x08000000u
#define QV_GICR_BASE        0x080A0000u
#define QV_GICR_SIZE        0x00F60000u
#define QV_GITS_BASE        0x08080000u

/*
 * Console. Started from the IFS script, not from here; this is recorded so the
 * board's own debug device and the script cannot drift apart.
 */
#define QV_PL011_BASE       0x09000000u
#define QV_PL011_IRQ        33u

/*
 * RAM. Recorded for reference only: `memory@40000000` in the device tree, size
 * following whatever -m the launch line gives (0x40000000 at -m 1G). startup
 * does NOT hard-code this — init_raminfo_fdt() walks the memory nodes — which
 * is the whole reason this board needs no init_raminfo.c of its own.
 */
#define QV_RAM_BASE         0x40000000ull

/* Where the IFS is placed, from the as-built buildfile's [image=0x40080000]. */
#define QV_IMAGE_BASE       0x40080000ull

#endif /* QEMU_VIRT_STARTUP_H_ */
