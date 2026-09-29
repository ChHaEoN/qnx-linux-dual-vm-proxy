"""Two MSI-X vectors on the ivshmem doorbell (Phase 3b / A6, 2026-09-29), host side: the ivshmem
client keeps every vector of a peer, the probe can ring vector 1, the launcher passes VECTORS, and
the two ifs-unmask images are ifs-bell.build with only the intended lines changed. The guest side
(qcc-built) is checked by text only: CI cannot build or run it."""
import ctypes
import difflib
import errno
import os
import shutil
import subprocess
import sys
import time

import pytest

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
COMMON = os.path.join(HERE, "..", "ipc-test", "common")
MON = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor")
SERVER = os.path.join(GC, "ivshmem_server.py")


@pytest.fixture(scope="module")
def shmchan(tmp_path_factory):
    gcc = shutil.which("gcc")
    if gcc is None or not sys.platform.startswith("linux"):
        pytest.skip("needs gcc on Linux: runs in CI's tooling job")
    d = tmp_path_factory.mktemp("unmask")
    lib = d / "libshmchan.so"
    subprocess.run([gcc, "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC", "-I", COMMON, "-o", str(lib),
                    os.path.join(GC, "shmchan.c"), os.path.join(COMMON, "shm_map_posix.c"),
                    os.path.join(COMMON, "ivshm_client.c")], check=True, capture_output=True)
    c = ctypes.CDLL(str(lib))
    c.shmchan_ivshm_connect.restype = ctypes.c_void_p
    c.shmchan_ivshm_connect.argtypes = [ctypes.c_char_p]
    c.shmchan_ivshm_id.restype = ctypes.c_longlong
    c.shmchan_ivshm_id.argtypes = [ctypes.c_void_p]
    c.shmchan_ivshm_efd.restype = ctypes.c_int
    c.shmchan_ivshm_efd.argtypes = [ctypes.c_void_p]
    c.shmchan_ivshm_peer_efd.restype = ctypes.c_int
    c.shmchan_ivshm_peer_efd.argtypes = [ctypes.c_void_p, ctypes.c_longlong]
    c.shmchan_ivshm_peer_efd_vec.restype = ctypes.c_int
    c.shmchan_ivshm_peer_efd_vec.argtypes = [ctypes.c_void_p, ctypes.c_longlong, ctypes.c_int]
    c.shmchan_ivshm_close.restype = None
    c.shmchan_ivshm_close.argtypes = [ctypes.c_void_p]
    return c, d


def _server(d, vectors):
    shm = "/dev/shm/unmask-test-%d-%d" % (os.getpid(), vectors)
    with open(shm, "wb") as f:
        f.write(b"\0" * 4096)
    sock, ready = str(d / ("s%d.sock" % vectors)), str(d / ("s%d.ready" % vectors))
    p = subprocess.Popen([sys.executable, SERVER, "--socket", sock, "--shm", shm, "--vectors", str(vectors),
                          "--ready", ready], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if os.path.exists(ready) and os.path.getsize(ready):
            break
        time.sleep(0.05)
    return p, sock, shm


def _read_nb(fd):
    try:
        return int.from_bytes(os.read(fd, 8), "little")
    except BlockingIOError:
        return None
    except OSError as e:
        if e.errno == errno.EAGAIN:
            return None
        raise


def test_a_peer_keeps_every_vector_and_each_rings_its_own_eventfd(shmchan):
    c, d = shmchan
    p, sock, shm = _server(d, 2)
    try:
        a = c.shmchan_ivshm_connect(sock.encode())
        b = c.shmchan_ivshm_connect(sock.encode())
        assert a and b, "both peers join a two-vector server (the own second vector is no protocol error)"
        bid = c.shmchan_ivshm_id(b)
        v0, v1 = c.shmchan_ivshm_peer_efd_vec(a, bid, 0), c.shmchan_ivshm_peer_efd_vec(a, bid, 1)
        assert v0 >= 0 and v1 >= 0 and v0 != v1
        assert c.shmchan_ivshm_peer_efd(a, bid) == v0, "the old call is vector 0"
        assert c.shmchan_ivshm_peer_efd_vec(a, bid, 2) == -1, "no third vector"
        for fd in (v0, v1):
            os.set_blocking(fd, False)
        os.write(v1, (1).to_bytes(8, "little"))
        assert _read_nb(v0) is None and _read_nb(v1) == 1, "vector 1's eventfd is not vector 0's"
        assert c.shmchan_ivshm_efd(b) >= 0
        c.shmchan_ivshm_close(a)
        c.shmchan_ivshm_close(b)
    finally:
        p.terminate()
        p.wait(timeout=10)
        os.remove(shm)


def test_vectors_past_the_table_are_ignored_not_fatal(shmchan):
    c, d = shmchan
    p, sock, shm = _server(d, 6)
    try:
        a = c.shmchan_ivshm_connect(sock.encode())
        b = c.shmchan_ivshm_connect(sock.encode())
        assert a and b, "a server with more vectors than the table still serves vector 0"
        bid = c.shmchan_ivshm_id(b)
        assert c.shmchan_ivshm_peer_efd_vec(a, bid, 3) >= 0 and c.shmchan_ivshm_peer_efd_vec(a, bid, 4) == -1
        c.shmchan_ivshm_close(a)
        c.shmchan_ivshm_close(b)
    finally:
        p.terminate()
        p.wait(timeout=10)
        os.remove(shm)


def test_one_vector_is_as_before(shmchan):
    c, d = shmchan
    p, sock, shm = _server(d, 1)
    try:
        a = c.shmchan_ivshm_connect(sock.encode())
        b = c.shmchan_ivshm_connect(sock.encode())
        bid = c.shmchan_ivshm_id(b)
        assert c.shmchan_ivshm_peer_efd(a, bid) >= 0 and c.shmchan_ivshm_peer_efd_vec(a, bid, 1) == -1
        c.shmchan_ivshm_close(a)
        c.shmchan_ivshm_close(b)
    finally:
        p.terminate()
        p.wait(timeout=10)
        os.remove(shm)


def test_the_launcher_passes_vectors_and_defaults_to_one():
    text = open(os.path.join(GC, "launch-qnx-kvm-bridged.sh"), encoding="utf-8").read()
    assert 'VECTORS="${VECTORS:-1}"' in text and 'case "${VECTORS}" in 1|2)' in text
    assert '--vectors "${VECTORS}"' in text and "ivshmem-doorbell,chardev=ivsh0,vectors=${VECTORS}" in text


def test_the_probe_and_library_ring_vector_one_only_when_asked():
    probe = open(os.path.join(GC, "latency_probe.py"), encoding="utf-8").read()
    assert 'ap.add_argument("--bell-vector", type=int, default=0,' in probe
    assert 'if a.bell_vector:\n            res["bell_vector"] = a.bell_vector' in probe
    lib = open(os.path.join(GC, "lib-measure.sh"), encoding="utf-8").read()
    assert '[ "$PROBE_BELL_VECTOR" != 0 ] && claim+=(--bell-vector "$PROBE_BELL_VECTOR")' in lib


def test_the_guest_kick_spec_keeps_msix_as_it_was_and_defers_only_the_unmask():
    src = open(os.path.join(COMMON, "shm_map_qnx.c"), encoding="utf-8").read()
    kick = src.split('if (strncmp(kick, "msix", 4) == 0) {')[1].split("\n\t}\n")[0]
    # one attach for both ways; no other IST form, no lightweight block
    assert kick.count("InterruptAttachEvent((int)lpi, &ev, _NTO_INTR_FLAGS_TRK_MSK)") == 1
    assert "InterruptAttachThread" not in src and "_NTO_INTR_WAIT_FLAGS_FAST" not in src
    assert "if (*m == '1') {" in kick and 'strcmp(m, ":defer") == 0' in kick
    # the banner every earlier harness greps: "kick msix (LPI 8193)" for plain "msix"
    assert '"%s; slot @%zu; peer %u; kick %s (LPI %u%s)"' in kick and 'k->defer ? ", unmask deferred" : ""' in kick
    wait = src.split("int shm_kick_wait(struct shm_kick *k)")[1]
    assert "InterruptWait(k->armed ? _NTO_INTR_WAIT_FLAGS_UNMASK : 0, NULL)" in wait
    assert "InterruptWait(0, NULL) == -1) {\n\t\t\treturn errno == EINTR ? 0 : -1;\n\t\t}\n\t\tInterruptUnmask(k->lpi, k->iid);" in wait
    probe = open(os.path.join(HERE, "..", "ipc-test", "qnx-its-probe", "its_probe.c"), encoding="utf-8").read()
    assert "do_msixcfg(argc >= 3 ? (unsigned)strtoul(argv[2], NULL, 0) : 1u)" in probe
    assert '" lpi=%u\\n", s.dev, devid, a1, MSIX_LPI);' in probe, "the one-vector marker is unchanged"


def test_the_unmask_images_are_ifs_bell_with_only_the_intended_lines():
    def lines(name):
        with open(os.path.join(MON, name), encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    bell = lines("ifs-bell.build")
    root = "E:/Project/qnx-linux-dual-vm-proxy/ipc-test/"
    for v, (k0, k1) in (("a", ("msix", "msix1:defer")), ("b", ("msix:defer", "msix1"))):
        ist = lines("ifs-unmask-%s.build" % v)
        ops = [(t, bell[i1:i2], ist[j1:j2]) for t, i1, i2, j1, j2
               in difflib.SequenceMatcher(None, bell, ist, autojunk=False).get_opcodes() if t != "equal"]
        changed = {ln for _t, _a, b in ops for ln in b}
        assert changed == {
            "/proc/boot/qnx-its-probe msixcfg 2",
            "/proc/boot/qnx-safety-monitor shmkick ivshmem@8192 %s &" % k0,
            "/proc/boot/qnx-safety-monitor shmkick ivshmem@12288 %s &" % k1,
            "[perms=0444] build/ifs.build=%sqnx-safety-monitor/ifs-unmask-%s.build" % (root, v),
            "[perms=0444] build.date = output/build/ifs-unmask-%s.build.date" % v,
            "[perms=555] qnx-safety-monitor=%sqnx-safety-monitor/qnx-safety-monitor-unmask" % root,
            "[perms=555] qnx-its-probe=%sqnx-its-probe/qnx-its-probe-2v" % root,
        } - ({"/proc/boot/qnx-safety-monitor shmkick ivshmem@8192 msix &"} if k0 == "msix" else set()), (v, ops)
        removed = {ln for _t, a, _b in ops for ln in a}
        assert removed == {
            "/proc/boot/qnx-its-probe msixcfg",
            "/proc/boot/qnx-safety-monitor shmkick ivshmem@8192 msix &",
            "[perms=0444] build/ifs.build=%sqnx-safety-monitor/ifs-bell.build" % root,
            "[perms=0444] build.date = output/build/ifs-bell.build.date",
            "[perms=555] qnx-safety-monitor=%sqnx-safety-monitor/qnx-safety-monitor-bell" % root,
            "[perms=555] qnx-its-probe=%sqnx-its-probe/qnx-its-probe" % root,
        } - ({"/proc/boot/qnx-safety-monitor shmkick ivshmem@8192 msix &"} if k0 == "msix" else set()), (v, ops)
        at = {ln: i for i, ln in enumerate(ist)}
        assert at["/proc/boot/qnx-its-probe msixcfg 2"] < at["/proc/boot/qnx-safety-monitor shm ivshmem &"]
