#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""pad-like.py - pad the T0 contract probe to a kimg's size (T0_PAD_LIKE).

Phase 3b, results/orin-native-port/20260909T1100Z/s1-design.md §15.13.4 (build
scripts): the J7a T0 build must match the board build in every size field, so
the probe is padded with zeros to the kimg's file length and carries the kimg's
image_size in its own arm64 header.

From the kimg it reads only the 64-byte arm64 header, which our shim wrote, and
the file's length. No QNX byte enters the output.

usage: pad-like.py <probe.bin> <kimg> <out.bin>
"""

import os
import struct
import sys

HDR = 0x40


def main():
    if len(sys.argv) != 4:
        sys.exit("usage: pad-like.py <probe.bin> <kimg> <out.bin>")
    probe_path, kimg_path, out_path = sys.argv[1:]

    with open(probe_path, "rb") as fh:
        probe = bytearray(fh.read())
    kimg_len = os.path.getsize(kimg_path)
    with open(kimg_path, "rb") as fh:
        head = fh.read(HDR)

    if len(head) != HDR or head[0x38:0x3C] != b"ARM\x64":
        sys.exit("pad-like: %s has no arm64 header" % kimg_path)
    k_text, k_image = struct.unpack_from("<QQ", head, 8)
    if k_text != 0x80000 or k_image % 0x1000 or k_image < kimg_len:
        sys.exit("pad-like: the kimg header is not a usable arm64 header")

    if len(probe) < HDR or probe[0x38:0x3C] != b"ARM\x64":
        sys.exit("pad-like: %s has no arm64 header" % probe_path)
    if len(probe) > kimg_len:
        sys.exit("pad-like: the probe is longer than the kimg")

    probe.extend(b"\0" * (kimg_len - len(probe)))
    struct.pack_into("<Q", probe, 16, k_image)

    with open(out_path, "wb") as fh:
        fh.write(probe)
    print("pad-like: probe padded to the kimg's length; image_size copied from its header")


if __name__ == "__main__":
    main()
