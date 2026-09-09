# startup/ — the `startup-t234-orin-nano` board directory

Empty on purpose. This is where M1 lives, and M1 has not been written.

The [plan](../../docs/orin-native-port-plan.md) §5 specifies what goes here and
why each piece is needed. Summarised, so the shape is visible before the code
exists:

| file | what it must do |
|---|---|
| `main.c` | the call order, and the board's own options `m:W:t` — RAM size, watchdog policy, EL2 virtual-timer probe. `-D`, `-P` and `-Q` come from the library's common set and must not be redefined. |
| `init_raminfo.c` | hard-coded RAM. The firmware device tree has no `/memory` node and `kexec` does not add one, so nothing can be read from it. |
| `aarch64/init_intrinfo.c` | GICv3 by explicit range, not the auto-sizing call — this SKU's redistributor frames are not contiguous and the auto-sizing form asserts on the last two cores. |
| `board_smp.c`, `psci_cpu_id.c` | six cores over PSCI, with a board override mapping the linear index to this SKU's actual affinities. The library's default returns the index verbatim, which is wrong here. |
| `hw_sertcu.c`, `aarch64/callout_debug_tcu.S` | the Tegra Combined UART as startup's debug device and as procnto's kernel console, one patcher per mailbox. |
| `wdt.c` | read and report both watchdogs always; disable or kick only when asked. A watchdog is armed at hand-off, so the milestones that outlast two minutes depend on this. |
| `build`, `Makefile`, `pinfo.mk` | modelled on the BSP's Apache-2.0 reference board. |

Everything here will be our own code under Apache-2.0 headers, to match the
templates it is modelled on. No QNX-shipped file is copied in, and the built
`startup-t234-orin-nano` is a build output, not a committed artefact.

The shim in [../shim/](../shim/) is what hands control to the image this
directory's startup will boot; it exists and assembles today.
