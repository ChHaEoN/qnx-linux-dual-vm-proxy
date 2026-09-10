/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * init_asinfo — the board's hook into address-space description.
 *
 * The library calls this from add_ram for every RAM range a board declares, so
 * that a board with a non-uniform memory map can attach attributes to what was
 * just added. It has no default: leaving it out links fine when the board
 * directory is built, because a startup is a relocatable object, and fails at
 * mkifs time when the image is finally linked. That is a long way from the
 * mistake, which is why it is worth a file of its own rather than a line
 * somewhere.
 *
 * Empty here, deliberately. The one range this board declares is plain
 * conventional DRAM, and the entries that matter — the GIC distributor and
 * redistributor apertures — are added by the library itself when
 * gic_v3_set_paddr_range runs. There is nothing this board knows about that
 * range that the library does not.
 *
 * When the memory map grows past the first 992 MiB fragment, this is where the
 * carve-outs between the fragments would be described.
 */

#include "t234_startup.h"

void
init_asinfo(unsigned mem)
{
	(void)mem;
}
