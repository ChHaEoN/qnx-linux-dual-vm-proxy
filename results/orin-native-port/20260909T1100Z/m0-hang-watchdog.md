# The watchdog does not recover the board. The plan's free safety net is not there.

2026-09-09, 23:45. The M0 shim was run again in `hang` mode: print the state bank,
then `wfi` forever with nothing petting WDT0. The question was whether the
watchdog systemd arms at two minutes brings the board back on its own, which the
plan had been treating as free unattended recovery ever since the watchdog was
discovered to be armed.

**It does not.** The board stayed unreachable for three and a half minutes past a
two-minute watchdog and had to be power-cycled by hand.

## What was observed

| time after the jump | state |
|---|---|
| 0 s | `kexec -s -l` then `systemctl kexec`; the ssh connection drops, as expected |
| 33, 76, 119, 163, 206 s | no ssh, no ping |
| ~210 s | the owner, at the board: **green power LED lit, fan stopped** |
| — | recovered only by pulling the power |

The LED and fan together are the useful part. The green LED is a power-rail
indicator and says nothing about software; the fan is driven by Linux's PWM fan
driver through the thermal zones, so it stops as soon as Linux is gone. Powered,
idle, nothing running — exactly what a CPU parked in `wfi` looks like from the
outside, and distinct from a brown-out or a hard crash, where the LED would be
off too.

Nothing could have woken it: the shim enters with `DAIF` masked and never unmasks,
so no interrupt reaches the parked core, and there is no console or network to
reach it through either.

## Why the watchdog did not fire

Most likely systemd disarms it on the way out. It is systemd that arms the
watchdog in the first place — `Using hardware watchdog 'NVIDIA Tegra186 WDT'`,
`Set hardware watchdog to 2min` — and a clean shutdown path, which
`systemctl kexec` is, is exactly where it would hand the device back rather than
leave a timer running into whatever comes next.

This is a hypothesis, not a reading. Settling it costs one boot: the shim already
prints `WDT0 CR/SR`, and the previous `probe` run showed `CR=0x00710010, SR=0x10`
at hand-over, so the register was still configured. The distinguishing test is
whether the counter is actually running, which needs either a second sample a
known interval later or a read of the TKE timer source feeding it.

## What changes because of this

- **The plan's "free unattended recovery" is deleted.** Every hang from here on
  costs a physical power cycle. That is a cheap sentence to write and an expensive
  one to live with on a board that is not always in reach.
- **Every milestone must reach a reset or a jump on every path.** The shim already
  does — `probe` resets, `jump` branches, and the exception vectors reset — but
  M1 onward inherits the rule: QNX startup failing into a wait loop with no
  watchdog behind it is a trip to the board.
- **The remotely switchable mains socket moves from recommended to necessary** for
  anyone wanting to run these experiments without standing next to the hardware.
  It is the only thing that restores the recovery path the watchdog was assumed
  to provide.
- **`-Wdisable` loses most of its point.** It existed so that M3 and M4, which
  outlast two minutes, would not be killed mid-measurement. If the watchdog is
  not counting after hand-over then nothing was going to kill them, and the flag
  becomes insurance against the opposite finding rather than a requirement.

## The second question this run asks

Whether the black box survives a cold power cycle. The `probe` run's text came
back through pstore after a PSCI reset, which is a warm reset that preserves
DRAM. This time the recovery was a power pull, and DRAM contents are not expected
to survive that. **It does not survive.** After the power pull, `/sys/fs/pstore` came back
completely empty — not just missing the shim's text, but missing the
`dmesg-ramoops` files from the previous day as well. The board had been up long
enough for the earlier ones to be several days old, and they are gone too, so
this is DRAM losing its contents rather than pstore choosing not to surface them.

That bounds the black box precisely:

| recovery path | shim's output |
|---|---|
| PSCI `SYSTEM_RESET`, as `probe` mode does | **survives** — 419 bytes came back through pstore |
| an exception, which the shim's vectors turn into a reset | survives, same mechanism |
| a hang, recovered by pulling the power | **lost** |

Which makes the rule sharper than "every path must reach a reset". A hang costs
the power cycle *and* everything the payload printed on its way there. Writing
incrementally, as the shim does — updating the length words on every byte so a
fault mid-line still leaves a readable prefix — buys nothing at all in the case
where a human has to reach for the plug. It buys everything in the case where
the code faults, which is the case the exception vectors already handle.

The practical consequence for M1 onward: a startup that fails into a wait loop
is the worst outcome available, worse than one that crashes, because crashing
prints. Anything resembling a spin should carry a bounded deadline and a reset
at the end of it.
