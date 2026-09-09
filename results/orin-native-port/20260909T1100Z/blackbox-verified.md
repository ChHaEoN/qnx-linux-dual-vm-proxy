# The RAM black box is fully settled — the port can start with no hardware purchase

Read-only board work, 2026-09-09 (orchestrating session; `sudo -n` reads only, no write, no reboot).
Evidence class: **VERIFIED** — every value below was read off the running board.

Plan [orin-native-port-plan.md](../../docs/orin-native-port-plan.md) ranked this unknown **7 of 13**
("pstore/ramoops zone layout on this kernel and DRAM retention across warm reset"), with the consequence
"black box unusable; adapter mandatory". Both halves are now closed, positively.

## Geometry, from the device tree (`/proc/device-tree/reserved-memory/ramoops_carveout`)

| property | value |
|---|---|
| `reg` | `0x2_725F0000`, length `0x200000` (2 MiB) |
| `record-size` | `0x10000` (64 KiB) |
| `console-size` | `0x80000` (512 KiB) |
| `ecc` | absent -> `ramoops: using 0x200000@0x2725f0000, ecc: 0` (dmesg) — **no ECC footer**, so the zone is plain |
| `ftrace-size` / `pmsg-size` | absent -> 0, consistent with `/dev/pmsg0` being absent |

Kernel layout order (dump zones, then console) puts the **console zone at `0x2_72770000`**
(carveout + `0x180000`, i.e. 2 MiB - 512 KiB), with `0x180000` of dump zones ahead of it in 24 records of
64 KiB. That arithmetic was not assumed — it was confirmed by reading the memory (below).

## The carveout is readable through `/dev/mem`, and the on-disk format is directly observed

`CONFIG_STRICT_DEVMEM=y`, but the carveout is `no-map` (never in the kernel's System RAM map), and a root
`mmap` of `/dev/mem` returns its contents:

| address | first 16 bytes (grouped by 4) | reading |
|---|---|---|
| `0x2_725F0000` (carveout start, dump zone 0) | `44424743 78590000 78590000 3d3d3d3d` | sig `DBGC`, `start = 0x5978`, `size = 0x5978`, data starts `====` |
| `0x2_72770000` (**console zone**) | `44424743 2a1a0000 2a1a0000 5b202020` | sig `DBGC`, `start = size = 0x1a2a`, data starts `[   ` — the kernel boot log |
| carveout + `0x100000` (an unused dump zone) | `44424743 00000000 00000000 ffffffff` | valid header, empty |
| carveout + `0x1F0000` (console tail) | `ffffffff ...` | unwritten |

So the `persistent_ram` header is exactly three little-endian 32-bit words followed by the data:

```
struct { uint32_t sig;    // 0x43474244, the four bytes 'D','B','G','C' in memory order
         uint32_t start;  // write cursor
         uint32_t size;   // bytes valid
         uint8_t  data[]; }
```

A payload that writes text at `0x2_72770000 + 12` and sets `start` and `size` to the byte count, leaving the
signature word alone, produces a zone the kernel accepts on the next boot and pstore exposes as
`/sys/fs/pstore/console-ramoops-0`. Retention was already demonstrated independently: that file currently
holds this boot's log, and `dmesg-ramoops-0` holds the 2026-09-08 23:30 drop-off.

## What changes in the plan

- **The USB-TTL adapter comes off the critical path for M0 and M1.** It stays worth buying — live output,
  interactive debugging, the UEFI menus M5 needs, and it removes the one-question-per-reboot cadence — but
  the port can now start, and produce readable evidence, with nothing bought.
- The shim's black-box writer becomes a **primary** output path, not a fallback: 3 words of header plus the
  text, at a physical address that is now known rather than guessed.
- The `dd if=/dev/mem` fallback in the plan is unnecessary (and did not work as written); the `mmap` path is
  the readback.
- Unknown 7 drops off the ranked list. Unknown 2 (does the SPE keep draining the TCU after Linux exits)
  loses most of its severity: if the TCU is silent, M0 and M1 still produce evidence.

## What it does not show

That a payload can *write* the carveout after Linux is gone (nothing was written — these were reads), that
the kernel accepts a zone written by non-Linux code, or anything about DRAM contents surviving the specific
reset path M0 will use. The M0 shim's first run tests all three at once, which is what it is for.
