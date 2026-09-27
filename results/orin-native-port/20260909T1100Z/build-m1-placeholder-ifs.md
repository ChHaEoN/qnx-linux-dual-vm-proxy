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
| **`startup_vaddr`** | **0x80082800** — fits the startup header's 32-bit field (`sys/startup.h`) at this base |
| last file end | 0x802b1000 + trailer — the whole image sits inside the 992 MiB window 0x80000000-0xBDFFFFFF with room for the M3 image |

So the arithmetic in plan §3.2 / §6.2 holds for the base 0x80081000: the raw IFS can follow a 4 KiB shim page
placed at 0x80080000 by kexec (`text_offset = 0x80000` on top of the 2 MiB-aligned hole at 0x80000000). The
arm64 Image header goes in that separate page, never over the IFS's own first bytes, which belong to the
bootfile's stub.

A note on the image's first bytes, made on 2026-09-09 from a byte listing of the QNX-shipped bootfile stub,
was withdrawn on 2026-09-27 under NC QDL v7 clause 4.6(c).

## What it does not show

Whether kexec actually places the payload there (K2/placement, still to be observed on the board), whether the
shim's jump into the stub works, or anything about running the image. It is a layout check only.

## Re-verified at `[image=0x80082000]` (2026-09-09, after the shim page was sized)

The shim turned out to need 8 KiB, not 4 KiB: the vector table must be 2 KiB-aligned and is itself 2 KiB, and
the state-bank printer plus its strings do not fit in what a 4 KiB page leaves. So the IFS base moved one page
further out and the layout check was re-run:

| field | value at `[image=0x80082000]` |
|---|---|
| `*.boot` | offset `0x80082000`, `0xfa0` bytes |
| startup header | `0x80082fa0`, flags1 `0x21`, `compress=0` |
| `startup_vaddr` | `0x80083800` — still fits the startup header's 32-bit field |
| image size | 2,289,732 B, ending well inside the 992 MiB window |

`mkifs` exit 0. The shim page is exactly 8,192 bytes (`build-shim.sh` fails the build otherwise), so
`kexec` places the header at `0x80080000` and the IFS begins at `0x80080000 + 0x2000 = 0x80082000`,
which is what the buildfile now says. The arithmetic is unchanged; only the constant moved.
