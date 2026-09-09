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
 * Widening this is a later, separate step that must start by re-reading
 * /proc/iomem after the DMA masters have been quiesced, not by trusting the
 * numbers written here.
 */

#include "t234_startup.h"

_Uint64t t234_ram_size_override;

void
t234_init_raminfo(void)
{
	_Uint64t size = (t234_ram_size_override != 0)
	              ? t234_ram_size_override
	              : T234_RAM_SIZE;

	add_ram(T234_RAM_BASE, size);

	/*
	 * Deliberately not added, and each for its own reason:
	 *
	 *   0x40000000  SysRAM, which the BPMP uses for inter-processor channels.
	 *   0xBE000000  a range whose owner we could not establish.
	 *   above 4 GB  the other System RAM fragments, once their carve-outs are
	 *               mapped out properly rather than guessed at.
	 *   the ramoops carveout at 0x2_725F0000, which is where startup and the
	 *               shim write their black-box output. It is above 4 GB and so
	 *               outside the claimed range anyway, but it is named here so
	 *               that whoever widens the range does not silently reclaim
	 *               the one output channel this port has before it has a
	 *               console.
	 */
}
