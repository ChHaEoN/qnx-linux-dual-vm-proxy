# R2 — kexec from L4T Linux as a volatile loader for a QNX image on arm64, and the Tegra TCU as a console for a non-Linux payload

Date: 2026-09-09, run id `20260909T1100Z`. External research task (read-only). No board
access in this task; every on-board fact below is taken from the H3 captures already in
`raw/orin-*.txt` (which were redacted at capture time) and is labelled as such.

**Method / limits.** Upstream sources were read through the web-fetch tool against
`raw.githubusercontent.com` (torvalds/linux `master` and tag `v5.15`, horms/kexec-tools
`main`, NVIDIA/edk2-nvidia `main`, OE4T mirror of the L4T kernel) plus NVIDIA docs and
forum pages. `git.kernel.org` refused the fetch tool (HTTP 403), so kexec-tools is quoted
from the maintainer's GitHub mirror. The fetch tool summarises long files; where it could
only paraphrase (never a verbatim line) that is said. Two large files (`tegra234.dtsi`
upstream, `sys/arm64/arm64/locore.S`) were truncated by the tool; the live L4T device tree
from the board was used instead. Nothing was downloaded to disk; no QNX binary was
disassembled; no package was installed.

Evidence classes: **VERIFIED** (I saw it: file:line / command output / a raw capture),
**VENDOR_CLAIM** (a doc or forum reply says so), **HYPOTHESIS** (reasoned, untested),
**UNKNOWN**. External-page quotes are kept to 15 words or fewer; kernel/kexec-tools/EDK2
source is quoted as short excerpts with the path.

Redactions: login → `<user>`, LAN address → `<orin-ip>`, key → `<orin-key>`.

---

## 0. Bottom line

1. **Entry EL.** The L4T kernel on this board runs at EL2 with VHE (`CPU: All CPU(s)
   started at EL2`, `kvm [1]: VHE mode initialized successfully`, VERIFIED,
   `raw/orin-firmware-el.txt:32,38`). For a VHE kernel `is_hyp_nvhe()` is false, so
   `machine_kexec()` does **not** take the HVC_SOFT_RESTART/hyp-stub path; it turns the
   MMU off by writing `sctlr_el1` (which E2H redirects to `SCTLR_EL2`) and branches at
   the *current* EL. The payload is therefore entered **at EL2, MMU off, with
   `HCR_EL2.E2H` (and `TGE`) still set and `VBAR_EL2` still pointing at Linux's
   vectors** — a state no bootloader ever hands to a kernel. Linux's own `head.S`
   copes (`init_el2` re-writes `HCR_EL2` and tests `HCR_E2H`); a QNX `startup` has to
   do the same. VERIFIED for the Linux side (§1); HYPOTHESIS/UNKNOWN for QNX (§1.5).
2. **Register contract** is the plain Linux one on both syscalls: `x0 = DTB physical
   address, x1 = x2 = x3 = 0`, DAIF masked, MMU off, image cleaned to PoC (VERIFIED,
   §1.3). `kexec -c/-l` (`kexec_load`) reaches the payload through kexec-tools'
   *purgatory* (same EL, MMU off, optional SHA-256 over every segment — pass `-i` to
   skip it); `kexec -s` (`kexec_file_load`) jumps straight to the image (VERIFIED).
3. **Header contract.** Both loaders reject anything without `"ARM\x64"` at 0x38.
   `kexec_load` (kexec-tools) checks *only* the magic; `kexec_file_load` additionally
   requires `image_size != 0`, an endianness that matches the running kernel, and a
   page-size flag the CPU supports (0 = unspecified passes); no signature check unless
   `CONFIG_KEXEC_SIG`, which this kernel does **not** set (VERIFIED, §2, §4). A raw
   non-Linux binary can be loaded by prefixing a 64-byte header whose `code0` is a
   branch over the header; the placement is `text_offset` above a 2 MiB-aligned base
   that kexec chooses (lowest hole for `-l`, bottom-up for `-s`), so the QNX IFS's
   fixed `[image=...]` address must be reconciled with that (§2.4, HYPOTHESIS).
   Xen, U-Boot and Zephyr ship exactly this header (VERIFIED); no published report of
   kexec-ing a non-Linux payload on arm64 was found (UNKNOWN).
4. **GIC and CPUs.** Linux offlines every secondary through **PSCI `CPU_OFF`** before
   `machine_kexec()` and waits for `AFFINITY_INFO == OFF`; it never touches the GIC
   distributor/redistributors on the way out (no kexec/syscore/shutdown hook in
   `irq-gic-v3.c`, VERIFIED). The payload gets all six CPUs back with PSCI `CPU_ON`
   (`method = "smc"`, `arm,psci-1.0`, PSCIv1.1, VERIFIED from the board); the GIC it
   inherits is *enabled and configured by Linux*, not reset. There is **no ITS node**
   on this board, so the LPI-table-reuse hazard does not apply here (VERIFIED, §3).
5. **L4T R36.4.7 kernel** (`5.15.148-tegra`) ships `CONFIG_KEXEC=y`,
   `CONFIG_KEXEC_FILE=y`, `# CONFIG_KEXEC_SIG is not set`, `CONFIG_CRASH_DUMP=y`,
   `kexec_load_disabled = 0`, no lockdown LSM, Secure Boot disabled, `kexec-tools
   2.0.22` installed (VERIFIED from `/proc/config.gz` and dpkg, §4). NVIDIA documents
   kdump only for AGX Orin/eMMC and calls kexec/kdump "not officially supported" on
   Orin NX; forum threads show a kexec'd *Linux* kernel does boot on Orin NX
   (R36.4.3) once `nvidia_drm` is unloaded (VENDOR_CLAIM, §4.3).
6. **TCU console.** The CCPLEX→SPE path is one 32-bit write per ≤3 characters into a
   single HSP shared-mailbox register, then poll bit 31 until the SPE clears it.
   On Tegra234 the TX mailbox is **AON HSP, shared mailbox 1, 32-bit type**:
   `0x0C150000 + 0x10000 + 1 × 0x8000 = 0x0C168000` (formula from
   `drivers/mailbox/tegra-hsp.c`, phandle/index from the live DT, and NVIDIA's own
   UEFI Kconfig default `0x0C168000` — three independent VERIFIED sources, §5).
   Word layout: `data[0..2]` in bits 0–23, byte count in bits 24–25, "flush" bit 26
   (set by NVIDIA's UEFI, not by Linux), FULL/"interrupt" bit 31. The SPE services
   this mailbox for MB1/MB2/PSC/BPMP/TZ/UEFI before Linux exists (VENDOR_CLAIM +
   VERIFIED UEFI source), so it will keep servicing it after Linux is gone
   (HYPOTHESIS by construction; untested).
7. **8250 path.** Tegra's non-TCU UARTs are 16550-register-compatible at a 4-byte
   stride: upstream `8250_tegra.c` sets `UPIO_MEM32` + `regshift = 2` for
   `nvidia,tegra20-uart`, and the 8250 DT binding lists `nvidia,tegra234-uart` with
   `nvidia,tegra20-uart` as fallback (VERIFIED). On this board the reachable ones are
   `serial@3100000` (uarta, ttyTHS1, 40-pin header UART1), `serial@3140000` (uarte,
   ttyTHS2), `serial@3110000` (uartb, **disabled**) and `serial@31d0000`
   (`arm,sbsa-uart`, ttyAMA0, PL011-register subset, clock set by firmware) — the
   TCU's *physical* UART (UARTC `0x0c280000`, SPE-owned) is not in the Linux DT at all
   (VERIFIED absent; VENDOR_CLAIM for the address) (§6).

---

## 1. arm64 kexec entry semantics when the running kernel is VHE at EL2

### 1.1 Which EL, and why the hyp-stub is *not* involved on this board

`arch/arm64/kernel/machine_kexec.c` (master), `machine_kexec()` — VERIFIED:

```c
	/*
	 * Both restart and kernel_reloc will shutdown the MMU, disable data
	 * caches. However, restart will start new kernel or purgatory directly,
	 * kernel_reloc contains the body of arm64_relocate_new_kernel
	 * In kexec case, kimage->start points to purgatory assuming that
	 * kernel entry and dtb address are embedded in purgatory by
	 * userspace (kexec-tools).
	 * In kexec_file case, the kernel starts directly without purgatory.
	 */
	if (kimage->head & IND_DONE) {
		typeof(cpu_soft_restart) *restart;

		cpu_install_idmap();
		restart = (void *)__pa_symbol(cpu_soft_restart);
		restart(is_hyp_nvhe(), kimage->start, kimage->arch.dtb_mem,
			0, 0);
	} else {
		void (*kernel_reloc)(struct kimage *kimage);

		if (is_hyp_nvhe())
			__hyp_set_vectors(kimage->arch.el2_vectors);
		cpu_install_ttbr0(kimage->arch.ttbr0, kimage->arch.t0sz);
		kernel_reloc = (void *)kimage->arch.kern_reloc;
		kernel_reloc(kimage);
	}
```

and in `machine_kexec_post_load()`: `kimage->arch.el2_vectors = 0; if (is_hyp_nvhe()) {
rc = trans_pgd_copy_el2_vectors(...); }` (VERIFIED). `arch/arm64/include/asm/virt.h`
(VERIFIED):

```c
static __always_inline bool is_kernel_in_hyp_mode(void)
{
	return read_sysreg(CurrentEL) == CurrentEL_EL2;
}
static inline bool is_hyp_nvhe(void)
{
	return is_hyp_mode_available() && !is_kernel_in_hyp_mode();
}
```

So with a VHE kernel (`CurrentEL == EL2`): `is_hyp_nvhe()` is **false**, `el2_vectors`
stays 0, and the CPU simply keeps running at EL2 through the MMU-off sequence.

`arch/arm64/kernel/cpu-reset.S` (master, whole function) — VERIFIED:

```asm
SYM_CODE_START(__cpu_soft_restart)
	mov_q	x12, INIT_SCTLR_EL1_MMU_OFF
	pre_disable_mmu_workaround
	/*
	 * either disable EL1&0 translation regime or disable EL2&0 translation
	 * regime if HCR_EL2.E2H == 1
	 */
	msr	sctlr_el1, x12
	isb

	cbz	x0, 1f				// el2_switch?
	mov	x0, #HVC_SOFT_RESTART
	hvc	#0				// no return

1:	mov	x8, x1				// entry
	mov	x0, x2				// arg0
	mov	x1, x3				// arg1
	mov	x2, x4				// arg2
	br	x8
SYM_CODE_END(__cpu_soft_restart)
```

The comment is the load-bearing line: with `E2H == 1` the `msr sctlr_el1` is
architecturally redirected to `SCTLR_EL2`, so the *EL2&0* regime is switched off and
`br x8` lands in the payload at EL2. Nothing in this path clears `HCR_EL2.E2H/TGE` or
re-points `VBAR_EL2`.

The relocation path (`arch/arm64/kernel/relocate_kernel.S`, master) ends the same way
(tool paraphrase of the tail, VERIFIED as to register roles): for `el2_vectors != 0`
(nVHE only) it does `mov x1, x28 /* entry */; mov x2, x26 /* dtb */; hvc #0` "Jumps from
el2"; otherwise `mov x0, x26 /* dtb */; mov x1, xzr; mov x2, xzr; mov x3, xzr; br x28`
"Jumps from el1" — the label is a misnomer on VHE, where this branch executes at EL2.

For completeness, the nVHE stub path (`arch/arm64/kernel/hyp-stub.S`, `elx_sync`,
VERIFIED) is:

```asm
2:	cmp	x0, #HVC_SOFT_RESTART
	b.ne	3f
	mov	x0, x2
	mov	x2, x4
	mov	x4, x1
	mov	x1, x3
	br	x4				// no return
```

i.e. the same `x0 = dtb, x1 = x2 = 0` contract, entered at EL2 with the stub's MMU-off
EL2 state. `HVC_SOFT_RESTART` is defined as 1, "CPU soft reset, used by the
cpu_soft_restart routine" (`asm/virt.h`, VERIFIED).

**v5.15 (the L4T kernel's base) is equivalent for this question.** `cpu-reset.h` there
computes `el2_switch = !is_kernel_in_hyp_mode() && is_hyp_mode_available()` (VERIFIED,
tool paraphrase quoting that expression), `machine_kexec()` calls
`cpu_soft_restart(reboot_code_buffer_phys, kimage->head, kimage->start,
kimage->arch.dtb_mem)` and `arm64_relocate_new_kernel` "passes control to the new kernel
with DTB in x0 and zeros in x1-x3" (VERIFIED as paraphrase; the file fetch was
rate-limited before a verbatim copy). Whether NVIDIA's `5.15.148-tegra` carries the
later "ttbr0 relocation" rewrite is UNKNOWN; it does not change the EL or the register
contract either way.

KVM does not undo VHE state at kexec either: `arch/arm64/kvm/arm.c` (master, VERIFIED)

```c
static void cpu_hyp_reset(void)
{
	if (!is_kernel_in_hyp_mode())
		__hyp_reset_vectors();
}
```

— a no-op on VHE. `kvm_arch_disable_virtualization_cpu()` only stops the timer/vGIC
per-CPU state and calls `cpu_hyp_uninit()`.

### 1.2 The Linux kernel *expects* this and handles it in `head.S` — a non-Linux payload must too

`arch/arm64/kernel/head.S` (master, VERIFIED excerpt):

```asm
SYM_INNER_LABEL(init_el2, SYM_L_LOCAL)
	msr	elr_el2, lr

	// clean all HYP code to the PoC if we booted at EL2 with the MMU on
	cbz	x0, 0f
	...
	mov_q	x0, INIT_SCTLR_EL2_MMU_OFF
	pre_disable_mmu_workaround
	msr	sctlr_el2, x0
	isb
0:

	init_el2_hcr	HCR_HOST_NVHE_FLAGS | HCR_ATA
	init_el2_state

	/* Hypervisor stub */
	adr_l	x0, __hyp_stub_vectors
	msr	vbar_el2, x0
	isb

	mov_q	x1, INIT_SCTLR_EL1_MMU_OFF

	mrs	x0, hcr_el2
	and	x0, x0, #HCR_E2H
	cbz	x0, 2f
```

A new *Linux* rewrites `HCR_EL2`, installs its own `VBAR_EL2` and then decides VHE vs
nVHE itself. That is the checklist for a QNX `startup` entered by kexec: it will be at
EL2 with `E2H=1`, `TGE=1`, stale `VBAR_EL2`, `MDCR_EL2`/`CPTR_EL2`/`CNTHCTL_EL2` as
Linux left them.

### 1.3 CPU/system state at the payload's first instruction

| Item | State at entry | Class | Where |
|---|---|---|---|
| EL | EL2 (VHE host EL); nVHE kernels also arrive at EL2 via the stub | VERIFIED | §1.1; board: `CPU: All CPU(s) started at EL2` (`raw/orin-firmware-el.txt:32`) |
| `HCR_EL2` | Linux host value, `E2H=1` (VHE) still set; not cleared by kexec | VERIFIED (code) / HYPOTHESIS (exact bit set) | `cpu-reset.S` comment; `kvm/arm.c` |
| MMU | off (`SCTLR_EL2.M=0` via redirected `sctlr_el1` write; `INIT_SCTLR_EL1_MMU_OFF` has no `M/C/I`) | VERIFIED | `cpu-reset.S` |
| D-cache | image cleaned to PoC: `kexec_segment_flush()` in the in-place case; relocation code does `dcache_by_myline_op_nosync civac` on each copied page then `dsb sy`; reloc code itself `dcache_clean_inval_poc` + `icache_inval_pou` | VERIFIED | `machine_kexec.c` `machine_kexec_post_load()`; `relocate_kernel.S` |
| Interrupts | `local_daif_mask()` before restart — all of DAIF masked | VERIFIED | `machine_kexec()` |
| `x0..x3` | `x0` = DTB PA, `x1=x2=x3=0` (both syscalls; via purgatory for `-l`) | VERIFIED | §1.1, §2.3 |
| `VBAR_EL2` | Linux's (stale) | VERIFIED (nothing rewrites it) | §1.1 |
| Secondaries | offlined by PSCI `CPU_OFF`, confirmed `AFFINITY_LEVEL_OFF` | VERIFIED | §3.1 |
| GIC | untouched by kexec — enabled, configured by Linux | VERIFIED | §3.2 |
| Timers | untouched; `CNTHCTL_EL2`, `CNTV/CNTP` enables as Linux left them | HYPOTHESIS (no code path found that resets them) | — |

`Documentation/arch/arm64/booting.rst` (master, VERIFIED quotes) states the contract
kexec is reproducing: "x0 = physical address of device tree blob (dtb) in system RAM.
x1 = 0 (reserved for future use) x2 = 0 (reserved for future use) x3 = 0 (reserved for
future use)"; "All forms of interrupts must be masked in PSTATE.DAIF"; "The CPU must be
in non-secure state, either in EL2 (RECOMMENDED in order to have access to the
virtualisation extensions), or in EL1."; "The MMU must be off. The instruction cache
may be on or off, and must not hold any stale entries corresponding to the loaded
kernel image. The address range corresponding to the loaded kernel image must be
cleaned to the PoC."; "The requirements described above for CPU mode, caches, MMUs,
architected timers, coherency and system registers apply to all CPUs. All CPUs must
enter the kernel in the same exception level."

### 1.4 What `kexec -e` runs before `machine_kexec()`

`kernel/kexec_core.c` `kernel_kexec()` non-crash path (VERIFIED):

```c
	kexec_in_progress = true;
	kernel_restart_prepare("kexec reboot");
	migrate_to_reboot_cpu();
	syscore_shutdown();
	cpu_hotplug_enable();
	pr_notice("Starting new kernel\n");
	machine_shutdown();
	kmsg_dump(KMSG_DUMP_SHUTDOWN);
	machine_kexec(kexec_image);
```

`kernel_restart_prepare()` runs the reboot notifier chain and `device_shutdown()`
(driver `->shutdown()` methods — this is where the NVIDIA forum "nvidia_drm blocks
kexec" symptom lives, §4.3). `arch/arm64/kernel/process.c` (VERIFIED):

```c
void machine_shutdown(void)
{
	smp_shutdown_nonboot_cpus(reboot_cpu);
}
```

with the comment "This must completely disable all secondary CPUs; simply causing
those CPUs to execute e.g. a RAM-based pin loop is not sufficient." and the preamble that
kexec needs "the kexec'd kernel to use any and all RAM as it sees fit, without having to
avoid any code or data used by any SW CPU pin loop."

### 1.5 What this means for a QNX `startup` (cross-reference, not researched here)

H2's inventory (`harvest-sdp.md` §0.4) found both shipped startups expect `x0 = FDT`,
which matches the kexec contract; whether `startup`'s EL2 handling (`lib/aarch64/
hypervisor_enable.S`, `lib/hypervisor_setup.c` in the BSP zip, names only from
`raw/bsp-startup-lib-files.txt:73-74,221`) tolerates arriving with `HCR_EL2.E2H=1` is
UNKNOWN and is the first thing a native-port attempt must establish. The QHV host image
already boots when QEMU enters it at EL2 (`-machine virt,virtualization=on`,
`scripts/launch-qhv-tcg.ps1:150`, VERIFIED), but QEMU/TCG enters with `E2H=0`, so that
is not evidence for the VHE case.

---

## 2. The arm64 Image header contract and how strictly each loader enforces it

### 2.1 The header (`arch/arm64/include/asm/image.h`, `booting.rst`, kexec-tools `image-header.h`) — VERIFIED

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0x00 | 4 | `code0` | executable; Linux: `b primary_entry` (or an `add` whose encoding spells `MZ` when EFI stub is on) |
| 0x04 | 4 | `code1` | executable |
| 0x08 | 8 | `text_offset` | LE; offset of the image from the 2 MiB-aligned base |
| 0x10 | 8 | `image_size` | LE; bytes the image needs from its start (must be non-zero for `kexec_file_load`) |
| 0x18 | 8 | `flags` | LE; bit 0 endianness "1 if BE, 0 if LE"; bits 1–2 page size (0 unspecified, 1 4K, 2 16K, 3 64K); bit 3 physical placement; bits 4–63 reserved |
| 0x20–0x37 | 24 | `res2..res4` | 0 |
| 0x38 | 4 | `magic` | `"ARM\x64"` = `0x644d5241` LE |
| 0x3C | 4 | `res5` | PE/COFF header offset if EFI |

`booting.rst` on bit 3 (VERIFIED quotes): 0 → "2MB aligned base should be as close as
possible to the base of DRAM, since memory below it is not accessible via the linear
mapping"; 1 → "2MB aligned base such that all image_size bytes counted from the start
of the image are within the 48-bit addressable range of physical memory". And: "The
Image must be placed text_offset bytes from a 2MB aligned base address anywhere in
usable system RAM and called there."

kexec-tools `kexec/arch/arm64/image-header.h` (VERIFIED, paraphrase): magic
`{'A','R','M',0x64}`, masks `(1UL << 0)` BE, `(3UL << 1)` page size, `(1UL << 3)`
placement; helpers `arm64_header_check_magic`, `arm64_header_check_pe_sig` ('MZ'),
`arm64_header_check_msb`, `arm64_header_text_offset`, `arm64_header_image_size`.

### 2.2 Kernel side — `kexec_file_load` (`kexec -s`) — VERIFIED (`arch/arm64/kernel/kexec_image.c`, master)

```c
static int image_probe(const char *kernel_buf, unsigned long kernel_len)
{
	const struct arm64_image_header *h =
		(const struct arm64_image_header *)(kernel_buf);

	if (!h || (kernel_len < sizeof(*h)))
		return -EINVAL;

	if (memcmp(&h->magic, ARM64_IMAGE_MAGIC, sizeof(h->magic)))
		return -EINVAL;

	return 0;
}
```

`image_load()` then requires (verbatim excerpts):

```c
	/*
	 * We require a kernel with an unambiguous Image header. Per
	 * Documentation/arch/arm64/booting.rst, this is the case when image_size
	 * is non-zero (practically speaking, since v3.17).
	 */
	h = (struct arm64_image_header *)kernel;
	if (!h->image_size)
		return ERR_PTR(-EINVAL);

	/* Check cpu features */
	flags = le64_to_cpu(h->flags);
	be_image = arm64_image_flag_field(flags, ARM64_IMAGE_FLAG_BE);
	be_kernel = IS_ENABLED(CONFIG_CPU_BIG_ENDIAN);
	if ((be_image != be_kernel) && !system_supports_mixed_endian())
		return ERR_PTR(-EINVAL);

	value = arm64_image_flag_field(flags, ARM64_IMAGE_FLAG_PAGE_SIZE);
	if (((value == ARM64_IMAGE_FLAG_PAGE_SIZE_4K) &&
			!system_supports_4kb_granule()) || ...
		return ERR_PTR(-EINVAL);

	/* Load the kernel */
	kbuf.buf_min = 0;
	kbuf.buf_max = ULONG_MAX;
	kbuf.top_down = false;
	...
	kbuf.memsz = le64_to_cpu(h->image_size);
	text_offset = le64_to_cpu(h->text_offset);
	kbuf.buf_align = MIN_KIMG_ALIGN;

	/* Adjust kernel segment with TEXT_OFFSET */
	kbuf.memsz += text_offset;
	...
	kernel_segment->mem += text_offset;
	kernel_segment->memsz -= text_offset;
	image->start = kernel_segment->mem;
```

Observations (VERIFIED): the kernel does **not** interpret flag bit 3 — placement is
always bottom-up (`top_down = false`, `buf_min = 0`) at the first 2 MiB-aligned free
hole that also fits the DTB/initrd; `image->start` is the *header* address, so `code0`
must be a real instruction; a page-size flag of 0 passes. `arch/arm64/kernel/
machine_kexec_file.c` registers only `kexec_image_ops` (VERIFIED), and the DTB it hands
over is rebuilt with `of_kexec_alloc_and_setup_fdt()` and placed 2 MiB-aligned,
top-down (VERIFIED, paraphrase). Signature: `kexec_image_ops.verify_sig =
kexec_kernel_verify_pe_sig` only `#ifdef CONFIG_KEXEC_IMAGE_VERIFY_SIG`, and
`kernel/kexec_file.c` `kimage_validate_signature()` only runs under
`CONFIG_KEXEC_SIG` (VERIFIED) — both absent on this board (§4). v5.15 Kconfig
(VERIFIED): `KEXEC_IMAGE_VERIFY_SIG` "depends on KEXEC_SIG" and "depends on EFI &&
SIGNED_PE_FILE_VERIFICATION".

### 2.3 kexec-tools side — `kexec_load` (`kexec -c` / `-l`) — VERIFIED (horms/kexec-tools `main`)

`kexec/arch/arm64/kexec-image-arm64.c`:

```c
int image_arm64_probe(const char *kernel_buf, off_t kernel_size)
{
	const struct arm64_image_header *h;

	if (kernel_size < sizeof(struct arm64_image_header)) {
		dbgprintf("%s: No arm64 image header.\n", __func__);
		return -1;
	}

	h = (const struct arm64_image_header *)(kernel_buf);

	if (!arm64_header_check_magic(h)) {
		dbgprintf("%s: Bad arm64 image header.\n", __func__);
		return -1;
	}

	return 0;
}
```

`image_arm64_load()` in file mode just hands the fds to the kernel; otherwise it calls
`arm64_process_image_header()` (`kexec-arm64.c`, VERIFIED):

```c
	if (!arm64_header_check_magic(h))
		return EFAILED;

	if (h->image_size) {
		arm64_mem.text_offset = arm64_header_text_offset(h);
		arm64_mem.image_size = arm64_header_image_size(h);
	} else {
		/* For 3.16 and older kernels. */
		arm64_mem.text_offset = 0x80000;
		arm64_mem.image_size = KERNEL_IMAGE_SIZE;
		...
```

then `kernel_segment = arm64_locate_kernel_segment(info)` →
`locate_hole(info, arm64_mem.text_offset + arm64_mem.image_size, MiB(2), 0, ULONG_MAX, 1)`,
and `kexec/kexec.c` `locate_hole()` with `hole_end > 0` takes the **lowest** fitting
range (`if (hole_end > 0) { hole_base = start; break; }`, VERIFIED). The image is added
with `add_segment_phys_virt(info, kernel_buf, kernel_size, kernel_segment +
arm64_mem.text_offset, arm64_mem.image_size, 0)`, and `arm64_load_other_segments()`
(VERIFIED snippets) sets `hole_min = image_base + arm64_mem.image_size`, refuses a DTB
> 2 MiB, places the DTB and initrd above the image, loads purgatory with
`elf_rel_build_load(...)`, sets `info->entry = elf_rel_get_addr(&info->rhdr,
"purgatory_start")` and patches `arm64_kernel_entry = image_base`,
`arm64_dtb_addr = dtb_base`, `arm64_sink` (optional console). The DTB comes from `--dtb`
or `/sys/firmware/fdt` and is edited by `setup_2nd_dtb()` (bootargs, initrd, seeds).

So on this board the `-l` placement is deterministic in principle: the first "System
RAM" range is `80000000-bdffffff` (`raw/orin-iomem.txt:180`, VERIFIED), so the header
lands at `0x80000000 + text_offset` and the running kernel at `0x9b290000` is simply
overwritten at exec time (that is what the relocation code is for). HYPOTHESIS for the
installed `kexec-tools 2.0.22` (Ubuntu build): the function has had this shape since
2016 but the 2.0.22 tree itself was not read.

Purgatory (`purgatory/arch/arm64/entry.S`, VERIFIED paraphrase): sets up a stack, calls
`purgatory()`, then `ldr x17, arm64_kernel_entry; ldr x0, arm64_dtb_addr; x1..x3 = 0;
br x17`. `purgatory/purgatory.c`: `if (!skip_checks && verify_sha256_digest()) for(;;);`
— with the MMU and caches off this hashes every segment uncached; `kexec -i /
--no-checks` ("Fast reboot, no memory integrity checks.", `kexec/kexec.c` usage,
VERIFIED) skips it. `purgatory-arm64.c` `setup_arch()` only prints entry/dtb (VERIFIED).

Syscall selection (`kexec/kexec.c` usage, VERIFIED): `-s` "Use file based syscall",
`-c` "Use the kexec_load syscall", `-a` "Use file based syscall for kexec and fall back
to the compatibility syscall when file based syscall is not supported or the kernel did
not understand the image (default)". Whether 2.0.22 already defaults to `-a` is
UNKNOWN — pass `-c` or `-s` explicitly.

Kernel-side `kexec_load` (`kernel/kexec.c`, VERIFIED paraphrase): checks
`kexec_load_permitted()`, `security_kernel_load_data(LOADING_KEXEC_IMAGE)`,
`security_locked_down(LOCKDOWN_KEXEC)`, arch flag, `nr_segments <= KEXEC_SEGMENT_MAX`;
it performs **no** inspection of segment contents.

### 2.4 Can a raw non-Linux binary be loaded with a synthetic 64-byte header?

Mechanically yes, on both syscalls (HYPOTHESIS assembled from VERIFIED parts):

* Prepend 64 bytes: `code0 = b +64` (or `b <payload entry>`), `code1 = nop`,
  `text_offset`, `image_size = 64 + payload + BSS/scratch the payload needs`,
  `flags = 0` (LE, page size unspecified — accepted by `image_load()`; bit 3 is ignored
  by both loaders), `magic = "ARM\x64"`. Since `image->start`/`arm64_kernel_entry` is
  the header address, `code0` is the first instruction executed.
* `kexec -c -l hdr+payload.bin --dtb <fdt> -i` or `kexec -s -l ...`; `--type=Image` if
  the probe order matters. The DTB in `x0` is the (edited) L4T FDT unless `--dtb`
  substitutes one.
* The QNX IFS from this repo is a *raw* image: its first 12 bytes are the `raw.boot`
  jump stub followed by NOP padding to `preboot_size = 0xfa0`, and no magic sits at
  0x38 (`raw/ifs-first-64-bytes.txt`, `raw/dumpifs-plain-ifs-header.txt`, VERIFIED).
  The stub's third instruction occupies 0x08–0x0B, i.e. the `text_offset` field, so the
  Linux header cannot be overlaid in place — it must be *prefixed*, shifting the IFS by
  64 bytes. The IFS is linked for a fixed physical address (`[image=0x40080000]`,
  `image_paddr=0x40080fa0`, `startup_vaddr=0x40081da8`), so an Orin build would need
  `[image=0x80080000]` (DRAM base + 0x80000) and a header with `text_offset = 0x80000 -
  0x40` so that the stub lands exactly at `0x80080000` when kexec picks the
  `0x80000000` hole (HYPOTHESIS; depends on §2.3's hole choice and on H2's view of how
  `startup` relocates itself).
* `kexec_file_load` will place the buffer at the *lowest free* 2 MiB-aligned hole,
  which is not guaranteed to be `0x80000000` on a running system; `kexec_load` gives the
  operator `--mem-min/--mem-max` to constrain it (VERIFIED options exist).

Precedent for the header on non-Linux payloads (the mechanism `booti`, QEMU `-kernel`
and kexec all share):

| Project | Header present? | Evidence | Class |
|---|---|---|---|
| Xen (`xen/arch/arm/arm64/head.S`) | yes — "DO NOT MODIFY. Image header expected by Linux boot-loaders.", `.quad 0 /* Image load offset */`, magic bytes 0x41 0x52 0x4d 0x64; requires "Xen must be entered in NS EL2 mode" | fetched source | VERIFIED |
| U-Boot (`arch/arm/include/asm/boot0-linux-kernel-header.h`, `CONFIG_LINUX_KERNEL_IMAGE_HEADER`) | yes — Kconfig help: "Place a Linux kernel image header at the start of the U-Boot binary. The format of the header is described in ... Documentation/arm64/booting.txt." | fetched source | VERIFIED |
| Zephyr (`arch/arm64/core/header.S`, `CONFIG_AARCH64_IMAGE_HEADER`) | yes — Linux-compatible header, page-size flag from `CONFIG_MMU_PAGE_SIZE` | fetched source (paraphrase) | VERIFIED |
| seL4 elfloader | "can be booted according to the Linux kernel's booting convention for ARM/ARM64" | docs.sel4.systems | VENDOR_CLAIM |
| FreeBSD (`sys/arm64/arm64/locore.S`) | no header at the top of the file; `LINUX_BOOT_ABI` blocks only affect FDT mapping | fetched source | VERIFIED (absent) |
| Linux `KEXEC` Kconfig (v5.15) | "And like a reboot you can start any kernel with it, not just Linux." | fetched source | VERIFIED |

A published account of actually kexec-ing Xen/U-Boot/seL4/Zephyr or "bare metal" from
Linux on arm64 was **not** found in five searches (UNKNOWN — absence of evidence only).
The closest in-tree analogue is QEMU's `-kernel` path used by this repo, which accepts
the header-less IFS as a raw file (`scripts/launch-qnx-vm.sh:75`, VERIFIED that the IFS
is passed to `-kernel`); kexec has no such raw fallback.

---

## 3. Does kexec keep or reset the GIC, and does the payload get all CPUs?

### 3.1 Secondary CPUs: PSCI `CPU_OFF` on the way out, `CPU_ON` on the way in — VERIFIED

* `machine_kexec_prepare()` refuses to load "if we have no way of hotplugging cpus or
  cpus are stuck in the kernel" (v5.15, VERIFIED paraphrase); `cpus_are_stuck_in_kernel()`
  (`smp.c`, master, VERIFIED) is true for spin-table systems (`!have_cpu_die()`) or
  protected KVM. This board uses `enable-method = "psci"` on all six CPUs
  (`raw/orin-devicetree.txt:339-374`) and VHE KVM, so it passes.
* `machine_shutdown()` → `smp_shutdown_nonboot_cpus(reboot_cpu)` (`kernel/cpu.c`)
  → per CPU `cpu_die()` (`smp.c`): `idle_task_exit(); local_daif_mask();
  cpuhp_ap_report_dead(); ops->cpu_die(cpu);` → `cpu_psci_cpu_die()` calls
  `psci_ops.cpu_off(state)`; the survivor's `cpu_psci_cpu_kill()` polls
  `AFFINITY_INFO` "until PSCI_0_2_AFFINITY_LEVEL_OFF" with a 100 ms timeout
  (`arch/arm64/kernel/psci.c`, VERIFIED paraphrase). `machine_kexec()` then
  `BUG_ON(!in_kexec_crash && (stuck_cpus || (num_online_cpus() > 1)))`.
* `booting.rst` (VERIFIED quote): "CPUs with a 'psci' enable method should remain
  outside of the kernel (i.e. outside of the regions of memory described to the kernel
  in the memory node, or in a reserved area of memory described to the kernel by a
  /memreserve/ region in the device tree)." and the kernel "will issue CPU_ON calls".
  The payload therefore brings the secondaries up itself with PSCI `CPU_ON` via SMC;
  `cpu_psci_cpu_boot()` is `psci_ops.cpu_on(cpu_logical_map(cpu),
  __pa_symbol(secondary_entry))` (VERIFIED paraphrase).
* Board facts (VERIFIED, `raw/orin-devicetree.txt:62-65`, `raw/orin-uefi-dmesg.txt`
  via `raw/orin-followup.txt`): `/psci compatible = "arm,psci-1.0"`, `method = "smc"`,
  `PSCIv1.1 detected in firmware`, `SMC Calling Convention v1.2`; the six MPIDR
  affinity values Linux booted are `0x0, 0x100, 0x200, 0x300, 0x10200, 0x10300`.
* Firmware side: upstream TF-A `plat/nvidia/tegra/common/tegra_pm.c` (BSD-3-Clause,
  VERIFIED) does on `CPU_OFF` `tegra_soc_pwr_domain_off(); /* disable GICC */
  tegra_gic_cpuif_deactivate();` and on `CPU_ON` finish `tegra_gic_pcpu_init()` (or a
  full `tegra_gic_init()` after SoC power-down). Upstream TF-A's `plat/nvidia/tegra/soc`
  listing shows only `t194` (VERIFIED via GitHub API) — Tegra234's TF-A is NVIDIA's
  own build and its `CPU_OFF/CPU_ON` GIC handling is UNKNOWN (VENDOR_CLAIM by analogy
  only). L4T public sources may contain it (`atf_src.tbz2`); not checked.
* Cross-reference for the payload: H2 found `fdt_psci_configure()` in `libstartup.a`
  matches only `compatible = "arm,psci"` (`harvest-sdp.md`, VERIFIED there). The live
  DT says `"arm,psci-1.0"` — that mismatch is now VERIFIED, not a hypothesis, and a
  native `startup` must pass the conduit/IDs some other way or extend the match.

### 3.2 GIC state: nothing is reset — VERIFIED

* `drivers/irqchip/irq-gic-v3.c` (master) contains none of the strings `kexec`,
  `syscore`, `reboot`, `shutdown` (VERIFIED by search in the fetched file); its only
  teardown-like path is the CPU-PM notifier (`CPU_PM_ENTER` → `gic_write_grpen1(0);
  gic_enable_redist(false)`), which is cpuidle, not kexec. There is no CPU-offline
  hotplug callback for the redistributor.
* Therefore the payload inherits: `GICD_CTLR` enabled with ARE/Group-1 as Linux set it,
  SPIs/PPIs configured and possibly enabled, the boot CPU's redistributor awake
  (`GICR_WAKER.ProcessorSleep=0`), `ICC_SRE_EL2.SRE=1`, `ICC_IGRPEN1_EL1=1`, priority
  mask as Linux left it. Linux's own re-init sequence is the model for what the payload
  must do first: "Disable the distributor" — `writel_relaxed(0, base + GICD_CTLR);
  gic_dist_wait_for_rwp();` then reconfigure (`gic_dist_init()`, VERIFIED), and per CPU
  `gic_enable_redist(true)` + `gic_cpu_sys_reg_init()` (`gic_cpu_init()`, VERIFIED).
  Interrupts stay masked in DAIF until the payload has done this (§1.3).
* ITS/LPIs: on kexec Linux deliberately *does not* disable LPIs; the next kernel detects
  `GICR_CTLR.EnableLPIs` and reuses the tables (`irq-gic-v3-its.c`: "Booting with kdump
  and LPIs enabled is generally fine. Any other case is wrong in the absence of
  firmware/EFI support." and `gic_reserve_range()` → `efi_mem_reserve_persistent()`,
  VERIFIED). A non-Linux payload would have to handle a redistributor with LPIs
  already enabled and PROPBASER/PENDBASER pointing into Linux memory. **Not applicable
  on this board**: the live DT's `interrupt-controller@f400000` has no child nodes, no
  `msi-controller`, no `its@` node anywhere, and dmesg has no `ITS|LPI|MSI` lines
  (`raw/orin-followup.txt` "children of the GICv3 node", VERIFIED). GICD is at
  `0x0f400000` (64 KiB) and the single redistributor region at `0x0f440000`
  (2 MiB) (`raw/orin-devicetree.txt:88-91`, VERIFIED).
* `booting.rst` GICv3 requirements the *firmware* met at cold boot still hold after
  kexec ("ICC_SRE_EL3.Enable ... 0b1", "ICC_SRE_EL3.SRE ... 0b1"; the EL1-entry
  `ICC_SRE_EL2` bullets do not apply to an EL2 entry) — VERIFIED quotes; the timer
  bullets ("CNTFRQ must be programmed ... CNTVOFF must be programmed with a consistent
  value on all CPUs") likewise survive.

---

## 4. NVIDIA L4T R36 kernel: kexec configuration and field reports

### 4.1 On the board (H3 capture, `/proc/config.gz`) — VERIFIED (`raw/orin-kexec.txt`)

```
CONFIG_KEXEC=y
CONFIG_KEXEC_FILE=y
# CONFIG_KEXEC_SIG is not set
CONFIG_CRASH_DUMP=y
CONFIG_EFI_STUB=y
CONFIG_EFI=y
CONFIG_KVM=y
CONFIG_KEXEC_CORE=y
CONFIG_SERIAL_8250=y
CONFIG_SERIAL_8250_TEGRA=y
CONFIG_SERIAL_TEGRA=y
CONFIG_SERIAL_TEGRA_TCU=y
CONFIG_SERIAL_TEGRA_TCU_CONSOLE=y
CONFIG_TEGRA_HSP_MBOX=y
CONFIG_ARM_GIC_V3=y
CONFIG_ARM_GIC_V3_ITS=y
```

plus `/proc/sys/kernel/kexec_load_disabled = 0`, `kexec_loaded = 0`,
`kexec_crash_size = 0`, lockdown "(absent)", `kexec-tools 1:2.0.22-2ubuntu2.22.04.2`
installed at `/usr/sbin/kexec`, `/boot/Image` is "Linux kernel ARM64 boot executable
Image, little-endian, 4K pages". Kernel `5.15.148-tegra`, L4T R36 REVISION 4.7,
UEFI "EDK II" `36.4.4`, "secureboot: Secure boot disabled" (`raw/orin-identity.txt`,
`raw/orin-uefi-dmesg.txt:11-14,118`, VERIFIED). `CONFIG_KEXEC` (v5.15) "depends on
PM_SLEEP_SMP" — satisfied.

### 4.2 The shipped defconfig (OE4T mirror of nv-tegra `linux-jammy`, branch
`oe4t-patches-l4t-r36.2-1018.18`, `arch/arm64/configs/defconfig`) — VERIFIED

`CONFIG_KEXEC=y`, `CONFIG_KEXEC_FILE=y`, `CONFIG_CRASH_DUMP=y`, `CONFIG_KVM=y`,
`CONFIG_SERIAL_TEGRA=y`, `CONFIG_SERIAL_TEGRA_TCU=y`, `CONFIG_SERIAL_8250=y`,
`CONFIG_SERIAL_OF_PLATFORM=y`; absent: `CONFIG_KEXEC_SIG`, `CONFIG_KEXEC_IMAGE_VERIFY_SIG`,
`CONFIG_SECURITY_LOCKDOWN_LSM`. (`CONFIG_TEGRA_HSP_MBOX` is not in that defconfig but is
`=y` on the board — presumably selected/enabled elsewhere; UNKNOWN which fragment.) The
same kexec lines are in upstream v5.15 `arch/arm64/configs/defconfig` and in master
(VERIFIED), so NVIDIA did not diverge here. The nv-tegra gitiles branch guess
`l4t/l4t-r36.4.ga` returned 404 (not checked at NVIDIA's host).

### 4.3 NVIDIA documentation and forum threads — VENDOR_CLAIM

| Source | What it says (≤15-word quotes) | Relevance |
|---|---|---|
| Jetson Linux Developer Guide r36.4.3, *Kernel Debugging Tools* | "We have tested the following steps on AGX Orin with EMMC boot. They might not work with Orin Nano and Orin NX."; steps: install `linux-crashdump`, `kexec-tools`, `kdump-tools`, add `crashkernel=2G` to `extlinux.conf` | kexec is documented only as kdump's vehicle |
| Forum 365485 "Supporting Kexec/Kdump on Jetson Orin NX" (Apr 2026) | kdump kernel "successfully loaded and began booting via kexec"; then PCIe/NVMe link failed, "CBB fabric errors", "EMEM errors"; NVIDIA: "Kexec/kdump is not officially supported at this time"; workaround `max-link-speed = <0x01>` | a kexec'd Linux boots on Orin NX; PCIe state after kexec is the problem — relevant to any payload that touches PCIe |
| Forum 344580 "How to reset display interface for kdump" (Orin NX, JP 6.1 / R36.4.3, Sep–Nov 2025) | crash kernel fails with `arm-smmu ... Blocked unknown Stream ID` and `tegra-mc ... nvdisplayr1 ... EMEM address decode error` while `nvidia_drm` is loaded; boots after unloading it; NVIDIA: "blacklisting the modules which is causing kexec boot" | the display engine keeps DMA-ing across kexec; a non-Linux payload inherits live SMMU/DMA clients unless Linux's `->shutdown()` quiesced them |
| Forum 241481 "How to use kdump on AGX Orin" (JP 5.1, 5.10.104-tegra, Feb 2023) | `CONFIG_CRASH_DUMP=y` by default; NVIDIA: "This is not supported on Jetpack 5.1." | older generation; shows config present but unsupported |
| Forum 303049 "Xavier unable to kexec/run crashdump kernel" (JP 5.1.2, Aug 2024) | "Starting crashdump kernel... Bye!" then nothing; `tegra-bpmp-i2c` transfer failure and regulator sync errors in shutdown; NVIDIA: "We don't have much experience in the tool" | a silent hang after `Bye!` is the failure signature to expect; root cause never found |

No thread mentions the TCU or BPMP misbehaving *after* a successful kexec on
Orin — the kdump kernels that came up printed on `ttyTCU0` as usual (implied by the
threads' logs; not stated as such — HYPOTHESIS).

---

## 5. Driving the TCU from a non-Linux payload

### 5.1 Linux's side of the protocol — VERIFIED

`drivers/tty/serial/tegra-tcu.c` (GPL-2.0, NVIDIA 2018):

```c
#define TCU_MBOX_BYTE(i, x)			((x) << (i * 8))
#define TCU_MBOX_BYTE_V(x, i)			(((x) >> (i * 8)) & 0xff)
#define TCU_MBOX_NUM_BYTES(x)			((x) << 24)
#define TCU_MBOX_NUM_BYTES_V(x)			(((x) >> 24) & 0x3)

static void tegra_tcu_write_one(struct tegra_tcu *tcu, u32 value,
				unsigned int count)
{
	void *msg;

	value |= TCU_MBOX_NUM_BYTES(count);
	msg = (void *)(unsigned long)value;
	mbox_send_message(tcu->tx, msg);
	mbox_flush(tcu->tx, 1000);
}
```

`tegra_tcu_write()` packs up to 3 characters per word (`if (written == 3)
tegra_tcu_write_one(tcu, value, 3)`), and turns `\n` into `\r\n` itself. Probe:
`tcu->tx = mbox_request_channel_byname(&tcu->tx_client, "tx")`, `... "rx"`; console
name `ttyTCU`; match `nvidia,tegra194-tcu`.

`drivers/mailbox/tegra-hsp.c`:

```c
#define HSP_INT_DIMENSIONING	0x380
#define HSP_SM_SHRD_MBOX	0x0
#define HSP_SM_SHRD_MBOX_FULL	BIT(31)
#define HSP_SM_SHRD_MBOX_FULL_INT_IE	0x04
#define HSP_SM_SHRD_MBOX_EMPTY_INT_IE	0x08
#define HSP_SHRD_MBOX_TYPE1_TAG		0x40
#define HSP_SHRD_MBOX_TYPE1_DATA0	0x48
...
	/* shared mailbox i */
	mb->channel.regs = hsp->regs + SZ_64K + i * SZ_32K;
	/* doorbells */
	offset = (1 + (hsp->num_sm / 2) + hsp->num_ss + hsp->num_as) * SZ_64K;
	offset += index * hsp->soc->reg_stride;

static void tegra_hsp_sm_send32(struct tegra_hsp_channel *channel, void *data)
{
	u32 value;

	/* copy data and mark mailbox full */
	value = (u32)(unsigned long)data;
	value |= HSP_SM_SHRD_MBOX_FULL;

	tegra_hsp_channel_writel(channel, value, HSP_SM_SHRD_MBOX);
}

static int tegra_hsp_mailbox_flush(struct mbox_chan *chan,
				   unsigned long timeout)
{
	...
	while (time_before(jiffies, timeout)) {
		value = tegra_hsp_channel_readl(ch, HSP_SM_SHRD_MBOX);
		if ((value & HSP_SM_SHRD_MBOX_FULL) == 0) {
			mbox_chan_txdone(chan, 0);
			...
			return 0;
		}

		udelay(1);
	}

	return -ETIME;
}
```

`tegra_hsp_sm_xlate()` picks the 128-bit ops only when the DT cell carries
`TEGRA_HSP_MBOX_TYPE_SM_128BIT (1 << 8)`; `tegra234_hsp_soc` has `has_128_bit_mb =
true`, `reg_stride = 0x100`, `has_per_mb_ie = false` (VERIFIED). `mbox_send_message()`
after the write also sets the EMPTY interrupt enable (`HSP_INT_IE`), which a polled
bare-metal writer does not need.

`include/dt-bindings/mailbox/tegra186-hsp.h` (VERIFIED, also present on the board at
`/usr/lib/modules/5.15.148-tegra/build/include/dt-bindings/mailbox/tegra186-hsp.h`,
`raw/orin-followup.txt`): `TEGRA_HSP_MBOX_TYPE_SM 0x1`, `TEGRA_HSP_SM_FLAG_TX (1 << 31)`,
`TEGRA_HSP_SM_TX(x) (TEGRA_HSP_SM_FLAG_TX | ((x) & TEGRA_HSP_SM_MASK))`.

### 5.2 Which mailbox, and its address — three independent VERIFIED sources

Live DT (`raw/orin-devicetree.txt:277-289`, `raw/orin-followup.txt` phandle resolution):

```
/serial  compatible = "nvidia,tegra234-tcu","nvidia,tegra194-tcu"
         mboxes = <0x121 0x1 0x00000000>, <0x143 0x1 0x80000001>
         mbox-names = "rx", "tx"
0x121 -> /bus@0/hsp@3c00000   (hsp_top0, reg 0x03c00000 len 0xa0000)
0x143 -> /bus@0/hsp@c150000   (hsp_aon,  reg 0x0c150000 len 0x90000)
```

Decoded: **rx** = `hsp_top0` shared mailbox 0 (type SM, RX flag clear), **tx** =
`hsp_aon` shared mailbox **1**, `TEGRA_HSP_SM_TX(1)`, type `0x1` without the 128-bit
flag → 32-bit `tegra_hsp_sm_send32` path. Upstream `tegra194.dtsi` has the identical
node (`<&hsp_aon TEGRA_HSP_MBOX_TYPE_SM TEGRA_HSP_SM_TX(1)>`, VERIFIED) and the
`nvidia,tegra194-tcu.yaml` binding example uses the same two channels.

Formula and result (driver `SZ_64K + i * SZ_32K`, register `HSP_SM_SHRD_MBOX = 0x0`):

| Channel | HSP base | + 0x10000 + i × 0x8000 | MMIO address of the 32-bit mailbox word |
|---|---|---|---|
| TX (hsp_aon SM1) | 0x0C150000 | 0x10000 + 0x8000 | **0x0C168000** |
| RX (hsp_top0 SM0) | 0x03C00000 | 0x10000 + 0 | **0x03C10000** |

NVIDIA's own UEFI agrees: `edk2-nvidia/Platform/NVIDIA/Kconfig` (VERIFIED)

```
config DEBUG_SERIAL_PORT_TCU_RX_MAILBOX
hex "TCU RX Mailbox address"
default 0x03C10000

config DEBUG_SERIAL_PORT_TCU_TX_MAILBOX
hex "TCU TX Mailbox address"
default 0x0C168000
```

fed into `PcdTegraCombinedUartTxMailbox` (`NVIDIA.common.dsc.inc`, VERIFIED). Both HSP
blocks are mapped by Linux from EL2 (`/proc/iomem`: `03c00000-03c9ffff : 3c00000.hsp`,
`0c150000-0c1dffff : c150000.hsp`, `raw/orin-iomem.txt:93,124`, VERIFIED), so they are
reachable from the payload at EL2 with the MMU off (identity PA).

### 5.3 The word format, as NVIDIA's bare-metal writer sees it — VERIFIED

`edk2-nvidia/Silicon/NVIDIA/Library/TegraCombinedSerialPort/TegraCombinedSerialPortLib.c`
(BSD-2-Clause-Patent) — a UEFI `SerialPortLib`, i.e. a non-Linux client of the same
mailbox:

```c
typedef struct {
  UINT8      Data[3];
  UINT8      NumberOfBytes : 2;
  BOOLEAN    Flush         : 1;
  BOOLEAN    HwFlush       : 1;
  UINT8      Reserved      : 3;
  BOOLEAN    Interrupt     : 1;
} TEGRA_COMBINED_UART_PIO;

typedef union {
  UINT32                     RawValue;
  TEGRA_COMBINED_UART_PIO    Pio;
} TEGRA_COMBINED_UART;

STATIC BOOLEAN EFIAPI IsDataPresent (UINTN MailboxAddress)
{
  TEGRA_COMBINED_UART  CombinedUartData;
  CombinedUartData.RawValue = MmioRead32 (MailboxAddress);
  return CombinedUartData.Pio.Interrupt;
}

  while (Buffer < Final) {
    while (IsDataPresent (TxMailbox) == TRUE) {
    }
    CombinedUartData.Pio.NumberOfBytes = 0;
    CombinedUartData.Pio.Reserved      = 0;
    CombinedUartData.Pio.Flush         = TRUE;
    while ((Buffer < Final) &&
           (CombinedUartData.Pio.NumberOfBytes < 3))
    {
      CombinedUartData.Pio.Data[CombinedUartData.Pio.NumberOfBytes] = *Buffer;
      CombinedUartData.Pio.NumberOfBytes++;
      Buffer++;
    }
    CombinedUartData.Pio.Interrupt = TRUE;
    MmioWrite32 (TxMailbox, CombinedUartData.RawValue);
    while (IsDataPresent (TxMailbox) == TRUE) {
    }
  }
```

So the 32-bit word is:

| Bits | Meaning | Linux driver | UEFI library |
|---|---|---|---|
| 0–7, 8–15, 16–23 | char 0, 1, 2 | `TCU_MBOX_BYTE(i, x)` | `Data[0..2]` |
| 24–25 | number of valid chars (1–3) | `TCU_MBOX_NUM_BYTES(count)` | `NumberOfBytes` |
| 26 | flush | not set | `Flush = TRUE` every word |
| 27 | hardware flush | not set | not set |
| 28–30 | reserved (0) | 0 | `Reserved = 0` |
| 31 | FULL — set by writer, cleared by the SPE | `HSP_SM_SHRD_MBOX_FULL` (set by `tegra-hsp.c`) | `Interrupt = TRUE` |

Minimal polled TX for a payload (HYPOTHESIS assembled from the two VERIFIED writers):
wait until `[0x0C168000] & BIT(31) == 0`; write `(c0 | c1<<8 | c2<<16 | n<<24 |
BIT(26) | BIT(31))`; wait again. Linux waits up to 1000 ms per word (`mbox_flush(tcu->tx,
1000)`); UEFI waits forever. Neither side needs interrupts, the HSP common-region
registers, or `HSP_INT_DIMENSIONING`. Send `\r\n` explicitly (Linux does the
translation in the tty layer/driver). RX (SM0 of `hsp_top0`) is the mirror image
(reader polls FULL, reads, then clears the word) but is not needed for a console.

### 5.4 Does the SPE keep servicing the mailbox once Linux is gone?

Reasoning from the boot chain (HYPOTHESIS, no test):

* NVIDIA: "The multiplexing is accomplished in the Sensor Processing Engine (SPE)."
  and the demuxer output lists streams "RCE, FSI, PSCFW, DCE, BPMP, SCE, SPE, TZ, and
  CCPLEX" (Developer Guide r36.4.3 *Tegra Combined UART*, VENDOR_CLAIM). The SPE is the
  AON Cortex-R5; the mailbox is in the AON HSP block; and the same CCPLEX mailbox is
  written by MB1/MB2 (per forum 370278, "UARTC ... outputs firmware logs from MB1, MB2,
  FSI, UEFI, and BPMP", VENDOR_CLAIM) and by UEFI (the EDK2 library above, VERIFIED)
  before any Linux runs. Nothing in Linux's kexec path talks to the SPE or the AON HSP
  (there is no HSP/TCU shutdown hook — `tegra-tcu.c` has no `->shutdown`; VERIFIED by
  reading the driver's probe/console code, absence of a shutdown method is HYPOTHESIS
  since the tool did not list every function).
* The `[RCE] TCU debug prints will be routed to traces.` dmesg line
  (`raw/orin-ttys.txt`) shows other firmware clients are live on the same mux while
  Linux runs, consistent with an always-on service.
* Risks: the SPE firmware might apply per-client flow control or expect the CCPLEX
  client to drain an RX mailbox; and on the way out Linux could leave the TX word FULL
  mid-message (harmless — the payload's first wait absorbs it). The SPE's protocol
  beyond the word format (tags, escape bytes, framing on the physical UART) is not
  public — UNKNOWN; the host-side `nv_tcu_demuxer` handles it.

### 5.5 Where it comes out physically

* The console the operator sees on the Orin Nano devkit is `ttyTCU0`
  (`console=ttyTCU0,115200`, `/sys/class/tty/console/active = ttyTCU0 tty0`,
  `serial-getty@ttyTCU0` running; `raw/orin-ttys.txt`, `raw/orin-boot-config.txt:16`,
  VERIFIED) on the J14 12-pin header: "Jetson UART2 TXD - Pin 3", "Jetson UART2 RXD -
  Pin 4", "Jetson GND - Pin 11" (Developer Guide r36.4.3 *Board Automation*,
  VENDOR_CLAIM). The same page says "The console port is physically connected to
  UART3 (the debug UART)." — the naming is at module-pin level.
* The SoC instance behind it is UARTC at `0x0c280000` (AON domain), owned by the
  BPMP/SPE combined-UART setup, pads `UART3_TX_PCC5/UART3_RX_PCC6` (forum 370278,
  NVIDIA: "This use case is unsupported and unverified" — VENDOR_CLAIM). Consistent
  with that, **no `serial@c280000` node exists anywhere in the live Linux DT**
  (`raw/orin-devicetree.txt:294-299`, VERIFIED) — i.e. the physical UART is not
  Linux's to touch; the mailbox is.

---

## 6. An 8250-compatible path

### 6.1 Register compatibility — VERIFIED

* `drivers/tty/serial/8250/8250_tegra.c` (GPL-2.0+, NVIDIA 2020): single match entry
  `{ .compatible = "nvidia,tegra20-uart", }`; probe sets `port->iotype = UPIO_MEM32;
  port->regshift = 2; port->type = PORT_TEGRA; port->flags = UPF_BOOT_AUTOCONF |
  UPF_FIXED_PORT | UPF_FIXED_TYPE;`; the only Tegra-specific code is
  `tegra_uart_handle_break()` (drain RX on break). It is a plain 8250 port with 32-bit
  registers at a 4-byte stride.
* `Documentation/devicetree/bindings/serial/8250.yaml`: the `items` list
  `nvidia,tegra30-uart ... nvidia,tegra234-uart` falls back to `const:
  nvidia,tegra20-uart`; `reg-shift`: "Quantity to shift the register offsets by."
* `drivers/tty/serial/serial-tegra.c` (the `hsuart` driver, GPL-2.0, NVIDIA 2012-2019):
  `tegra_uart_read/write` are `readl/writel(... membase + (reg << regshift))` with
  `u->regshift = 2` in probe; it uses the standard `UART_LCR/IER/FCR/LSR/TX` register
  numbers; matches `nvidia,tegra20/30/186/194-hsuart` with per-chip
  `tegra_uart_chip_data` (FIFO-reset quirks, DMA burst, baud tolerance). Same register
  file, different driver policy (DMA, FIFO handling).
* `nvidia,tegra20-hsuart.yaml` title: "NVIDIA Tegra20/Tegra30 high speed (DMA based)
  UART controller driver"; requires `clocks`, `resets`, `dmas` — i.e. the block is
  clock/reset-managed through BPMP.
* QNX already ships the matching callout: `callout_debug_tegra.S` — "nVidia Tegra
  polled serial I/O. Similar to 8250 uart with 32-bit registers.", TX spins on `LSR` at
  `+0x14` then stores to `+0x00` (H2, `harvest-sdp.md` table row `callout_debug_tegra.o`,
  VERIFIED there; Apache-2.0 source in the BSP zip), plus `callout_debug_8250_32b.S`,
  `hw_ser8250_32b.c`, and `callout_debug_pl011.S` / `hw_serpl011.c`
  (`raw/bsp-startup-lib-files.txt:24-29,126,173-175`, VERIFIED names).

Polled TX on such a port: `THR = base + 0x00`, `LSR = base + 0x14` (5 << 2), wait
`LSR.THRE (bit 5)` (or `TEMT` bit 6), 32-bit accesses. Baud/LCR/FCR as configured by
whoever last opened the port.

### 6.2 Which ports exist on this board (live DT + tty state) — VERIFIED

| Node | compatible | status | Linux tty | Physical | Notes |
|---|---|---|---|---|---|
| `serial@3100000` (uarta) | `nvidia,tegra194-hsuart` | okay | `ttyTHS1` (irq 112, `TEGRA_UART`, "TX in PIO mode") | 40-pin header UART1 (`uart1_tx_pr2/uart1_rx_pr3`, function `uarta`, `raw/orin-header-uart.txt`) | no getty, nobody holds it (`fuser` empty) |
| `serial@3110000` (uartb) | `nvidia,tegra234-uart`,`nvidia,tegra20-uart` | **disabled** | none (ttyS0–3 have `iomem_base=0x0`) | unknown | the only 8250_tegra-class node; clocks `<&bpmp 0x9c>`, resets `<&bpmp 0x65>` |
| `serial@3140000` (uarte) | `nvidia,tegra194-hsuart` | okay | `ttyTHS2` (irq 113) | unknown (`dma-names = rx,tx`) | no getty |
| `serial@31d0000` (uarti) | `arm,sbsa-uart` | okay | `ttyAMA0` (PL011 SBSA, irq 117, `current-speed = 115200`, no `clocks`/`resets`) | on AGX Orin: micro-USB debug port ("ttyACM1"); on Orin Nano: UNKNOWN — Ghaf says AGX "is the only NVIDIA Jetson Orin with the UARTI port available" (third-party claim) | firmware-configured; SBSA register subset; QNX has PL011 callouts |
| `/serial` (tcu) | `nvidia,tegra234-tcu`,`nvidia,tegra194-tcu` | okay | `ttyTCU0` (console) | J14 pins 3/4 via SPE/UARTC | §5 |

Source lines: `raw/orin-devicetree.txt:209-292`, `raw/orin-ttys.txt`,
`raw/orin-followup.txt` ("per-tty port info"), `raw/orin-iomem.txt:69-74`.

Correction for H2: `harvest-sdp.md` line 397 labels `serial@3100000` as
`"nvidia,tegra234-uart","nvidia,tegra20-uart"` — the live DT shows that compatible on
`serial@3110000` (disabled), while `serial@3100000` is `nvidia,tegra194-hsuart` (VERIFIED
above). H2's conclusion (the Tegra callout is the right *shape*) still holds because
both compatibles describe the same 4-byte-stride 16550 register file.

### 6.3 Practical caveats for a post-kexec payload (HYPOTHESIS)

* Clocks/resets for `serial@31x0000` are BPMP-managed (`clocks = <&bpmp ...>`); the
  `serial-tegra` driver enables the clock on open and may gate it on close, and
  `serial@3110000` (disabled) has never been enabled by Linux. Touching a clock-gated
  Tegra block from the CPU typically ends in a CBB fabric error/SError — so an 8250 path
  is only safe on a port Linux *left* clocked (e.g. keep `ttyTHS1` open until
  `kexec -e`, or have the payload talk to BPMP — out of scope). The TCU mailbox avoids
  this entirely: the AON HSP is always-on and the SPE is the consumer.
* The SBSA UART at `0x31d0000` needs no clock management by construction (no
  `clocks` property; firmware-owned baud) and Linux has it as `ttyAMA0` — the
  lowest-risk *MMIO* console **if** it reaches a connector on the P3768 carrier, which
  is UNKNOWN for this kit.
* With `-l`, kexec-tools' purgatory can print through `arm64_sink` (a byte sink
  address patched from the command line) — useful for a first "did we get past
  purgatory" signal on an already-clocked 8250 port; the exact option name in 2.0.22
  was not verified (UNKNOWN).

---

## 7. Open unknowns (carried into the structured output)

1. Whether QNX `startup` (`hypervisor_enable.S` / `hypervisor_setup.c` and `cstart`)
   tolerates entry at EL2 with `HCR_EL2.E2H=1`/`TGE=1` and a stale `VBAR_EL2`.
2. Whether the L4T `5.15.148-tegra` `machine_kexec.c` is the v5.15 version or carries
   the later ttbr0-relocation rewrite (no effect on EL/registers).
3. Ubuntu `kexec-tools 2.0.22`: default syscall selection (`-a` semantics) and the
   exact `arm64_locate_kernel_segment()` in that version.
4. Tegra234 TF-A: what its PSCI `CPU_OFF`/`CPU_ON` handlers do to the GIC CPU
   interface/redistributor (upstream TF-A has no `t234`).
5. SPE combined-UART firmware behaviour toward a client that never drains RX; framing
   on the physical UART; whether bit 26 (flush) matters for latency.
6. Physical routing of UARTI (`0x31d0000`) on the P3768 carrier; whether `uarte`
   reaches a connector.
7. Which config fragment sets `CONFIG_TEGRA_HSP_MBOX=y` in the R36.4.7 build (it is
   `=y` on the board but absent from the r36.2 mirror defconfig).
8. No published arm64 report of kexec-ing a non-Linux payload was found; the header
   mechanism is shared but nobody documented the `E2H=1` entry problem for third-party
   kernels.

---

## 8. Sources

Linux (torvalds/linux via raw.githubusercontent.com; `master` unless noted):
`arch/arm64/kernel/machine_kexec.c` (+ `v5.15`), `arch/arm64/kernel/cpu-reset.S`
(+ `v5.15`), `arch/arm64/kernel/cpu-reset.h` (`v5.15`), `arch/arm64/kernel/hyp-stub.S`
(+ `v5.15`), `arch/arm64/kernel/relocate_kernel.S` (+ `v5.15`),
`arch/arm64/include/asm/virt.h`, `arch/arm64/kernel/head.S`,
`arch/arm64/kernel/kexec_image.c`, `arch/arm64/kernel/machine_kexec_file.c`,
`arch/arm64/include/asm/image.h`, `Documentation/arch/arm64/booting.rst`,
`arch/arm64/kernel/smp.c`, `arch/arm64/kernel/psci.c`, `arch/arm64/kernel/process.c`,
`kernel/cpu.c`, `kernel/kexec_core.c`, `kernel/kexec.c`, `kernel/kexec_file.c`,
`arch/arm64/Kconfig` (+ `v5.15`), `arch/arm64/configs/defconfig` (+ `v5.15`),
`arch/arm64/kvm/arm.c`, `drivers/irqchip/irq-gic-v3.c`, `drivers/irqchip/irq-gic-v3-its.c`,
`drivers/tty/serial/tegra-tcu.c`, `drivers/mailbox/tegra-hsp.c`,
`include/dt-bindings/mailbox/tegra186-hsp.h`,
`Documentation/devicetree/bindings/serial/nvidia,tegra194-tcu.yaml`,
`Documentation/devicetree/bindings/serial/nvidia,tegra20-hsuart.yaml`,
`Documentation/devicetree/bindings/serial/8250.yaml`,
`drivers/tty/serial/8250/8250_tegra.c`, `drivers/tty/serial/serial-tegra.c`,
`arch/arm64/boot/dts/nvidia/tegra194.dtsi`, `tegra234.dtsi` (truncated by tool),
`tegra234-p3768-0000+p3767.dtsi`, `tegra234-p3767.dtsi`.

kexec-tools (github.com/horms/kexec-tools, `main`): `kexec/arch/arm64/kexec-arm64.c`,
`kexec/arch/arm64/kexec-image-arm64.c`, `kexec/arch/arm64/image-header.h`,
`kexec/kexec.c`, `purgatory/arch/arm64/entry.S`, `purgatory/arch/arm64/purgatory-arm64.c`,
`purgatory/purgatory.c`.

NVIDIA: `github.com/NVIDIA/edk2-nvidia` (`Silicon/NVIDIA/Library/TegraCombinedSerialPort/
TegraCombinedSerialPortLib.{c,inf}`, `Silicon/NVIDIA/NVIDIA.dec`,
`Platform/NVIDIA/NVIDIA.common.dsc.inc`, `Platform/NVIDIA/Kconfig`);
`github.com/OE4T/linux-jammy-nvidia-tegra` branch `oe4t-patches-l4t-r36.2-1018.18`
`arch/arm64/configs/defconfig`; docs.nvidia.com Jetson Linux Developer Guide r36.4.3:
`AT/JetsonLinuxDevelopmentTools/TegraCombinedUART.html`, `SD/Kernel/DebuggingTools.html`,
`AT/BoardAutomation.html`; forums.developer.nvidia.com threads 365485, 344580, 241481,
303049, 370278, 300625.

Others: `github.com/xen-project/xen` `xen/arch/arm/arm64/head.S`; `github.com/u-boot/u-boot`
`arch/arm/include/asm/boot0-linux-kernel-header.h`, `arch/arm/Kconfig`;
`github.com/zephyrproject-rtos/zephyr` `arch/arm64/core/header.S`;
`github.com/freebsd/freebsd-src` `sys/arm64/arm64/locore.S`; docs.sel4.systems
`projects/elfloader/`; `github.com/ARM-software/arm-trusted-firmware`
`plat/nvidia/tegra/common/tegra_pm.c` and the `plat/nvidia/tegra/soc` listing;
ghaf.tii.ae `nvidia_uarti_net_vm`.

Repo-internal: `results/orin-native-port/20260909T1100Z/raw/orin-{kexec,identity,
firmware-el,uefi-dmesg,devicetree,iomem,ttys,header-uart,followup,followups,boot-config}.txt`,
`raw/ifs-first-64-bytes.txt`, `raw/dumpifs-plain-ifs-header.txt`,
`raw/bsp-startup-lib-files.txt`, `harvest-sdp.md`, `scripts/launch-qnx-vm.sh`,
`scripts/launch-qhv-tcg.ps1`.
