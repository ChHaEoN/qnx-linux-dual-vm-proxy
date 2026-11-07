# `scripts/aws/` — one bare-metal AWS session for an A6 ladder

KVM here boots our startup-qemu-virt; this is not a QNX-supported
configuration, and no timing claim attaches to the boot.

Tooling for running the A6 ladder on an AWS bare-metal Graviton host, with the
termination checks and redaction applied as the session runs.

An earlier form of these files drove the billed session behind
`20260922T-a6-a1metal-kick` (held locally under NC QDL v7 4.6(i)).
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
  any name it was not given. A certificate id or a canonical user id that
  stands alone looks like a sha256 and is such a name. A secret access key and
  a session token have no shape either, and an IAM unique id is known by four
  prefixes only. The redactor on the instance has no rule for an IoT endpoint,
  a PEM block, an e-mail address or an IAM id: a bare-metal capture that holds
  one is refused at the fetch, not masked. A git remote in its SSH form
  (`git@<host>:owner/repo.git`) has an e-mail address's form, so a capture
  that records one is refused as well. So is one that holds a block of 64 or
  more base64 characters that is neither hex nor a path nor a PEM block's
  body (`undecoded data`), or something found only once its percent escapes
  are decoded: what encoded text holds is seen by no pattern. Shorter blocks,
  the URL-safe alphabet and any other encoding are not seen at all.
- **Account names.** Resource names come from the environment instead of being
  written inline.
- **Provenance.** The instance-side scripts and their hashes are copied into the
  record.
- **Host facts.** The host-facts block records the port-to-bridge mapping and
  the L2/L3 cache sharing, which the earlier form did not.

`tests/test_aws_tooling.py` drives the code against stub `aws`, `ssh` and
`scp` programs. The tooling has also driven billed sessions; their measured
results are held locally. Neither the tests nor those sessions establish a
cost bound for a host whose kernel stops running the termination timers.

Why bare metal: non-metal Graviton instances expose no `/dev/kvm`
([ADR-002](../../docs/phase2-topology-decision.md)), and the ladder needs KVM.
This is a test bed for one measurement session, never a runtime host.

| file | runs on | job |
|---|---|---|
| `drive-metal.sh` | the operator's machine (Git Bash or Linux; GNU sed, `git`, Python 3, `aws`) | launch, wait, upload, run each phase, fetch, terminate, verify, clear |
| `userdata.sh` | the instance, at first boot | arm both self-termination nets (reboot-safe), install QEMU, the compiler and Python |
| `remote-ladder.sh` | the instance | setup, quiesce, launch the guest, the ladder, capture |
| `capture.py` | the instance | the publishable copy, redacted on the host that produced it |
| `leakscan.py` | the operator's machine | refuse a fetched capture that still identifies anything |

## The session, step by step

```bash
cp scripts/aws/.env.example scripts/aws/.env.local   # then fill it in; it is gitignored
```

A `METAL_*` value exported in the environment wins over the file's. Pass a
session's own `METAL_REPO_TAR` that way. `METAL_TYPE` (default `c7g.metal`) names
the bare-metal instance type to launch.

**Check these before `launch`, while nothing is billed yet.** `launch` validates only
`METAL_KEY_NAME`, `METAL_SG_NAME`, the shape of `METAL_QEMU_PKG` and (SDV)
`METAL_VOLUME_SIZE` and `METAL_SESSION_MIN`; the values below are
first read once the instance is up, so a stale one costs a launched bare-metal instance and the
full 15-minute provisioning wait before `wait` aborts and terminates it.
- The security group still admits **your current address** on 22. A home address moves,
  and an SSH that never connects is indistinguishable from a failed boot from here.
- `METAL_PEM` is set, and is the private key matching `METAL_KEY_NAME`.
- `METAL_REPO_TAR`, `METAL_IFS` and `METAL_DISK_GZ` all exist and `METAL_DISK_GZ` is
  named `disk-qemu.gz`; `upload`, after `wait`, is the first step that reads them.
- `METAL_QEMU_PKG`, when the session expects one QEMU package build on both hosts, is the
  other host's `qemu-system-arm` version as its `dpkg-query` prints it that day, epoch
  included. Export it for the session, as `METAL_REPO_TAR` is passed, and do not keep it
  in `.env.local`: a value left there is the last session's. `launch` refuses one that is
  not a package version; whether it is the right one is first known at `run setup`, on
  the billed instance (see "What `run setup` says about the host").

`run-instances` itself rejects a key pair or security group that no longer exists,
unconfigured credentials, and a `METAL_AMI` that is not in `METAL_REGION` (an AMI id is
region-local, and the default is an `eu-central-1` one: Canonical's public Ubuntu 24.04
arm64 server image, pinned by id in `drive-metal.sh`). Those cost nothing: `launch` asks
EC2 by its client token whether anything started anyway, and when nothing did it removes
the token and the minutes it had recorded, so the next `launch` is not refused.

The image and the disk are QNX-derived, so nothing here builds or holds them; the pair
used on 2026-09-22 is named with its hashes in the inputs of record
`20260922T-a6-a1metal-kick` (held locally).

```bash
bash scripts/aws/drive-metal.sh launch
```

Then the remaining steps, one at a time and in order:
- `wait`, then `upload`;
- `run setup`, `run quiesce`, `run launch`, `run ladder`, `run capture`;
- `fetch`, `terminate`, `verify`, later `verify-vol`, and finally `clear`.

`upload` runs once per session (SDV). Once the session state holds `uploaded` it refuses:
`setup` verified that upload and does not run again, so a second one would leave the first
tarball's repository on the instance beside the second's inputs. A changed input needs a new
session. An upload that failed part-way never wrote `uploaded`, and can be run again.

### The session's minutes (SDV Phase 7 WP6-T)

A session runs for 90 minutes unless `launch` is given others. **`METAL_SESSION_MIN`** is the
session's minutes: 90 when unset or empty, otherwise a whole number from 60 to 180 in plain decimal
digits (no sign, no leading zero, no space).
- `launch` alone reads it, and refuses any other value before its first `aws` call, with nothing
  written to the session state. It also refuses there a `userdata.sh` that does not have exactly one
  line `MIN=90`.
- It sends `userdata.sh` with that one line made `MIN=N` and every other byte as it is, so the
  default sends `userdata.sh`'s own bytes. The rendered copy is a file in the session state, removed
  as soon as `run-instances` returns, whatever it did.
- It records the minutes in the session state as `session_min` (one line, the number) before
  `run-instances`, and prints `session minutes: N`, with `(not the default 90)` on the same line for
  any other number. A state that holds `session_min` is not clean, as for the other session files.
- Every later step reads the state's `session_min`, never the environment. `wait` holds the
  monotonic timer to more than N-30 minutes and at most N minutes, to the second, and the wall-clock
  poweroff to more than N-30 minutes and at most N+1. A state without `session_min`, from a session
  launched before there was one, is a 90-minute session. A `session_min` that is not such a number
  is a failure of `wait`, which terminates the instance.
- Export it for the session, as `METAL_REPO_TAR` is passed, and do not keep it in `.env.local`: a
  value left there would be every later session's.
- The harnesses' stop point follows the deadline. The vss harnesses' `stop_at` and `wait-run`'s
  give-up point are counted back from the deadline `userdata.sh` writes, so a longer session moves
  them later by as much, with no change to any harness or to the deadline library.
- **The session budget** applies to the session's worst case: its minutes at the instance's rate.
  Check that budget before launch; a longer session needs its own budget review.

The tests drive all of this against stub programs. They show nothing about an instance: not that a
session of other minutes arms its nets for them there, nor what such a session costs.

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

### A metal session instead (2026-09-25)

This runs `run-metal.sh`: the natural-state confinement comparison and the tick
bin, on this host's own cores and HZ.
- `METAL_IFS` is `ifs-stamp.bin`.
- One phase replaces `launch` and `ladder`: `run metal` boots the guest and
  runs the harness **in the same SSH session**. The harness confines every
  other session scope to the cores QEMU and the probe do not use, so a guest
  booted by an earlier phase would be confined with them.
- `K` defaults to 40. Every other step is the same.

### A harness session instead (2026-09-27)

This runs several harnesses that boot their own guests, each on its own image, in one session:
`run-someip.sh`, `run-someip0.sh`, `run-someip1.sh`, `run-trace.sh`, `run-trace2.sh`,
`run-haltpoll.sh` and (2026-09-29) `run-bell.sh` on `ifs-bell.bin`, `run-paths.sh` on `ifs-paths.bin` (at `K=18` only: the phase does not pass `SMOKE`), and `run-mmio.sh` and `run-bellrate.sh` on `ifs-bell.bin`, and two that boot more than one image: `run-unmask.sh` (`IMG_UA=ifs-unmask-a.bin IMG_UB=ifs-unmask-b.bin`; it reads no `IMAGE=`) and `run-bellrobust.sh` (`IMAGE=ifs-bell.bin IMG_R=ifs-robust.bin IMG_UA=ifs-unmask-a.bin`).
- `METAL_IFS` is the first image. `METAL_IFS_EXTRA` holds more, as space-separated paths.
  `upload` sends them all, and `setup` checks each against its sha256.
- One call per harness:
  `LADDER_ENV="HARNESS=run-trace2.sh IMAGE=ifs-trace.bin" K=12 drive-metal.sh run harness`.
  - The phase refuses a harness outside that list, and an image this session did not
    upload.
  - `IMG_B=`, `IMG_R=`, `IMG_UA=` and `IMG_UB=` words name a multi-image harness's images, each
    one this session uploaded. Before it makes `rec/<name>`, the phase refuses: no `LADDER_ENV`; a
    word it does not read, or one with no value; a word given twice; an `IMG_` word it does not
    take for that harness (only these two take any; every other harness's image is `IMAGE=`, even
    one that reads `IMG_B`); a `K` with a leading zero, or 0; and a multi-image harness missing one
    of its images. An omitted `IMG_R`, `IMG_UA` or `IMG_UB` would fall back to the harness's own
    `$HOME/output` default, absent here, and the run would fail at its preflight; an omitted
    `IMG_B` would be the session's first image, and the run would go on with it. Either way it
    would use up that harness's one run per session.
    `run-unmask.sh` needs two different images and `K` a multiple of 4; `run-bellrobust.sh` takes
    no `K`.
  - Both of those list a1.metal among what their pre-registrations do not test, so a run here is a
    replication outside them, not part of either. `run-unmask.sh`'s stated reason (one `IMAGE=`,
    and not in this list) predates these words.
  - It writes into `rec/<name>` (`trace2` here), and runs each harness once per session.
- The SOME/IP harnesses build vsomeip on the instance first, once per session. The older
  `someip` phase does the same. The build's packages are the versioned Boost 1.74 ones, the
  four the Orin's provisioning script installs: on Ubuntu 24.04 the plain `-dev` names are a
  later Boost. `build-vsomeip.sh` runs its build under a memory cap, so the phase passes a
  job count and a cap sized to the host: the cap is half the host's memory, with the Orin's
  share of it for each job and never more jobs than cores.
- Every other step is the same, and `capture` takes the session once any harness has
  finished. `run-bellrobust.sh` keeps no `lat-*.json`: its exchange sets are `ex-*.json` from the
  same probe, held to the same byte-for-byte rule, and a `scenarios.log` exchange-set line also
  counts, so a run in which every set that ran was aborted is still captured.

### A vss session instead (plan Phase 3)

This drives the VSS slice's two harnesses on the instance. What differs from a harness session:

- **The tarball** also carries `sdv`, built in Git Bash from the commit the session runs:
  `git archive <commit> -- orin-native/gpu-concurrency ipc-test scripts/setup-bridge.sh sdv`.
  The harness phase refuses a vss harness when the tarball lacks `sdv/stack/step3.py` or
  `orin-native/gpu-concurrency/lib-vss-deadline.sh`.
- **`METAL_IFS`** is `ifs-vss.bin` for `PLAN=v1` or `PLAN=v2`, and `ifs-vss-carla.bin` for
  `PLAN=carla` (SDV Phase 7).
  - `ifs-vss-carla.bin` is a private build (Phase 7 WP4b) and is never in any branch.
  - Its guest's `vss rules:` lines must list profile 3, or the suite's preflight refuses
    `PLAN=carla` and spends its one run.
- **`METAL_VOLUME_SIZE=32`.** The root volume's size in whole GiB, from 16 to 64; 16 when unset.
  `launch` refuses any other value before its first `aws` call. After the launch it reads the size
  back from EC2, and a different size is a launch failure: the instance is terminated and the
  termination confirmed. The volume id is recorded first, so `verify-vol` can see it go.
- **`METAL_FILES`**: the upload bundle's files, as space-separated paths.
  - Before it sends anything, `upload` refuses a name outside `[A-Za-z0-9._-]`, a name given twice,
    an image's or the disk's name, and a path that is not a readable file.
  - It sends them to `~/a1/in`, and writes a `file NAME SHA256` line per file into `inputs.txt` and a
    `FILES=` line into `inputs.env`.
  - `setup` checks each against its hash, names them in its "artefacts verified" line, and copies
    `bundle.json` into `rec/tooling/`.
  - When one of them is `bundle.json`, its `commit` must be the tarball's (`git get-tar-commit-id`).
    `upload` refuses a mismatch, a `bundle.json` without a commit, and a tarball that carries none,
    before it sends anything; otherwise the setup harness would find it only on the instance.
- **`quiesce` needs `setup` first**, on this tooling and in every session, A6 ones included.
  - After the apt timers it runs `platform-quiesce.sh stop` with one fixed state path,
    `~/a1/platform-quiesce.state`, then `/usr/local/bin/k3s-killall.sh` as root when that is
    executable.
  - Their outputs and exit statuses go to `rec/quiesce.txt`, which heads every later
    `host-before.txt`.
  - A stop that refused before it changed anything (exit 3) is recorded, and the session goes on.
    Any other non-zero status of either is fatal.
  - Nothing restores the units: an instance is discarded. A rehearsal host that lives on needs
    `platform-quiesce.sh restore ~/a1/platform-quiesce.state` by hand.
- **Two harnesses, run detached.**
  - `run-vss-setup.sh` takes `IMAGE=` alone. `run-vss-suite.sh` takes `IMAGE=` and `PLAN=v1`,
    `PLAN=v2` or `PLAN=carla`, in a later login than setup's, so that the docker group applies:
    `LADDER_ENV="HARNESS=run-vss-suite.sh IMAGE=ifs-vss.bin PLAN=v1" bash scripts/aws/drive-metal.sh run harness`.
    Both refuse `K` and every `IMG_` word, and `PLAN=` is the suite's alone. `IMAGE=` must be the
    session's `METAL_IFS`: another uploaded image would fail the harness's own check later, and
    spend its one run.
  - **`PLAN=carla`** (SDV Phase 7) runs the suite's plan over the CARLA pair, in a session whose
    `METAL_IFS` is `ifs-vss-carla.bin`. The phase passes the word through. The suite's own
    preflight refuses it when the profiles setup's guest listed in its `vss rules:` lines do not
    include 3, and that refusal spends the suite's one run.
  - **`VSS_HOST=`** (2026-10-17), optional on either harness, is the host mode the harness gets. The
    driver gives it: `launch` records the type it launched, and `run harness` adds that type's word to
    a vss harness's `LADDER_ENV` (`a1.metal`: `a1-metal`, `c7g.metal`: `c7g-metal`, the default type),
    refuses a word that is not the type's, and refuses a vss harness on a type with neither. On the
    instance, no word is `a1-metal`, as before (a state from before the type was recorded passes the
    words as given). `c7g-metal` is the a1.metal path with step 3's role `c7g-metal` and the mode in
    `setup.json` and `suite.json` (the harnesses' headers, THE MODES). The phase refuses `orin` and any
    other value, and the word on an A6 harness. It keeps setup's word in `~/a1/vss-host`, outside
    `rec`, and refuses a suite whose word is not setup's: the suite's own preflight would refuse that
    setup and spend its one run. The word is checked against the type the driver asked EC2 for;
    nothing reads the type on the instance.
  - Before it makes anything, the phase refuses a vss harness:
    - without `rec/quiesce.txt`;
    - when `~/a1/inputs.env` is no longer the copy `setup` verified and kept in
      `rec/tooling/inputs.env` (an upload after `setup`);
    - while `rec` holds an A6 record, any directory but `tooling/`, a vss stem, or `setup`'s own
      `ladder/` while it is empty. A vss capture publishes by its whitelist and would leave that
      record out, so a vss session runs no A6 harness, before a vss harness as well as after;
    - for the suite, unless `rec/vss-setup` has `done` and a last status line of `status=DONE`:
      a suite started too early would spend its one run on a preflight failure.
  - It then writes the session marker, makes `rec/vss-setup` (or `rec/vss-suite`) and its
    `host-before.txt`, and starts the harness under `setsid nohup` with all of the runner's output
    in `detach.log`. So this ssh session ends at once. One run per harness per session still holds.
  - The runner's `run.log` is the proof that it started: the runner opens it only once its own
    checks passed. When it appears, the phase prints `started` and returns 0. When it has not
    appeared after a bounded wait, the phase sends TERM to the runner's process group (the runner
    leads its own under `setsid`), prints `detach.log`, removes the stem directory it made, so that
    it can be run again, and fails. The session marker stays.
  - The detached runner and the harness run with SIGPIPE, SIGHUP, SIGINT and SIGQUIT ignored: bash
    ignores INT and QUIT for a command it starts in the background with no job control, and
    `nohup` and the runner's trap ignore HUP and PIPE. Whatever the harness runs directly inherits
    all four. A unit under its cap starts with only SIGPIPE of them ignored, because `timeout`
    catches the others before it forks. The caps' TERM and KILL are not ignored.
  - The runner runs the harness into `run.log`. If the harness exits 0 and its status file's last
    line is `status=DONE` or `status=TIMEOUT …`, the runner writes `host-after.txt`. Otherwise it
    appends `status=FAILED rc=N` and writes none. Either way it syncs and touches `done`.
- **`wait-run`**, after each harness:
  `LADDER_ENV="HARNESS=run-vss-setup.sh" bash scripts/aws/drive-metal.sh run wait-run`, run as a
  background task with no tool timeout.
  - It reads only `HARNESS=`. It blocks in that one ssh session, sleeping on the instance and never
    logging in per look, until `done` exists or the give-up point (below) has passed.
  - It prints the last status line, whether `done` exists, and `run.log`'s last 30 lines. It exits 0
    for DONE and TIMEOUT, 2 when it gave up, and 1 otherwise.
  - After a disconnect, run it once more by hand, never in a loop.
- **The deadline contract**, in `orin-native/gpu-concurrency/lib-vss-deadline.sh`, which the vss
  harnesses source. These are design values, not measured ones.
  - The deadline is the poweroff time `userdata.sh` writes to `/var/lib/qnx-metal-deadline`.
    `stop_at` is 25 minutes before it.
  - At each check point a harness stops when now has reached `stop_at`: a clean stop, a
    `status=TIMEOUT` line, the units not run listed, exit 0.
  - Each unit runs under `timeout --kill-after` thirty seconds, with a cap of `stop_at` plus
    10 minutes less now. `vss_capped` returns the cap's status when it fires, so a harness under
    `set -e` calls it as `rc=0; vss_capped CMD... || rc=$?` and then tests `vss_cap_fired "$rc"`:
    called bare, a fired cap would end the harness with no status line and no clean stop.
  - Every cap ends at the same moment, `stop_at` plus 10 minutes. `vss_cap_fired` takes 124 or 137
    for the cap's own only from then on. Before it, that status is the command's own, such as an
    OOM kill's 137.
  - A cap's TERM goes to the unit's process group. Its KILL, thirty seconds later, goes out only
    while the unit's direct child still lives, and then to the whole group. Once that child has died
    of the TERM, timeout returns 124 at once, and whatever in the group ignored the TERM (the docker
    CLI of a container whose PID 1 ignores it) outlives the cap. The harness's clean stop removes
    those it knows of, the containers, and also stops a QEMU still shutting down.
  - `wait-run` gives up at `stop_at` plus 12 minutes, 13 minutes before the deadline.
- **The session marker**, `~/a1/vss-session`, outside `rec`, so it is never captured. Once a vss
  harness has started, Docker may have run on this host.
  - So the harness phase refuses every A6 harness of its list by name, and `launch`, `ladder`,
    `launch-live`, `liveness`, `launch-stamp`, `stamp`, `metal` and `someip` refuse at their first
    line.
  - lib-measure.sh's stamp refusal while dockerd runs outside cores 3 and 5 is a second,
    independent guard.
- **`capture`** takes a vss record when a vss stem (`rec/vss-setup`, `rec/vss-suite`) has `done`
  and a terminal status line: DONE, TIMEOUT or FAILED.
  - A FAILED stem has no `host-after.txt` and is packed all the same, for its diagnostics. Its
    status line and `capture.log` say what it is, so it is not read as a whole record.
  - While a vss stem has no `done`, its harness may still be running, and `capture` refuses. Past
    `wait-run`'s give-up point it packs that stem as it stands, named INCOMPLETE in `capture.log`.
    Without a readable deadline it refuses.
  - `capture.py`'s evidence for a vss record is a stem whose last status line is DONE, with its own
    result file (`raw/setup.json`, `raw/suite.json`); a TIMEOUT or a FAILED stem, with or without
    one (a missing result file is noted); or an INCOMPLETE one.
  - A whitelist replaces the whole-tree walk. Nothing under an `in/` or `bin/` directory is
    published, and neither is `scenario.lock`, a raw `docker info` or `inspect`, or anything else
    unlisted (an A6 harness's directory in the same `rec` included). Each file left out is named in
    `capture.log`.
  - A JSON file, or a JSONL line, that does not parse refuses the capture, except in a stem that did
    not end whole (TIMEOUT, FAILED, INCOMPLETE or NO STATUS), where a cap, a kill or a harness still
    writing may have cut it short: there the file is left out and named. A JSONL file's last line is
    judged first, in any stem: with no newline, one that does not parse or decode is a torn write,
    dropped and noted.
  - A file the walk listed and the read cannot open, removed meanwhile by a harness still running
    or unreadable, is left out and named, and the capture goes on. Every file is read once, and
    what is published is the bytes that were read and checked.
  - A text file, the bridge log's text lines included, also loses every IPv6 address after the
    redactor, by the JSON strings' rule. A text file that did not end in a newline is published
    without one, so a line cut short still reads as cut.
  - The report `capture.log` also goes into `pub.tgz`, through the redactor and the IPv6 rule. It
    holds how each stem ended (a FAILED stem's line quotes the harness's own last status line too),
    what was left out, and the torn JSONL lines dropped. It names the substitutions per file that had
    any, then their totals: the 12-digit and the IPv6 ones in each text file, and every mask written
    into a JSON string, by kind.
- **`run-vss-setup.sh`** (plan Phase 3 WP4) brings the instance up for the suite. Its header lists its
  thirteen steps, each behind the deadline's check point and under its cap.
  - It boots the guest and smokes `:7100` before and after Docker. Of each smoke it keeps the exit
    status and the bad and rej counts, and nothing else of the probe's output.
  - It installs Docker with the containerd image store, then loads and pulls the slice's images and
    verifies them with `bundle.py`. It builds the host venv, loads vcan and stages the inputs in
    `~/a1/sdv`. pip keeps its download cache in the session user's `~/.cache/pip`: outside the
    record, never captured.
  - It runs every image's SIGILL probe, then applies the thirty-minute rule.
  - Its record is `rec/vss-setup/raw`: `setup.json`, which holds the skip list, and the other files
    on the whitelist. Every docker, iptables and kernel-log call runs under `sudo -n`.
  - Vcan comes from `linux-modules-extra-$(uname -r)` when apt has a candidate for it. With none (an
    AMI's kernel the archive has no extra package for), it comes from the running kernel's own
    modules, as in the Orin mode, and `setup.json` says so (`facts.vcan.source`: `running-kernel`).
  - Vcan that cannot be had either way, or a probe that does not pass, puts the modes that need it
    into the skip list. A probe that outlives its bound is ended by removing its container.
  - Whatever its guest answers, setup goes on. Its close says, in the lines `wait-run` prints, the
    guest's verdict and whether the suite will take this setup.
  - It fails only when it cannot go on: in the preflight, the Docker install or its store, the load,
    the pulls, the venv or the staging, each `status=FAILED at=<step>`. A step that exits non-zero for
    any other reason ends the same way, and so does a harness that stops without a status line: its
    EXIT trap records "the harness stopped unexpectedly". No readable deadline file is
    `status=FAILED at=preflight`, and a `setup.json` that cannot be written at the end is
    `status=FAILED at=close`.
  - At every stop it records whether its sweep could show the guest stopped and the probe containers
    gone. When it could not, `setup.json` holds `verified` false under `facts.stop`, with why, and
    `run.log` says so. The status line stays as it was.
- **`run-vss-suite.sh`** (plan Phase 3 WP5) runs the plan's step-3 calls against the guest. Its
  header gives the plans and the order of each run.
  - `PLAN=v1` is replay `honest`, then broker `honest`. `PLAN=v2` is the six specs in broker, then
    in replay with `injected-stop` once more, then in can; then `compare --modes broker replay`, the
    exit, and a compare over all three modes only when every can run finished. `PLAN=carla` is
    `v2`'s units and compares over the CARLA pair (SDV Phase 7).
  - Its preflight refuses: a `PLAN` other than `v1`, `v2` or `carla`, a login without the docker group,
    a setup that has no `done` or did not end `status=DONE`, and a QEMU that already runs. Under
    `PLAN=carla` it also refuses a recording without the log its manifest line names, and a setup
    whose guest's `vss rules:` profiles do not include the recordings' profile, 3 (or that recorded
    none).
  - It also refuses a setup whose guest booted but did not answer on `:7160`, had no `vss rules:`
    line that held, or named a catalog other than the bridge's. The suite boots the same image
    against the same `images.json`, so it could not judge a run.
  - Each run boots the guest afresh, with its own console under `rec/vss-suite/raw/guest`. It then
    opens and closes one connection to `:7160` with no bytes, as the readiness check, and makes one
    `step3.py run` call with its own `--name NN-<spec>-<mode>`, from `~/a1/repo` with the venv's
    python. QEMU is stopped after every boot, a failed one included.
  - A mode in setup's skip list is listed, not run. A run that fails its gates, or a guest that does
    not boot or answer, is recorded, and the suite goes on.
  - If a run's guest does not answer before any run's guest has, the rest of the plan is listed
    instead of booted.
  - Its one real failure is a preflight refusal, `status=FAILED at=preflight`. Two more FAILED lines
    exist: `status=FAILED at=record` when `suite.json` cannot be written at the end, and
    `status=FAILED at=<unit>` when the harness stops without a status line: its EXIT trap records
    "the harness stopped unexpectedly".
  - At every stop, `DONE` included, it stops a QEMU it launched and, after any step-3 call, removes
    every container labelled `sdv.stack.run`. When those cannot be listed it removes the stack's own
    container names. A QEMU that outlived a run's KILL is tried once more there. It records the stop
    unverified (`verified` false under `stop`, with why) when it could not list the containers, a
    removal failed, or a QEMU still runs. `run.log` says so, and the status line stays as it was.
  - Its record is `rec/vss-suite/raw`: `suite.json`, the consoles, and step 3's own directories
    under `runs/`.

The tests drive all of this against stub harnesses and stub `setsid`, `sudo`, `timeout` and
`platform-quiesce.sh`, and run `capture` on a fake vss record of documentation values.
`tests/test_vss_harness.py` runs both vss harnesses themselves against stubs of every command they
call, a stand-in `step3.py` with the real one's arguments, and a stand-in guest `:7160`.
They show nothing about an instance. That a real disconnect leaves a detached harness running rests
on the `setsid nohup` precedent in `launch-qnx-kvm-bridged.sh` and on a rehearsal in WSL with a real
`setsid` and a stand-in harness; no instance has shown it. What a real vss record holds is for the
capture rehearsal on the PC.

### An OTA drill session (SDV plan Phase 6)

This is a vss session whose second harness is `run-ota-drill.sh`, the OTA drill's: the drill's images
come by the session's tar, the updater runs as a transient unit, the drill's
six steps are local spool records, and no guest or bridge runs beside it. The harness is
host-neutral: the instance is `METAL_TYPE`'s and the role is `VSS_HOST`'s. What differs from a vss
session:

- **`METAL_TYPE` and `VSS_HOST` go together**: `c7g.metal`, the default type, with `VSS_HOST=c7g-metal`,
  or `METAL_TYPE=a1.metal` with `VSS_HOST=a1-metal`. `run harness` adds the type's word to
  `run-vss-setup.sh`'s call by itself, but not to the drill's, so give it there by hand. The phase
  refuses a drill whose word is not setup's (no word is `a1-metal` on either side), before it makes
  anything.
- **`METAL_IFS=ifs-vss.bin`**: setup boots it for its smokes; the drill boots no image.
- **The tarball** is the vss form (above), from a commit that has `sdv/drill`: the phase refuses the
  drill when the tarball lacks `sdv/drill/drill.py`.
- **`METAL_FILES`**: the slice's upload bundle, as for a vss session, and the drill's three files:
  - `drill-images.json`, the repo's `sdv/drill/drill-images.json` from the same commit, byte for byte;
  - `sdv-drill.tar`, `build_drill.py save`'s one `docker save` of the three pinned arm64 IDs, the
    session's transport. The harness hands it whole to `drill.py manifest --tar`,
    which checks it against the pins and splits it into one tar per version, because the updater's
    tar transport loads a tar of one image;
  - `sdv-drill.tar.sha256`, two lines: the tar's sha256 as `sha256sum` prints it, `<64 hex>  sdv-drill.tar`
    (in binary mode, Git Bash's, `<64 hex> *sdv-drill.tar`, which is taken too), then `commit <40 hex>`,
    the commit the tar was built at. That commit must be the tarball's (`git get-tar-commit-id`).

  `upload` puts all of them in `~/a1/in`. `run setup` checks every file's hash there and then moves the
  drill's three to `~/a1/drill-in`, because `run-vss-setup.sh`'s preflight runs `bundle.py verify` on
  `in/`, which refuses a file that `bundle.json` does not list. The harness phase gives the drill
  `DRILL_IN=~/a1/drill-in`.
- **The steps**: `launch`, `wait`, `upload`; `run setup`, `run quiesce`;
  `LADDER_ENV="HARNESS=run-vss-setup.sh IMAGE=ifs-vss.bin" bash scripts/aws/drive-metal.sh run harness`
  and its `wait-run`; then, in a later login,
  `LADDER_ENV="HARNESS=run-ota-drill.sh VSS_HOST=c7g-metal" bash scripts/aws/drive-metal.sh run harness`
  and `LADDER_ENV="HARNESS=run-ota-drill.sh" bash scripts/aws/drive-metal.sh run wait-run`; then
  `run capture`, `fetch`, `terminate`, `verify`, later `verify-vol`, and `clear`. `METAL_VOLUME_SIZE=32`.
- **The budget** is checked before launch against the chosen session length and host rate.
- **The harness phase** takes `run-ota-drill.sh` as a vss harness: detached, under the session marker
  and the A6 refusals, once per session, into `rec/ota-drill`. It takes `VSS_HOST=` and nothing else:
  `IMAGE=`, `PLAN=`, `K` and every `IMG_` word are refused. Like the suite, it is refused unless
  `rec/vss-setup` has `done` and a last status line of `status=DONE`. Neither it nor the suite starts
  while the other still runs (its stem without `done`): they would share the host's Docker and stack.
- **`run-ota-drill.sh`** (its header has the whole of it):
  - Its preflight refuses, first and before it touches `drill-work` or the record, a `drill-work` in
    which an earlier run began its units (a start by hand: the phase starts the drill once per
    session); its status line is all it writes. Then it refuses a
    login without the docker group; a setup that has no `done`, did not end `status=DONE`, ran in
    another host mode, or skipped broker or can (the drill needs `vcan0`); a QEMU that runs; a drill
    file missing from `inputs.env`'s `FILES` or of another hash; a sum file that does not name the
    tar's hash, or whose commit is not the tarball's; a `drill-in/drill-images.json` that is not the
    repo's, or that names no pin; a tar whose `index.json` does not list exactly those pins' IDs (the
    first check `drill.py manifest` makes of the save); and anything setup should have left that is
    missing. Either role is refused on a host that L4T's release file or an NVIDIA device tree marks
    as a Jetson.
  - Then, each behind the deadline's check point and under its cap: the drill's tar loaded with
    `sudo -n docker load` and each pin's config digest proved from a `docker save` stream; the
    updater's venv made from setup's `py312/` and the app's `requirements.aarch64.lock`
    (`--require-hashes --no-deps --only-binary=:all:`, pip's cache in `~/.cache/pip`, outside the
    record); `stack.py prepare`, then `stack.py up --feed vcan --app external --images loaded` on the
    host's role; `drill.py manifest --transport tar` and `drill.py run --via spool`; `stack.py down`.
    No core list is given anywhere: off the Orin the stack and the updater take none.
  - Its status lines are the vss harnesses' kinds: `status=DONE`, `status=TIMEOUT at=<unit>
    reason=deadline` or `reason=step-timeout`, `status=FAILED at=preflight`, `status=FAILED at=<unit>`
    for a unit that failed (drill.py run's refusal included; its exit 1, a verdict that is not ok, is
    a result, and the harness ends DONE; but a drill.py run that exited 0 or 1 and left no
    drill-result.json in its record fails at `drill`) or when the harness stops without a status line,
    through its EXIT trap ("the harness stopped unexpectedly", the unit it was in recorded failed), and
    `status=FAILED at=record` when `drill.json` cannot be written.
  - Every stop once a unit has begun, DONE included, sweeps: the unit `ota-lite` stopped, every container
    labelled `sdv.ota.app` or `sdv.stack.run` removed (by name when they cannot be listed), and no
    `containerd-shim` left of a container docker no longer lists. A sweep that cannot show that records
    `verified` false under `stop` in `drill.json`, with why, and says so in `run.log`; the status line
    stays as it was.
  - Its record is `rec/ota-drill/raw`: `drill.json` (the harness's facts and the sweep), `venv.txt`, the
    up run's `manifest.json`, and the drill's `drill-result.json`, the updater's `ota-lite.jsonl` and
    `state.json`, and the status files the run kept (`status*.json`). Each is copied into a file the
    login owns, by `sudo -n cat` when the login cannot read it: the updater runs as root and writes its
    log and state 0600. A file neither can read is named under `record.not_kept` in `drill.json`.
- **`capture`** treats `ota-drill` as a vss stem: the gate waits for its `done` as for the others, and
  `capture.py` holds it to the same evidence (DONE with `raw/drill.json`, TIMEOUT, FAILED, INCOMPLETE).
  Its whitelist takes exactly those files under `ota-drill/raw` and the stem's `run.log`, `status`,
  `host-before.txt` and `host-after.txt`; the stem's `detach.log` and anything else are left out and named.

`tests/test_ota_drill_harness.py` runs the harness against stubs of every command it calls and
stand-ins of `drill.py` and `stack.py`, by their command lines. It shows nothing about an instance:
not that the drill passes there, nor any timing.

### An aw session (SDV plan Phase 8)

This is a vss session whose two later harnesses are the Autoware session's (SDV Phase 8 WP6 9.2):
`run-aw-setup.sh` pulls Autoware's Jazzy arm64 image by its digest and smokes it, and
`run-aw-suite.sh` drives Autoware's planning simulator through a scenario while the QNX guest's ctl
monitor judges its Control through the claim node. Every container of either runs under the project
entrypoint with every capability dropped, and each harness checks the host's network settings around
its stem. What differs from a vss session:

- **`METAL_TYPE` and `VSS_HOST` go together**, and only one way: `c7g.metal`, the default type, with
  `VSS_HOST=c7g-metal`. The owner took a1.metal off the Autoware image's hosts on 2026-10-24 (after the A72 scan of
  the image), and the Orin's days are its own helper's. `run harness` adds the type's word to `run-vss-setup.sh`'s call by
  itself, but not to the aw harnesses' calls, so give it there by hand. The phase refuses either aw
  harness with no word or another one, and with a word that is not setup's.
- **`METAL_IFS=ifs-ctl.bin`**, WP5's image (kind 2 on `:7150`), a private build that is never in any
  branch. `run-vss-setup.sh` boots it for its smokes; the aw suite boots it once for all its units.
- **The tarball** is the vss form, from a commit that has `sdv/aw` and `sdv/ctl`'s scenario driver: the
  phase refuses an aw harness when the tarball lacks `sdv/aw`.
- **`METAL_FILES`**: the slice's upload bundle, as for a vss session (`run-vss-setup.sh` needs it), and
  the aw inputs, each name beginning `aw-`:
  - `aw-inputs.json`, `{"format": 1, "commit": "<40 hex>", "files": {"<aw-name>": "<sha256>", ...}}`: the
    commit the inputs were made for, which must be the tarball's (`git get-tar-commit-id`), and every
    other aw input with its sha256;
  - `aw-scan.json`, the ISA scan's output for the arm64 image: its `image_digest`
    must be the digest `images.json`'s `autoware.arm64` pins. Its verdict is recorded, not required (the owner's
    decision of 2026-10-24);
  - `aw-map.tar`, the scenario's map: `sample-map-planning/` holding exactly the four files the scenario
    names, each of its sha256, made with `tar -cf aw-map.tar -C <maps dir> sample-map-planning`, where
    `<maps dir>/sample-map-planning` holds those four files and nothing else. A member named with a
    leading `./` (as `tar -cf aw-map.tar -C <maps dir>/sample-map-planning .` writes) is refused at stage,
    after the preflight has passed, which spends the session's one `run-aw-setup.sh`: list the tar with
    `tar -tf aw-map.tar` before the upload.

  `upload` puts all of them in `~/a1/in`. `run setup` checks every file's hash there and then moves
  every `aw-*` file to `~/a1/aw-in`, as it moves the drill's files: `run-vss-setup.sh`'s `bundle.py
  verify` refuses a file in `in/` that `bundle.json` does not list. The harness phase gives the two aw
  harnesses `AW_IN=~/a1/aw-in`.
- **`METAL_VOLUME_SIZE=48`**, a design value: the vss session's 32, and room for the Autoware arm64
  image. This is a provisioning allowance, not a published image-size result.
- **The steps**: `launch`, `wait`, `upload`; `run setup`, `run quiesce`;
  `LADDER_ENV="HARNESS=run-vss-setup.sh IMAGE=ifs-ctl.bin VSS_HOST=c7g-metal" bash scripts/aws/drive-metal.sh run harness`
  and its `wait-run`; then, in a later login,
  `LADDER_ENV="HARNESS=run-aw-setup.sh IMAGE=ifs-ctl.bin VSS_HOST=c7g-metal" bash scripts/aws/drive-metal.sh run harness`
  and `LADDER_ENV="HARNESS=run-aw-setup.sh" bash scripts/aws/drive-metal.sh run wait-run`; then, in a new
  login,
  `LADDER_ENV="HARNESS=run-aw-suite.sh IMAGE=ifs-ctl.bin PLAN=a2 VSS_HOST=c7g-metal" bash scripts/aws/drive-metal.sh run harness`
  (or another plan) and its `wait-run`; then `run capture`, `fetch`, `terminate`, `verify`, later
  `verify-vol`, and `clear`. Terminate only after the fetch has passed.
- **The budget** covers the chosen session length at the host's rate; review it before launch.
- **The harness phase** takes both as vss harnesses: detached, under the session marker and the A6
  refusals, once per session, into `rec/aw-setup` and `rec/aw-suite`. Each needs `IMAGE=`, the session's
  `METAL_IFS`, and `VSS_HOST=c7g-metal`; `PLAN=` is the suite's alone, one of `PLAN=a1`, `PLAN=a2`,
  `PLAN=b1`, `PLAN=b2` or `PLAN=s`; `K` and every `IMG_` word are refused. Before it makes anything the
  phase refuses `run-aw-setup.sh` unless `rec/vss-setup` has `done` and a last status line of
  `status=DONE`, and `run-aw-suite.sh` unless `rec/aw-setup` has too; neither starts while another vss
  harness still runs.
- **Container hardening on a metal host.** Every `docker run` either harness makes from the Autoware image carries
  `--entrypoint` the tarball's `sdv/aw/aw-entrypoint.sh` (mounted read-only), `--user aw`, `--cap-drop ALL`
  and `--security-opt no-new-privileges`, never `--privileged`, `--cap-add` or a `/proc/sys` or `/sys` mount;
  `CYCLONEDDS_URI` names the project's single-host DDS file from `sdv/aw/ros-env.json`, never the image's
  own; `ROS_LOG_DIR` is a directory of the harness's working files, never captured. Each harness reads
  `sdv/aw/hostcheck.sh`'s four settings before its first container and after its sweep, into its stem's
  `host-before.txt` and `host-after.txt`, and a difference, or an after-read that fails, ends the stem
  `status=FAILED at=host-check` with each changed setting named. The detached runner appends its host
  snapshot to that `host-after.txt` instead of writing it anew.
- **`run-aw-setup.sh`** (its header has the whole of it): its preflight refuses, first, an image other than
  `ifs-ctl.bin` (the suite boots no other, so nothing is pulled for one); a login without the docker
  group; a `run-vss-setup.sh` that is not DONE or ran in another host mode; the tarball without
  `sdv/aw` or the scenario; aw inputs that are missing, of another hash, not in `inputs.env`'s `FILES`,
  joined by another file, or of another commit; a scan of another digest; a container of an earlier aw run
  still there; and a host check it cannot read. Then, each behind the deadline's check point and under its
  cap: the map staged in `~/a1/sdv/aw/map`; `docker pull` of the pinned digest, never a tag, read back
  (RepoDigests, the ID, the store's type, the pull's whole seconds); the SIGILL smoke, `ros2 --help` in
  the image under the project entrypoint, whose exit status and stderr are recorded and which fails the
  stem unless it exits 0; `MemAvailable` before and after; and the 30-minute rule: under 30 minutes left before
  `stop_at` after the pull sets `budget_short`, which the suite refuses. Its record is `rec/aw-setup/raw`:
  `setup.json` and `inputs.txt`.
- **`run-aw-suite.sh`** (its header has the whole of it): its preflight refuses a `PLAN` other than the
  five, a login without the docker group, an aw setup that is not DONE or recorded `budget_short`, a QEMU
  that runs, an image other than `ifs-ctl.bin`, a generation whose `vss_ctl.py` compiles no profiles 1 and
  2, a staged map that is not the scenario's, an image not in the store, a container of an earlier aw run,
  and a host check it cannot read. It boots the guest once and checks it: `:7150` accepting, its console's
  `ctl rules:` line naming `vss_ctl.py`'s digest and profiles 1 and 2, and the `:7100` smoke after Docker;
  a guest that fails any of them ends the suite `status=FAILED at=preflight`. Then the plan's units, each
  behind the check point and under its cap, each a fresh `aw-sim` (the planning simulator), the claim node
  `aw-claim-node` to the guest's `:7150` started before the scenario driver `aw-scenario` sets the route,
  and the driver: `PLAN=a1` one planning-sim run with no claim node; `PLAN=a2` the honest scenario, then
  the scripted injections each at its own fixed seq; `PLAN=b1` the same, the honest drive recorded as a bag
  outside the record and exported with `ctl_export.py`; `PLAN=b2` the controller killed once the drive is
  engaged (a composable node in the component container that also holds the gate, so it is unloaded from
  that container with `ros2 component unload` inside `aw-sim`, never a process killed), the injections, and
  profile 2's window; `PLAN=s` the honest drive with
  `MemAvailable` and `docker stats` sampled by the harness every 5 s, never by new logins. A drive that
  times out, a simulator that does not come up or a claim node that refuses is a result, and the suite goes
  on. Each unit's containers are removed on every end. Its record is `rec/aw-suite/raw`: `suite.json` and per
  unit `<NN>-<unit>/` the claim node's `replies.jsonl` and log, the driver's `scenario.jsonl`, the console's
  part the unit saw, `export.jsonl` for the recorded unit, and `unit.json`; never a ROS log, a bag or `~/.ros`.
- **`capture`** treats `aw-setup` and `aw-suite` as vss stems: the gate waits for each one's `done`, and
  `capture.py` holds each to the same evidence (DONE with its `raw/setup.json` or `raw/suite.json`,
  TIMEOUT, FAILED, INCOMPLETE). Its whitelist takes exactly those records and each stem's `run.log`,
  `status`, `host-before.txt` and `host-after.txt`; the stem's `detach.log`, a ROS log directory, a bag
  directory, `~/.ros` and anything else are left out and named.

`tests/test_aw_harness.py` runs both harnesses against stubs of every command they call (docker among
them, whose stand-in leaves what the claim node, the scenario driver and the exporter leave) and the real
`sdv/aw` host check on stand-ins for `ip` and `sysctl`. It shows nothing about an instance: not the pull,
not that Autoware runs there or that the guest judges its commands, nor any timing.

## What bounds the cost

- **Self-termination, checked before upload.** The instance is
  launched with shutdown behaviour `terminate`, so a poweroff from inside it is a
  termination. User-data arms two nets that power it off (2026-10-10), because
  the wall clock of a freshly booted instance may still be stepped:
  - **A monotonic timer, armed first.** User-data's first command is a transient
    systemd timer (`systemd-run`, unit `qnx-metal-monotonic`) that powers the
    instance off when the time since boot reaches the uptime at that moment plus
    the session's minutes (90 unless `launch` was given others: "The session's
    minutes", above). It is set as a time since boot, so no step of the
    wall clock moves it, in either direction, and a `daemon-reload` does not
    start it counting again, as systemd's source says it would a timer set
    relative to its own start (read there, not tried on an instance).
    What it cannot bound: it lives in the service manager, so it does not
    survive a reboot.
  - **The wall-clock poweroff, scheduled once the clock has had time to be
    set.** `shutdown -h` is an absolute wall-clock time: a clock stepped after it
    is scheduled moves the time left by the size of the step. So user-data first
    waits, for a bounded time (tens of seconds, a constant in `userdata.sh`), for
    the kernel to call its clock synchronised, and then, synchronised or not,
    schedules the poweroff for what is left of the session's minutes and writes that
    deadline to disk. What it cannot bound: a clock that is stepped after that
    moment. A step forward shortens the session. A step backward would lengthen
    it, and until a reboot the monotonic timer is the bound.
  - **If `systemd-run` is missing or refuses,** the wall-clock poweroff is
    scheduled at once, as it was before there were two nets, and scheduled again
    after the wait. `wait` then refuses the session, which has one net.
  - **A reboot.** Both nets live in memory: a pending shutdown in `/run`, which a
    reboot empties, and the timer in the service manager; and a kernel whose
    `kernel.panic` is not 0 reboots when it panics. So the deadline is on disk as
    an absolute time, written right after the first net, with a per-boot script
    that re-arms both for whatever time remains, the monotonic timer never for
    more than the session's minutes. It powers off at once if the deadline has
    passed or cannot be read: a deadline that is missing, empty or not a plain
    number of seconds was lost, and the session's end with it. What this cannot
    bound: the deadline on disk is itself a wall-clock time, so after a reboot
    both nets are counted from the clock of that boot. A clock that is wrong at
    that boot and is not set, or one that was stepped backward after the
    deadline was written, lets that boot run past the session's end by the size
    of the error, at most the session's minutes again for each boot. What this
    image's kernel does on a panic is read, not assumed: `run setup` prints it
    and records it in `host-facts.txt`, and warns when a panic would halt the
    host instead.
  - `wait` goes on only if both are right: the timer unit active with no more
    than the session's minutes left on it, a poweroff 61–91 minutes ahead by the
    wall clock for a 90-minute session (N-29 to N+1 for N minutes), and the
    per-boot re-arm installed. `upload`, `run` and `fetch` refuse until it has.
  - `wait` prints what the instance recorded at each arming (the wall clock, the
    uptime, whether the kernel called its clock synchronised) beside the same
    reads taken then, before it decides. A refusal therefore says what the clock
    did, and so does a session that goes on; one that goes on with a clock the
    instance does not call synchronised is told what a later step would do.
  - The two nets, the per-boot script and `wait`'s proof of them run in the
    tests, against stub programs, and `wait` checks them on each instance
    before anything is uploaded.
- **Every failure between launch and that proof terminates**, and the
  termination is confirmed. Such failures include:
  - EC2 not knowing the new id yet (retried, not fatal);
  - a throttled or failed call;
  - a wrong root volume, no public address, or failed provisioning;
  - a missing or mistimed shutdown, or a missing or mistimed timer.

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
  `shutting-down` or `terminated`. Billing stops at `shutting-down`; a bare-metal
  instance then stays in that state for many minutes before `terminated`.

**What this cannot bound:** a host kernel that hangs without rebooting runs no
timer of either kind, and where `kernel.panic` is 0 a panic is such a hang.
Neither net is a bound then. A host that keeps rebooting with a wall clock that
is behind at each boot is not bounded in sum: each boot is held to the session's
minutes, their number is not. Nothing here watches the instance from outside the
instance.

Review the session's minutes at the chosen host's rate before launch.
The termination checks do not establish a measured cost ceiling.

## What `run setup` says about the host (2026-10-08)

The instance runs the image's own kernel, whatever its series, so `setup` says what it met
before it checks anything:
- It prints one `host fact:` line each for the kernel release, `CONFIG_HZ` and the file it
  was read from, the tick handler's name as `/proc/kallsyms` has it, the lockdown state,
  whether the KVM counters read, the `qemu-system-arm` package version found and the one
  expected, and what `kernel.panic` and the command line say about a panic. None of them
  is an identifier, and they reach the transcript whole.
  - One exception is the operator's machine's doing, not the instance's. `red()` masks
    the operator's own login wherever it stands, inside a word too: a transcript is never
    data. On a machine whose login is `ubuntu`, a package version in these lines prints
    with that word masked. `host-facts.txt` has it whole.
  - `tick_handler` is one of the three names the reports accept, or `unknown` when
    kallsyms has none of them. A kernel that has more than one gets each of them,
    comma-separated, in kallsyms' order: mainline up to 6.6 defines two of the three, one
    of them a different function from the one that took the name later.
  - `kvm_counters` is `readable`; or `unreadable:` and the names of the counters that
    did not give an integer; or `unread`, when the list could not be taken from the
    uploaded tarball or `/sys/kernel/debug/kvm` could not be looked at (no debugfs
    mounted there yet, or `sudo` wants a password). It is read here and checked later:
    the check that stops `setup` on a counter comes after the bridge, as before.
- It writes `host-facts.txt` as soon as the record has a directory, and again once the
  bridge is up. A `setup` that stops later, on a KVM counter that does not read for one,
  leaves both the printed lines and the file. The five checks before that point (the
  inputs file, user-data finished, access to `/dev/kvm`, a leftover record,
  `METAL_QEMU_PKG`) refuse before a record directory exists, and leave the printed lines.
- `METAL_QEMU_PKG`, when set, is the `qemu-system-arm` version the session expects: the
  other host's, as its `dpkg-query` prints it. The image and the Orin's archive give one
  QEMU release, but user-data installs the day's package and the Orin keeps the build it
  has. `run setup` carries the value to the instance, and `setup` refuses a host whose
  `dpkg` has another.
  - It refuses before the record has a directory, so nothing is left behind: a mistyped
    value is corrected and `run setup` run again. When the value was right, the session
    ends there, since no harness may run on the other build.
  - Whether the KVM counters read is printed by then, and the refusal repeats it, so a
    session that stops there has still learnt what a fallback is planned from.
  - The comparison is made once more as `setup`'s final act, on a fresh read: the
    package timers are stopped only by `quiesce`, and a package that changed while
    `setup` ran stops it there.
  - Unset, nothing is expected. `host-facts.txt` records the version found and the one
    expected.

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
  - JSONL files get the same rule line by line, the file's strings in one
    redactor call. Replay mode's monotonic nanoseconds are 12-digit numbers too.
    A torn last line (no newline, does not parse) is dropped and noted; any other
    line that does not parse refuses the capture.
  - In `vss-claim-bridge.log`, a line that is dockerd's stamp and then JSON gets
    the JSON rule for that JSON; the stamp and every other line are text.
  - JSON and JSONL strings also lose every IPv6 address except `::`, `::1` and
    the guest's link-local one, by `leakscan.py`'s own pattern, in `capture.py`. Text files
    lose them in the redactor, by the same rule, and in a vss record once more in `capture.py`.
  - The arm files are checked to be identical to what the run wrote.
  - The account-id mask takes a run of twelve digits only when it stands alone.
    Inside a longer run of digits it is kept, as it is inside a word. Until
    2026-10-08 a longer run whose length was a multiple of twelve lost its last
    twelve wherever a word ended with it.
  - An IPv6 address is masked by the rule the scan after the fetch refuses on: a run
    of hex digits and colons that is not glued to a word, holds `::` or at least five
    colons, and is not a MAC. The guest's link-local address, which follows from its
    fixed MAC, is kept, and so are the unspecified and the loopback address (`::`, `::1`),
    as the scan keeps all three. Until 2026-10-08 the redactor masked IPv4 only: an
    instance's own IPv6 address in a text file reached `pub.tgz`, and the scan then
    refused the whole capture.
  - A capture of nothing, or into a used directory, is refused.
  - A vss record has more rules: see "A vss session instead".
- **A scan after the fetch.** `leakscan.py` runs before anything can be copied
  anywhere, and its findings print the shape of a leak, never its value. It
  refuses:
  - AWS resource ids, ARNs and EC2 host names;
  - addresses outside the project's bridge subnet, and MACs other than the
    guest's. Of IPv6 it keeps the guest's link-local address, `::` and `::1`;
  - UUIDs, 12-digit numbers in text, and JSON that no longer parses: a `.json`
    file or a `.jsonl` line. It reads the JSON after dockerd's stamp in
    `vss-claim-bridge.log` as JSON too, as `capture.py` writes it;
  - the operator's own key path, key-pair and security-group names, and user
    name;
  - the cloud twin's shapes (plan Phase 4), in JSON strings as in
    text: an account's own host of the IoT service, with or without `-ats`;
    `cert/` and the 64 hex characters after it; a registry host that starts with
    an account id; a PEM block's first or last line; an e-mail address; an IAM
    unique id or key id. A sha256 that is not after `cert/` is kept, and so is a
    systemd unit's name (`getty@tty1.service`): a vss capture holds both.
- **The operator's transcript is redacted too.** Everything `drive-metal.sh`
  prints, `aws` CLI errors included, goes through `red()`, which also masks
  those literal local values. As in the redactor, a 12-digit run beside a
  letter or a digit is part of a longer token, such as a sha256, and is not
  taken for an account id, so the hashes `upload` prints stay whole.

## What it does not do

- **Publish the guest image or disk.** Both are QNX-derived; they are uploaded to
  the instance and never committed.
- **Make a cloud leg** in this project's sense. QHV needs EL2, and a KVM guest gets
  EL1, so the QNX Hypervisor cannot run here.
- **Check the vCPU quota.** `c7g.metal`, the default and the closer core match to the
  Orin, takes 64 vCPUs of the account's on-demand quota in the region, `a1.metal` 16.
  A launch over the quota fails at no cost (`VcpuLimitExceeded`).
