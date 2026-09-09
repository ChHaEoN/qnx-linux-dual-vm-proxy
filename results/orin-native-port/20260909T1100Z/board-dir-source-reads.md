# The three source reads the board directory needed (§14 item 6, 2026-09-09)

Three focused reads of Apache-2.0 and BSD source, run before writing any board code so that the code is
written against what the library actually does rather than against what the plan assumed it does. All three
came back determinable. No QNX binary was disassembled; these are source reads, which is what the licence
permits and what the whole approach rests on.

## 1. GICv3: how a board reaches all six redistributor frames

The plan's fix F3 — call `gic_v3_set_paddr_range` rather than `gic_v3_set_paddr` — is confirmed, and the
mechanism is now exact rather than inferred.

`gic_v3_set_paddr(gicd, gicr, gits)` is a one-line wrapper for `gic_v3_set_paddr_range(gicd, gicr, 0, gits)`,
and a zero size makes the library derive the limit from the CPU count: `gicr_index_limit = board_smp_num_cpu()`,
which on this SKU is 6. The redistributor frames it must reach are **not** contiguous — CPUs 0-3 occupy frames
0-3, but the two cluster-1 cores occupy frames **6 and 7**, with 4 and 5 belonging to floor-swept cores. A
limit of 6 can never reach frame 7. Passing the real region size instead gives
`gicr_index_limit = gicr_size >> 17 = 0x200000 >> 17 = 16`, which spans it.

The frame walk in `gic_v3_gicc_init` compares each frame's `GICR_TYPER` affinity against the CPU's own and
advances until it matches. It does **not** consult `GICR_TYPER.Last` — that macro is defined in the header and
referenced nowhere in the implementation — and it has no special case for an unpopulated frame, so walking
past frames 4 and 5 is fine as long as they are inside the mapped region. What it does have is
`ASSERT(gicr_index < gicr_index_limit)` inside the loop, which calls `crash()` unconditionally, release build
included. So the failure mode of getting this wrong is a named startup abort, not a silent hang — useful,
given the board has no console until we give it one.

A second trap worth recording. `gic_v3_use_mm_reg_callouts(NULL_PADDR, 0)` is a **complete no-op**: the
function's body is guarded on `gicc != NULL_PADDR`, and `use == 0` leaves the default alone. System-register
callouts are already the default, statically. But `gic_v3_initialize` re-checks the CPU: if
`ID_AA64PFR0_EL1[27:24]` reports no system-register GIC interface it forces memory-mapped callouts and then
asserts that a GICC base was supplied — which it was not. On this board that field is non-zero (Linux logs
`GIC system register CPU interface`), so the path is safe, but the board should pass `NULL_PADDR` rather than
`0`: `NULL_PADDR` is all-ones, and a literal `0` would be taken as a real physical address and mapped.

## 2. EL2 host: what `hyp_enable_el2_host` expects, and the one ordering that is enforced

`hyp_enable_el2_host` is seven instructions. It zeroes `CNTHP_CTL_EL2` and then ORs `TGE` and `E2H` into
`HCR_EL2`, leaving every other field as found. It touches nothing else — not `SCTLR_EL2`, not `CPTR_EL2`, not
`VBAR_EL2`, not the GIC system-register enable — and it performs no exception-level check of its own. All of
that baseline is `at_el2`'s job, which the library runs on the boot CPU and on every secondary before this is
reached. This is exactly the dependency the plan's K3 describes, now read rather than assumed.

Feasibility is two gates. If `CurrentEL >> 2 == 1` the CPU is already at EL1 and any `-Q enable` crashes
immediately. At EL2, EL2-host is possible when `ID_AA64MMFR1_EL1 & 0x0f00` is non-zero. Asking for `el2-host`
explicitly when that field is zero is a hard crash; asking for plain `enable` silently downgrades to EL1-host.
That asymmetry is worth knowing before choosing which to write in the buildfile.

**`hypervisor_init(0)` must be called before `init_smp`, `init_mmu`, `init_intrinfo` and `init_qtime`**, and
two of those are enforced rather than conventional. Before `init_smp`, because secondaries call
`hypervisor_init(cpunum)` from their own startup path and the library crashes if their flags do not match the
ones CPU 0 recorded — flags CPU 0 has not recorded yet if the order is wrong. Before `init_mmu` and
`init_qtime`, because enabling VHE redirects most EL1 register accesses to their EL2 counterparts, so any EL1
configuration done first is simply not carried over. The library's own comment says so.

One thing the reviewer explicitly declined to call load-bearing: `init_intrinfo`'s position after
`hypervisor_init` appears to be convention, with no source-level dependency found. Recorded as convention.

`-Q` needs nothing from the board. The library's common option handler parses it; the board only has to pass
unrecognised options through to `handle_common_option`.

## 3. TCU receive: release by writing zero, and why the reference implementation looks like it does not

The plan's K4 recorded release-by-writing-zero as verified. It is correct, but the reference implementation
obscures it, and the obscuring detail matters for anyone writing the callout.

NVIDIA's `TegraCombinedSerialPortLib` consumes **one byte per call**. When bytes remain in the word it shifts
the remaining ones down and writes the word back with bit 31 still set — using the hardware register as its
own scratch buffer between calls. Only on the call that takes the last byte does it write a literal zero, and
that is the release. So a reader that copied the reference implementation's shape without understanding it
could easily write back a word that does not release the mailbox at all.

A QNX `poll_key` does not need any of that. Read the whole word once, take all one to three bytes into a
software buffer, write literal zero back immediately. Linux's mailbox core does exactly this, and its own
comment says the full register must be cleared by the consumer, naming the TCU as a producer that depends on
it. The hardware contract is only that bit 31 returns to zero before the SPE will deposit another word.

Two caveats the reviewer was careful to keep separate from the verified parts. That the SPE is what sets bit
31 on the receive mailbox is inferred from the symmetry of the shared-mailbox hardware, not read from SPE
firmware, which is closed. And the reference implementation's `Read()` blocks until it has the bytes it wants,
so a non-blocking poll must test bit 31 first rather than follow that function's shape.
