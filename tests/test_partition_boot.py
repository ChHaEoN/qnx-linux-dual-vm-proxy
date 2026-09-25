"""partition-boot.sh (Phase 3b / A6, 2026-09-25): add, select and remove the partition boot
entry on a copy of an L4T extlinux.conf, with a stub sudo; the original must come back
byte for byte."""
import hashlib
import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(__file__)
SCRIPT = os.path.join(HERE, "..", "orin-native", "gpu-concurrency", "partition-boot.sh")
BASH = shutil.which("bash")
L4T = """TIMEOUT 30
DEFAULT primary

MENU TITLE L4T boot options

LABEL primary
      MENU LABEL primary kernel
      LINUX /boot/Image
      INITRD /boot/initrd
      APPEND ${cbootargs} root=/dev/mmcblk0p1 rw rootwait rootfstype=ext4 console=ttyTCU0,115200 console=tty0

# When testing a custom kernel, it is recommended that you create a backup of
# the original kernel and add a new entry to this file.
#
# LABEL backup
#    MENU LABEL backup kernel
#    LINUX /boot/Image.backup
"""
pytestmark = pytest.mark.skipif(BASH is None, reason="no bash")


def _env(tmp_path):
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "sudo").write_text('#!/bin/sh\n[ "$1" = -n ] && shift\nexec "$@"\n', newline="\n")
    os.chmod(stub / "sudo", 0o755)
    conf = tmp_path / "extlinux.conf"
    conf.write_text(L4T, newline="\n")
    env = dict(os.environ, CONF=conf.as_posix(), PATH="%s%s%s" % (stub.as_posix(), os.pathsep, os.environ["PATH"]))
    return conf, env


def _run(env, *args):
    r = subprocess.run([BASH, SCRIPT] + list(args), capture_output=True, text=True, env=env, timeout=60)
    return r.returncode, r.stdout + r.stderr


def test_install_select_and_remove_round_trip(tmp_path):
    conf, env = _env(tmp_path)
    before = hashlib.sha256(conf.read_bytes()).hexdigest()
    rc, out = _run(env, "install")
    assert rc == 0, out
    text = conf.read_text()
    assert text.startswith(L4T) and "\nLABEL partition\n" in text and "DEFAULT primary" in text
    new = text[len(L4T):]
    assert "#" not in new and "MENU LABEL partition: isolcpus=managed_irq,domain,0-2,4 irqaffinity=3,5" in new
    assert "console=tty0 isolcpus=managed_irq,domain,0-2,4 irqaffinity=3,5\n" in new
    assert "LINUX /boot/Image\n" in new and "INITRD /boot/initrd\n" in new
    assert _run(env, "install")[0] != 0                       # twice: refused
    rc, out = _run(env, "default", "partition")
    assert rc == 0 and "\nDEFAULT partition\n" in conf.read_text(), out
    assert _run(env, "default", "backup")[0] != 0             # only primary or partition
    rc, out = _run(env, "status")
    assert "default: partition" in out and "labels: primary partition" in out and "saved: yes" in out, out
    rc, out = _run(env, "default", "primary")
    assert rc == 0, out
    rc, out = _run(env, "remove")
    assert rc == 0, out
    assert hashlib.sha256(conf.read_bytes()).hexdigest() == before
    assert not os.path.exists(str(conf) + ".pre-partition")
    assert _run(env, "remove")[0] != 0                        # nothing left to restore


def test_it_refuses_a_file_it_cannot_trust(tmp_path):
    conf, env = _env(tmp_path)
    conf.write_text(L4T.replace("DEFAULT primary", "DEFAULT nothere"), newline="\n")
    rc, out = _run(env, "install")
    assert rc != 0 and "does not check" in out
    assert not os.path.exists(str(conf) + ".pre-partition")
    conf.write_text(L4T.replace("      APPEND", "      APPEND x\n      APPEND"), newline="\n")
    rc, out = _run(env, "install")
    assert rc != 0 and "exactly one APPEND" in out
