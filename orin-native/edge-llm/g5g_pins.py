#!/usr/bin/env python3
"""g5g_pins.py APPROVED -- the apt preferences file of a g5g.metal session, from its approved-names file.

For every `pkg NAME=VERSION SOURCE SIZE SHA256` line of APPROVED whose SOURCE is `nvidia` (NVIDIA's CUDA repository),
in the file's order, one stanza on standard output:

    Package: NAME
    Pin: version VERSION
    Pin-Priority: 1001

with one empty line between stanzas, as apt_preferences(5) separates records, and nothing else. A line whose SOURCE is
`ubuntu` gives no stanza. Every other line of APPROVED (comments, key, keyfile, pins, llama, index, index-cap, total)
is not this tool's and is passed over. A `pkg` line this tool cannot read is refused with its line number, and nothing
is printed.

WHY. NVIDIA's repository carries later releases under the same unversioned names, and apt takes the newest for a name
it is not asked for by version. The session's prep resolves the package closure under these pins, and the gpu-install
phase's plan (scripts/aws/remote-ladder.sh) writes the same bytes from the same approved file before it resolves, so a
name apt is not asked for resolves on the instance as it did in the prep. The approved file carries this output's
sha256, and the plan refuses on another.

THE FILE'S NAME IS FIXED: `g5g_pins.py --name` prints it. apt reads a file of its preferences directory only when the
name has no extension, or the extension `pref`, and holds only letters, digits, "-", "_" and "."; it passes over any
other with a notice (apt_preferences(5)).

It reads one file and writes standard output; it fetches nothing and installs nothing. That a real apt applies the
file it writes is not shown here: the plan reads every pinned name's candidate back from apt before it resolves.
"""
import re
import sys

NAME = "g5g-nvidia-pins"
PKG = re.compile(r"^pkg ([a-z0-9][a-z0-9+.-]+)=([A-Za-z0-9.+:~-]+) (ubuntu|nvidia) ([0-9]+) ([0-9a-f]{64})$")


def stanzas(text):
    out = []
    for i, line in enumerate(text.split("\n"), 1):
        if not line.startswith("pkg ") and line != "pkg":
            continue
        m = PKG.match(line)
        if not m:
            sys.exit("g5g_pins.py: line %d is not `pkg NAME=VERSION ubuntu|nvidia SIZE SHA256`: nothing written" % i)
        if m.group(3) == "nvidia":
            out.append("Package: %s\nPin: version %s\nPin-Priority: 1001\n" % (m.group(1), m.group(2)))
    return "\n".join(out)


def main(argv):
    if argv == ["--name"]:
        print(NAME)
        return 0
    if len(argv) != 1:
        sys.exit("usage: g5g_pins.py APPROVED | g5g_pins.py --name")
    with open(argv[0], "rb") as f:
        text = f.read().decode("utf-8")
    sys.stdout.write(stanzas(text))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
