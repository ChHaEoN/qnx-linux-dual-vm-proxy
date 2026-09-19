"""Tests for the measurement tooling itself.

Two things are pinned here:

  * latency_probe.percentile -- the arithmetic every published figure from that
    probe was computed with. It was lifted out of main() so it could be tested;
    if someone "improves" it, new runs stop being comparable with recorded ones
    and these tests say so.

  * scripts/twin/delta.awk -- the single shared delta formula. The claims gate
    calls it, diff-results.sh calls it. A test proves the awk and the Python
    helper agree, which is what makes "extract, don't fork" safe.
"""
import os
import shutil
import subprocess

import pytest

import claims_lib as C


# --------------------------------------------------------------------------
# latency_probe
# --------------------------------------------------------------------------


def test_percentile_nearest_rank(latency_probe):
    values = [float(i) for i in range(1, 11)]  # 1..10, already sorted
    assert latency_probe.percentile(values, 0) == 1.0
    assert latency_probe.percentile(values, 100) == 10.0
    # Nearest rank: round(0.5 * 9) = 4 -> values[4] = 5.0
    assert latency_probe.percentile(values, 50) == 5.0


def test_percentile_matches_the_original_nested_closure(latency_probe):
    """Byte-for-byte the arithmetic that was inside main() before extraction."""
    def original(rtts, p):
        k = int(round((p / 100.0) * (len(rtts) - 1)))
        return rtts[k]

    values = sorted([0.9, 0.1, 0.5, 0.33, 0.7, 0.2, 0.8, 0.4, 0.6, 1.0])
    for p in (0, 1, 25, 50, 90, 99, 99.9, 100):
        assert latency_probe.percentile(values, p) == original(values, p)


def test_percentile_single_sample(latency_probe):
    assert latency_probe.percentile([4.2], 50) == 4.2
    assert latency_probe.percentile([4.2], 99.9) == 4.2


def test_build_frame_is_the_wire_format(latency_probe):
    """64-byte frame: 16-byte header + 48-byte payload, little-endian."""
    frame = latency_probe.build_frame(7)
    assert len(frame) == 64
    import struct
    seq, tstamp = struct.unpack("<QQ", frame[:16])
    assert seq == 7
    assert tstamp == 0
    payload = frame[16:]
    assert payload[latency_probe.P_CLASS] == 3
    assert payload[latency_probe.P_CONF] == 95
    assert struct.unpack("<I", payload[latency_probe.P_INFER_US:latency_probe.P_INFER_US + 4])[0] == 124


def test_build_frame_never_emits_the_sentinel(latency_probe):
    """UINT64_MAX is the monitor's keepalive and carries no claim."""
    import struct
    for seq in (0, 1, 12345):
        seq_out = struct.unpack("<Q", latency_probe.build_frame(seq)[:8])[0]
        assert seq_out != 0xFFFFFFFFFFFFFFFF


# --------------------------------------------------------------------------
# the shared delta formula
# --------------------------------------------------------------------------

AWK = shutil.which("awk")


def _run_delta(repo_root, cloud, hw):
    out = subprocess.check_output(
        [
            AWK,
            "-v", "cp50=%d" % cloud, "-v", "hp50=%d" % hw,
            "-v", "cp99=%d" % cloud, "-v", "hp99=%d" % hw,
            "-v", "cmax=%d" % cloud, "-v", "hmax=%d" % hw,
            "-v", "MODE=csv",
            "-f", os.path.join(repo_root, "scripts", "twin", "delta.awk"),
        ],
        stdin=subprocess.DEVNULL,
    ).decode("utf-8")
    return float(out.strip().splitlines()[0].split(",")[4])


@pytest.mark.skipif(AWK is None, reason="awk not available on this host")
def test_delta_awk_agrees_with_claims_lib(repo_root):
    """The awk and the Python must not drift apart; CI relies on both."""
    for cloud, hw in [(100, 125), (2002500, 2213370), (500, 400), (7, 7)]:
        assert _run_delta(repo_root, cloud, hw) == pytest.approx(C.pct_delta(cloud, hw), abs=1e-6)


@pytest.mark.skipif(AWK is None, reason="awk not available on this host")
def test_delta_awk_default_mode_is_the_human_report(repo_root):
    """Default output must stay the format diff-results.sh has always printed."""
    out = subprocess.check_output(
        [
            AWK,
            "-v", "cp50=2002500", "-v", "hp50=2213370",
            "-v", "cp99=2332300", "-v", "hp99=2596291",
            "-v", "cmax=2332300", "-v", "hmax=2596291",
            "-f", os.path.join(repo_root, "scripts", "twin", "delta.awk"),
        ],
        stdin=subprocess.DEVNULL,
    ).decode("utf-8")
    lines = out.strip().splitlines()
    assert len(lines) == 3
    assert lines[0].strip().startswith("P50")
    assert "cloud=2002500" in lines[0]
    assert "hw=2213370" in lines[0]
    assert "+10.5" in lines[0]


# --------------------------------------------------------------------------
# the repo's own selftests, wrapped
# --------------------------------------------------------------------------


def test_kpf_decode_selftest_passes(repo_root):
    """kpf-decode.py ships 86 synthetic selftest cases; run them in CI.

    They return an exit code rather than raising, so the assertion is on rc.
    """
    tool = os.path.join(repo_root, "orin-native", "s1", "kpf-decode.py")
    proc = subprocess.run(
        [os.sys.executable, tool, "--selftest"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
    )
    output = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0, output[-2000:]
    assert "failed=0" in output


def test_mkcpio_selftest_passes(repo_root):
    tool = os.path.join(repo_root, "orin-native", "s1", "mkcpio.py")
    proc = subprocess.run(
        [os.sys.executable, tool, "--selftest"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace")[-2000:]
