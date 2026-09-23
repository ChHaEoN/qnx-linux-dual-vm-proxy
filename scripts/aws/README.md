# `scripts/aws/` — one bare-metal AWS session for an A6 ladder

Tooling for running the A6 ladder on an AWS bare-metal Graviton host, with the
cost and the leak risk designed out rather than cleaned up afterwards.

An earlier form of these files drove the billed session behind
[`results/orin-native-port/20260922T-a6-a1metal-kick`](../../results/orin-native-port/20260922T-a6-a1metal-kick/results.md).
A review then found several failure paths in that form that could have left an
instance running, and a check the operator had done by hand. The committed
versions differ in these ways:

- **Termination on failure.** `launch` and `wait` terminate on any failure, and
  confirm that the termination happened.
- **Reboot-safe self-termination.** The shutdown safety net now survives a
  reboot.
- **Leak scan.** `fetch` refuses a capture in which `leakscan.py` still finds
  something identifying. It is a named pattern list, not a proof: it does not
  look inside a JSON string for a 12-digit account id, and it knows nothing of
  key ids or of any name it was not given.
- **Account names.** Resource names come from the environment instead of being
  written inline.
- **Provenance.** The instance-side scripts and their hashes are copied into the
  record.
- **Host facts.** The host-facts block records the port-to-bridge mapping and
  the L2/L3 cache sharing, which the earlier form did not.

They pass `tests/test_aws_tooling.py`. Those tests drive the real code against
stub `aws`, `ssh` and `scp` programs. The committed versions have **not yet
driven a billed session themselves**.

Why bare metal: non-metal Graviton instances expose no `/dev/kvm`
([ADR-002](../../docs/phase2-topology-decision.md)), and the ladder needs KVM.
This is a test bed for one measurement session, never a runtime host.

| file | runs on | job |
|---|---|---|
| `drive-metal.sh` | the operator's machine (Git Bash or Linux; GNU sed, `git`, Python 3, `aws`) | launch, wait, upload, run each phase, fetch, terminate, verify, clear |
| `userdata.sh` | the instance, at first boot | arm the self-termination (reboot-safe), install QEMU, the compiler and Python |
| `remote-ladder.sh` | the instance | setup, quiesce, launch the guest, the ladder, capture |
| `capture.py` | the instance | the publishable copy, redacted on the host that produced it |
| `leakscan.py` | the operator's machine | refuse a fetched capture that still identifies anything |

## The session, step by step

```bash
cp scripts/aws/.env.example scripts/aws/.env.local   # then fill it in; it is gitignored
```

**Check these before `launch`, while nothing is billed yet.** `launch` validates only
`METAL_KEY_NAME` and `METAL_SG_NAME`; the values below are first read once the instance
is up, so a stale one costs a launched `a1.metal` and the full 15-minute provisioning
wait before `wait` aborts and terminates it.
- The security group still admits **your current address** on 22. A home address moves,
  and an SSH that never connects is indistinguishable from a failed boot from here.
- `METAL_PEM` is set, and is the private key matching `METAL_KEY_NAME`.
- `METAL_REPO_TAR`, `METAL_IFS` and `METAL_DISK_GZ` all exist and `METAL_DISK_GZ` is
  named `disk-qemu.gz`; `upload`, after `wait`, is the first step that reads them.

`run-instances` itself rejects a key pair or security group that no longer exists,
unconfigured credentials, and a `METAL_AMI` that is not in `METAL_REGION` (an AMI id is
region-local, and the default is an `eu-central-1` one). Those cost nothing, but they
leave `$METAL_STATE/token` behind, and every later `launch` refuses the unclean session
state until it is removed by hand (`clear` will not remove it: it waits on a `verify-vol`
pass, and no volume was recorded).

The image and the disk are QNX-derived, so nothing here builds or holds them; the pair
that ran on 2026-09-22 is named with its hashes in
[that record's inputs](../../results/orin-native-port/20260922T-a6-a1metal-kick/results.md).

```bash
bash scripts/aws/drive-metal.sh launch
```

Then the remaining steps, one at a time and in order:
- `wait`, then `upload`;
- `run setup`, `run quiesce`, `run launch`, `run ladder`, `run capture`;
- `fetch`, `terminate`, `verify`, later `verify-vol`, and finally `clear`.

### A liveness session instead (OD14)

This replicates the liveness deadline's two A6 runs. The differences from a
ladder session:
- `METAL_IFS` is `ifs-live.bin`, and the tarball also carries
  `orin-native/edge-llm`.
- Two phases replace `launch` and `ladder`:
  - `run launch-live` boots the guest plainly and checks that :7102 runs the
    2000 ms deadline mode;
  - `run liveness` runs the synthetic demo, then the deadline's cost (`K=12` by
    default).
- Every other step is the same.

On a host with no `tegrastats` the cost run records its GPU checks and window
sampler as not applicable, in its stamp; `TEGRA=0` forces that path on the
Orin, so a rehearsal there runs exactly what the instance will.

## What bounds the cost

- **Self-termination, proven before anything is spent.**
  - The instance is launched with shutdown behaviour `terminate`, and user-data
    schedules `shutdown -h +90` first.
  - It also writes the absolute deadline to disk with a per-boot script that
    re-arms whatever time remains, or powers off at once if the deadline has
    passed. A pending shutdown lives in `/run`, which a reboot empties, and this
    AMI boots with `panic=-1`.
  - `wait` goes on only if a poweroff is armed 61–91 minutes ahead and the
    per-boot re-arm is installed. `upload`, `run` and `fetch` refuse until it has.
- **Every failure between launch and that proof terminates**, and the
  termination is confirmed. Such failures include:
  - EC2 not knowing the new id yet (retried, not fatal);
  - a throttled or failed call;
  - a wrong root volume, no public address, or failed provisioning;
  - a missing or mistimed shutdown.

  A `run-instances` call that fails is followed by a lookup by client token, so an
  instance that started anyway is found and terminated. If a termination cannot
  be confirmed, the script says so and exits 3; it does not record one.
- **After `wait`, a failing step does not terminate.** The instance is left to
  the proven self-termination, or to `terminate`.
- **One instance.** `launch` takes a lock, refuses unclean session state, and
  refuses if anything is already running or pending in the region. A client token
  makes a doubled launch return the same instance.
- **One root volume, read back.** `launch` checks there is exactly one block
  device, that it is the root, and that it is deleted on termination.
  `verify-vol` confirms it is gone.
- **Teardown is verified, not assumed.** `verify` requires nothing running or
  pending in the region, no available (orphaned) volume, and the instance
  `shutting-down` or `terminated`. Billing stops at `shutting-down`; an `a1.metal`
  then stays in that state for about ten minutes.

**What this cannot bound:** a host kernel that hangs without rebooting runs no
timer. Nothing here watches the instance from outside the instance.

The 2026-09-22 session: about 11 minutes billed, about $0.09.

## What keeps identifiers out of the repo

- **Session state outside the repository, enforced.**
  - The instance id, volume id, address and `known_hosts` go to `METAL_STATE`,
    by default `~/.cache/qnx-metal-session`.
  - The script refuses a state or fetch directory inside the repository.
  - On Git Bash `chmod 700` does nothing; the Windows profile's ACL is what
    protects the default location.
- **Redaction on the instance, at capture time.** `capture.py` sends text files
  through `orin-native/gpu-concurrency/redact-aws.sh`.
  - JSON files are published byte-for-byte once every string in them has passed
    the redactor unchanged. Their numbers are never redacted, because the
    account-id mask would rewrite 12-digit KVM counters.
  - The arm files are checked to be identical to what the run wrote.
  - A capture of nothing, or into a used directory, is refused.
- **A scan after the fetch.** `leakscan.py` runs before anything can be copied
  anywhere, and its findings print the shape of a leak, never its value. It
  refuses:
  - AWS resource ids, ARNs and EC2 host names;
  - addresses outside the project's bridge subnet, and MACs other than the
    guest's;
  - UUIDs, 12-digit numbers in text, and JSON that no longer parses;
  - the operator's own key path, key-pair and security-group names, and user
    name.
- **The operator's transcript is redacted too.** Everything `drive-metal.sh`
  prints, `aws` CLI errors included, goes through `red()`, which also masks
  those literal local values.

## What it does not do

- **Publish the guest image or disk.** Both are QNX-derived; they are uploaded to
  the instance and never committed.
- **Make a cloud leg** in this project's sense. QHV needs EL2, and a KVM guest gets
  EL1, so the QNX Hypervisor cannot run here.
- **Choose the instance type for you.** `c7g.metal`, the closer core match to the
  Orin, needs a 64-vCPU quota this account does not have.
