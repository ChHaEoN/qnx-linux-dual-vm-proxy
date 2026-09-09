# M0 gate passed: both kexec paths accept the shim, and it lands where the arithmetic said

2026-09-09, on the board. **No reboot.** The image was staged into kernel memory, the result read back, and
the image unloaded again; the board stayed up throughout (`up 22:53` before and after, `kexec_loaded` back to
`0`). This is the step the plan puts before any reboot is risked, and it is the first time any of this port's
code has touched the hardware at all.

Image: `t234-shim.kimg`, 8,192 bytes, probe mode, sha256 `03f45e77…7edae`, byte-identical on both ends.

## What was run

```bash
sudo kexec -d -s -l t234-shim.kimg   # kexec_file_load, the primary path
cat /sys/kernel/kexec_loaded ; sudo kexec -u
sudo kexec -d -c -l t234-shim.kimg   # kexec_load with purgatory, the fallback
cat /sys/kernel/kexec_loaded ; sudo kexec -u
```

## Result

Both syscalls **accepted** the image: `rc=0` and `kexec_loaded=1` in each case, `0` again after the unload.
No signature check, no PE check, nothing beyond the header. The `kexec_file_load` debug trace shows it trying
formats in order — gzip, then `elf_arm64_probe: Not an ELF executable` — and then accepting it as an arm64
`Image`, which is exactly the path the design depends on.

**Claim K2 is settled on its acceptance half.** It was UNSETTLED: no reviewer could confirm from source alone
that this kernel would take a non-Linux payload carrying only the header.

## The segment map, which is the more valuable half

The `kexec_load` path prints where it will put things, and it agrees with the arithmetic the plan derived on
paper:

| segment | address | size | what |
|---|---|---|---|
| 0 | **`0x80080000`** | `0x2000` | the shim page — **exactly** the address the landing check expects |
| 1 | `0x80082000` | `0x3e000` | the device tree |
| 2 | `0x800c0000` | `0x4000` | purgatory |

Segment 0 landing at `0x80080000` confirms the placement the plan had marked HYPOTHESIS: the first 2 MiB-aligned
System RAM hole is `0x80000000`, plus `text_offset` `0x80000`. The shim's own landing check will therefore
pass rather than print `BAD-LANDING` and reset — and if it ever does print that, we now know it means the
placement changed, not that the arithmetic was wrong to begin with.

## One correction to the plan

The plan says the DTB is placed "top-down above the image". That is what `kexec_file_load` does in the kernel.
`kexec-tools` on the `kexec_load` path places it **bottom-up, immediately after the image** — here at
`0x80082000`, which is where the IFS will live once there is one. With the real image the payload grows and
the DTB moves past it, so there is no conflict, but the placement should be re-read from `kexec -d` when the
first shim+IFS image is built rather than assumed. This is the second time on this port that a placement
assumption held only because the numbers happened to line up.

## What this does not show

That the shim runs. Nothing executed: `kexec -l` stages an image and `kexec -u` discards it. The exception
level at entry, whether the SPE still drains the TCU mailbox, whether the ramoops write survives, and whether
the un-petted watchdog returns the board are all still open, and all of them need the reboot this test
deliberately avoided.
