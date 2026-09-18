/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * init_asinfo for the QEMU virt board.
 *
 * Empty, as the ARMv8 Foundation Model board's is. The address-space entries
 * this hook exists to add are for board memory that is not RAM and not a
 * device the library already registers; the virt machine has none that startup
 * needs to describe. The GIC's own entries are added by init_intrinfo, and RAM
 * by the RAM path, neither of which goes through here.
 */

#include <startup.h>

void
init_asinfo(unsigned mem)
{
	(void)mem;
}
