#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""mkcpio.py - the S1-F initrd builder: a newc cpio reader and writer.

Phase 3b, results/orin-native-port/20260909T1100Z/s1-design.md section 3.5
(option I-a) and section 4.2; T0 step 2 (section 6.1) runs --selftest, then
build.

    mkcpio.py --selftest
    mkcpio.py build MANIFEST [-o OUT] [--unpinned]
    mkcpio.py list ARCHIVE

build   Reads a manifest (orin-native/s1/initrd.manifest), checks every pin
        and writes a gzip newc archive. Nothing is written unless every check
        passes. An output pin of '-' is refused unless --unpinned is given;
        that flag exists only to print the first pin, and says pin=none.
list    Prints one line per member of a newc archive, raw or gzip,
        concatenated archives included, for the T0 checks:
            KIND PERM UID:GID NLINK SIZE SHA256 PATH [-> TARGET | MAJOR:MINOR]
        KIND is f d l c b p s; SHA256 is '-' except for regular files. A
        header line gives the input's and the cpio stream's sha256.
--selftest
        Round trip, device node, symlink, the refusals (hash mismatches
        included) and deterministic bytes, on in-memory fixtures and a
        temporary directory. Exits 0 only if every case passes.

Manifest grammar. One directive per line; '#' starts a comment. PATH is an
archive path with no leading '/'. FILE and source paths are relative to the
manifest's directory.

    source NAME FILE SHA256
        A newc archive (raw or gzip) that members are copied from. Its sha256
        is checked before it is parsed.
    output FILE GZ_SHA256 CPIO_SHA256
        Where build writes, with the pins of the gzip file and of the cpio
        stream inside it. The cpio bytes are a function of the inputs alone;
        the gzip bytes also depend on the zlib build, so a mismatch in the
        gzip pin alone is reported as exactly that.
    dir PATH MODE
    file PATH MODE SHA256 NAME MEMBER
        A byte copy of MEMBER of source NAME. MEMBER must occur exactly once,
        as a regular file with one link, and MODE must equal its permission
        bits.
    file PATH MODE SHA256 local FILE
        A file of ours.
    link PATH TARGET [NAME]
        A symlink. With NAME, source NAME must hold the same symlink at the
        same path: that is how a usrmerge link is reproduced as in the source.
    node PATH MODE c|b MAJOR MINOR
    busybox PATH [+math] APPLET...
        Find busybox's applet name table in PATH's bytes and require every
        APPLET in it. +math also requires the error texts of busybox's
        shell/math.c, which is built only with FEATURE_SH_MATH, the option
        that gives ash $(( )). Every symlink that resolves to PATH must be
        named by an APPLET. Reading strings of busybox is allowed (GPLv2);
        this tool is never pointed at a QNX binary (NC QDL v7 4.6(c)).

MODE is four octal digits. Every parent directory of an entry must be
declared by a dir line, so no directory mode is implicit.

Determinism. Entries are sorted by path components, so a directory always
precedes its contents; inode numbers run 1..N in that order; mtime, uid, gid
and dev are 0, and rdev is 0 apart from a node's; nlink is 1, or 2 for a
directory; the trailer is padded to a 512-byte boundary, as cpio(1) pads;
gzip is level 9 with mtime 0 and no file name.

Standard library only, so the device node needs no root on Windows. Every
check that cannot be performed fails closed.
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import posixpath
import re
import stat
import sys
import tempfile
import zlib

MAGIC_NEWC = b"070701"
MAGIC_CRC = b"070702"
HEADER_LEN = 110
TRAILER = "TRAILER!!!"
BLOCK = 512

# Error texts of busybox shell/math.c. That file is built only with
# FEATURE_SH_MATH, so all three present means ash has $(( )). "divide by zero"
# is left out: busybox's bc carries the same text.
MATH_TEXTS = (b"arithmetic syntax error", b"exponent less than 0",
              b"expression recursion loop detected")

# sha256 of write_newc(_fixture()): pins the on-disk format itself, which does
# not depend on zlib. A change here is a format change, never a refresh.
FIXTURE_CPIO_SHA256 = (
    "3fc42d18a47b3b6f7aabff4543979cdb565c25f0bbfa4780636329cc962a28e7")

KIND = {stat.S_IFREG: "f", stat.S_IFDIR: "d", stat.S_IFLNK: "l",
        stat.S_IFCHR: "c", stat.S_IFBLK: "b", stat.S_IFIFO: "p",
        stat.S_IFSOCK: "s"}

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MODE_RE = re.compile(r"[0-7]{4}\Z")
HEX_RE = re.compile(rb"[0-9A-Fa-f]{104}\Z")
PATH_CHARS_RE = re.compile(r"[\x21-\x7e]+\Z")
NONZERO_RE = re.compile(rb"[^\0]")
NAME_RUN_RE = re.compile(rb"(?:[a-z0-9_.\[\]-]{1,32}\0){20,}")
VERSION_RE = re.compile(rb"BusyBox v[0-9][\x20-\x7e]{0,80}")

ARITY = {"source": (3, 3), "output": (3, 3), "dir": (2, 2), "file": (5, 5),
         "link": (2, 3), "node": (5, 5), "busybox": (2, None)}


class CpioError(Exception):
    """A malformed archive."""


class BuildError(Exception):
    """A refused build: a pin, a manifest line or a source member."""


class Member:
    """One archive entry. mode is the full st_mode; data is a file's bytes or
    a symlink's target; rdev is (major, minor)."""

    __slots__ = ("path", "mode", "data", "rdev", "uid", "gid", "nlink",
                 "mtime", "ino")

    def __init__(self, path, mode, data=b"", rdev=(0, 0), uid=0, gid=0,
                 nlink=1, mtime=0, ino=0):
        self.path = path
        self.mode = mode
        self.data = data
        self.rdev = rdev
        self.uid = uid
        self.gid = gid
        self.nlink = nlink
        self.mtime = mtime
        self.ino = ino

    @property
    def kind(self):
        return KIND.get(stat.S_IFMT(self.mode), "?")

    @property
    def perm(self):
        return stat.S_IMODE(self.mode)

    @property
    def target(self):
        return self.data.decode("utf-8", "surrogateescape")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------ reader

def unpack(blob):
    """Return (format, cpio bytes): gzip is decompressed, anything else is
    passed through as raw. Concatenated gzip members are joined."""
    if blob[:2] == b"\x1f\x8b":
        try:
            return "gzip", gzip.decompress(blob)
        except (OSError, EOFError, zlib.error) as e:
            raise CpioError("gzip: %s" % e)
    return "raw", blob


def read_newc(raw):
    """Parse one or more concatenated newc archives, with NUL padding between
    them. Returns (members in archive order, number of trailers)."""
    members = []
    archives = 0
    open_archive = False
    n = len(raw)
    off = 0
    while True:
        m = NONZERO_RE.search(raw, off)
        if m is None:
            break
        off = m.start()
        if off & 3:
            raise CpioError("offset %d: header not on a 4-byte boundary" % off)
        magic = raw[off:off + 6]
        if magic not in (MAGIC_NEWC, MAGIC_CRC):
            raise CpioError("offset %d: not a newc header" % off)
        if off + HEADER_LEN > n:
            raise CpioError("offset %d: truncated header" % off)
        hexes = raw[off + 6:off + HEADER_LEN]
        if not HEX_RE.match(hexes):
            raise CpioError("offset %d: header is not hexadecimal" % off)
        (ino, mode, uid, gid, nlink, mtime, size, _dmaj, _dmin, rmaj, rmin,
         namesize, check) = [int(hexes[8 * i:8 * i + 8], 16) for i in range(13)]
        name_end = off + HEADER_LEN + namesize
        if namesize < 1 or name_end > n or raw[name_end - 1] != 0:
            raise CpioError("offset %d: bad name field" % off)
        name = raw[off + HEADER_LEN:name_end - 1].decode("utf-8",
                                                          "surrogateescape")
        start = (name_end + 3) & ~3
        end = start + size
        if end > n:
            raise CpioError("%s: truncated data" % name)
        data = bytes(raw[start:end])
        if magic == MAGIC_CRC and (sum(data) & 0xFFFFFFFF) != check:
            raise CpioError("%s: checksum mismatch" % name)
        off = (end + 3) & ~3
        if name == TRAILER:
            archives += 1
            open_archive = False
            continue
        open_archive = True
        members.append(Member(name, mode, data, (rmaj, rmin), uid, gid, nlink,
                              mtime, ino))
    if open_archive:
        raise CpioError("no trailer after the last member")
    return members, archives


def norm(path):
    """A member name as a lookup key: no leading './' or '/'."""
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


# ------------------------------------------------------------------ writer

def _put(out, ino, mode, nlink, data, rdev, name):
    nb = name.encode("utf-8", "surrogateescape") + b"\0"
    fields = (ino, mode, 0, 0, nlink, 0, len(data), 0, 0, rdev[0], rdev[1],
              len(nb), 0)
    out.extend(MAGIC_NEWC)
    for v in fields:
        out.extend(b"%08X" % v)
    out.extend(nb)
    out.extend(b"\0" * (-len(out) % 4))
    out.extend(data)
    out.extend(b"\0" * (-len(out) % 4))


def write_newc(entries):
    """The archive bytes for entries, under the module docstring's rules.
    Only path, mode, data and rdev are taken from each entry."""
    ordered = sorted(entries, key=lambda e: e.path.split("/"))
    seen = set()
    out = bytearray()
    for ino, e in enumerate(ordered, 1):
        if e.path in seen:
            raise BuildError("duplicate path %s" % e.path)
        seen.add(e.path)
        _put(out, ino, e.mode, 2 if e.kind == "d" else 1, e.data, e.rdev,
             e.path)
    _put(out, 0, 0, 1, b"", (0, 0), TRAILER)
    out.extend(b"\0" * (-len(out) % BLOCK))
    return bytes(out)


def gzip_bytes(raw):
    bio = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", compresslevel=9, fileobj=bio,
                       mtime=0) as g:
        g.write(raw)
    return bio.getvalue()


# ------------------------------------------------------------------ busybox

def busybox_applets(blob):
    """The longest strictly increasing run of short NUL-terminated names in
    blob. busybox keeps its applet names as one sorted NUL-separated string;
    this finds it without executing anything. Empty if under 20 names."""
    best = []
    for m in NAME_RUN_RE.finditer(blob):
        names = m.group(0).split(b"\0")[:-1]
        run = names[:1]
        for name in names[1:]:
            if name > run[-1]:
                run.append(name)
                continue
            if len(run) > len(best):
                best = run
            run = [name]
        if len(run) > len(best):
            best = run
    if len(best) < 20:
        return []
    return [x.decode("ascii") for x in best]


def busybox_version(blob):
    m = VERSION_RE.search(blob)
    return m.group(0).decode("ascii") if m else "unknown"


def resolve(entries, path, hops=40):
    """Follow symlinks among entries, component by component. None on a loop."""
    todo = path.split("/")
    done = []
    while todo:
        done.append(todo.pop(0))
        e = entries.get("/".join(done))
        if e is None or e.kind != "l":
            continue
        hops -= 1
        if hops < 0:
            return None
        t = e.target
        joined = t if t.startswith("/") else "/".join(done[:-1] + [t])
        stack = []
        for p in joined.split("/"):
            if p in ("", "."):
                continue
            if p == "..":
                if stack:
                    stack.pop()
                continue
            stack.append(p)
        todo = stack + todo
        done = []
    return "/".join(done)


# ------------------------------------------------------------------ build

def _read(base, rel):
    if os.path.isabs(rel) or rel[1:2] == ":":
        raise BuildError("%s: manifest file paths must be relative" % rel)
    with open(os.path.join(base, *rel.split("/")), "rb") as fh:
        return fh.read()


def build(manifest, out_override=None, unpinned=False, log=print):
    """Build the archive a manifest describes. Raises BuildError on any
    refusal, before anything is written. Returns a dict of the results."""
    base = os.path.dirname(os.path.abspath(manifest))
    label = os.path.basename(manifest)
    with open(manifest, "rb") as fh:
        text = fh.read().decode("utf-8")

    def fail(no, msg):
        raise BuildError("%s:%d: %s" % (label, no, msg))

    def need_pin(no, pin):
        if not SHA256_RE.match(pin):
            fail(no, "not a lowercase sha256: %s" % pin)

    def need_mode(no, mode):
        if not MODE_RE.match(mode):
            fail(no, "mode must be four octal digits: %s" % mode)
        return int(mode, 8)

    def need_path(no, path):
        parts = path.split("/")
        if (not PATH_CHARS_RE.match(path) or path.startswith("/")
                or path == TRAILER or any(p in ("", ".", "..") for p in parts)):
            fail(no, "bad archive path: %s" % path)
        return path

    sources = {}
    entries = {}
    lines = {}
    busy = []
    output = None

    def add(no, member):
        if member.path in entries:
            fail(no, "duplicate path %s (first on line %d)"
                 % (member.path, lines[member.path]))
        entries[member.path] = member
        lines[member.path] = no

    for no, raw_line in enumerate(text.splitlines(), 1):
        toks = raw_line.split("#", 1)[0].split()
        if not toks:
            continue
        kw, args = toks[0], toks[1:]
        if kw not in ARITY:
            fail(no, "unknown directive %s" % kw)
        lo, hi = ARITY[kw]
        if len(args) < lo or (hi is not None and len(args) > hi):
            fail(no, "wrong number of fields for %s" % kw)

        if kw == "source":
            name, rel, pin = args
            need_pin(no, pin)
            if name in sources or name == "local":
                fail(no, "source name %s is taken" % name)
            blob = _read(base, rel)
            got = sha256(blob)
            if got != pin:
                fail(no, "source %s sha256 mismatch got=%s want=%s"
                     % (name, got, pin))
            try:
                fmt, raw = unpack(blob)
                members, archives = read_newc(raw)
            except CpioError as e:
                fail(no, "source %s: %s" % (name, e))
            index = {}
            for m in members:
                index.setdefault(norm(m.path), []).append(m)
            sources[name] = index
            log("MKCPIO source %s file=%s sha256=%s format=%s members=%d "
                "archives=%d ok" % (name, rel, got, fmt, len(members),
                                    archives))

        elif kw == "output":
            if output is not None:
                fail(no, "a second output line")
            for pin in args[1:]:
                if pin != "-":
                    need_pin(no, pin)
            output = (no, args[0], args[1], args[2])

        elif kw == "dir":
            add(no, Member(need_path(no, args[0]),
                           stat.S_IFDIR | need_mode(no, args[1])))

        elif kw == "file":
            path, mode, pin, src, what = args
            need_path(no, path)
            perm = need_mode(no, mode)
            need_pin(no, pin)
            if src == "local":
                data = _read(base, what)
            else:
                if src not in sources:
                    fail(no, "unknown source %s (declare it first)" % src)
                hits = sources[src].get(norm(what), [])
                if len(hits) != 1:
                    fail(no, "member %s occurs %d times in source %s"
                         % (what, len(hits), src))
                m = hits[0]
                if m.kind != "f":
                    fail(no, "member %s is not a regular file" % what)
                if m.nlink != 1:
                    fail(no, "member %s is hard-linked (nlink=%d)"
                         % (what, m.nlink))
                if m.perm != perm:
                    fail(no, "mode %04o differs from the member's %04o"
                         % (perm, m.perm))
                data = m.data
            got = sha256(data)
            if got != pin:
                fail(no, "%s sha256 mismatch got=%s want=%s" % (path, got, pin))
            add(no, Member(path, stat.S_IFREG | perm, data))

        elif kw == "link":
            path, target = need_path(no, args[0]), args[1]
            if len(args) == 3:
                src = args[2]
                if src not in sources:
                    fail(no, "unknown source %s (declare it first)" % src)
                hits = sources[src].get(path, [])
                found = ",".join("%s:%s" % (h.kind, h.target if h.kind == "l"
                                            else "-") for h in hits) or "none"
                if (len(hits) != 1 or hits[0].kind != "l"
                        or hits[0].target != target):
                    fail(no, "link %s -> %s is not in source %s as that "
                         "symlink (found %s)" % (path, target, src, found))
            add(no, Member(path, stat.S_IFLNK | 0o777,
                           target.encode("utf-8")))

        elif kw == "node":
            path, mode, ntype, major, minor = args
            need_path(no, path)
            perm = need_mode(no, mode)
            if ntype not in ("c", "b"):
                fail(no, "node type must be c or b")
            if not (major.isdigit() and minor.isdigit()):
                fail(no, "node numbers must be decimal")
            fmt_bits = stat.S_IFCHR if ntype == "c" else stat.S_IFBLK
            add(no, Member(path, fmt_bits | perm, b"",
                           (int(major), int(minor))))

        elif kw == "busybox":
            busy.append((no, args[0], args[1:]))

    if output is None:
        raise BuildError("%s: no output line" % label)

    for path in sorted(entries):
        parts = path.split("/")
        for i in range(1, len(parts)):
            parent = "/".join(parts[:i])
            e = entries.get(parent)
            if e is None or e.kind != "d":
                fail(lines[path], "parent %s of %s is not a declared dir"
                     % (parent, path))

    for no, path, want in busy:
        e = entries.get(path)
        if e is None or e.kind != "f":
            fail(no, "busybox %s is not a file entry" % path)
        table = busybox_applets(e.data)
        if not table:
            fail(no, "no applet table found in %s" % path)
        names = [w for w in want if w != "+math"]
        have = set(table)
        missing = [a for a in names if a not in have]
        math = all(t in e.data for t in MATH_TEXTS)
        linked = sorted(posixpath.basename(p) for p, x in entries.items()
                        if x.kind == "l" and resolve(entries, p) == path)
        unlisted = [a for a in linked if a not in names]
        log('MKCPIO busybox %s version="%s" applets=%d need=%s missing=%s '
            "math=%s links=%s" % (path, busybox_version(e.data), len(table),
                                  ",".join(names), ",".join(missing) or "none",
                                  "yes" if math else "no",
                                  ",".join(linked) or "none"))
        if missing:
            fail(no, "applets missing from %s: %s" % (path, ",".join(missing)))
        if "+math" in want and not math:
            fail(no, "%s lacks shell/math.c's texts: no $(( ))" % path)
        if unlisted:
            fail(no, "links %s resolve to %s but are not listed applets"
                 % (",".join(unlisted), path))

    raw = write_newc(entries.values())
    gz = gzip_bytes(raw)
    cpio_sha, gz_sha = sha256(raw), sha256(gz)
    no, rel, gz_pin, cpio_pin = output
    log("MKCPIO build entries=%d cpio_bytes=%d cpio_sha256=%s gz_bytes=%d "
        "gz_sha256=%s zlib=%s" % (len(entries), len(raw), cpio_sha, len(gz),
                                  gz_sha, zlib.ZLIB_RUNTIME_VERSION))
    pinned = gz_pin != "-" and cpio_pin != "-"
    if not pinned and not unpinned:
        fail(no, "output pins are '-': pin them, or pass --unpinned to print "
                 "the first values")
    if cpio_pin != "-" and cpio_sha != cpio_pin:
        fail(no, "output cpio_sha256 mismatch got=%s want=%s: the archive "
                 "content differs" % (cpio_sha, cpio_pin))
    if gz_pin != "-" and gz_sha != gz_pin:
        fail(no, "output gz_sha256 mismatch got=%s want=%s zlib=%s: the cpio "
                 "bytes %s, only the gzip stream differs"
             % (gz_sha, gz_pin, zlib.ZLIB_RUNTIME_VERSION,
                "match" if cpio_pin != "-" else "are unpinned"))

    target = out_override or os.path.join(base, *rel.split("/"))
    parent = os.path.dirname(os.path.abspath(target))
    os.makedirs(parent, exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(gz)
    os.replace(tmp, target)
    log("MKCPIO wrote %s pin=%s" % (out_override or rel,
                                    "ok" if pinned else "none"))
    return {"entries": len(entries), "cpio_sha256": cpio_sha,
            "gz_sha256": gz_sha, "path": target}


# ------------------------------------------------------------------ list

def quote(s):
    return s if PATH_CHARS_RE.match(s) else json.dumps(s)


def format_member(m):
    sha = sha256(m.data) if m.kind == "f" else "-"
    line = "%s %04o %d:%d %d %d %s %s" % (m.kind, m.perm, m.uid, m.gid,
                                          m.nlink, len(m.data), sha,
                                          quote(m.path))
    if m.kind == "l":
        line += " -> " + quote(m.target)
    elif m.kind in ("c", "b"):
        line += " %d:%d" % m.rdev
    return line


def cmd_list(path):
    with open(path, "rb") as fh:
        blob = fh.read()
    try:
        fmt, raw = unpack(blob)
        members, archives = read_newc(raw)
    except CpioError as e:
        print("MKCPIO FAIL list %s: %s" % (os.path.basename(path), e))
        return 1
    print("MKCPIO list %s format=%s input_sha256=%s cpio_sha256=%s members=%d "
          "archives=%d" % (os.path.basename(path), fmt, sha256(blob),
                           sha256(raw), len(members), archives))
    for m in members:
        print(format_member(m))
    return 0


# ------------------------------------------------------------------ selftest

def _fixture():
    """Covers every kind build writes. usr/bin-extra sorts after usr/bin/tool
    by components but before it as a plain string, which tests the rule."""
    return [
        Member("usr", stat.S_IFDIR | 0o755),
        Member("usr/bin", stat.S_IFDIR | 0o755),
        Member("usr/bin/tool", stat.S_IFREG | 0o755, b"#!/bin/sh\necho t\n"),
        Member("usr/bin-extra", stat.S_IFREG | 0o644, b"x"),
        Member("bin", stat.S_IFLNK | 0o777, b"usr/bin"),
        Member("dev", stat.S_IFDIR | 0o755),
        Member("dev/console", stat.S_IFCHR | 0o600, b"", (5, 1)),
        Member("init", stat.S_IFREG | 0o755, b"#!/bin/sh\n"),
    ]


FIXTURE_ORDER = ["bin", "dev", "dev/console", "init", "usr", "usr/bin",
                 "usr/bin/tool", "usr/bin-extra"]


def _fake_busybox(math=True):
    names = sorted([b"[", b"[[", b"ash", b"cat", b"echo", b"mount", b"sh",
                    b"sleep", b"uname"] + [b"z%02d" % i for i in range(20)])
    blob = (b"\x7fELF-selftest\0junk-before\0BusyBox v0.0 (selftest)\0"
            + b"\0".join(names) + b"\0")
    if math:
        blob += b"\0".join(MATH_TEXTS) + b"\0"
    return blob


def _expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def selftest():
    results = []

    def case(name, fn):
        try:
            fn()
        except Exception as e:  # any exception is a failed case
            results.append(False)
            print("MKCPIO selftest %s FAIL %s: %s" % (name, type(e).__name__,
                                                      e))
            return
        results.append(True)
        print("MKCPIO selftest %s ok" % name)

    fixture = _fixture()
    by_path = {m.path: m for m in fixture}

    def roundtrip():
        raw = write_newc(list(reversed(fixture)))
        _expect(len(raw) % BLOCK == 0, "not padded to 512")
        for label, blob in (("raw", raw), ("gzip", gzip_bytes(raw))):
            fmt, cpio = unpack(blob)
            _expect(fmt == label, "format %s read as %s" % (label, fmt))
            members, archives = read_newc(cpio)
            _expect(archives == 1, "archives=%d" % archives)
            _expect([m.path for m in members] == FIXTURE_ORDER,
                    "order %s" % [m.path for m in members])
            for ino, m in enumerate(members, 1):
                want = by_path[m.path]
                _expect((m.mode, m.data, m.rdev) == (want.mode, want.data,
                                                     want.rdev),
                        "%s fields differ" % m.path)
                _expect((m.uid, m.gid, m.mtime, m.ino) == (0, 0, 0, ino),
                        "%s owner, mtime or inode" % m.path)
                _expect(m.nlink == (2 if m.kind == "d" else 1),
                        "%s nlink" % m.path)

    def device_node():
        members, _ = read_newc(write_newc(fixture))
        m = [x for x in members if x.path == "dev/console"][0]
        _expect(m.kind == "c" and m.perm == 0o600 and m.rdev == (5, 1)
                and m.data == b"", "dev/console is not c 0600 5:1, empty")
        line = format_member(m)
        _expect(line.startswith("c 0600 0:0 1 0 - ")
                and line.endswith("dev/console 5:1"), line)

    def symlink():
        members, _ = read_newc(write_newc(fixture))
        m = [x for x in members if x.path == "bin"][0]
        _expect(m.mode == stat.S_IFLNK | 0o777 and m.target == "usr/bin",
                "bin is not a 0777 symlink to usr/bin")
        _expect(format_member(m).endswith("bin -> usr/bin"), format_member(m))
        entries = {x.path: x for x in fixture}
        _expect(resolve(entries, "bin/tool") == "usr/bin/tool", "resolve")
        loop = {"a": Member("a", stat.S_IFLNK | 0o777, b"b"),
                "b": Member("b", stat.S_IFLNK | 0o777, b"a")}
        _expect(resolve(loop, "a") is None, "a symlink loop resolved")

    def format_pin():
        got = sha256(write_newc(fixture))
        _expect(got == FIXTURE_CPIO_SHA256, "fixture cpio sha256 %s" % got)

    def deterministic():
        a = write_newc(fixture)
        rotated = fixture[3:] + fixture[:3]
        _expect(write_newc(rotated) == a, "input order changed the bytes")
        g1, g2 = gzip_bytes(a), gzip_bytes(write_newc(list(reversed(fixture))))
        _expect(g1 == g2, "gzip bytes differ between builds")
        _expect(g1[:4] == b"\x1f\x8b\x08\x00" and g1[4:8] == b"\0\0\0\0",
                "gzip header carries a name or an mtime")

    def concatenated():
        one = write_newc([fixture[0]])
        two = write_newc([fixture[7]])
        for label, blob in (("raw", one + two),
                            ("gzip", gzip_bytes(one) + gzip_bytes(two))):
            members, archives = read_newc(unpack(blob)[1])
            _expect(archives == 2 and [m.path for m in members]
                    == ["usr", "init"], "%s concatenation" % label)

    def malformed():
        raw = write_newc(fixture)
        for label, blob, text in (
                ("truncated", raw[:200], "truncated"),
                ("no trailer", raw[:raw.index(TRAILER.encode()) - HEADER_LEN],
                 "no trailer"),
                ("bad magic", b"070707" + raw[6:], "not a newc header")):
            try:
                read_newc(blob)
            except CpioError as e:
                _expect(text in str(e), "%s refused for %s" % (label, e))
                continue
            raise AssertionError("%s archive accepted" % label)

    for name, fn in (("roundtrip", roundtrip), ("device_node", device_node),
                     ("symlink", symlink), ("format_pin", format_pin),
                     ("deterministic", deterministic),
                     ("concatenated", concatenated),
                     ("malformed", malformed)):
        case(name, fn)

    with tempfile.TemporaryDirectory(prefix="mkcpio-selftest-") as tmp:
        _manifest_cases(tmp, case)

    ok = all(results)
    print("MKCPIO selftest %s cases=%d failed=%d"
          % ("ok" if ok else "fail", len(results), results.count(False)))
    return 0 if ok else 1


def _manifest_cases(tmp, case):
    """Builds through the manifest path: one pinned build, a deterministic
    rebuild, then each refusal, which must name its own cause and write
    nothing."""
    bb, nomath = _fake_busybox(), _fake_busybox(math=False)
    lib = b"\x7fELF-libx\0"
    dup = b"dup\0"
    src_a = write_newc([
        Member("usr", stat.S_IFDIR | 0o755),
        Member("usr/bin", stat.S_IFDIR | 0o755),
        Member("usr/bin/busybox", stat.S_IFREG | 0o755, bb),
        Member("usr/bin/nomath", stat.S_IFREG | 0o755, nomath),
        Member("usr/bin/dup", stat.S_IFREG | 0o644, dup),
        Member("usr/lib", stat.S_IFDIR | 0o755),
        Member("usr/lib/libx.so.1", stat.S_IFREG | 0o644, lib),
        Member("lib", stat.S_IFLNK | 0o777, b"usr/lib"),
    ])
    src_b = write_newc([Member("usr/bin/dup", stat.S_IFREG | 0o644, dup)])
    src = gzip_bytes(src_a) + gzip_bytes(src_b)
    init = b"#!/bin/sh\necho S1-INIT start\n"
    with open(os.path.join(tmp, "src.cpio.gz"), "wb") as fh:
        fh.write(src)
    with open(os.path.join(tmp, "init.sh"), "wb") as fh:
        fh.write(init)

    pins = {"SRC": sha256(src), "BB": sha256(bb), "LIB": sha256(lib),
            "INIT": sha256(init), "DUP": sha256(dup), "NOMATH": sha256(nomath),
            "GZ": "-", "CPIO": "-"}
    template = """# selftest manifest
source src src.cpio.gz SRC
output out/test.cpio.gz GZ CPIO
dir dev 0755
dir usr 0755
dir usr/bin 0755
dir usr/lib 0755
file usr/bin/busybox 0755 BB src usr/bin/busybox
file usr/lib/libx.so.1 0644 LIB src usr/lib/libx.so.1
file init 0755 INIT local init.sh
link lib usr/lib src
link usr/bin/sh busybox
link usr/bin/cat busybox
node dev/console 0600 c 5 1
busybox usr/bin/busybox +math sh ash cat
"""
    quiet = []

    def render(text, **over):
        values = dict(pins, **over)
        for key in sorted(values, key=len, reverse=True):
            text = re.sub(r"\b%s\b" % key, values[key], text)
        path = os.path.join(tmp, "m%d.manifest" % len(quiet))
        quiet.append(path)
        with open(path, "w", newline="\n") as fh:
            fh.write(text)
        return path

    first = build(render(template), os.path.join(tmp, "first.gz"), True,
                  quiet.append)
    pins["GZ"], pins["CPIO"] = first["gz_sha256"], first["cpio_sha256"]

    def pinned_build():
        out = os.path.join(tmp, "pinned.gz")
        r = build(render(template), out, False, quiet.append)
        with open(out, "rb") as fh:
            members, _ = read_newc(unpack(fh.read())[1])
        paths = [m.path for m in members]
        _expect(paths == ["dev", "dev/console", "init", "lib", "usr",
                          "usr/bin", "usr/bin/busybox", "usr/bin/cat",
                          "usr/bin/sh", "usr/lib", "usr/lib/libx.so.1"],
                "pinned build members %s" % paths)
        _expect(r["cpio_sha256"] == pins["CPIO"], "pinned build hash")

    def rebuild_identical():
        outs = []
        for n in (1, 2):
            out = os.path.join(tmp, "again%d.gz" % n)
            build(render(template), out, False, quiet.append)
            with open(out, "rb") as fh:
                outs.append(fh.read())
        _expect(outs[0] == outs[1] and sha256(outs[0]) == pins["GZ"],
                "two builds differ")

    case("manifest_pinned_build", pinned_build)
    case("manifest_deterministic", rebuild_identical)

    extra_dup = "file usr/bin/dup 0644 DUP src usr/bin/dup\n"
    extra_nomath = ("file usr/bin/nomath 0755 NOMATH src usr/bin/nomath\n"
                    "busybox usr/bin/nomath +math sh\n")
    refusals = [
        ("refuse_source_sha256", template, {"SRC": "0" * 64},
         "source src sha256 mismatch"),
        ("refuse_member_sha256", template, {"BB": "0" * 64},
         "usr/bin/busybox sha256 mismatch"),
        ("refuse_local_sha256", template, {"INIT": "f" * 64},
         "init sha256 mismatch"),
        ("refuse_cpio_pin", template, {"CPIO": "0" * 64},
         "cpio_sha256 mismatch"),
        ("refuse_gz_pin", template, {"GZ": "0" * 64},
         "only the gzip stream differs"),
        ("refuse_unpinned", template, {"GZ": "-", "CPIO": "-"},
         "--unpinned"),
        ("refuse_mode", template.replace("libx.so.1 0644", "libx.so.1 0755"),
         {}, "differs from the member's"),
        ("refuse_link_not_in_source",
         template.replace("link lib usr/lib src", "link lib usr/lob src"), {},
         "is not in source src"),
        ("refuse_ambiguous_member", template + extra_dup, {},
         "occurs 2 times"),
        ("refuse_undeclared_parent",
         template.replace("dir usr/lib 0755\n", ""), {},
         "parent usr/lib of usr/lib/libx.so.1 is not a declared dir"),
        ("refuse_duplicate_path", template + "dir dev 0755\n", {},
         "duplicate path dev"),
        ("refuse_dotdot_path", template + "dir usr/../etc 0755\n", {},
         "bad archive path"),
        ("refuse_missing_applet",
         template.replace("+math sh ash cat", "+math sh ash cat vi"), {},
         "applets missing"),
        ("refuse_unlisted_link", template + "link usr/bin/vi busybox\n", {},
         "are not listed applets"),
        ("refuse_no_math", template + extra_nomath, {},
         "lacks shell/math.c"),
        ("refuse_device_numbers",
         template.replace("c 5 1", "c 5 x"), {}, "must be decimal"),
    ]
    for name, text, over, cause in refusals:
        def refused(text=text, over=over, cause=cause, name=name):
            out = os.path.join(tmp, name + ".gz")
            try:
                build(render(text, **over), out, False, quiet.append)
            except BuildError as e:
                _expect(cause in str(e), "refused for another cause: %s" % e)
                _expect(not os.path.exists(out), "refusal wrote the output")
                return
            raise AssertionError("build accepted")
        case(name, refused)


# ------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="mkcpio.py",
        description="S1-F initrd builder: newc cpio reader and writer")
    ap.add_argument("--selftest", action="store_true",
                    help="run the self-tests and exit")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build", help="build the archive a manifest describes")
    b.add_argument("manifest")
    b.add_argument("-o", "--output", help="write here instead of the "
                   "manifest's output path (the pins still apply)")
    b.add_argument("--unpinned", action="store_true",
                   help="accept '-' output pins, to print the first values")
    ls = sub.add_parser("list", help="list a newc archive, raw or gzip")
    ls.add_argument("archive")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.cmd == "build":
        try:
            build(a.manifest, a.output, a.unpinned)
        except (BuildError, CpioError, OSError) as e:
            print("MKCPIO FAIL %s" % e)
            return 1
        return 0
    if a.cmd == "list":
        return cmd_list(a.archive)
    ap.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
