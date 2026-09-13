#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""blob-consts.py - derive the three build constants from the payload.

Phase 3b, results/orin-native-port/20260909T1100Z/m5-design.md §3.3 (the build
constants) and §13 decision D (the CRC covers the file's own bytes, not the
image_size the header advertises).

Prints, on one line: <length> <crc32> <image_size>

build-m5-loader.sh embeds these in m5load-blob.S, which is the only file that
differs between the T0 build and the board build (§3.4 gate item 8). Nothing
here is typed by hand, so the loader can never be built against a constant that
does not describe the bytes it carries.
"""

import struct
import sys
import zlib


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: blob-consts.py <blob>")
    with open(sys.argv[1], "rb") as fh:
        b = fh.read()

    if len(b) < 0x40:
        sys.exit("blob is too short to carry an arm64 header")
    if b[0x38:0x3C] != b"ARM\x64":
        sys.exit("blob has no ARM\\x64 magic at 0x38")

    text_offset, image_size = struct.unpack_from("<QQ", b, 8)
    if text_offset != 0x80000:
        sys.exit("blob text_offset is %#x, expected 0x80000" % text_offset)
    if image_size < len(b):
        sys.exit("blob image_size %#x is under its own length %#x" % (image_size, len(b)))
    if image_size % 0x1000:
        sys.exit("blob image_size %#x is not a page multiple" % image_size)

    print("%d %d %d" % (len(b), zlib.crc32(b) & 0xFFFFFFFF, image_size))


if __name__ == "__main__":
    main()
