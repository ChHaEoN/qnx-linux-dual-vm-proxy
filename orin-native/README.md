# orin-native — Phase 3b: QNX running natively on the Jetson Orin Nano

Source for the native port. Everything here is our own code, written against
public documentation and Apache-2.0 / BSD sources. No QNX-shipped file, header
or binary lives in this directory, and none is committed anywhere in the repo.

The plan this implements, with its evidence classes, milestone ladder and
claims register, is [docs/orin-native-port-plan.md](../docs/orin-native-port-plan.md).
The facts it rests on are in `results/orin-native-port/`. Nothing here has run
on the board yet.

## Why a shim exists at all

The board runs NVIDIA L4T. The port does not replace the firmware or the boot
chain: it uses `kexec` from the running Linux to hand control to a QNX image,
so a power cycle always brings the board back untouched. `kexec` will only
accept a payload that carries the 64-byte arm64 `Image` header, and a QNX raw
IFS already has its own preboot stub in the bytes that header would occupy. So
an 8 KiB page carrying the header is prefixed to the IFS, and that page is also
where the first native code runs.

## Layout

| path | what it is |
|---|---|
| `shim/t234-shim.S` | the M0 shim: arm64 Image header, EL2 vectors, the state report, the minimal normalisation the QNX startup library does not do, and the jump into the IFS. MIT. |
| `shim/build-shim.sh` | assembles the shim, checks the header byte-for-byte, and optionally concatenates it with an IFS. Compile-only. |
| `startup/` | the `startup-t234-orin-nano` board directory (M1 onward). Not written yet. |

## Building

Needs the QNX SDP 8.0 toolchain. Either source `qnxsdp-env.sh` first, or point
the script at the install:

```bash
QNX_BASE=~/qnx800 ./shim/build-shim.sh probe
```

Three modes, all from the same source:

| mode | what it does | what it answers |
|---|---|---|
| `probe` | print the state bank, then PSCI `SYSTEM_RESET` | the exception level kexec enters at, what Linux left armed, whether either console works, where we landed |
| `hang` | print, then `wfi` forever with nothing petting the watchdog | whether the systemd-armed WDT0 returns the board on its own |
| `jump` | print, normalise, branch into the IFS | M1 |

Output goes to two places at once: the Tegra Combined UART through its HSP
mailbox (needs a 3.3 V USB-TTL adapter on J14 to see live), and the ramoops
console zone in DRAM, which `pstore` surfaces as
`/sys/fs/pstore/console-ramoops-0` once L4T is back. The second channel needs
no hardware, which is why M0 and M1 can run before anything is bought.

## Running it

The first step is deliberately not a boot. It loads the image into kernel
memory and unloads it again, which proves the header format and the syscall
path without risking a reboot:

```bash
sudo kexec -s -l t234-shim.kimg && cat /sys/kernel/kexec_loaded && sudo kexec -u
```

The rest of the M0 sequence, including how to quiesce DMA first and how the
board recovers from each failure, is in §7 of the plan. Nothing in that
sequence writes to the ESP, the UEFI variables, `extlinux.conf`, the QSPI or
the boot partitions.

## Licence note

Our code here is MIT, matching the repo. The board directory under `startup/`
will carry Apache-2.0 headers to match the QNX BSP templates it is modelled on.
Logs and measurements this code produces are evaluation output under the QNX
Non-Commercial licence and stay private until that is cleared — see §9 of the
plan.
