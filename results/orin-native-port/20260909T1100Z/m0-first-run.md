# M0 ran. Four of the plan's ranked unknowns closed in one boot.

2026-09-09, 23:38 local. The M0 shim executed on the Jetson Orin Nano — the first
instruction of this port to run on the hardware. It printed its state, normalised
what it meant to normalise, and reset the board, which came back on its own about
twenty seconds later. Nothing was flashed and nothing persists: the boot
configuration hashes are unchanged and the only file on the board is the 8 KiB
image in the owner's home directory.

Run by the owner from their own shell:

```bash
sudo kexec -s -l t234-shim.kimg && sudo systemctl kexec
```

## What came back

Recovered from `/sys/fs/pstore/console-ramoops-0`, 419 bytes, written by the shim
into the ramoops console zone and surfaced by the kernel on the next boot:

```
T234-SHIM EL=2 HCR=0000000488000000 SCTLR2=0000000030400800 MMFR1=0000000010212122
MPIDR=0000000081000000 CNTFRQ=0000000001dcd650 CNTHCTL=0000000000000cb6
CNTHPCTL=0000000000000005 MDCR=0000000000000006 WDT0=0000000000710010/0000000000000010
WDT1=0000000000700000/0000000000000000 TXMB=0000000000000000 PC=0000000080080000
X0=0000000270400000 DTBMAGIC=00000000edfe0dd0
NORMALISED TCUDROPS=0000000000000000
PROBE-RESET
```

(One line in the original; wrapped here.)

## Decoded

| field | value | what it settles |
|---|---|---|
| `EL` | **2** | **Unknown #1, the highest-ranked risk in the plan.** kexec on NVIDIA's 5.15.148-tegra fork enters the payload at EL2, as upstream source said it would. This was kill criterion (a): at EL1 the whole kexec approach would have been dead and the only route left would have been the UEFI path with its stacked firmware unknowns. |
| `TCUDROPS` | **0** | **Unknown #2.** Every one of the ~330 characters went into the mailbox with the FULL bit clearing each time, so the SPE is still draining it after Linux is gone. Precisely: the SPE consumed the words. Whether they reached the physical wire is still unobserved — nobody has a serial adapter on J14 yet. |
| `PC` | **0x80080000** | **Unknown #6, now confirmed at execution rather than from a dry run.** The landing check passed. The placement arithmetic the plan carried as a hypothesis for a day is correct on this board. |
| black box | 419 bytes in pstore | **Unknown #7's remaining half.** A non-Linux payload can write the ramoops console zone in a form the kernel accepts, and pstore surfaces it on the next boot. This is the output channel that made the USB-TTL adapter optional, and it now works end to end. |
| `HCR` | `0x4_8800_0000` | E2H (34), RW (31) and TGE (27) all set: exactly the VHE state the plan predicted Linux leaves behind, uncleaned. |
| `SCTLR2` | `0x30400800` | M, C and I all clear — MMU and both caches off at entry, as the entry contract says. |
| `MMFR1` | `0x10212122` | The VH field at bits 11:8 is 1, so **`-Q enable,el2-host` is feasible on this silicon**. That is K8's hardware half, previously reasoned from the part number. |
| `CNTHPCTL` | `0x5` | ENABLE set and ISTATUS set: the EL2 physical timer was **armed and had already fired** when we took over. The shim disarms the timers for exactly this reason, and this is the first direct evidence that it needed to. |
| `CNTFRQ` | `0x1dcd650` | 31,250,000 Hz — 32 ns per tick, confirming the conversion every future measurement depends on. |
| `WDT0` | `0x710010` / `0x10` | Armed and counting at hand-off, reconfirming K9 from inside the payload rather than from Linux. |
| `X0` / `DTBMAGIC` | `0x2_7040_0000` / `0xedfe0dd0` | A valid device tree, placed high in RAM. Note this is the **top-down** placement the kernel does on the `kexec_file_load` path — the opposite of what `kexec-tools` did on the `kexec_load` path, where the tree landed immediately after the image. Both behaviours are now observed rather than assumed. |
| `MPIDR` | `0x81000000` | Boot core affinity 0, with the RES1 and MT bits set. Consistent with the affinity table the board directory carries. |
| `TXMB` | `0` | The mailbox was empty before the first write, so the SPE had already drained whatever Linux left. |

## What it does not show

No QNX instruction ran. This was the shim alone in probe mode; the board directory
that was written today has never been packaged into an image, and M1 has not been
attempted.

The `hang` mode was not run, so whether an **un-petted** watchdog returns the board
is still open. This run reset itself deliberately through PSCI, which is a
different mechanism and says nothing about the watchdog path.

And the characters reaching the SPE is not the same as characters reaching a
terminal. The serial adapter remains the only way to see output live rather than
after a reset.

## Afterwards

The board is up, `kexec_loaded` is 0, `/boot` is untouched, and the watchdog is
armed again under systemd. The raw `/dev/mem` read of the carveout in the harvest
script bus-errors now that ramoops has reclaimed the zone — harmless, and the
pstore path is the better one anyway.
