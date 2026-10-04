"""The registered text of every pre-registered harness, pinned by hash (2026-10-04).

A harness under orin-native/gpu-concurrency states its rule, its checks and its prediction in
the comment block above its first `set -u`, written and committed before any run, and most say
in so many words that the text is not to be amended. The code below that line does change: a
kernel renames a function, a board renames an interface, a guard is added. This test is what
lets the code move while the registered text stays byte for byte what it was: one changed byte
above `set -u` fails here.

The pin is the sha256 of the file's bytes before the first "\\nset -u\\n" (CRLF read as LF). It
covers every run-*.sh that has a prediction section or a section on what was known before the
run. A pin is changed only on purpose, in the commit that says why the registered text had to
change, and a new pre-registered harness gets its pin in the commit that adds it:

    python tests/test_preregistered_headers.py        # prints the dictionary below, as it is now
"""
import hashlib
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
MARKS = (b"THE PREDICTION", b"WHAT IS " + b"KNOWN")
SPLIT = b"\nset -u\n"

PINS = {
    "run-arrival.sh": "eff1b72a5a501ad0b4b05efe7dd2c33143948cfecdba28f1d604ccf015f89229",
    "run-bell.sh": "b86c64bb8107095a91ec985e85dba6a93ee5262c9caaea3649f73be9f2d09ee1",
    "run-bellrate.sh": "afe88399ed8ca907a283d47faf8cdf28129c8b67aa5aa0395800d5fbbe489d38",
    "run-bellrobust.sh": "453f5ee7806a30d58fc12c14c44d98981c5586827f00064db6d1259a4c10f33f",
    "run-blockpath.sh": "a2334fee670dbc5bd82fd324380ca4778fbb8401b83677ad6dc7ad979f6d0595",
    "run-boots.sh": "d9e32640742182945191477a396c4194e48e69d97d927924cb4553a76e8a5255",
    "run-boots2.sh": "947c7e8ee079448772cab59f54f96422ef2216dca955439cf24533c90aff6e79",
    "run-bursts.sh": "c62bf2ff5a01d293c9722c34008112eb7e2d1fadde0765a7dbdb2316d112151e",
    "run-caches.sh": "506ef5192d40006fcc9f8844cf4b0dfb24d861457752e54e5e89cff7cd8c2c69",
    "run-clock.sh": "7d8040774020c5eea4a3f92a3b2588141bad475e03979171d1278e3a93427709",
    "run-confine.sh": "933a3b29c40c48027389902b280134f25d03dacb29262fa5d3a1d91e1da7d2d6",
    "run-edge.sh": "a7450ac508d7c479edbccd16b76503f28c578081f4524fdd62d9c8a6d00ddd55",
    "run-free.sh": "158fe0cea7e8f96edc0f592943a3ec5383e0c74db19694153dfcfc791430da53",
    "run-guesttick.sh": "8e731eaa83f0639911872ba5c9054b73c8a5ca9bc65c8a144aefa4f232bc2a8e",
    "run-haltpoll.sh": "df04c34920e1f6b501cf92fa11fafc5047360c9fcb5fc5e50cf152114f7a33bd",
    "run-headless.sh": "151dd9e93842ccf1f888c61b2c81a8c669d0f414f69b4c34fe641ddcf0bb1649",
    "run-ipcbench.sh": "965e74bd3ee13676d6a7832f904019e4ac79b03954c7f413e8ba0b6a22943462",
    "run-irqconf.sh": "15ca178eed5968a82d9b7e305897e866a262adf511a42d06665619372e9248d5",
    "run-listeners.sh": "83c3fd1c6bb5eb16ee520038a2e146e5244267c484019c93163c6a9ad5bbcc6e",
    "run-metal.sh": "ba98058b2022c51bbbd5b153019c3aeb271386fa5e4a3bf5ad06d62f8b6490d6",
    "run-mmio.sh": "f4a85cd24fccb8aac07d65d07c6f8f07661791227fa4db453562ec60cfdfe523",
    "run-mss.sh": "d201a89ebc6f75c4f393a9ce2211d17c4ef52a3777f8fecfe4d4892ccdd3d496",
    "run-natural.sh": "4400ef186a5ad421bdc62d8b41762cb7cdec619d8bacf6198579a09da45781b7",
    "run-offload.sh": "59fb96e957005ad9a4f5b952d15f26c4ca5386ba00981e1afc27a0c00c4efa54",
    "run-partition.sh": "64fb1e0c2ccc4885c5e6e8bfe9ab09f6af9e3e0b1bdb3ffa9aa6568b00460cf5",
    "run-paths.sh": "a1940200a708e67c309718464af25bc2181dbc8a355632945c6e4b43ae788a43",
    "run-pin.sh": "eec286ed9132b5d8c79935e6b6c3c82b4429cc1458ea9391bc0e1ddad3d51985",
    "run-power.sh": "cb82bd4cd751f79c2027521c47bc57ad235fa2ab8364e83a89b5ab0512e66e90",
    "run-queue.sh": "6f62e15efaf7b81891c863806a89fb503b0697f4eac34475b1431dc3f2a2ded4",
    "run-rate.sh": "6bfa9d0f6a89b6b432584f2e755b74b7aaf347fa4435c3fb82eb94c4af4cb68b",
    "run-readpath.sh": "0f39d76e6b7afaf499fa8bad3a3acff376de61658a40b5d28fa550006a8b134b",
    "run-reads.sh": "7f1bba5ad6b10b7ba01904763b9a73f2eb2f48a37ddffcb3e4110a384131ba7d",
    "run-readtime.sh": "e91c68f3f800308289289cbb94e96f5b79fefb7e579c6374a887f80af0c04e1a",
    "run-smp.sh": "8f075a9876e2fb8edeabff4c0120c1155331449f88b76f954f2dec282780cc4c",
    "run-someip.sh": "67d9eedba5d43dc9d3183954bbb4189861b5a60c5d68a5ac13bfe5458be669d2",
    "run-someip0.sh": "853f1ec6597cff2f343cd48f90788e9917fa91bfb36b16d997bfcfdb4b6d63e5",
    "run-someip1.sh": "a17001d30cc1fa5f2611754406d74e628a7b87e3785937a4d81e65a035af44b5",
    "run-spin.sh": "b6392156a9184a5678b215619214b0cdedeed875b11097db8af1b993991a1be8",
    "run-sweep.sh": "9296cdf16e377dbd3ef3df11b3fde23ed73a30104565ba6532f99c4b240d067c",
    "run-tail.sh": "9de4e243171a7e06dcb40ad9f753b917713caf175a2780e6235a941745b2684a",
    "run-tailhost.sh": "63fb6a95784dcad4eea9c62102dcc2325ddd80abc5646fcdd1498d663df2a3e9",
    "run-tailpath.sh": "ff21bb2c084930a4842405cf2e3be5d018711dd3cbcb86dac97ee0c3ea53c17d",
    "run-tick.sh": "3adc21b66d8e6a2a27c14650045821103917592860665b75d803602fa6529c0c",
    "run-tjphase.sh": "8da024c458cd1762a28fac7be7eaf98be446877a5f85d0c0b7de69036646b814",
    "run-trace.sh": "005b547cf5df1daa65ccccc777d2e60af37c171abea1e9c213c1c4d8aec9fb24",
    "run-trace2.sh": "0c1d6dd5b82c12d0b98ee1d29693587a1b177e8163b879473f2fb8bca4f19928",
    "run-uevent.sh": "93378d5101e78364b7824d6657de2b7374013e4c8b302116fe69a80502a032b6",
    "run-unmask.sh": "e57bff439d2807d932972d6c0261f531d823f9a2cb4850e7e6df1be967dba6e0",
    "run-vcpupin.sh": "d6c12a2842229db4567859646e547912882a9b11d8982f6d556a7cca4272f7e9",
    "run-waitfor.sh": "e18445740f34b5890c424fa30add1dd50f7ba5bbaf44e3eac1a3d8da6e9bcf21",
    "run-walks.sh": "b25976212c06614709d9aadabf1843585d40103107767dc5a4954393a4230dfc",
    "run-wifi.sh": "14af75e246d53cf71f20648bb4990f9ae815faf5651711b007744d5cca0ad19b",
}

# The harnesses whose code the 2026-10-04 change edits below their headers (the HZ guard, the
# Wi-Fi helper, the one CONFIG_HZ reader). Each has to be pinned, whatever its header says.
EDITED_2026_10_04 = (
    "run-tick.sh", "run-guesttick.sh", "run-partition.sh", "run-boots.sh", "run-boots2.sh", "run-irqconf.sh",
    "run-wifi.sh", "run-tailhost.sh", "run-tjphase.sh", "run-metal.sh", "run-bell.sh", "run-bellrate.sh",
    "run-edge.sh", "run-free.sh", "run-ipcbench.sh", "run-mmio.sh", "run-offload.sh", "run-paths.sh", "run-pin.sh",
    "run-readtime.sh", "run-someip.sh", "run-someip0.sh", "run-someip1.sh", "run-spin.sh", "run-trace.sh",
    "run-trace2.sh", "run-unmask.sh")


def header(path):
    """(the bytes before the first `set -u` line, whether that line exists)."""
    with open(path, "rb") as f:
        raw = f.read().replace(b"\r\n", b"\n")
    head, sep, _rest = raw.partition(SPLIT)
    return head, bool(sep)


def registered():
    """Every run-*.sh whose header states a prediction or what was known before the run."""
    out = []
    for n in sorted(os.listdir(GC)):
        if n.startswith("run-") and n.endswith(".sh"):
            head, found = header(os.path.join(GC, n))
            if found and any(m in head for m in MARKS):
                out.append(n)
    return out


def digest(name):
    return hashlib.sha256(header(os.path.join(GC, name))[0]).hexdigest()


@pytest.mark.parametrize("name", sorted(PINS))
def test_a_registered_header_is_byte_for_byte_what_was_registered(name):
    head, found = header(os.path.join(GC, name))
    assert found, "%s has no `set -u` line of its own: where its registered text ends cannot be told" % name
    assert hashlib.sha256(head).hexdigest() == PINS[name], (
        "%s: the text above `set -u` is not what was registered. A registered rule, check or prediction is not "
        "amended; if this change is meant, say why in the commit and update the pin." % name)


def test_every_registered_harness_is_pinned_and_every_pin_has_its_harness():
    assert registered() == sorted(PINS), sorted(set(registered()) ^ set(PINS))
    assert set(EDITED_2026_10_04) <= set(PINS), sorted(set(EDITED_2026_10_04) - set(PINS))


def test_the_pin_sees_one_changed_byte_and_only_above_set_u(tmp_path):
    """The check checked: a byte changed in a copy's header moves the hash, and a byte changed
    below `set -u` does not."""
    src = os.path.join(GC, "run-tick.sh")
    with open(src, "rb") as f:
        raw = f.read().replace(b"\r\n", b"\n")
    cut = raw.index(SPLIT)
    assert b"tick_sched_timer" in raw[:cut], "the registered check names the handler the kernel had then"
    for at, same in ((raw.index(b"tick_sched_timer"), False), (cut - 1, False), (cut + len(SPLIT) + 5, True)):
        p = tmp_path / ("copy-%d.sh" % at)
        p.write_bytes(raw[:at] + bytes([raw[at] ^ 1]) + raw[at + 1:])
        got = hashlib.sha256(header(str(p))[0]).hexdigest()
        assert (got == PINS["run-tick.sh"]) is same, at


if __name__ == "__main__":
    print("PINS = {")
    for _n in registered():
        print('    "%s": "%s",' % (_n, digest(_n)))
    print("}")
