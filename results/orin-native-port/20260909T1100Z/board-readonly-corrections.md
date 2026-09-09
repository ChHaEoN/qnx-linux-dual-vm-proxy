# Read-only board checks that correct the synthesised plan (2026-09-09)

Executed by the orchestrating session over ssh, `sudo -n` **reads only**: no write, no reboot, no kexec, no
module load/unload, no persistent change. Raw output: `raw/orin-readonly-followup-2.txt` (redacted).
Evidence class: **VERIFIED** unless stated.

## 1. K9 is REFUTED: a hardware watchdog *is* armed at hand-off

The plan (claim K9, and correction F6 in §2.1) concluded no CCPLEX watchdog counts, because the live device
tree has `/bus@0/watchdog@2190000` with `status = "disabled"`. That was the wrong node to look at:

- `dmesg`: `systemd[1]: Using hardware watchdog 'NVIDIA Tegra186 WDT', version 0, device /dev/watchdog`
  followed by `systemd[1]: Set hardware watchdog to 2min.`
- `/dev/watchdog` and `/dev/watchdog0` exist; `/sys/class/watchdog/watchdog0/device` -> **`2080000.timer`**
  (the TKE timer block), not `watchdog@2190000`. The driver is built in, so nothing appears in `lsmod`.
- Register peek: `WDT0 @0x02190000 WDTCR = 0x00710010`, `WDTSR = 0x00000011` — configured and counting.
  (`WDT1 @0x021A0000` is idle: CR `0x00700000`, SR `0`.)

**Consequences for the port, both directions:**

- *Free unattended recovery.* Once systemd stops petting it (it is the last thing alive before `kernel_kexec`),
  an un-petted WDT0 should reset the SoC and bring L4T back with no human at the board. The plan wanted exactly
  this and proposed writing shim code to arm it (§3.3 step 5); that code is unnecessary. HYPOTHESIS until M0's
  `hang` test observes it: whether systemd disarms the watchdog on the kexec path rather than leaving it armed.
- *A hard time limit on every experiment.* If it stays armed, any QNX payload has roughly **2 minutes** before a
  reset — enough for M0/M1 markers, **not** enough for M3/M4 (guest boot plus a trace capture at 11 KB/s over
  the TCU). So the board `-W` policy stops being optional: startup must read WDTCR/WDTSR, and M3/M4 need either
  `-Wdisable` (unlock `WDTUR = 0xC45A`, then `WDTCMDR` disable) or a kicker (`wdtkick`, Apache-2.0, in the BSP
  zip under `src/hardware/support/wdtkick`). M0 must print both registers *before* anything else, which it
  already does.

## 2. The kexec-load hazard does not exist on this board

`/etc/default/kexec` has `LOAD_KEXEC=false`, so the shutdown script never re-loads a Linux kernel over our
payload. Plan §3.4's `systemctl mask --runtime kexec-load.service` step can be dropped; `systemctl kexec` is
safe to use directly, keeping the clean SD unmount.

## 3. The RAM black box is real, and DRAM survives a reset

`/sys/fs/pstore` holds `console-ramoops-0` (5,571 B) and `dmesg-ramoops-0` (67,970 B) dated 2026-09-08 23:30-23:33
— i.e. from the board's own drop-off that evening. `ramoops` + `reed_solomon` are loaded, `CONFIG_PSTORE_CONSOLE=y`.
That settles plan unknown #7's retention half positively (DRAM contents survive the reset and pstore recovers
them) and gives a zero-hardware output channel while waiting for the USB-TTL adapter. Still UNKNOWN: the zone
offsets (`/sys/module/ramoops/parameters/*` all read empty), so a payload cannot yet address the console zone
directly; `/dev/pmsg0` is absent, so the pmsg round-trip test in §7 M0 pre-flight cannot be run as written.
`CONFIG_STRICT_DEVMEM=y`, though device ranges are readable (the peek above worked), so the `dd if=/dev/mem`
fallback for a `no-map` RAM range remains HYPOTHESIS.

## 4. Smaller items

- TCU mailboxes are idle as the protocol assumes: TX `0x0C168000` and RX `0x03C10000` both read `0x00000000`
  (bit 31 clear). The write path in plan §4.1 is consistent with what the hardware shows at rest.
- CPU clock is **not** pinned: governor `schedutil`, current 1,113,600 kHz against a 1,344,000 kHz max. The
  plan's `performance` pin before kexec stays necessary, and the M4 PMCCNTR calibration stays load-bearing.
- `/dev/ttyTHS1` is root-owned and unheld; the plan's "open it from Linux before kexec to leave uarta clocked"
  step needs `sudo`, which it did not say.
