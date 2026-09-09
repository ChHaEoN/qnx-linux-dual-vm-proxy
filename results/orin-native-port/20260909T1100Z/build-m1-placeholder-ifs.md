# Placeholder M1 IFS at `[image=0x80081000]` — mkifs layout check (compile-only)

"First action today" #3 of the synthesised plan, executed 2026-09-09 on the Windows build host by the
orchestrating session. Evidence class: **VERIFIED** (mkifs/dumpifs output recorded below). No board involved;
the image lives in a private scratch directory and is not committed (NCEULA).

## Two syntax corrections to the plan's buildfile (both found by mkifs refusing the file)

1. `boot = {` is not mkifs 8.0 syntax — the bootstrap section is **`[virtual=aarch64le,raw] .bootstrap = {`**
   (exactly what mkqnximage writes in `qhv/host/output/build/system.build`). With `boot = {` mkifs reports
   `No startup program found while creating bootable image`.
2. `[+keeplinked]` cannot be set on the global attribute line (`[virtual=aarch64le,raw] [+keeplinked]` ->
   `Missing filename`); it is a per-file attribute, e.g. `[+keeplinked] procnto-smp-instr -v`.

## Buildfile used (own text; shipped `startup-armv8_fm` as a stand-in for the future `startup-t234-orin-nano`)

```
[image=0x80081000]
[-compress]
[virtual=aarch64le,raw] .bootstrap = {
    startup-armv8_fm -vvv -P1
    PATH=/proc/boot LD_LIBRARY_PATH=/proc/boot
    procnto-smp-instr -v
}
[+script] .script = {
    display_msg "T234 M1 placeholder: procnto up"
    procmgr_symlink ../../proc/boot/ldqnx-64.so.2 /usr/lib/ldqnx-64.so.2
    devc-pty
    pidin info
}
[type=link] /usr/lib/ldqnx-64.so.2=/proc/boot/ldqnx-64.so.2
libc.so.6
libgcc_s.so.1
/bin/ksh=ksh
/bin/pidin=pidin
/sbin/devc-pty=devc-pty
```

## Result (`mkifs -v`, exit 0; `dumpifs -v`)

| field | value |
|---|---|
| image size | 2,293,828 B |
| `*.boot` (raw.boot stub) | offset 0x80081000, 0xfa0 bytes |
| startup header | 0x80081fa0, flags1=0x21 (virtual, little-endian), compress=0 |
| `image_paddr` / `ram_paddr` | 0x80081fa0 |
| `startup_size` / `imagefs_size` | 0x2a148 / 0x204f5c |
| **`startup_vaddr`** | **0x80082800** — a 32-bit value, so the stub's word-sized load of it and the branch that follows still work at this base (opcodes withheld — the repo does not publish machine code of QNX-shipped binaries, QDL v7 4.6(c)) |
| first 64 bytes | byte-identical to the repo's 0x40080000-based images (opcodes withheld, QDL v7 4.6(c)): three shipped-stub instructions then NOPs. The stub is position-agnostic, and the arm64 Image header must be **prefixed** in a separate page, never overlaid — bytes 0x08-0x0B, where `text_offset` goes, are the stub's third instruction |
| last file end | 0x802b1000 + trailer — the whole image sits inside the 992 MiB window 0x80000000-0xBDFFFFFF with room for the M3 image |

So the arithmetic in plan §3.2 / §6.2 holds for the base 0x80081000: the raw IFS can follow a 4 KiB shim page
placed at 0x80080000 by kexec (`text_offset = 0x80000` on top of the 2 MiB-aligned hole at 0x80000000).

## What it does not show

Whether kexec actually places the payload there (K2/placement, still to be observed on the board), whether the
shim's jump into the stub works, or anything about running the image. It is a layout check only.
