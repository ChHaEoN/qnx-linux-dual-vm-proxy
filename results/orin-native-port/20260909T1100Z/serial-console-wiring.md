# Serial console: why the 40-pin header gave nothing, and why J14 is the right header

2026-09-10. The owner connected an FTDI FT232R USB-TTL adapter to watch M1 live.
This records the wiring attempt, why it produced no output, and the corrected
choice — including a recommendation of mine that the evidence reversed.

## The adapter came up after a driver bind

Windows enumerated the adapter as `FT232R USB UART` with Device Manager error 28
(driver not installed). The FTDI driver packages were already in the driver store
(`ftdibus.inf` and `ftdiport.inf`, FTDI 2.12.36.20, WHCP-signed); a device
re-enumeration bound them and the adapter appeared as **COM3**, status OK.

## First choice: J12, the 40-pin header — no output

I recommended J12 over J14 on two grounds: its location is unambiguous, and its
wiring can be verified from Linux before any of our code runs. The owner wired
adapter RX to **J12 pin 8** and GND to **pin 6**.

A capture script opened COM3 at 115200 8N1 while the board transmitted:

| test | result |
|---|---|
| three lines written to `/dev/ttyTHS1` | **0 bytes** on COM3 |
| distinct labels written to `ttyTHS1`, `ttyTHS2` and `ttyAMA0` at once | **0 bytes** from any of them |

The capture window fully covered the transmit, so timing was ruled out. All three
UARTs failing together pointed away from "wrong port" and toward the pin itself.

## Why: the pin is not muxed to the UART

The carrier board specification (SP-11324-001 v1.0, Table 3-3) confirms pin 8 is
the right pin — `UART1_TXD`, with `UART1_RXD` on pin 10. So the choice of pin was
correct. What the board does with that pin is a different question, and the kernel
answered it:

```
[2430000.pinmux] pin 110 (UART1_TX_PR2): (MUX UNCLAIMED) (GPIO UNCLAIMED)
[2430000.pinmux] pin 111 (UART1_RX_PR3): (MUX UNCLAIMED) (GPIO UNCLAIMED)
```

The `uarta` function exists and lists these groups, but nothing has claimed them.
The UART controller probes (`ttyTHS1`, `status=okay`, 0x03100000) and accepts
writes, yet the pad is not routed to it, so nothing reaches the pin. This matches
two NVIDIA forum threads documenting exactly this failure on the same board family:
driver present, writes succeeding, no signal on pins 8/10.

A caveat worth stating: `MUX UNCLAIMED` is the kernel's view of which driver owns
the pin, not a read of the hardware pinmux register, which the bootloader's pinmux
configuration sets. It is strong evidence, consistent with every observation, but
it is not a register read.

## The reversal: J14 is the header to use

The research that located J14 also undercut the case for J12:

- **uarta is not the console.** Firmware never touches it and Linux only configures
  it on demand, so it would carry nothing from MB1, MB2 or UEFI — and relying on it
  for QNX output would add a dependency on this exact pinmux, and on BPMP keeping
  its clock alive after Linux is gone, which is untested.
- **J14 carries the TCU**, the board's real console (`console=ttyTCU0,115200`).
  It needs none of our code to verify — reboot, and the firmware and Linux boot log
  comes out of it. And the path is already proven end to end: the M0 shim wrote
  roughly 330 characters to the TCU mailbox with `TCUDROPS=0`.

Both earlier objections to J14 are now settled by the carrier specification
(Table 3-4, read in full from the primary PDF):

| J14 pin | signal | direction (from the board) |
|---|---|---|
| 3 | `UART2_RXD` (DEBUG) | input, 3.3 V |
| **4** | **`UART2_TXD` (DEBUG)** | **output, 3.3 V** |
| 7, 9, 11 | ground | — |

J14 is a 1x12 single-row header at the **top edge, left side** of the carrier,
directly above the two camera connectors (J20, J21). The long-standing doubt over
whether TXD is pin 3 or pin 4 is resolved in favour of **pin 4**: the table states
it plainly and defines direction from the board's side. (The same specification
elsewhere calls J14 a "2x4" header; its own 12-pin table and placement legend are
the load-bearing sources, and that line looks like a leftover from an older devkit.)

Wiring for M1: **adapter RX to J14 pin 4, adapter GND to J14 pin 7, nothing else.**
Do not connect the adapter's VCC. Several other J14 pins are reset, recovery and
power-sequencing controls (pin 8 `SYS_RESET*`, pin 10 `FORCE_RECOVERY*`), so a
wire on the wrong pin can reset the board or put it in recovery mode — count
carefully.

## The adapter is not in question

The owner has used this FT232R adapter on another project, so it is known good. That
closes the one alternative explanation for the J12 silence: with a working adapter,
a correct pin, a covered capture window and all three UARTs silent at once, the
unclaimed pinmux is the only cause left standing. It also means that if J14 is
silent too, the problem is the J14 wiring or pin count, not the adapter, and no
self-loopback test is needed.
