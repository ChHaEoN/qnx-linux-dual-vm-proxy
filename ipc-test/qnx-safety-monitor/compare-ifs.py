#!/usr/bin/env python3
"""compare-ifs.py OLD.bin NEW.bin [EXPECTED...] -- accept a derived guest image by
its contents, never by mkifs's exit code.

Every file in these build files is [+optional], so an unresolved host path is
skipped SILENTLY and mkifs still exits 0: an image missing a file, or carrying
the wrong one, builds "successfully". The acceptance rule every A6 image has
used is therefore a content comparison against the image it derives from --
done until now by a scratch script that was never committed. This is that
comparison, committed.

Both images are extracted with dumpifs -x. Files are compared byte for byte,
except that in ELF files each program header's p_paddr is zeroed first: mkifs
writes the physical load address, which moves whenever an earlier file in the
image changes size, so an identical binary placed elsewhere would otherwise
count as changed. Nothing else is ignored.

Exit 0 only if the files that differ are exactly EXPECTED (by path inside the
image), none was removed, and the files added are exactly those named after
--added (2026-09-26, for an image that stages one more program, ifs-clock.bin):
  compare-ifs.py OLD.bin NEW.bin [EXPECTED...] [--added PATH]... Prints the verdict per file. Contains
no QNX code; needs the SDP's dumpifs on PATH to run.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile


def extract(image, into):
    os.makedirs(into)
    r = subprocess.run(["dumpifs", "-x", os.path.abspath(image)], cwd=into,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("dumpifs -x %s failed: %s" % (image, r.stderr.strip()[:300]))
    files = {}
    for d, _dirs, names in os.walk(into):
        for n in names:
            p = os.path.join(d, n)
            files[os.path.relpath(p, into).replace(os.sep, "/")] = p
    return files


def normalised(path):
    b = bytearray(open(path, "rb").read())
    if b[:4] != b"\x7fELF" or len(b) < 64:
        return bytes(b)
    cls, data = b[4], b[5]
    end = "<" if data == 1 else ">"
    if cls == 2:                                   # ELF64
        phoff, = struct.unpack_from(end + "Q", b, 32)
        phentsize, phnum = struct.unpack_from(end + "HH", b, 54)
        paddr_at, width = 24, 8
    else:                                          # ELF32
        phoff, = struct.unpack_from(end + "I", b, 28)
        phentsize, phnum = struct.unpack_from(end + "HH", b, 42)
        paddr_at, width = 12, 4
    for i in range(phnum):
        o = phoff + i * phentsize + paddr_at
        if o + width <= len(b):
            b[o:o + width] = b"\0" * width
    return bytes(b)


def main(argv):
    if len(argv) < 3:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 2
    old_img, new_img, rest = argv[1], argv[2], argv[3:]
    expected, want_added = set(), set()
    while rest:
        a = rest.pop(0)
        if a == "--added":
            if not rest:
                print("--added needs a path", file=sys.stderr)
                return 2
            want_added.add(rest.pop(0))
        else:
            expected.add(a)
    tmp = tempfile.mkdtemp(prefix="compare-ifs-")
    try:
        old = extract(old_img, os.path.join(tmp, "old"))
        new = extract(new_img, os.path.join(tmp, "new"))
        added = sorted(set(new) - set(old))
        removed = sorted(set(old) - set(new))
        same, paddr_only, differ = [], [], []
        for f in sorted(set(old) & set(new)):
            a, b = open(old[f], "rb").read(), open(new[f], "rb").read()
            if a == b:
                same.append(f)
            elif normalised(old[f]) == normalised(new[f]):
                paddr_only.append(f)
            else:
                differ.append(f)
        print("identical: %d; identical but for ELF p_paddr: %d" % (len(same), len(paddr_only)))
        for f in paddr_only:
            print("  p_paddr only  %s" % f)
        for f in differ:
            print("  DIFFERS       %s%s" % (f, "" if f in expected else "   <-- NOT EXPECTED"))
        for f in added:
            print("  ADDED         %s%s" % (f, "" if f in want_added else "   <-- NOT EXPECTED"))
        for f in sorted(want_added - set(added)):
            print("  expected to be added but is not: %s" % f)
        for f in removed:
            print("  REMOVED       %s   <-- NOT EXPECTED" % f)
        missing = sorted(expected - set(differ))
        for f in missing:
            print("  expected to differ but does not: %s" % f)
        ok = set(added) == want_added and not removed and set(differ) == expected
        print("ACCEPT" if ok else "REFUSE")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
