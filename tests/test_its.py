"""The ivshmem doorbell into the guest (A6, 2026-09-29): the host ring tool against a fake ivshmem
server and a fake guest, the startup build script's variant switch, and ifs-its.build as ifs-kick.build
plus exactly the ITS lines. Everything here is synthetic; nothing runs QNX or QEMU."""
import mmap
import os
import select
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
RING = os.path.join(ROOT, "orin-native", "gpu-concurrency", "ivshmem_ring.py")
BUILD = os.path.join(ROOT, "orin-native", "startup", "build-qemu-virt.sh")
VARIANT_SRC = os.path.join(ROOT, "orin-native", "startup", "qemu-virt-its", "aarch64", "init_intrinfo.c")
IFS_DIR = os.path.join(ROOT, "ipc-test", "qnx-safety-monitor")
BASH = shutil.which("bash")
ECHO_OFF = 65536

needs_fd_passing = pytest.mark.skipif(
    os.name != "posix" or not hasattr(socket, "send_fds") or not hasattr(os, "eventfd"),
    reason="needs AF_UNIX fd passing and eventfd (Linux)")


class FakeWorld:
    """A server that hands one peer (id 2) the protocol the real one does, and a guest (peer 1)
    that, when echo is on, rings back the peer whose id the host left at ECHO_OFF."""

    def __init__(self, tmp_path, echo=True, guest_present=True):
        self.sock_path = str(tmp_path / "ivsh.sock")
        self.shm_path = tmp_path / "shm"
        self.shm_path.write_bytes(b"\0" * (2 * ECHO_OFF))
        self.guest_efd = os.eventfd(0, os.EFD_NONBLOCK)
        self.own_efd = os.eventfd(0, os.EFD_NONBLOCK)
        self.echo, self.guest_present = echo, guest_present
        self.stop = threading.Event()
        self.rung = 0
        self.seen_ids = []
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(self.sock_path)
        self.listener.listen(1)
        self.threads = [threading.Thread(target=self.serve, daemon=True),
                        threading.Thread(target=self.guest, daemon=True)]
        for t in self.threads:
            t.start()

    def serve(self):
        conn, _ = self.listener.accept()
        shm_fd = os.open(str(self.shm_path), os.O_RDWR)

        def send(v, fd=None):
            data = struct.pack("<q", v)
            if fd is None:
                conn.sendall(data)
            else:
                socket.send_fds(conn, [data], [fd])
        send(0)
        send(2)
        send(-1, shm_fd)
        if self.guest_present:
            send(1, self.guest_efd)
        send(2, self.own_efd)
        self.stop.wait(10)
        conn.close()

    def guest(self):
        p = select.poll()
        p.register(self.guest_efd, select.POLLIN)
        with open(self.shm_path, "r+b") as f:
            m = mmap.mmap(f.fileno(), 0)
            while not self.stop.is_set():
                if not p.poll(20):
                    continue
                os.read(self.guest_efd, 8)
                self.rung += 1
                peer = struct.unpack_from("<I", m, ECHO_OFF)[0]
                self.seen_ids.append(peer)
                if self.echo and peer == 2:
                    os.write(self.own_efd, struct.pack("<Q", 1))
            self.final_id = struct.unpack_from("<I", m, ECHO_OFF)[0]
            m.close()

    def close(self):
        self.stop.set()
        for t in self.threads:
            t.join(5)
        self.listener.close()


def _ring(world, tmp_path, *extra):
    out = tmp_path / "ring.json"
    r = subprocess.run([sys.executable, RING, "--socket", world.sock_path, "--gap-ms", "1",
                        "--json", str(out)] + list(extra), capture_output=True, text=True, timeout=60)
    time.sleep(0.1)
    world.close()
    return r, out


@needs_fd_passing
def test_every_ring_reaches_the_guest_and_every_echo_comes_back(tmp_path):
    w = FakeWorld(tmp_path)
    r, out = _ring(w, tmp_path, "--count", "5", "--echo", "--timeout-ms", "1000")
    assert r.returncode == 0, r.stdout + r.stderr
    import json
    d = json.loads(out.read_text())
    assert len(d["rtt_ns"]) == 5 and d["timeouts"] == 0 and d["own_peer"] == 2
    assert w.rung == 5 and set(w.seen_ids) == {2}
    assert w.final_id == 0, "the tool must clear its id from the shared memory when it leaves"


@needs_fd_passing
def test_a_guest_that_does_not_echo_is_counted_as_timeouts(tmp_path):
    w = FakeWorld(tmp_path, echo=False)
    r, out = _ring(w, tmp_path, "--count", "2", "--echo", "--timeout-ms", "50")
    assert r.returncode == 1 and "0 echoed, 2 timed out" in r.stdout, r.stdout + r.stderr
    assert w.rung == 2


@needs_fd_passing
def test_without_echo_the_tool_leaves_no_id_and_waits_for_nothing(tmp_path):
    w = FakeWorld(tmp_path)
    r, _out = _ring(w, tmp_path, "--count", "3")
    assert r.returncode == 0 and w.rung == 3 and set(w.seen_ids) == {0}, r.stdout + r.stderr


@needs_fd_passing
def test_no_guest_on_the_server_is_refused(tmp_path):
    w = FakeWorld(tmp_path, guest_present=False)
    r, _out = _ring(w, tmp_path, "--count", "1")
    assert r.returncode != 0 and "not connected" in r.stderr, r.stdout + r.stderr


@pytest.mark.skipif(BASH is None, reason="bash not available")
def test_the_startup_build_script_parses_and_knows_one_variant(tmp_path):
    r = subprocess.run([BASH, "-n", BUILD], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    env = dict(os.environ, VARIANT="bogus", BSP=str(tmp_path))
    r = subprocess.run([BASH, BUILD], capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 1 and "the only variant is 'its'" in r.stderr, r.stderr


def test_the_its_variant_sets_what_kvm_needs_before_initialising():
    import re
    src = re.sub(r"/\*.*?\*/", "", open(VARIANT_SRC, encoding="utf-8").read(), flags=re.S)
    body = src[src.index("init_intrinfo(void)"):]
    init = body.index("gic_v3_initialize();")
    for call in ("QV_GITS_BASE", "gic_v3_lpi_add_entry(&qv_lpi)", "gic_v3_its_set_dt_page_size(0, 65536u)",
                 "gic_v3_its_set_ct_page_size(0, 65536u)", "gic_v3_its_set_cmd_q_params(0, &cacheable",
                 "gic_v3_set_lpi_cfgtbl_params(&cacheable"):
        assert 0 <= body.index(call) < init, call
    assert "PROT_NOCACHE" not in body[:init], "the callouts' views must stay cacheable"


def test_ifs_its_is_ifs_kick_plus_exactly_the_its_lines():
    def lines(name):
        with open(os.path.join(IFS_DIR, name), encoding="utf-8") as f:
            return [ln.rstrip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    kick, its = lines("ifs-kick.build"), lines("ifs-its.build")
    removed = [ln for ln in kick if ln not in its]
    added = [ln for ln in its if ln not in kick]
    assert removed == ["    startup-qemu-virt",
                       "[perms=0444] build/ifs.build=E:/Project/qnx-linux-dual-vm-proxy/ipc-test/qnx-safety-monitor/ifs-kick.build",
                       "[perms=0444] build.date = output/build/ifs-kick.build.date"], removed
    assert added == ["    startup-qemu-virt-its -vv",
                     "/proc/boot/qnx-its-probe info",
                     "/proc/boot/qnx-its-probe selftest 20",
                     "/proc/boot/qnx-its-probe msixcfg",
                     "/proc/boot/qnx-its-probe msixwait &",
                     "[perms=0444] build/ifs.build=E:/Project/qnx-linux-dual-vm-proxy/ipc-test/qnx-safety-monitor/ifs-its.build",
                     "[perms=0444] build.date = output/build/ifs-its.build.date",
                     "[perms=555] qnx-its-probe=E:/Project/qnx-linux-dual-vm-proxy/ipc-test/qnx-its-probe/qnx-its-probe"], added
    # msixcfg sizes BAR1 with decoding off: it must come after shmcfg and before every shm monitor.
    at = {ln: i for i, ln in enumerate(its)}
    cfg = at["/proc/boot/qnx-its-probe msixcfg"]
    assert at["/proc/boot/qnx-safety-monitor shmcfg ivshmem"] < cfg
    assert cfg < at["/proc/boot/qnx-safety-monitor shm ivshmem &"]
    assert cfg < at["/proc/boot/qnx-safety-monitor shmkick ivshmem@4096 /dev/vcon2 &"]
