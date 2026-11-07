#!/usr/bin/env python3
"""twinctl.py -- the twin's create and teardown driver, with a dry run (SDV Phase 4 WP6).

WHAT IT IS
  Standard-library Python over the AWS CLI. Every call is an argv list handed to subprocess with no shell: Git
  Bash rewrites an argument such as a log group's name into a Windows path, and the service's topic names are full
  of `$`. Every JSON document a call needs is a file of templates/ with @@NAME@@ placeholders: rendered, parsed
  back, checked, written to the render directory and passed as file://<path> in the form the platform opens.

  ONE STEP TABLE (table()) drives every command. Per step: its id and row of the resource table, the create calls,
  the reads that prove it, the delete calls, what it depends on, its listing call, and whether the owner makes it
  by hand. `plan`, `apply`, `status`, `teardown` and `verify-gone` are walks of that one table. One step can be
  ADOPTED instead of made: IoT's own log group, which the service makes itself once logging was ever on in the
  region. If it is there before the twin, `apply` refuses it as not ours and names the owner's choice: delete it
  by hand, or keep it and set TWIN_IOT_LOG_GROUP_ADOPT=1. Adopted, it is a step of the owner's kind: read and held
  to the render, never created and never deleted here.

THE COMMANDS
  literals            write <state>/literals.json from the names file and the state, for the redactor and the
                      scanner. Prints nothing. Refuses a value under 8 characters and one a search of this work
                      tree already finds, by its position, never by the value.
  build-breaker       build the breaker function's zip from sdv/cloud/breaker/breaker.py into the file
                      TWIN_BREAKER_ZIP names, outside every work tree: one entry under the name the handler asks
                      for, stored, with a fixed time and mode, so two builds give the same bytes under any Python.
                      Prints its sha256, in hex and in the form the service reports a function's code in. Refuses
                      a source with a carriage return, one with no handler, and one that holds a literal of the
                      state. Sends no call. THE ZIP IS HELD TO THE SOURCE: `apply function` (and `plan`) refuses a zip
                      that is not the build of the breaker's source as it stands, with its render printed and saying
                      so; `status` says beside the function's line when the source has changed since the build the
                      function was made from, and does not fail on it (the account runs what was approved).
  baseline            store what every listing returns, before the first create.
  plan [--no-cli]     render every call of every step, and every call a command sends that is no step's own (OTHER),
                      check every document, and give each call to the CLI itself to read offline
                      (--generate-cli-skeleton output, no AWS_ variable of the caller, two empty credential files, a
                      closed local endpoint and proxy, after a control call under the same settings failed).
                      Executes nothing. It also holds the operator role's rendered policy to every call it lists
                      (operator_gaps()): each needs an action the policy allows and no Deny statement names. With
                      --rehearsal, whose table holds no role, the twin's policy is rendered from the same names, written
                      nowhere, and held to the rehearsal's calls: they are sent under that role too. Two
                      limits of the CLI, seen on 2.35.1: the calls that take an output file know no skeleton and
                      are read by nothing (SKELETON_UNSUPPORTED), and a sample reply that fails the CLI's own
                      validation is told from a refused argument line by line (sample_only()). For such a call
                      only the options' names, the required options and each value's form were read: the service
                      model's validation of the call's own arguments never ran. plan names these calls by service
                      and operation (no value) on a line and in plan.json (read_names_and_forms_only).
  apply STEP          print the step's calls and documents, redacted, and the render's sha256; refuse unless the
                      same step and hash come back as --approve STEP:HASH. Then: the caller must be an assumed
                      session of the operator role; read (refuse what exists and is not ours); create; read back
                      and compare with the intent; record. One printing lets ONE run of the calls through. A step
                      recorded as being deleted is not made again before `verify-gone STEP`, or its teardown run
                      again, recorded it as deleted. The certificate, which is read by an id only a reply gives
                      and so by no name before its create, is held to its listing instead: with a name there
                      that neither the baseline nor a state knows, nothing is created (listed-not-ours).
  status              the proving reads of every step as states, never values; each alarm's state, whether its
                      actions are enabled and what they target; the function's reserved concurrency. Fails when
                      the function's certificates are not exactly the twin's, or when an ACTIVE certificate of the
                      account is outside the twin's set. A read that is denied is said in its place and stops
                      neither assertion; a read an assertion stands on, denied, fails that assertion. A step that
                      has no read at all (no id in the state) is said so, never "not found". A go-live step whose rule
                      or certificate is read and is not live says `not live (tripped, or not made live)`: what a trip
                      leaves is there, and is not "not found". The function's code is
                      held to the sha256 the state recorded when it was made, and a zip at the path that is no
                      longer that one is said beside it. After the alarms' lines it prints the sha256 of the
                      thresholds file the alarms are rendered from (TWIN_THRESHOLDS, as it stands and as derive.py's
                      check and the owner's design take it): the burst tool is given that hash and refuses any
                      other file (sdv/cloud/burst). A hash of the file's bytes, never a count of it.
  trip                invoke the function with {"manual": "trip"}, then `status`. The owner's one-command stop: it
                      asks for no approval, because stopping is the safe direction and is reversible. ITS FIRST ACT
                      is the file of the manual stop's four calls by hand, <state>/trip-by-hand.txt, written before
                      anything of the trip can be refused: for this twin, as far as the names file and the state
                      give them. A call whose every value is there is a line to run; a call that lacks one is a
                      comment with its slot left in, and each open slot is said by the key its value comes from.
                      The certificate's id is taken from the state only when the state was made under the account,
                      region, prefix and thing the names file gives now; a state that records no names yet (one made
                      before its first write, or one whose entry `names` was taken out on the salt-missing advice)
                      gives its certificate with no comparison. Otherwise another twin's id is not put beside this
                      twin's names. The file's place is printed; its content, which is unredacted, never is.
                      A literals file that is missing or behind does not stop a trip (the names file's and the
                      state's own values are taken), nor does a state that cannot be read (the invoke goes by the
                      names file, and the state is not written), nor an identity that cannot be read, nor another
                      operator role or profile than the state was made under: THE STOP IS HELD TO THE ACCOUNT ONLY.
                      Nor another bucket suffix or notice's switch (the owner's A4 answers of 2026-10-16): no call
                      of a stop is made of either.
                      A caller of ANOTHER account is refused: its function is not this twin's. NO ENDING OF A TRIP
                      IS ONLY A REFUSAL: one that ends before its invoke holds the file already, and after the
                      refusal the four calls are named once more, with the file's place; where no file could be
                      written they are printed with their slots and the keys the slots are made of.
                      THE STOP NEEDS NO OPERATOR ROLE: a names file that lost TWIN_OPERATOR_ROLE, or gives it in a form
                      the driver does not take, is said by the key and the trip goes on (every other command is
                      refused). A reply to the read of the caller that names no account is an identity that could
                      not be read, not another account. IN THE FILE a call is written without --profile where the
                      names file gives none in its form (the manual stop's calls have none: the profile is the shell's),
                      so a profile alone costs no call; where the certificate's id is open, a comment gives the read
                      that finds it in the account; a rehearsal's trip says in the file's head and on the terminal
                      that the file is the rehearsal's set's; and when the write could not take the file's place,
                      the file it got as far as (trip-by-hand.txt.tmp) is named if it holds this run's calls whole.
                      A command line that names `trip` and cannot be read gets the file too, in the state directory
                      it names by --state or by TWIN_STATE; of the words it could not read only the options' names
                      are printed, each as typed up to its `=`. With no CLI that runs, the manual stop's console way is
                      named after the calls.
                      A trip that ran, like the dry trip (`apply dry-trip`), prints what the function's own record
                      says each write was answered, in the form a write word has and in no other: a write the
                      service answered with an error passes when its read-back shows the cut, and is said.
                      `status` follows also when the invoke failed or ended in a function error: it is the manual stop's
                      proof for the calls by hand. AN INVOKE THAT WAS SENT AND WHOSE ANSWER IS NOT KNOWN (a reply that
                      is no JSON, a CLI cut off, a reply that could not be written) is said so: the function may have
                      run, `status` follows, and the trip is not called refused before its invoke. THE CALLER IS READ
                      ONCE MORE BEFORE A TRIP'S STATUS: when the profile now answers for another account, no status
                      is printed (it would be that account's all-clear) and the trip ends as a refusal.
                      An invoke that was throttled is said to have met a run of the
                      function (it runs one invoke at a time), and `status` is read before anything is done by
                      hand. A function error is said by its kind and by the file its message is read in; the
                      function's own failure message is printed only when the error's type is the breaker's own
                      and every clause of the message is one of the function's own sentence forms (OWN_CLAUSES).
  restore             render the three reverse calls and their proofs for the owner to run. Refuses while a
                      breaker alarm is missing, is in ALARM, or has its actions disabled (gap aa).
  teardown [STEP]     the table in reverse. Without STEP: the order. With it: that step's delete calls and their
                      hash, refused without --approve STEP:HASH, refused while a later step still stands, and
                      refused on its own precondition (a certificate INACTIVE and detached, a thing with no named
                      shadow listed, a bucket empty). Emptying a bucket is the step `bucket-objects`, with an
                      approval of its own that names what is listed at that moment. No file a create took its
                      content from (the signing request, the zip) has to be there still. A render that stands on a
                      value the state has lost (the certificate's id) is refused whatever it holds: no delete call
                      is printed or sent on a placeholder. A step with nothing to read is never "read back, not
                      found". Every create call is on record before it is sent, and stays there however it ended:
                      a call whose reply was lost (a reply that is no JSON, a CLI cut off, a run that ended
                      there) is not taken for one that never went through, and neither is one the service
                      answered with an error, because an error does not say that nothing was made (a 5xx after
                      the work was done) and which codes are certain refusals is from memory. With such a call
                      on record and no id, the step's listing decides: a name there that neither the baseline
                      nor the state knows, and the teardown is refused (nothing-to-read); none, and the record is
                      taken back on that one read. No record with a call on it is taken back unread. One read
                      may be behind what was just made (not established for the real listing): `apply` reads that
                      listing again before it creates such a step, and refuses while it holds a name neither the
                      baseline nor a state knows (listed-not-ours).
  recover STEP        put the certificate's id back into a state that lost it, from a reply file the runner itself
                      wrote under this state directory: never a typed id. Printed and approved like a step; reads
                      only. The id is recorded only when exactly one certificate the replies name stands in the
                      account, holds its own reply's PEM, is not in the baseline, and (once the attachments are
                      recorded) is attached to the twin's thing.
  verify-gone [STEP]  read-only: every recorded resource read by name is not found, every listing less the
                      baseline is empty, and a tag query finds nothing. None of the three sees a named shadow:
                      their check is in `teardown`, before the thing goes. A listing that says there is more (a
                      token, a flag) is refused here as in every read: half a listing is not judged. A step that
                      has no read at all (no id in the state) is said so, never "not found", and is not settled
                      while the state records it as made.
  branch-scan         gap ab: each literal of the state searched in the files git tracks or does not ignore, in
                      the history's patches and in its commit messages. The one command that runs git.
  exit-checks         A5's read-only checks, each reduced to a count or a shape, redacted into a capture directory.
  push                PHASE 6: an image into the twin's repository sdv-twin/<app> by digest (--app NAME --version X.Y.Z --arch
                      arm64 --store-id ID --config-digest CFG [--docker PREFIX] [--approve push:HASH]). It prints its render
                      (the repository, the tag <version>-<arch>, the store ID, the config digest, docker's prefix, the CLI's two
                      calls) and its hash, and is refused without the approval, or while the step ecr-repository is not
                      recorded as made and proven. Then, before anything is tagged: the config digest proved from a `docker
                      save` stream (the store ID's blob hashes to it and is one platform's manifest, an index is refused; the
                      config blob hashes to the digest given; the config is linux/<arch>); and an image with no other name than
                      the registry's reference is refused before anything is tagged (docker image inspect: the tag goes by `docker
                      rmi`, which removes an image whose only name it is). Then the store ID tagged; `aws ecr
                      get-login-password` piped into `docker --config <a temporary directory> login --password-stdin`, the
                      password on no argv, in no reply file and in no file but that directory's, which is removed in a
                      `finally` with the tag; the push recorded in the state before it is sent (status `sending`, in `pushes`:
                      the tag, the store ID, the config digest); the push; `describe-images` by the tag must give the store ID
                      as imageDigest, and the record is then `pushed` with the manifest digest. A push that ended in an error
                      stays `sending`, one whose read-back failed or gave another digest `unverified`: either may have put the
                      image, and `status` lists every push that is not `pushed`. Docker's
                      words are never printed: they name the registry, which holds the account. The prefix is split as a POSIX
                      shell splits words; for WSL's docker (wsl.exe -d Ubuntu-24.04 -- docker) the temporary directory is
                      given as /mnt/<drive>/...
  ecr-config --out F  PHASE 6: the pulling host's one root-only file (D7), for sdv/cloud/ecrlogin.py and the updater's
                      --registry-file: credential_endpoint (describe-endpoint for iot:CredentialProvider), role_alias, region
                      and registry, as JSON, outside every work tree, mode 0600; nothing of its content is printed. Refused
                      while the step role-alias is not recorded as made and proven.

WHERE THINGS LIVE (gap b). NOTHING OF THIS IS IN A WORK TREE, and a path inside one is refused: found by walking
up for .git, never by running git.
  <state>/names.env        the chosen names, the account, the profile, the thresholds file's path (.env.example
                           is the tracked template). A TWIN_* variable of the environment wins over the file;
                           TWIN_NO_NAMES_FILE=1 keeps the file unread (the tests' switch). An unknown TWIN_* key is
                           refused in both. TWIN_REGION is any region but ONE: us-east-1 is refused where the names
                           are read, by the key and never by the value (names-region-not-taken). The bucket's
                           create passes a LocationConstraint, which the service refuses for that region, and one
                           read of the exit's checks goes through it as a second region.
  <state>/trip-by-hand.txt the manual stop's four calls with this twin's own values, UNREDACTED: a trip's first act
  <state>/literals.json    what the redactor takes out (sdv/cloud/redact.py)
  <state>/state.json       what each step did, the facts a reply gave (the certificate's id), and, as salted
                           fingerprints, the names it was made under (BOUND_NAMES); since Phase 6 also the pull
                           certificate's id, the pull role's fingerprint once a pull step is recorded and the pull
                           thing's once pull-thing is (LATE_BOUND), and `pushes` (each tag's latest push: its store
                           ID, config digest and status, and its manifest digest once `pushed`)
  <state>/baseline.json, approvals.jsonl, salt, replies/ (every raw reply), rehearsal/ (A2's own state)
  <render>                 the rendered documents and plan.json; <state>/render unless --render names another

THE CALLER
  Every command that sends a call reads the caller's identity first (sts get-caller-identity) and is refused unless
  it is an assumed session of the operator role the names file names, in the names file's account. That holds for
  the commands that only read as for the ones that write: baseline, status, restore, verify-gone, exit-checks, an
  owner-made step's reads, a teardown's reads. A profile is repointed in the CLI's own configuration without any
  approval, and a read that another account answers is a wrong verdict on this one. `trip` alone is held to the
  account only, and goes on when the identity cannot be read at all: whoever may invoke the function may stop the
  twin. The runner itself sends nothing but that one read until it was made (caller-not-read).

THE NAMES A STATE WAS MADE UNDER
  A state says that a step was made; the render that deletes it is printed with every name masked. So the state
  holds the account, the region, the prefix, the thing and the bucket's suffix it was made under, and with them
  the operator role, the profile and the notice's switch (BOUND_NAMES), and under any other value every command is
  refused by the key's name (names-changed), never by a value: the same redacted render would otherwise go to a
  resource this state never made, or under a role no approval named. ONE EXCEPTION, the owner's decision of
  2026-10-12: `trip` is not held to the role or to the profile. Under another of either it goes on, under the profile
  the names file gives now, and says so; a profile renamed while the twin is live does not cost the one-command stop.
  Since the owner's A4 answers of 2026-10-16 the same holds for the bucket's suffix and the notice's switch, of which
  no call of a stop is made. Under another account, region, prefix or thing a trip is refused like every command,
  with its file of the four calls written first. When nothing is recorded as standing,
  `literals` and then `baseline --again` take new names, with a baseline of their own and no step recorded; an
  approval printed under the old role or profile is none under the new (both are in the render's hash).
  Row 19's three keys are not bound (they are given while the twin stands): once its alarm is recorded as made, its
  steps stay in the table whatever the names file says, and are refused by the missing key's name.
  THE SALT. The fingerprints and every render's hash are salted with <state>/salt. With that file gone and names
  recorded, every command is refused as salt-missing. The way back: the file from a copy of the state directory;
  or, knowing that the names file is the one the state was made under, the entry `names` taken out of state.json
  (and of rehearsal/state.json), after which the next write records the present names under a new salt and every
  render is printed again.

PHASE 6: THE IMAGE TRANSPORT (the image-transport contract)
  NOTHING OF IT IS THERE UNTIL ITS KEY IS: with TWIN_ECR unset or 0 and no TWIN_PULL_ROLE, every render, hash, `status` and
  `exit-checks` is the one the twin stands on (tests/test_sdv_cloud.py holds each step's render
  to the baseline recorded before Phase 6 WP4).
  TWIN_ECR=1 adds two steps after every step of the twin's, so that a teardown removes them first: `ecr-repository` (row B2;
  one repository per app, sdv-twin/<app>, tags IMMUTABLE, AES256 given explicitly, the twin's tag, no scanning configuration,
  never a repository policy; one that is there and not ours is refused) and `ecr-lifecycle` (one rule, priority 1, any tag
  status, the newest LIFECYCLE_KEEP images kept). A repository is deleted only once it holds no image (no --force): emptying it
  is by hand. TWIN_PULL_ROLE adds the Orin's pull identity (D2 (a)): `pull-role` (row B1, the owner's kind: trusted by the
  credential provider alone, for this account and the role alias; GetAuthorizationToken on * and BatchGetImage and
  GetDownloadUrlForLayer on the twin's repositories, nothing else), `role-alias` (sdv-twin-ecr-pull, the pull role, 3600 s),
  `pull-policy` (<prefix>-ecr-pull: iot:AssumeRoleWithCertificate on that alias, nothing else), `pull-thing` (only with
  TWIN_PULL_THING), `pull-certificate` (from TWIN_ORIN_CSR, INACTIVE, written to TWIN_ORIN_CERTIFICATE_OUT), `pull-attachment`,
  and the actions `pull-active` and `pull-inactive`, each run by its own printed hash. A state that records one of these steps
  keeps it in its table whatever the names file says, as row 19's. TWIN_ECR follows that table: TWIN_ECR=0 takes effect only once
  no ECR step stands; while one does, the operator policy keeps its ECR grants, `plan` push's calls and `exit-checks` its ECR
  rows. The pull role is BOUND ONCE RECORDED (LATE_BOUND), not with a state's first write: a state made before Phase 6 records no
  fingerprint of it. It is then held while any pull step is on record, the owner's read of the role and a record taken back as
  stale among them: twinctl never deletes the owner's pull role, so once `apply pull-role` has read it the binding stays for good,
  as TWIN_OPERATOR_ROLE's does, and the way out is the twin's own (`literals` and `baseline --again` once nothing stands).
  TWIN_PULL_THING is BOUND ONCE `pull-thing` IS RECORDED, and held while that step is on record: the attachment's detach and the
  certificate's teardown read the thing by that name. `trip` is held to neither.
  The operator role's policy gains Phase 6's grants only with their keys (D8: templates/operator-role-policy-ecr.json and
  -pull.json, merged into the one document the owner makes the role from); with TWIN_ECR=1 its Deny names ECR Public's writes in
  place of ecr-public:*, so that the exit can read that ECR Public holds nothing. The wildcard exceptions gain the twin's
  repositories and the pull role's token on * (the spec's), and nothing else.
  `status` knows two certificate sets: the function's environment is held to the twin's data certificate alone, as before; an
  ACTIVE certificate outside the data set and the pull certificate fails; the pull certificate ACTIVE is said ("active: a board
  day") and is no failure. `exit-checks` adds, with TWIN_ECR=1, no repository policy on a sdv-twin/ repository, no registry
  policy, no replication or pull-through cache rule (the registry's scan type as a shape), nothing in ECR Public (read through
  us-east-1), and the repositories exactly the expected ones, IMMUTABLE, AES256; with TWIN_PULL_ROLE, the pull role, the alias
  and the pull policy as rendered and the pull certificate carrying the pull policy and no other.
  Does not demonstrate: anything in the account (no step was applied: B1-B5 come after the merge, D10); that the credential
  provider gives credentials to a certificate attached to no thing (wp0-facts C9); that ECR answers a listing of every
  repository to a principal allowed DescribeRepositories on * (a listing names no repository, so no repository's ARN can hold
  it); which service name CreateRoleAlias passes the pull role to (the statement names the one role and no service); that a
  push from Docker's containerd store keeps the manifest's bytes (the read-back settles it: D4); or that `aws ecr
  get-login-password` knows no skeleton (plan takes it so, from memory of the CLI's customizations).

A RECORD DOES NOT OUTLIVE WHAT IT STOOD ON
  An action's `done` (the dry trip, an alarm's test, the policy attached again) and an owner-made step's `verified`
  are records of the function, the certificate, the alarms as they were then. When a step is deleted or made anew,
  every such record that stands on it, directly or through other steps' needs, becomes `stale`, and a step that
  needs it is refused (step-needs) until it was applied again: go-live does not pass on a dry trip another function
  ran, and the function is not created on a role that was read against another certificate.
  An action's `done` is the record of its LAST run, not of one run among several. Applied again, a run that does not
  come to its end (a call that fails, an invoke that ends in a function error, a reply that cannot be read) takes the
  earlier record back to `stale`, with every record that stands on it, until the action was applied again and ran to
  its end. A first run that fails leaves no record, and an approval refused before anything was sent changes none.
  A manual `trip` whose invoke ends in a function error takes the dry trip's `done` back the same way: it is a run of
  the same invoke, and it showed that the function, as it is now, does not run to its end. An invoke the service
  refused changes no record, and a trip that ran clean puts none back: `apply dry-trip` does.

THE APPROVAL
  THE SCRIPT CANNOT TELL WHO TYPED AN APPROVAL. It checks these things only: the approval names this step, its
  hash is the hash of the render as it is now (calls and documents, salted with a value that never leaves the
  state directory), that render was printed before, and it has let no run of calls through since it was last
  printed (a render that did not change has the same hash: create, delete, create is three printings). The rule
  stays outside the script: the session passes --approve for a step only after the owner said yes to that step
  in chat.
  THE FILES A CREATE UPLOADS (the function's zip, the certificate's signing request) are covered by their CONTENT,
  not by their path: the file's sha256 is in the render's hash, is printed with the render and is recorded in the
  state when the step is made. A file replaced after the printing is another render, and its approval is refused.
  The function is then held to the recorded hash (CodeSha256), whatever lies at the path later. What is not held:
  the file is read once for the hash and again by the CLI within the one run that sends the call; for the zip the
  read-back catches a change in between, for the signing request nothing does.

WHAT IS PRINTED
  Everything goes through the redactor: the literals first, then every shape the scanner knows. A line the
  redactor refuses is withheld and its refusal printed in its place. No refusal of this file holds a value of the
  names file or of a reply. The unredacted documents are in the render directory, for the owner to read there.
  THE REGION IS NO LITERAL OF THE DRIVER'S: the redactor does not treat a region as an identifier, so the one document
  that holds nothing else (the bucket's location, at `apply bucket` and `teardown bucket`) prints TWIN_REGION's value.
  An owner who keeps it off the terminal adds a kind `region` with that value to <state>/literals.json by hand:
  `twinctl literals` keeps a kind that is not its own, every command then prints `<region>`, and a stop whose literals
  file is behind (another role or profile) still takes the kinds the file holds (stop_literals()).

ENCODED REPLY FIELDS (the hard review of 2026-10-08)
  No call ever asks a function's invoke for its log tail: FORBIDDEN_OPTIONS is checked on every argv before it
  runs. ENCODED_REPLY_FIELDS is the one list of reply fields that carry encoded text; a reply that holds one is
  refused before anything of it is copied into a capture, and only the replies of COPIED_REPLIES are ever copied.
  Of a function error only its kind goes into a capture, unless its message is the function's own in its own sentence
  forms: the rule of the terminal, held for the copy (captured_payload()).
  A refusal of the redactor for encoded text is a stop, not a retry: the reply stays in the state directory.
  What that second line does not see: a block under 64 characters or wrapped under 64 columns, the URL-safe
  alphabet, hex, text encoded twice.

EXIT STATUS  0; 1 a refusal or a check that failed; 2 a command line that cannot be read; 3 a render was printed
and nothing was done (no approval was given).

Does not demonstrate: that a call is authorised, that a name is free, that IAM accepts a role at once, or what a
call costs. Every reply shape this file reads, every error code it takes for "not found", every IAM action and
ARN form in the templates is written from memory of the documentation and is held by the tests to a stub only;
what the service accepts is seen in the account, not here. The breaker function is sdv/cloud/breaker/breaker.py (WP7): its handler
(breaker.handler) and the four variables of its environment are the ones this file renders and holds, and the
stand-in the tests drive runs that file's handler out of the zip. What the real function does in the account, and
what its runtime's SDK holds, is first seen at the function status and dry-trip checks.
"""
from __future__ import annotations

import argparse
import ast
import base64
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
import zlib
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, NoReturn, Optional, Sequence, Set, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TEMPLATES = HERE / "templates"


def _by_file(name: str, path: Path) -> Any:
    """A module of this repository by its file, leaving no bytecode beside it."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError("a module twinctl needs is not where it reads it from")
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


REDACT = _by_file("_sdv_cloud_redact", HERE / "redact.py")
TOPICS = _by_file("_sdv_connector_topics", REPO / "sdv" / "connector" / "topics.py")

EXIT_OK, EXIT_REFUSED, EXIT_USAGE, EXIT_SHOWN = 0, 1, 2, 3

REGION_DEFAULT = "eu-central-1"
# THE ONE REGION THE TWIN IS NOT WRITTEN FOR, refused where the names are read (names-region-not-taken). The bucket's
# create passes a LocationConstraint of the twin's region, which the service refuses for this one, whose buckets take
# none (the S3 CreateBucket example page, as the re-check of 2026-10-12 read it: T11, row L22). And the account's
# Block Public Access is read a second time THROUGH this region (_b_other(), exit_checks()), a read written for a twin
# that lives in another one.
GLOBAL_REGION = "us-east-1"
TAG_KEY = "dualvm-twin"
IOT_LOG_GROUP = "AWSIotLogsV2"                 # the service's own name for its log group
SHADOWS: Tuple[str, ...] = tuple(TOPICS.SHADOWS)
REHEARSAL_SHADOW = "rehearsal"
PROVISIONAL_CERT_ID = "0" * 64                 # stands in a render until the certificate exists; such a render is never applied
MIN_LITERAL = 8                                # a shorter literal cuts into records that only happen to hold it
OFFLINE_ENDPOINT = "http://127.0.0.1:9"        # the discard port: nothing listens there
ALARMS_PRINCIPAL = "lambda.alarms.cloudwatch.amazonaws.com"
BREAKER_ALARMS: Tuple[str, ...] = ("bytes", "records", "shadow", "publish", "failure")
RETENTION_DAYS = 30
HANDLER = "breaker.handler"                    # confirmed by WP7: the zip's one entry is breaker.py, its function `handler`
BREAKER_SOURCE = HERE / "breaker" / "breaker.py"
ZIP_ENTRY = HANDLER.split(".")[0] + ".py"       # the entry's name and the handler agree, or the function fails at its first invoke

# PHASE 6 WP4: THE ACCOUNT SIDE OF THE IMAGE TRANSPORT (the image-transport contract). Every name a pulling host sees is a
# constant of the spec, with no value of the names file in it: the repositories' namespace and the role alias.
ECR_NAMESPACE = "sdv-twin"
ECR_APPS: Tuple[str, ...] = ("hard-brake-hazard",)  # one repository per app: sdv-twin/<the manifest's name>
ROLE_ALIAS = "sdv-twin-ecr-pull"
ROLE_ALIAS_SECONDS = 3600                       # the provider's default and the role's least maximum session (wp0-facts C5)
LIFECYCLE_KEEP = 10                             # a design value: v1-v3 of a few apps fit, and the rule expires the oldest beyond it
ECR_STEPS = ("ecr-repository", "ecr-lifecycle")
PULL_STEPS = ("pull-role", "role-alias", "pull-policy", "pull-certificate", "pull-thing", "pull-attachment", "pull-active", "pull-inactive")
PULL_UNCONFIRMED = "pull_certificate_id_unconfirmed"
# ECR Public's actions of the access levels Write, Permissions management and Tagging, as the Service Authorization Reference's
# page for ECR Public lists them (the AWS Service Authorization Reference): with TWIN_ECR=1 the operator role's Deny names these in
# place of ecr-public:*, so that its one read (DescribeRepositories, in us-east-1) can say that nothing is there (D8).
ECR_PUBLIC_WRITES: Tuple[str, ...] = (
    "ecr-public:BatchDeleteImage", "ecr-public:CompleteLayerUpload", "ecr-public:CreateRepository", "ecr-public:DeleteRepository",
    "ecr-public:DeleteRepositoryPolicy", "ecr-public:InitiateLayerUpload", "ecr-public:PutImage", "ecr-public:PutRegistryCatalogData",
    "ecr-public:PutRepositoryCatalogData", "ecr-public:SetRepositoryPolicy", "ecr-public:TagResource", "ecr-public:UntagResource",
    "ecr-public:UploadLayerPart")

# The reply fields that carry encoded text. Never copied into a capture; a reply that holds one is refused before
# the copy. A field is added here when a capture is refused for `undecoded data`; it is never answered by decoding
# in place, by a mask, or by reading without the literals.
ENCODED_REPLY_FIELDS: Tuple[str, ...] = ("LogResult",)
# No argv may hold one of these: `lambda invoke --log-type Tail` is what puts LogResult into a reply.
FORBIDDEN_OPTIONS: Tuple[str, ...] = ("--log-type",)
# The only replies that are ever copied into a capture (redacted): each holds states and counts, no name.
COPIED_REPLIES: Tuple[Tuple[str, str], ...] = (("lambda", "invoke"), ("lambda", "invoke-payload"))

# What a read answers when the thing is not there. From memory of each service's API pages: A2 records what the
# account really answers.
NOT_FOUND = frozenset((
    "ResourceNotFoundException", "ResourceNotFound", "NotFoundException", "NotFound", "404", "NoSuchBucket", "NoSuchEntity",
    "EntityNotFoundException", "NoSuchBucketPolicy", "NoSuchLifecycleConfiguration", "NoSuchPublicAccessBlockConfiguration",
    "ServerSideEncryptionConfigurationNotFoundError", "OwnershipControlsNotFoundError", "NoSuchTagSet", "NotConfiguredException",
    # ECR's (Phase 6), from the API reference's error lists as remembered: no existing call answers with one of these
    "RepositoryNotFoundException", "RepositoryPolicyNotFoundException", "LifecyclePolicyNotFoundException", "RegistryPolicyNotFoundException",
    "ImageNotFoundException"))
# A code that means "not there" only with these words in the message (the code alone is the service's word for any
# bad request).
NOT_FOUND_WORDS = {("athena", "InvalidRequestException"): "is not found"}
# A call that answers a missing thing with a code that also means "denied": the listing settles it. Not listed: not
# there. Listed: the call was denied, and that is a refusal. (From memory: a rule that does not exist is answered so;
# the delete is held to the same rule as the read, so that a create that failed can be torn down.)
AMBIGUOUS = {("iot", "get-topic-rule"): ("UnauthorizedException", "--rule-name", "rules"),
             ("iot", "delete-topic-rule"): ("UnauthorizedException", "--rule-name", "rules")}
# What in a reply says that the listing goes on: a token that is not empty, a flag that is true. The CLI follows the
# pages of most listings by itself; for three of the driver's it has no paginator (its own data, 2.35.1: Firehose's
# streams, Athena's workgroups, a thing's named shadows), and the driver follows none. A reply that says "more" is
# refused wherever it is read: half a listing is not judged.
MORE_TOKENS: Tuple[str, ...] = ("NextToken", "nextToken", "NextMarker", "nextMarker", "NextContinuationToken", "ContinuationToken",
                               "PaginationToken", "position")
MORE_FLAGS: Tuple[str, ...] = ("HasMoreDeliveryStreams", "IsTruncated")
ERROR_CODE = re.compile(r"An error occurred \(([A-Za-z0-9.]+)\) when calling the ([A-Za-z0-9]+) operation")
# WHAT THE CLI'S SKELETON CANNOT DO (seen on CLI 2.35.1, offline, 2026-10-10; the offline validation limits below apply).
# The commands that take an output file know no --generate-cli-skeleton at all ("Unknown options"): their arguments
# are read by nothing before the account does.
SKELETON_UNSUPPORTED: Tuple[Tuple[str, str], ...] = (("lambda", "invoke"), ("iot-data", "update-thing-shadow"),
                                                     ("iot-data", "delete-thing-shadow"), ("iot-data", "get-thing-shadow"),
                                                     # Phase 6's push: a customization of the CLI, no operation of a service model, takes
                                                     # no skeleton either (from memory of the CLI's customizations; not seen offline)
                                                     ("ecr", "get-login-password"))
# And for many calls the CLI builds a sample reply that fails its OWN validation (a size of 0 where the model wants 1
# or more, a made-up id shorter than a real one) and exits 252 under the heading it would have for a bad value of ours.
# For such a call ONLY THE OPTIONS' NAMES, THE REQUIRED OPTIONS AND EACH SCALAR'S FORM WERE READ: the service model's
# validation of the call's own arguments never ran (wp8-item1's probe: with a --tags map whose value is no string and an
# --environment with an unknown member, the CLI's words for `lambda create-function` were the same eight sample lines).
# plan names these calls by service and operation (no value). The two are told apart line by line (sample_only()): a
# line is the call's own only when it names an option the call gave AND the value the call gave it, or says "in input",
# or says that a member is missing from or unknown in a document the call gave (by file or as a structure: the path's
# first member is an option of the call). The member is read by its WHOLE path: the sample reply of `athena
# get-work-group` has a member WorkGroup.Configuration.ExecutionRole whose made-up value has 13 characters, `WorkGroup`
# is also how the option --work-group reads, and a workgroup's name under a prefix of 8 characters has 13
# (WP6-verify-2: `plan` could never be clean under such a prefix). A path that goes on into a member (`.Name`) cannot be
# about an option that was given plain words, which have no member.
SAMPLE_LINE = re.compile(r"^Invalid (value|length|type) for parameter ([A-Za-z0-9_]+)([^,]*), value: ([^,]*)")
SAMPLE_INDEX = re.compile(r"^(?:\[[0-9]+\])*")
# the first member of the path a Missing/Unknown line names: up to a `.`, a `[` or the `:`
SAMPLE_MEMBER = re.compile(r"^(?:Missing required|Unknown) parameter in ([A-Za-z0-9_]+)")
SAMPLE_HEAD = "Parameter validation failed:"


def _plain(value: str) -> bool:
    """Whether an option's value is plain words: no file, no JSON, no shorthand of a structure or a map."""
    return not value.startswith(("file://", "fileb://", "{", "[")) and "=" not in value


def sample_only(call: "Call", said: str) -> bool:
    """Whether what the CLI said after --generate-cli-skeleton output is ONLY its own sample reply failing its own
    validation. Anything it cannot place counts as the call's own: a refusal that is looked at costs a minute, a bad
    argument that is waved through is first seen in the account."""
    head, sep, rest = said.partition(SAMPLE_HEAD)
    lines = [ln.strip() for ln in rest.split("\n") if ln.strip()]
    if not sep or "usage:" in head or "arguments are required" in head or not lines:
        return False
    given: Dict[str, List[str]] = {}
    name = ""
    for arg in call.args:
        if arg.startswith("--"):
            name = "".join(w.capitalize() for w in arg[2:].split("-"))
            given[name] = given[name[:1].lower() + name[1:]] = []
        elif name:
            given[name].append(arg)
            given[name[:1].lower() + name[1:]] = given[name]
    for line in lines:
        m = SAMPLE_LINE.match(line)
        if m:
            kind, member, value = m.group(1), m.group(2), m.group(4).strip()
            if member not in given:
                continue
            values = given[member]
            if not values or any(v.startswith(("file://", "fileb://")) for v in values):
                return False
            if SAMPLE_INDEX.sub("", m.group(3), count=1).strip():
                # the path goes on past the option's own name, and past any index of a list, into a member: the reply's when
                # every value the call gave is plain words; the call's own when it gave a structure in any form
                if all(_plain(v) for v in values):
                    continue
                return False
            if any((str(len(v)) if kind == "length" else v) == value for v in values):
                return False
        else:
            at = SAMPLE_MEMBER.match(line)
            if " in input:" in line or not at:
                return False
            # A member that is missing or unknown in a document the call gave (by file, or as a structure) is the CLI's
            # refusal of that document; so is it for an option given with no value. The sample reply's own member is told
            # by an option the call did not give, or gave as plain words, which have no member to lack.
            gave = given.get(at.group(1))
            if gave is not None and (not gave or not all(_plain(v) for v in gave)):
                return False
    return True


class TwinError(Exception):
    """A refusal, by name. Its text never holds a value of the names file or of a reply."""

    def __init__(self, name: str, detail: str, status: int = EXIT_REFUSED) -> None:
        super().__init__("%s: %s" % (name, detail))
        self.name = name
        self.detail = detail
        self.status = status


def refuse(name: str, detail: str) -> NoReturn:
    raise TwinError(name, detail)


# --------------------------------------------------------------------------------------------------- what is printed

def _usable_literal(value: str, masks: Set[str]) -> bool:
    return (len(value) >= REDACT.MIN_LITERAL and value == value.strip() and not any(ord(c) < 32 for c in value)
            and not any(value in mask for mask in masks))


class Out:
    """Everything this file prints. A text has the local directories replaced by their names, then goes through the
    redactor; what the redactor refuses is withheld, and its refusal (which holds no value) is printed instead."""

    def __init__(self) -> None:
        self.kinds: Dict[str, List[str]] = {}
        self.paths: List[Tuple[str, str]] = []
        self.literals: Any = REDACT.NONE
        self.stdout: Any = None
        self.stderr: Any = None
        home = os.path.expanduser("~")
        if home and home != "~":
            self.name(home, "<home>")
        self._build()

    def name(self, path: Any, mask: str) -> None:
        """A local directory is printed as `mask`, in every form a tool may write it."""
        p = os.path.abspath(str(path))
        forms = {p, p.replace("\\", "/")}
        try:
            real = os.path.realpath(p)
            forms |= {real, real.replace("\\", "/")}
        except OSError:
            pass
        for f in list(forms):
            if re.match(r"^[A-Za-z]:/", f):                      # Git Bash's form of a drive path
                forms.add("/" + f[0].lower() + f[2:])
                forms.add(f[0].lower() + f[1:])
                forms.add(f[0].upper() + f[1:])
        self.paths = sorted(set(self.paths) | {(f, mask) for f in forms if len(f) >= 3}, key=lambda t: (-len(t[0]), t[0]))

    def use(self, kinds: Dict[str, List[str]]) -> None:
        self.kinds = {k: list(v) for k, v in kinds.items()}
        self._build()

    def _build(self) -> None:
        kinds = {k: list(v) for k, v in self.kinds.items()}
        masks = set(REDACT.MASKS) | {"<%s>" % k for k in kinds} | {"<local>"}
        local = [v for v in (os.environ.get("USERNAME", ""), os.environ.get("USER", ""), os.environ.get("LOGNAME", ""))
                 if _usable_literal(v, masks)]
        if local:
            kinds["local"] = sorted(set(kinds.get("local", []) + local))
        self.literals = REDACT.Literals(kinds)

    def clean(self, text: str, as_json: bool = False) -> str:
        for form, mask in self.paths:
            text = text.replace(form, mask)
        try:
            return str(REDACT.redact_json(text, self.literals) if as_json else REDACT.redact_text(text, self.literals))
        except REDACT.RedactError as e:
            return "(withheld: %s)" % e

    def say(self, text: str = "", err: bool = False, as_json: bool = False) -> None:
        stream = (self.stderr or sys.stderr) if err else (self.stdout or sys.stdout)
        stream.write(self.clean(text, as_json).rstrip("\n") + "\n")
        stream.flush()


OUT = Out()


def say(text: str = "", err: bool = False, as_json: bool = False) -> None:
    OUT.say(text, err, as_json)


# --------------------------------------------------------------------------------------------------- local directories

def outside(value: Any, what: str) -> Path:
    """`value` as a directory outside every work tree, or a refusal that names no directory."""
    path = Path(os.path.abspath(os.path.expanduser(str(value))))
    why = REDACT.in_a_work_tree(path / "x")
    if why:
        refuse("inside-a-work-tree", "the %s would lie %s: it stays outside every work tree (nothing was read or written)" % (what, why))
    return path


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(str(tmp), str(path))


def dump(obj: Any) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=True) + "\n"


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --------------------------------------------------------------------------------------------------- the names file

PATH_KEYS = ("TWIN_THRESHOLDS", "TWIN_DERIVE", "TWIN_BREAKER_ZIP", "TWIN_CSR", "TWIN_CERTIFICATE_OUT", "TWIN_REHEARSAL_CSR",
             "TWIN_REHEARSAL_CERTIFICATE_OUT", "TWIN_ORIN_CSR", "TWIN_ORIN_CERTIFICATE_OUT")
NAME_KEYS: Dict[str, Tuple[bool, str]] = {
    "TWIN_ACCOUNT": (True, r"[0-9]{12}"),
    "TWIN_REGION": (False, r"[a-z]{2}(?:-[a-z]+)+-[0-9]"),
    "TWIN_PROFILE": (True, r"[A-Za-z0-9_.-]{8,64}"),
    "TWIN_OPERATOR_ROLE": (True, r"[A-Za-z0-9_.-]{8,64}"),
    "TWIN_OPERATOR_MFA": (False, r"[01]"),
    "TWIN_PREFIX": (True, r"[a-z][a-z0-9]{7,23}"),
    "TWIN_THING": (True, r"[A-Za-z0-9_-]{8,128}"),
    "TWIN_BUCKET_SUFFIX": (True, r"[a-z0-9]{8,16}"),
    "TWIN_NOTICE": (True, r"[01]"),
    "TWIN_NOTICE_ADDRESS": (False, r"[^@\s,=]{1,64}@[A-Za-z0-9.-]{1,180}\.[A-Za-z]{2,24}"),
    "TWIN_IOT_LOG_GROUP_ADOPT": (False, r"[01]"),
    "TWIN_SHARES": (False, r"[0-9.]{1,12},[0-9.]{1,12},[0-9.]{1,12}"),
    "TWIN_N_DAYS": (False, r"[0-9]{1,3}(?:\.[0-9]{1,9})?"),
    "TWIN_FAILURE_ACTION_TYPE": (False, r"[A-Za-z0-9]{1,64}"),
    "TWIN_RULE_COUNT_METRIC": (False, r"[A-Za-z0-9.]{1,128}"),
    "TWIN_RULE_COUNT_DIMENSIONS": (False, r"[A-Za-z0-9]{1,64}=[A-Za-z0-9_.:-]{1,128}(?:,[A-Za-z0-9]{1,64}=[A-Za-z0-9_.:-]{1,128})*"),
    "TWIN_RULE_COUNT_READING": (False, r"per_execution|per_5kb_unit"),
    # Phase 6 (spec 2.7): 1 adds the ECR steps; the pull role, given, adds the pull steps; the pull thing only if B3 finds that a
    # certificate with no thing gets no credentials (wp0-facts C9)
    "TWIN_ECR": (False, r"[01]"),
    "TWIN_PULL_ROLE": (False, r"[A-Za-z0-9_.-]{8,64}"),
    "TWIN_PULL_THING": (False, r"[A-Za-z0-9_-]{8,128}"),
}
NAME_KEYS.update({k: (False, r"[^\x00-\x1f]{1,1024}") for k in PATH_KEYS})
CONTROL_KEYS = ("TWIN_STATE", "TWIN_RENDER", "TWIN_AWS", "TWIN_NO_NAMES_FILE")
ROW_19_KEYS = ("TWIN_RULE_COUNT_METRIC", "TWIN_RULE_COUNT_DIMENSIONS", "TWIN_RULE_COUNT_READING")
NAMES_FILE = "names.env"
# The names every resource's own name is made of, the role and the profile every call is sent under, and the switch
# that decides whether the table has the notice's steps. A state records them with its first write, as salted
# fingerprints, and no command runs under other values than the ones its records were made under (hold_names()).
# The role and the profile are in no call's own arguments and so in no printed render: without them here an approval
# printed under one role was one `literals` away from running under another (the hard review, SHOULD 3). Row 19's
# three keys are NOT bound, since they are given while the twin stands: table() keeps their steps while the state
# records the alarm as made.
BOUND_NAMES = ("TWIN_ACCOUNT", "TWIN_REGION", "TWIN_PREFIX", "TWIN_THING", "TWIN_BUCKET_SUFFIX", "TWIN_OPERATOR_ROLE", "TWIN_PROFILE",
               "TWIN_NOTICE")
# The four of them that do not hold the one-command stop (hold_names()): `trip` is held to the account only. The role and
# the profile since 2026-10-12, the bucket's suffix and the notice's switch since 2026-10-16 (the owner's A4 answers): no
# call of a stop, its invoke or its four calls by hand, is made of any of the four.
STOP_NOT_HELD = ("TWIN_OPERATOR_ROLE", "TWIN_PROFILE", "TWIN_BUCKET_SUFFIX", "TWIN_NOTICE")
# The four of them that the manual stop's four calls by hand are made of. The certificate's id is a fact of the state: it is
# this twin's only when the state was made under these four as the names file gives them now (stop_certificate()).
STOP_NAMES = ("TWIN_ACCOUNT", "TWIN_REGION", "TWIN_PREFIX", "TWIN_THING")
# The one required key the stop needs no value of: its invoke is made of the prefix, its identity check is the account
# alone, and the four calls by hand carry no role. A names file that lost the key, or gives it in a form the driver does
# not take (a role renamed or deleted, and the line edited after it), does not cost the one-command stop: the lack is said
# and the trip goes on (names_given(), stop). The profile is NOT such a key: every call is sent under it.
STOP_NEEDS_NOT = ("TWIN_OPERATOR_ROLE",)
# BOUND ONCE RECORDED (Phase 6, spec 2.7). Not among BOUND_NAMES, which every state binds with its first write: a state made
# before Phase 6 records no fingerprint of them, and would be refused (names-changed) for a key it never stood on. Each key with
# the steps whose record binds it: a state records the key's fingerprint when one of its steps is recorded (Twin.bind_late()), and
# while one of its steps is ON RECORD in any form but `absent` and `deleted` (an owner's `verified`, an action's `done`, a record
# taken back as `stale` among them) every command but `trip` is refused under another value, or none. The pull role by every pull
# step: twinctl never deletes the owner's pull role, so once `apply pull-role` has read it the binding stays for good, as
# TWIN_OPERATOR_ROLE's does, and the way out is the twin's own (`literals` and `baseline --again` once nothing stands). The pull
# thing by its own step (fable#3): pull-attachment's detach and the certificate's teardown read it by that name, and under another
# one they would record "deleted" while the old thing kept the certificate. Nothing of a stop is made of either.
LATE_BOUND: Dict[str, Tuple[str, ...]] = {"TWIN_PULL_ROLE": PULL_STEPS, "TWIN_PULL_THING": ("pull-thing",)}
WINDOWS = sys.platform == "win32"


def names_given(state_dir: Path, lenient: bool = False, stop: bool = False) -> Tuple[Dict[str, str], Dict[str, str]]:
    """What the names file and the environment give: (the values, each in its key's form; for the keys whose value is NOT
    taken, why, as a clause that goes after the key's name and holds no value). Not lenient, every fault is a refusal by
    its name and the second is empty: that is read_names(), the reading every command stands on. WITH `stop`, THE ONE-COMMAND
    STOP'S OWN READING, one fault is no refusal: a key of STOP_NEEDS_NOT that is not set, or has not its form, is left out
    and named in the second, and every other fault is refused as for every command.

    LENIENT IS THE STOP'S OWN READING, for the file of the four calls by hand (hand_text()), and nothing else reads so.
    Nothing is refused: a names file that cannot be read gives nothing, a line or a variable that is no KEY=VALUE of a
    known key is passed over, and a value that has not its key's form, or is the one region the twin is not written
    for, is left out and its key named. A stop under a names file with one fault still gets every value that is in
    order. ONE VALUE IS NOT ASSUMED: the region has a default, and "a misspelt key must not read as unset" holds here
    too, so once anything was passed over unread a region that was not given is named as not taken, and its default
    is not put in its place."""
    values: Dict[str, str] = {}
    unfit: Dict[str, str] = {}
    holes = False                                                   # lenient: something of the names was passed over unread

    def bad(name: str, detail: str) -> None:
        if not lenient:
            refuse(name, detail)

    path = state_dir / NAMES_FILE
    if os.environ.get("TWIN_NO_NAMES_FILE", "") not in ("", "0"):
        pass
    elif path.is_file():
        try:
            text = path.read_text(encoding="utf-8-sig")             # a byte order mark an editor left is no part of the first key
        except (OSError, UnicodeDecodeError):
            bad("names-unreadable", "the state directory's %s cannot be read as UTF-8" % NAMES_FILE)
            text, holes = "", True
        for n, line in enumerate(text.split("\n"), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, eq, value = line.partition("=")
            key = key.strip()
            if not eq or key not in NAME_KEYS:
                bad("names-key-unknown", "line %d of the state directory's %s is no KEY=VALUE of a key twinctl knows (a misspelt key "
                    "must not read as unset)" % (n, NAMES_FILE))
                holes = True
                continue
            values[key] = value.strip()
            if WINDOWS and key in PATH_KEYS and re.match(r"^/[A-Za-z]/", values[key]):
                # Git Bash turns /e/... into E:/... on a command line and in the environment; nothing does in a file's text,
                # and Windows Python then looks for \e\... on the current drive (the hard review's NIT 5: input-missing)
                bad("names-path-form", "line %d of the state directory's %s gives %s in Git Bash's form (/x/...): the file is read by "
                    "Windows Python, which gets no path conversion. Write it as X:/..." % (n, NAMES_FILE, key))
    for key, value in os.environ.items():
        if not key.startswith("TWIN_") or key in CONTROL_KEYS:
            continue
        if key not in NAME_KEYS:
            bad("names-key-unknown", "the environment holds a TWIN_ variable twinctl does not know (variable %d of the TWIN_ ones, "
                "by name order): a misspelt key must not read as unset"
                % (sorted(k for k in os.environ if k.startswith("TWIN_")).index(key) + 1))
            holes = True
            continue
        values[key] = value.strip()
    for key, (required, pattern) in sorted(NAME_KEYS.items()):
        if stop and key in STOP_NEEDS_NOT and (values.get(key, "") == "" or not re.fullmatch(pattern, values[key])):
            # the stop needs no value of this key: its fault is said by the key (Twin puts it into `lacks`), and not refused
            unfit[key] = "is not set" if values.get(key, "") == "" else "is not given in the form twinctl takes for it"
            continue
        if key not in values or values[key] == "":
            values.pop(key, None)
            if required:
                bad("names-missing", "%s is not set, in the state directory's %s or the environment" % (key, NAMES_FILE))
            continue
        if not re.fullmatch(pattern, values[key]):
            bad("names-invalid", "%s does not have the form twinctl takes for it (sdv/cloud/.env.example says which); the value is "
                "not printed" % key)
            unfit[key] = "is not given in the form twinctl takes for it"
        elif key == "TWIN_REGION" and values[key] == GLOBAL_REGION:
            # HERE, where the names are held to their form, so that `literals`, `plan` and every other command refuse alike
            # and before anything is rendered. By the key, never by the value (which a refusal of this file never holds).
            bad("names-region-not-taken", "TWIN_REGION names the one region the twin is not written for (the value is not printed): the "
                "bucket's create passes a LocationConstraint, which the service refuses for that region, and the exit's check of the "
                "account's Block Public Access reads a second time through it, a read written for a twin that lives in another "
                "one. Give another region (sdv/cloud/.env.example)")
            unfit[key] = "names the one region the twin is not written for"
    for key in unfit:
        values.pop(key, None)
    if holes and "TWIN_REGION" not in values and "TWIN_REGION" not in unfit:
        unfit["TWIN_REGION"] = ("is not given, and its default is not put in its place: something of the names was passed over unread, "
                                "and a misspelt key must not read as unset")
    return values, unfit


def read_names(state_dir: Path) -> Dict[str, str]:
    """The names file's values with the environment's on top. A key that is not known is refused, in either."""
    return names_given(state_dir)[0]


def stop_names(prefix: str, thing: str, rehearsal: bool) -> Tuple[str, str, str]:
    """The three names the manual stop's four calls by hand are made of: (the rule, the device policy, the thing, which is the
    client's id), from the prefix and the thing's name. One place: Names takes them from here, and so does the file a
    stop writes before it has any Names (hand_text())."""
    p = prefix + ("rh" if rehearsal else "")
    return p + "_telemetry", p + "-device", (p + "-thing") if rehearsal else thing


def arn_of(service: str, region: str, account: str, resource: str) -> str:
    return "arn:aws:%s:%s:%s:%s" % (service, region, account, resource)


class Names:
    """Every name the twin's resources carry, derived from the names file. With `rehearsal`, A2's set: the same
    kinds under the prefix and two more letters, in a state of their own."""

    def __init__(self, values: Dict[str, str], rehearsal: bool = False) -> None:
        self.v = values
        self.rehearsal = rehearsal
        self.account = values["TWIN_ACCOUNT"]
        self.region = values.get("TWIN_REGION", REGION_DEFAULT)
        self.profile = values["TWIN_PROFILE"]
        self.operator_role = values.get("TWIN_OPERATOR_ROLE", "")           # "" only in a stop whose names file gives no usable one
        self.mfa = values.get("TWIN_OPERATOR_MFA", "1") == "1"
        self.prefix = values["TWIN_PREFIX"]
        self.notice = values["TWIN_NOTICE"] == "1"
        if not values["TWIN_THING"].startswith(self.prefix):
            refuse("names-invalid", "TWIN_THING does not begin with TWIN_PREFIX: the operator role's resources are the prefix's")
        p = self.prefix + ("rh" if rehearsal else "")
        self.p = p
        self.tag_key = TAG_KEY
        self.rule, self.policy, self.thing = stop_names(self.prefix, values["TWIN_THING"], rehearsal)
        self.bucket = "%s-telemetry-%s" % (p, values["TWIN_BUCKET_SUFFIX"])
        self.firehose_log_group = p + "-firehose-errors"
        self.firehose_log_stream = "delivery"
        self.stream = p + "-telemetry"
        self.glue_database = p + "_twin"
        self.glue_table = "telemetry"
        self.workgroup = p + "-twin"
        self.function = p + "-breaker"
        self.breaker_log_group = "/aws/lambda/" + self.function
        self.iot_log_group = IOT_LOG_GROUP
        self.topic = p + "-notice"
        self.rule_role = p + "-rule-role"
        self.firehose_role = p + "-firehose-role"
        self.iot_logging_role = p + "-iot-logging-role"
        self.breaker_role = p + "-breaker-role"
        self.alarm = {k: "%s-%s" % (p, k) for k in BREAKER_ALARMS + ("errors", "rule-count")}
        # Phase 6: the image transport's names. The repositories and the role alias are constants of the spec; the pull policy is
        # the prefix's like every IoT policy of the twin (the operator role's Policies statement); the pull role is the owner's. `ecr`
        # is the key's here; a Twin whose state records an ECR step as standing sets it whatever the key says (Twin.__init__)
        self.ecr = values.get("TWIN_ECR", "0") == "1"
        self.pull_role = values.get("TWIN_PULL_ROLE", "")
        self.pull_thing = values.get("TWIN_PULL_THING", "")
        if self.pull_thing and not self.pull_thing.startswith(self.prefix):
            refuse("names-invalid", "TWIN_PULL_THING does not begin with TWIN_PREFIX: the operator role's things are the prefix's")
        self.pull_policy = self.prefix + "-ecr-pull"
        self.repositories = ["%s/%s" % (ECR_NAMESPACE, app) for app in ECR_APPS]
        self.registry = "%s.dkr.ecr.%s.amazonaws.com" % (self.account, self.region)
        self._thresholds: Optional[Dict[str, int]] = None
        try:
            self.topics = TOPICS.Topics(self.thing, self.rule)
        except ValueError:
            refuse("names-invalid", "the thing's or the rule's name cannot go into a topic (sdv/connector/topics.py); the value is not "
                   "printed")

    def thresholds(self) -> Dict[str, int]:
        """The thresholds file's counts, read and checked once (load_thresholds)."""
        if self._thresholds is None:
            self._thresholds = load_thresholds(self)
        return self._thresholds

    def thresholds_sha256(self) -> str:
        """The sha256 of the thresholds file's bytes as they stand, for a file that load_thresholds takes (refused by
        the same names otherwise). It is what the burst tool is given as --thresholds-sha256: a hash, and no count."""
        self.thresholds()
        try:
            return hashlib.sha256(Path(os.path.expanduser(self.v["TWIN_THRESHOLDS"])).read_bytes()).hexdigest()
        except OSError:
            refuse("thresholds-missing", "the thresholds file could not be read again for its sha256")

    # --- ARNs: known from the names before anything exists
    def arn(self, service: str, resource: str, region: Optional[str] = None) -> str:
        return arn_of(service, self.region if region is None else region, self.account, resource)

    def role_arn(self, name: str) -> str:
        return "arn:aws:iam::%s:role/%s" % (self.account, name)

    def role_policy_name(self, name: str) -> str:
        return name + "-policy"

    @property
    def bucket_arn(self) -> str:
        return "arn:aws:s3:::" + self.bucket

    @property
    def function_arn(self) -> str:
        return self.arn("lambda", "function:" + self.function)

    @property
    def topic_arn(self) -> str:
        return self.arn("sns", self.topic)

    def alarm_arn(self, key: str) -> str:
        return self.arn("cloudwatch", "alarm:" + self.alarm[key])

    def log_group_arn(self, name: str) -> str:
        return self.arn("logs", "log-group:" + name)

    def path(self, key: str, what: str) -> Path:
        """A file the names file points at; refused by name when the key is unset or the file is not there."""
        if key not in self.v:
            refuse("input-unset", "%s is not set: %s" % (key, what))
        path = Path(os.path.expanduser(self.v[key]))
        if not path.is_file():
            refuse("input-missing", "the file %s names is not there: %s" % (key, what))
        return path

    def context(self) -> Dict[str, Any]:
        """The placeholders every template may use, less the ones a render looks up as it needs them (lookup())."""
        c: Dict[str, Any] = {
            "ACCOUNT": self.account, "REGION": self.region, "PREFIX": self.prefix, "TAG_KEY": self.tag_key,
            "BUCKET": self.bucket, "BUCKET_ARN": self.bucket_arn,
            "FIREHOSE_LOG_GROUP": self.firehose_log_group, "FIREHOSE_LOG_STREAM": self.firehose_log_stream,
            "FIREHOSE_LOG_GROUP_ARN": self.log_group_arn(self.firehose_log_group),
            "STREAM": self.stream, "STREAM_ARN": self.arn("firehose", "deliverystream/" + self.stream),
            "RULE": self.rule, "RULE_ARN": self.arn("iot", "rule/" + self.rule),
            "THING": self.thing, "CLIENT_ARN": self.arn("iot", "client/" + self.thing),
            "POLICY": self.policy, "POLICY_ARN": self.arn("iot", "policy/" + self.policy),
            "GLUE_DATABASE": self.glue_database, "GLUE_TABLE": self.glue_table,
            "FUNCTION": self.function, "FUNCTION_ARN": self.function_arn,
            "BREAKER_LOG_GROUP_ARN": self.log_group_arn(self.breaker_log_group),
            "IOT_LOG_GROUP": self.iot_log_group, "IOT_LOG_GROUP_ARN": self.log_group_arn(self.iot_log_group),
            "TOPIC_ARN": self.topic_arn,
            "RULE_ROLE_ARN": self.role_arn(self.rule_role), "FIREHOSE_ROLE_ARN": self.role_arn(self.firehose_role),
            "IOT_LOGGING_ROLE_ARN": self.role_arn(self.iot_logging_role), "BREAKER_ROLE_ARN": self.role_arn(self.breaker_role),
            "OPERATOR_ROLE_ARN": self.role_arn(self.operator_role),
            "FAILURE_ACTION_TYPE": self.v.get("TWIN_FAILURE_ACTION_TYPE", "Firehose"),
            "BREAKER_ACTIONS": [self.function_arn] + ([self.topic_arn] if self.notice else []),
            "NOTICE_ACTIONS": [self.topic_arn],
            # Phase 6: only the new templates use these
            "ECR_REPOSITORIES_ARN": self.arn("ecr", "repository/%s/*" % ECR_NAMESPACE), "ROLE_ALIAS_ARN": self.arn("iot", "rolealias/" + ROLE_ALIAS),
            "PULL_ROLE_ARN": self.role_arn(self.pull_role), "LIFECYCLE_KEEP": LIFECYCLE_KEEP,
        }
        for key in BREAKER_ALARMS + ("errors", "rule-count"):
            up = key.upper().replace("-", "_")
            c["ALARM_" + up] = self.alarm[key]
            c["ALARM_%s_ARN" % up] = self.alarm_arn(key)
            c["SID_" + up] = "alarm-" + key
        return c


# --------------------------------------------------------------------------------------------------- the thresholds

THRESHOLD_KEYS = {"bytes": "Firehose.IncomingBytes", "records": "Firehose.IncomingRecords", "shadow": "IoT.UpdateThingShadow.Accepted",
                  "publish": "IoT.PublishIn.Success", "failure": "IoT.RuleAction.Failure", "errors": "Lambda.Errors"}
RULE_COUNT_KEYS = {"per_execution": "IoT.RulesExecuted.per_execution", "per_5kb_unit": "IoT.RulesExecuted.per_5kb_unit"}
DECIDED_CAP_USD = 10.0                          # S10 (owner, 2026-10-04)
MODEL_MONTH_DAYS = 730.0 / 24.0                 # the model's month (gap r): the N a file is held to unless TWIN_N_DAYS names the owner's
DECIDED_THINGS = 1                              # gap ah
DECIDED_CONFIG_CHANGE_S = 60                    # gap i


def load_thresholds(n: Names) -> Dict[str, int]:
    """The thresholds of the file the names file points at: {alarm key: count}. Refused by name when the file is not
    there, when derive.py's own check does not pass it, or when a design field is not the decided value."""
    if "TWIN_THRESHOLDS" not in n.v:
        refuse("thresholds-unset", "TWIN_THRESHOLDS is not set: the alarms are rendered from the thresholds file derive.py wrote (WP5)")
    path = Path(os.path.expanduser(n.v["TWIN_THRESHOLDS"]))
    if REDACT.in_a_work_tree(path):
        refuse("thresholds-inside-a-work-tree", "the thresholds file stays outside every work tree")
    if not path.is_file():
        refuse("thresholds-missing", "the thresholds file is not there: the owner has not chosen the breaker's numbers, or derive.py "
               "refused them (the stop names rule)")
    derive = Path(os.path.expanduser(n.v["TWIN_DERIVE"])) if "TWIN_DERIVE" in n.v else path.parent / "derive.py"
    if not derive.is_file():
        refuse("thresholds-check-unavailable", "derive.py is not beside the thresholds file (or where TWIN_DERIVE says): its own check "
               "cannot be run, so no alarm is rendered")
    try:
        done = subprocess.run([sys.executable, "-B", str(derive), "--check", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              stdin=subprocess.DEVNULL, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        refuse("thresholds-check-unavailable", "derive.py could not be run")
    if done.returncode != 0:
        names = sorted(set(re.findall(r"refused: ([A-Za-z0-9_.:-]+):", done.stderr.decode("utf-8", "replace"))))
        refuse("thresholds-check-failed", "derive.py --check does not pass the thresholds file (exit %d; its refusals: %s)"
               % (done.returncode, ", ".join(names) or "none named"))
    try:
        doc = json.loads(path.read_text(encoding="ascii"))
        d, t = doc["design"], doc["thresholds"]
        if not isinstance(d, dict) or not isinstance(t, dict):
            raise TypeError
    except (OSError, ValueError, KeyError, TypeError):
        refuse("thresholds-unreadable", "the thresholds file is no thresholds document")

    def number(x: Any) -> bool:
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    if "TWIN_SHARES" not in n.v:
        refuse("thresholds-design:shares", "TWIN_SHARES is not set: the file's shares are held to the ones the owner chose")
    try:
        shares = [float(s) for s in n.v["TWIN_SHARES"].split(",")]
    except ValueError:
        refuse("names-invalid", "TWIN_SHARES is not three numbers")
    try:
        decided_n = float(n.v["TWIN_N_DAYS"]) if "TWIN_N_DAYS" in n.v else MODEL_MONTH_DAYS
    except ValueError:
        refuse("names-invalid", "TWIN_N_DAYS is no number")
    held: List[Tuple[str, bool]] = [
        ("cap_usd", number(d.get("cap_usd")) and d.get("cap_usd") == DECIDED_CAP_USD and d.get("decided_cap_usd") == DECIDED_CAP_USD),
        ("n_days", number(d.get("n_days")) and abs(d["n_days"] - decided_n) <= 1e-9),
        ("things", d.get("things") == DECIDED_THINGS and not isinstance(d.get("things"), bool)),
        ("alarms_priced", d.get("alarms_priced") == (7 if n.notice else 6) and not isinstance(d.get("alarms_priced"), bool)),
        ("config_change_s", d.get("config_change_s") == DECIDED_CONFIG_CHANGE_S and not isinstance(d.get("config_change_s"), bool)),
        ("batch_bytes", number(d.get("batch_bytes")) and d.get("batch_bytes") == d.get("batch_bytes_largest")),
        ("shares", all(number(d.get(k)) and abs(d[k] - s) <= 1e-12
                       for k, s in zip(("share_messages", "share_bytes", "share_shadow"), shares))),
    ]
    for field, ok in held:
        if not ok:
            refuse("thresholds-design:" + field, "the thresholds file's design field %s is not the decided value (the notice topic "
                   "decides the alarm count, TWIN_SHARES holds the owner's shares, and TWIN_N_DAYS the owner's N when it is not the "
                   "model's month)" % field)
    out: Dict[str, int] = {}
    keys = dict(THRESHOLD_KEYS)
    if not n.notice:
        keys.pop("errors")
    if "TWIN_RULE_COUNT_READING" in n.v:
        keys["rule-count"] = RULE_COUNT_KEYS[n.v["TWIN_RULE_COUNT_READING"]]
    for key, name in sorted(keys.items()):
        value = t.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            refuse("thresholds-value:" + name, "the thresholds file holds no whole count of 1 or more for %s" % name)
        out[key] = value
    for key in ("failure", "errors"):
        if out.get(key, 1) != 1:
            refuse("thresholds-value:" + THRESHOLD_KEYS[key], "the threshold of %s is not 1 (gaps q and t)" % THRESHOLD_KEYS[key])
    return out


# --------------------------------------------------------------------------------------------------- the state

def salt(top: Path) -> bytes:
    """The state directory's own random value: it salts the renders' hashes and the names' fingerprints, and never
    leaves the directory."""
    path = top / "salt"
    if not path.is_file():
        write_atomic(path, os.urandom(32))
    return path.read_bytes()


def fingerprint(s: bytes, key: str, value: str) -> str:
    """What a state records in place of one of the names it was made under: the key and the value, salted and hashed."""
    return hashlib.sha256(s + key.encode("ascii") + b"\0" + value.encode("utf-8")).hexdigest()[:32]


class State:
    """<state>/state.json: what each step did, the facts a reply gave, and (as salted fingerprints, `names`) the names it
    was made under. Written whole, by write-then-rename, after every call that changed anything: a run that stops
    half-way leaves what `teardown` finishes from. `blank` is a state that could not be read, for the stop alone: it
    knows nothing, and it is never written over what is there."""

    def __init__(self, directory: Path, blank: bool = False) -> None:
        self.dir = directory
        self.path = directory / "state.json"
        self.frozen = blank
        self.bound: Optional[Dict[str, str]] = None                 # the present names' fingerprints: recorded with the first write
        self.data: Dict[str, Any] = {"v": 1, "steps": {}, "facts": {}}
        if self.path.is_file() and not blank:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or data.get("v") != 1 or not isinstance(data.get("steps"), dict) \
                        or not isinstance(data.get("facts"), dict) or not isinstance(data.get("names", {}), dict) \
                        or not all(isinstance(e, dict) for e in data["steps"].values()):
                    raise ValueError
            except (OSError, ValueError):
                refuse("state-unreadable", "the state directory's state.json is not a state of this version: nothing is done on a "
                       "state that cannot be read")
            self.data = data

    def save(self) -> None:
        if self.frozen:
            return
        if "names" not in self.data and self.bound is not None:
            self.data["names"] = dict(self.bound)
        write_atomic(self.path, dump(self.data).encode("ascii"))

    def status(self, step: str) -> str:
        return str(self.data["steps"].get(step, {}).get("status", "absent"))

    def record(self, step: str, **fields: Any) -> None:
        entry = self.data["steps"].setdefault(step, {})
        entry.update(fields)
        entry["at"] = now()
        self.save()

    def done(self, step: str) -> List[int]:
        return list(self.data["steps"].get(step, {}).get("done", []))

    def sent(self, step: str) -> List[int]:
        """The create calls of a step that were sent, however each ended: the ones that went through (`done`), any whose
        reply was lost, and any the service answered with an error (an error does not say that nothing was made)."""
        return list(self.data["steps"].get(step, {}).get("sent", []))

    def fact(self, name: str) -> Optional[str]:
        value = self.data["facts"].get(name)
        return value if isinstance(value, str) else None

    def learn(self, **facts: str) -> None:
        self.data["facts"].update(facts)
        self.save()

    def forget(self, name: str) -> None:
        if self.data["facts"].pop(name, None) is not None:
            self.save()

    def drop(self, step: str) -> None:
        """Take a step's record out: the state then records nothing made for it."""
        if self.data["steps"].pop(step, None) is not None:
            self.save()


OURS = ("creating", "partial", "created", "unverified", "deleting")     # made here and not yet deleted: what "stands"
# What an action's `done` and an owner-made step's `verified` become once a step they stood on is deleted or made
# anew (take_back()): the record is of something that is no longer there. Applied again, it is `done` or `verified`.
STALE = "stale"


# --------------------------------------------------------------------------------------------------- templates, renders

PLACEHOLDER = re.compile(r"@@([A-Z0-9_]+)@@")


class Call(NamedTuple):
    service: str
    op: str
    args: Tuple[str, ...]
    write: bool

    def argv(self) -> List[str]:
        return [self.service, self.op] + list(self.args)


def R(service: str, op: str, *args: str) -> Call:
    return Call(service, op, tuple(args), False)


def W(service: str, op: str, *args: str) -> Call:
    return Call(service, op, tuple(args), True)


class Built(NamedTuple):
    creates: List[Call] = []
    reads: List[Tuple[str, Call]] = []
    deletes: List[Call] = []


class Render:
    """One step's documents and where they are written. A document is a template with every @@NAME@@ filled: a
    string that is one placeholder and nothing else takes the value as it is (a number, a list); a placeholder inside
    a longer string takes a string. Rendered, written out with sorted keys, parsed back, checked. `strict` is a render
    whose create calls may be sent (apply) or are to be judged whole (plan): a file a create takes its content from
    has to be there. A render for a read or a teardown is not strict: it sends no create."""

    def __init__(self, twin: "Twin", step: str, strict: bool = True) -> None:
        self.twin = twin
        self.step = step
        self.strict = strict
        self.dir = twin.render_dir / (("rehearsal-" if twin.n.rehearsal else "") + step)
        self.texts: Dict[str, str] = {}
        self.objs: Dict[str, Any] = {}
        self.provisional: Set[str] = set()
        self.inputs: Dict[str, str] = {}                            # the sha256 of each file a create call uploads, by its key
        self.unfit: Optional[Tuple[str, str]] = None                # why this render is printed and never applied: (a refusal's name, its sentence)
        self.context = twin.n.context()

    def input(self, key: str, what: str) -> Path:
        """A file a create call takes its content from (the signing request, the function's zip). Strict: refused by name
        when the key is unset or the file is not there. Otherwise only its place is taken: `status`, `teardown` and
        `verify-gone` send no create, and a throwaway input that is gone since must not keep a step from being read or
        deleted."""
        n = self.twin.n
        if self.strict:
            path = n.path(key, what)
            try:
                # THE CONTENT, not the path, is what an approval covers: the hash goes into the render's hash, into what is
                # printed and into the state (WP6's critic, problem 5: a zip replaced after the printing was uploaded)
                self.inputs[key] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                refuse("input-unreadable", "the file %s names is there and cannot be read: %s" % (key, what))
            return path
        return Path(os.path.expanduser(n.v.get(key, key.lower() + "-is-not-set")))

    def lookup(self, name: str, template: str) -> Any:
        if name in self.context:
            return self.context[name]
        n = self.twin.n
        if name in ("CERT_ID", "CERT_ARN"):
            cert = self.twin.state.fact("certificate_id")
            if cert is None:
                self.provisional.add("certificate")
                cert = PROVISIONAL_CERT_ID
            return cert if name == "CERT_ID" else n.arn("iot", "cert/" + cert)
        if name in ("PULL_CERT_ID", "PULL_CERT_ARN"):                # Phase 6: the pull certificate's, by the same rule
            cert = self.twin.state.fact("pull_certificate_id")
            if cert is None:
                self.provisional.add("pull-certificate")
                cert = PROVISIONAL_CERT_ID
            return cert if name == "PULL_CERT_ID" else n.arn("iot", "cert/" + cert)
        if name.startswith("THRESHOLD_"):
            key = name[len("THRESHOLD_"):].lower().replace("_", "-")
            if n.rehearsal:
                return 1
            thresholds = n.thresholds()
            if key not in thresholds:
                refuse("input-unset", "the reading of the rule-side count is not in the names file (TWIN_RULE_COUNT_READING): row 19 "
                       "waits for A4's readings")
            return thresholds[key]
        if name in ("RULE_COUNT_METRIC", "RULE_COUNT_DIMENSIONS"):
            for key in ROW_19_KEYS:
                if key not in n.v:
                    refuse("input-unset", "%s is not set: row 19 waits for A4's readings (and an alarm that was made from them is read "
                           "and deleted under them)" % key)
            if name == "RULE_COUNT_METRIC":
                return n.v["TWIN_RULE_COUNT_METRIC"]
            return [{"Name": pair.split("=", 1)[0], "Value": pair.split("=", 1)[1]} for pair in n.v["TWIN_RULE_COUNT_DIMENSIONS"].split(",")]
        refuse("template-placeholder-unknown", "the template %s names a placeholder twinctl has no value for (@@%s@@)" % (template, name))

    def _fill(self, node: Any, template: str) -> Any:
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                key = self._fill(k, template)
                if not isinstance(key, str) or key in out:
                    refuse("template-invalid", "the template %s has a key that does not render to one string of its own" % template)
                out[key] = self._fill(v, template)
            return out
        if isinstance(node, list):
            return [self._fill(v, template) for v in node]
        if not isinstance(node, str):
            return node
        whole = PLACEHOLDER.fullmatch(node)
        if whole:
            return self.lookup(whole.group(1), template)

        def one(m: Any) -> str:
            value = self.lookup(m.group(1), template)
            if not isinstance(value, str):
                refuse("template-invalid", "the template %s puts @@%s@@, which is no string, inside a string" % (template, m.group(1)))
            return value

        return PLACEHOLDER.sub(one, node)

    def doc(self, name: str, template: Optional[str] = None, edit: Optional[Callable[[Any], Any]] = None) -> Any:
        """Render templates/<template>.json as the document `name`, check it, keep it."""
        template = template or name
        try:
            raw = json.loads((TEMPLATES / (template + ".json")).read_text(encoding="ascii"))
        except (OSError, ValueError):
            refuse("template-invalid", "the template %s is not there, or is not JSON" % template)
        obj = self._fill(raw, template)
        if edit is not None:
            obj = edit(obj)
        return self.put(name, obj, template)

    def fragment(self, template: str) -> Any:
        """templates/<template>.json filled, and NOT kept as a document of the render: a part another document is made of (the
        operator policy's Phase 6 statements), checked as the document it goes into."""
        try:
            raw = json.loads((TEMPLATES / (template + ".json")).read_text(encoding="ascii"))
        except (OSError, ValueError):
            refuse("template-invalid", "the template %s is not there, or is not JSON" % template)
        return self._fill(raw, template)

    def put(self, name: str, obj: Any, check: Optional[str] = None) -> Any:
        text = dump(obj)
        if "@@" in text or json.loads(text) != obj:
            refuse("template-invalid", "the document %s does not render to JSON that reads back as itself" % name)
        check_document(check or name, obj, self.twin.n)
        self.texts[name] = text
        self.objs[name] = obj
        return obj

    def obj(self, name: str) -> Any:
        return self.objs[name]

    def url(self, name: str) -> str:
        """file://<the document's path>, with forward slashes: what a native Windows CLI opens, and a POSIX one."""
        if name not in self.texts:
            raise KeyError(name)
        return "file://" + (self.dir / (name + ".json")).as_posix()

    def write(self) -> None:
        for name, text in sorted(self.texts.items()):
            write_atomic(self.dir / (name + ".json"), text.encode("ascii"))


def file_url(path: Path, binary: bool = False) -> str:
    return ("fileb://" if binary else "file://") + Path(os.path.abspath(str(path))).as_posix()


# --------------------------------------------------------------------------------------------------- the documents' checks

V = "2012-10-17"
OPERATOR_ALLOW = (
    "iot:CreateCertificateFromCsr", "iot:ListAttachedPolicies", "iot:GetV2LoggingOptions", "iot:SetV2LoggingOptions",
    "iot:DescribeEndpoint", "iot:ListThings", "iot:ListCertificates", "iot:ListPolicies", "iot:ListTopicRules", "iot:ListAuthorizers",
    "iot:ListDomainConfigurations", "s3:ListAllMyBuckets", "s3:GetAccountPublicAccessBlock", "logs:DescribeLogGroups",
    "firehose:ListDeliveryStreams", "glue:GetDatabases", "athena:ListWorkGroups", "lambda:ListFunctions", "sns:ListTopics",
    "cloudwatch:DescribeAlarms", "cloudwatch:GetMetricData", "cloudwatch:ListMetrics", "tag:GetResources",
    "ec2:DescribeSecurityGroups", "cognito-identity:ListIdentityPools",
    "iot:CreateThing", "iot:DescribeThing", "iot:DeleteThing", "iot:ListThingPrincipals", "iot:ListThingPrincipalsV2",
    "iot:AttachThingPrincipal", "iot:DetachThingPrincipal", "iot:GetThingShadow", "iot:UpdateThingShadow", "iot:DeleteThingShadow",
    "iot:ListNamedShadowsForThing", "iot:UpdateCertificate", "iot:AttachPolicy", "iot:DetachPolicy", "iot:DescribeCertificate",
    "iot:DeleteCertificate", "iot:CreateTopicRule", "iot:GetTopicRule", "iot:DeleteTopicRule", "iot:EnableTopicRule",
    "iot:DisableTopicRule", "iot:TagResource", "iot:CreatePolicy", "iot:GetPolicy", "iot:DeletePolicy", "iot:ListTargetsForPolicy",
    "iot:DeleteConnection",
    "s3:CreateBucket", "s3:DeleteBucket", "s3:ListBucket", "s3:GetBucketLocation", "s3:PutBucketPublicAccessBlock",
    "s3:GetBucketPublicAccessBlock", "s3:PutBucketOwnershipControls", "s3:GetBucketOwnershipControls", "s3:PutEncryptionConfiguration",
    "s3:GetEncryptionConfiguration", "s3:PutLifecycleConfiguration", "s3:GetLifecycleConfiguration", "s3:PutBucketPolicy",
    "s3:GetBucketPolicy", "s3:GetBucketPolicyStatus", "s3:PutBucketTagging", "s3:GetBucketTagging", "s3:GetBucketVersioning",
    "s3:GetObject", "s3:DeleteObject", "s3:PutObject",
    "logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:PutRetentionPolicy", "logs:CreateLogStream", "logs:DescribeLogStreams",
    "logs:GetLogEvents", "logs:FilterLogEvents", "logs:TagResource",
    "firehose:CreateDeliveryStream", "firehose:DescribeDeliveryStream", "firehose:DeleteDeliveryStream", "firehose:TagDeliveryStream",
    "glue:CreateDatabase", "glue:GetDatabase", "glue:DeleteDatabase", "glue:CreateTable", "glue:GetTable", "glue:DeleteTable",
    "athena:CreateWorkGroup", "athena:GetWorkGroup", "athena:DeleteWorkGroup", "athena:StartQueryExecution", "athena:GetQueryExecution",
    "athena:GetQueryResults", "athena:StopQueryExecution", "athena:TagResource",
    "lambda:CreateFunction", "lambda:GetFunction", "lambda:DeleteFunction", "lambda:InvokeFunction", "lambda:GetPolicy",
    "lambda:RemovePermission", "lambda:PutFunctionConcurrency", "lambda:GetFunctionConcurrency", "lambda:DeleteFunctionConcurrency",
    "lambda:ListFunctionUrlConfigs", "lambda:TagResource", "lambda:AddPermission",
    "sns:CreateTopic", "sns:DeleteTopic", "sns:GetTopicAttributes", "sns:SetTopicAttributes", "sns:ListSubscriptionsByTopic",
    "sns:ConfirmSubscription", "sns:Unsubscribe", "sns:TagResource", "sns:Subscribe",
    "cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms", "cloudwatch:SetAlarmState", "cloudwatch:TagResource",
    "iam:PassRole", "iam:GetRole", "iam:GetRolePolicy", "apigateway:GET",
)
# The Deny of Cognito's identity pools names the three actions that make a pool or give it roles, not the service: an
# explicit Deny wins over the Allow of the same document, and the exit's own check reads the pools (A5). No call of the
# driver reads the user pools or ECR Public, so those two stay whole.
OPERATOR_DENY = (
    "lambda:CreateFunctionUrlConfig", "lambda:UpdateFunctionUrlConfig", "iot:CreateAuthorizer", "iot:UpdateAuthorizer",
    "iot:SetDefaultAuthorizer", "iot:CreateDomainConfiguration", "iot:UpdateDomainConfiguration", "iot:CreateTopicRuleDestination",
    "iot:UpdateTopicRuleDestination", "iot:ConfirmTopicRuleDestination", "apigateway:POST", "apigateway:PUT", "apigateway:PATCH",
    "apigateway:DELETE", "cognito-identity:CreateIdentityPool", "cognito-identity:UpdateIdentityPool",
    "cognito-identity:SetIdentityPoolRoles", "cognito-idp:*", "ecr-public:*", "s3:PutAccountPublicAccessBlock", "s3:PutBucketAcl",
    "s3:PutObjectAcl", "s3:PutObjectVersionAcl", "sns:Subscribe", "lambda:AddPermission",
)
# PHASE 6 (D8): what the operator role's policy allows in addition, each list rendered only with its key (TWIN_ECR,
# TWIN_PULL_ROLE), so that with neither the render is the one A1 row 3 made the role from. Each action on the narrowest resource
# the Service Authorization Reference gives it (the AWS Service Authorization Reference): the ones with no resource type, and the
# account's repository listing (a listing names no repository, so no repository's ARN can hold it), on `*` in NoResourceType;
# the repository actions on the twin's repositories (EcrRepositories); the alias's on that one alias (PullRoleAlias); the pull
# role's reads and its PassRole on that one role (ReadAndPassThePullRole). No repository policy, registry policy, replication,
# pull-through cache or scanning WRITE is allowed.
OPERATOR_ALLOW_ECR = (
    "ecr:GetAuthorizationToken", "ecr:DescribeRegistry", "ecr:GetRegistryPolicy", "ecr:DescribePullThroughCacheRules",
    "ecr:GetRegistryScanningConfiguration", "ecr:DescribeRepositories", "ecr-public:DescribeRepositories",
    "ecr:CreateRepository", "ecr:DeleteRepository", "ecr:TagResource", "ecr:PutLifecyclePolicy", "ecr:GetLifecyclePolicy",
    "ecr:DeleteLifecyclePolicy", "ecr:GetRepositoryPolicy", "ecr:ListImages", "ecr:DescribeImages", "ecr:BatchDeleteImage",
    "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage",
    "ecr:BatchGetImage",
)
OPERATOR_ALLOW_PULL = ("iot:ListRoleAliases", "iot:CreateRoleAlias", "iot:DescribeRoleAlias", "iot:DeleteRoleAlias", "iam:GetRole",
                       "iam:GetRolePolicy", "iam:PassRole")
# What each policy document allows, and denies: the second copy the templates are held to. An action a template
# gains or loses is refused at every render until this list says the same.
ALLOWS: Dict[str, Tuple[str, ...]] = {
    "device-policy": ("iot:Connect", "iot:Publish", "iot:Subscribe", "iot:Receive"),
    "rule-role-policy": ("firehose:PutRecord",),
    "firehose-role-policy": ("s3:AbortMultipartUpload", "s3:GetBucketLocation", "s3:GetObject", "s3:ListBucket",
                             "s3:ListBucketMultipartUploads", "s3:PutObject", "logs:PutLogEvents"),
    "iot-logging-role-policy": ("logs:CreateLogStream", "logs:PutLogEvents"),
    "breaker-role-policy": ("iot:UpdateCertificate", "iot:DetachPolicy", "iot:DescribeCertificate", "iot:DisableTopicRule",
                            "iot:GetTopicRule", "iot:DeleteConnection", "iot:ListTargetsForPolicy", "logs:CreateLogStream",
                            "logs:PutLogEvents"),
    "operator-role-policy": OPERATOR_ALLOW,
    "bucket-policy": (),
    "topic-policy": ("sns:Publish",),
    "function-policy": ("lambda:InvokeFunction",),
    "function-policy-rule-count": ("lambda:InvokeFunction",),
    # Phase 6: the pull role pulls and does nothing else (no BatchImportUpstreamImage, which AWS's pull-only managed policy holds
    # for a pull-through cache: wp0-facts R3); the pull certificate's IoT policy takes the role alias's credentials and nothing else
    "pull-role-policy": ("ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"),
    "pull-policy": ("iot:AssumeRoleWithCertificate",),
}
DENIES: Dict[str, Tuple[str, ...]] = {"operator-role-policy": OPERATOR_DENY, "bucket-policy": ("s3:*", "s3:PutObject")}
TRUSTS = {"rule-role-trust": "iot.amazonaws.com", "firehose-role-trust": "firehose.amazonaws.com",
          "iot-logging-role-trust": "iot.amazonaws.com", "breaker-role-trust": "lambda.amazonaws.com", "operator-role-trust": "",
          "pull-role-trust": "credentials.iot.amazonaws.com"}


def expected_actions(doc_id: str, n: "Names") -> Tuple[Set[str], Set[str]]:
    """What a policy document allows and denies by the lists above, for these names: the operator role's gains OPERATOR_ALLOW_ECR,
    and its Deny names ECR Public's writes in place of ecr-public:*, with TWIN_ECR=1; it gains OPERATOR_ALLOW_PULL with
    TWIN_PULL_ROLE. Every other document is its lists' alone."""
    allows, denies = set(ALLOWS[doc_id]), set(DENIES.get(doc_id, ()))
    if doc_id == "operator-role-policy":
        if n.ecr:
            allows |= set(OPERATOR_ALLOW_ECR)
            denies = (denies - {"ecr-public:*"}) | set(ECR_PUBLIC_WRITES)
        if n.pull_role:
            allows |= set(OPERATOR_ALLOW_PULL)
    return allows, denies


def wildcard_exceptions(n: Names) -> Dict[Tuple[str, str], Tuple[str, ...]]:
    """THE EXCEPTIONS, here and nowhere else: the resources of an Allow statement that may hold a wildcard, each as the
    exact string it renders to. Everything else with `*` or `?` in an action or a resource is refused. A Deny
    statement is not held to the rule (a wider Deny only refuses more): the operator role's three and the bucket
    policy's two. The plan's list: the operator role's actions that have no resource type, its cert/* and <P>*
    resources, and the stream wildcard after a log group's ARN. One kind the plan's list lacks and an object permission
    cannot be written without: a key wildcard after one of the bucket's fixed prefixes."""
    p, a, reg = n.prefix, n.account, n.region
    iot = "arn:aws:iot:%s:%s:" % (reg, a)
    logs = "arn:aws:logs:%s:%s:log-group:" % (reg, a)
    fn = "arn:aws:lambda:%s:%s:function:%s*" % (reg, a, p)
    sns = "arn:aws:sns:%s:%s:%s*" % (reg, a, p)
    op = "operator-role-policy"
    out: Dict[Tuple[str, str], Tuple[str, ...]] = {
        (op, "NoResourceType"): ("*",),
        (op, "Things"): (iot + "thing/%s*" % p,),
        (op, "Certificates"): (iot + "cert/*",),
        (op, "Rules"): (iot + "rule/%s*" % p,),
        (op, "Policies"): (iot + "policy/%s*" % p,),
        (op, "Clients"): (iot + "client/%s*" % p,),
        (op, "Bucket"): ("arn:aws:s3:::%s*" % p,),
        (op, "AthenaResults"): (n.bucket_arn + "/athena-results/*",),                    # the one bucket: a `*` of IAM takes `/` too
        (op, "LogGroups"): (logs + p + "*", logs + "/aws/lambda/" + p + "*", logs + IOT_LOG_GROUP + "*"),
        (op, "Stream"): ("arn:aws:firehose:%s:%s:deliverystream/%s*" % (reg, a, p),),
        # the third: the delete of a database is authorised on every table AND every user-defined function in it (the
        # service authorization reference lists that resource type as required for glue:DeleteDatabase, read 2026-10-12:
        # codex-review T12). The twin makes no function; without the resource the teardown's delete could be refused.
        (op, "Glue"): ("arn:aws:glue:%s:%s:database/%s*" % (reg, a, p), "arn:aws:glue:%s:%s:table/%s*/*" % (reg, a, p),
                       "arn:aws:glue:%s:%s:userDefinedFunction/%s*/*" % (reg, a, p)),
        (op, "Workgroup"): ("arn:aws:athena:%s:%s:workgroup/%s*" % (reg, a, p),),
        (op, "Function"): (fn,),
        (op, "FunctionInvokedByAlarmsOnly"): (fn,),
        (op, "Topic"): (sns,),
        (op, "TopicSubscribedByEmailOnly"): (sns,),
        (op, "Alarms"): ("arn:aws:cloudwatch:%s:%s:alarm:%s*" % (reg, a, p),),
        ("firehose-role-policy", "Objects"): (n.bucket_arn + "/telemetry/*", n.bucket_arn + "/errors/*"),
        ("iot-logging-role-policy", "Logs"): (n.log_group_arn(n.iot_log_group) + ":log-stream:*",),
        ("breaker-role-policy", "Logs"): (n.log_group_arn(n.breaker_log_group) + ":log-stream:*",),
    }
    # Phase 6 (spec 5 item 5), each only with its key: the twin's repositories, for the operator's ECR actions and the pull role's
    # two, and nothing else; and the pull role's GetAuthorizationToken, an action with no resource type, on * as the spec gives it
    repositories = n.arn("ecr", "repository/%s/*" % ECR_NAMESPACE)
    if n.ecr:
        out[(op, "EcrRepositories")] = (repositories,)
    if n.pull_role:
        out[("pull-role-policy", "PullFromTheTwinsRepositories")] = (repositories,)
        out[("pull-role-policy", "GetTheToken")] = ("*",)
    return out


def _listed(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else [value]


def canon_policy(doc: Any) -> Any:
    """A policy document in a form two spellings of one policy share: a string for a list of one, the order of a
    list, the case of a condition key. A document that is no policy gives None."""
    try:
        if isinstance(doc, str):
            doc = json.loads(doc)
        statements = []
        for st in _listed(doc["Statement"]):
            c: Dict[str, Any] = {}
            for k, v in st.items():
                if k in ("Action", "NotAction", "Resource", "NotResource"):
                    c[k] = sorted(str(x) for x in _listed(v))
                elif k == "Principal" and isinstance(v, dict):
                    c[k] = {pk: sorted(str(x) for x in _listed(pv)) for pk, pv in v.items()}
                elif k == "Condition":
                    c[k] = {op: {ck.lower(): sorted(str(x).lower() if isinstance(x, bool) else str(x) for x in _listed(cv))
                                 for ck, cv in body.items()} for op, body in v.items()}
                else:
                    c[k] = v
            statements.append(json.dumps(c, sort_keys=True))
        return {"Version": doc.get("Version"), "Statement": sorted(statements)}
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def subset(want: Any, got: Any) -> bool:
    """Whether `got` holds everything `want` says: a reply may carry more keys than the intent, never other values."""
    if isinstance(want, dict):
        return isinstance(got, dict) and all(k in got and subset(v, got[k]) for k, v in want.items())
    if isinstance(want, list):
        if not isinstance(got, list) or len(want) != len(got):
            return False
        left = list(got)
        for w in want:
            for i, g in enumerate(left):
                if subset(w, g):
                    del left[i]
                    break
            else:
                return False
        return True
    if isinstance(want, bool) or isinstance(got, bool):
        return want is got
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        return float(want) == float(got)
    return bool(want == got)


def _wild(text: Any) -> bool:
    return not isinstance(text, str) or "*" in text or "?" in text


def check_policy(doc_id: str, obj: Any, n: Names) -> None:
    """A policy document: its statements have a Sid each, its actions are the expected set, and nothing an Allow
    statement names holds a wildcard that is not on the list of exceptions."""
    def bad(why: str) -> NoReturn:
        refuse("document-refused:" + doc_id, why)

    if not isinstance(obj, dict) or obj.get("Version") != V or not isinstance(obj.get("Statement"), list) or not obj["Statement"]:
        bad("it is no policy document of version %s with a list of statements" % V)
    exceptions = wildcard_exceptions(n)
    allows: Set[str] = set()
    denies: Set[str] = set()
    sids: Set[str] = set()
    for i, st in enumerate(obj["Statement"], 1):
        where = "statement %d" % i
        if not isinstance(st, dict) or not isinstance(st.get("Sid"), str) or st["Sid"] in sids or st.get("Effect") not in ("Allow", "Deny"):
            bad("%s has no Sid of its own, or an Effect that is neither Allow nor Deny" % where)
        sids.add(st["Sid"])
        if "Action" not in st or "NotAction" in st:
            bad("%s names its actions by NotAction, or names none" % where)
        actions = _listed(st["Action"])
        if st["Effect"] == "Deny":
            denies.update(str(a) for a in actions)
            continue
        allows.update(str(a) for a in actions)
        if any(_wild(a) for a in actions):
            bad("%s allows an action with a wildcard" % where)
        if "NotResource" in st:
            bad("%s allows by NotResource" % where)
        allowed = exceptions.get((doc_id, st["Sid"]), ())
        for res in _listed(st.get("Resource", [])):
            if _wild(res) and res not in allowed:
                bad("%s allows on a resource with a wildcard that is not on the list of exceptions" % where)
        principal = st.get("Principal")
        if principal is not None and (not isinstance(principal, dict) or any(_wild(p) for v in principal.values() for p in _listed(v))):
            bad("%s allows a wildcard principal" % where)
        if "Resource" not in st and "Principal" not in st:
            bad("%s names neither a resource nor a principal" % where)
    want_allows, want_denies = expected_actions(doc_id, n)
    if allows != want_allows or denies != want_denies:
        bad("its action set is not the expected one (%d allowed, %d denied; expected %d and %d)"
            % (len(allows), len(denies), len(want_allows), len(want_denies)))


def check_trust(doc_id: str, obj: Any, n: Names) -> None:
    def bad(why: str) -> NoReturn:
        refuse("document-refused:" + doc_id, why)

    try:
        st, = obj["Statement"]
        if obj["Version"] != V or st["Effect"] != "Allow" or st["Action"] != "sts:AssumeRole" or set(st) - {"Sid", "Effect", "Principal",
                                                                                                         "Action", "Condition"}:
            raise ValueError
        principal = st["Principal"]
    except (KeyError, TypeError, ValueError):
        bad("it is no trust policy of one Allow statement for sts:AssumeRole")
    service = TRUSTS[doc_id]
    if service:
        if principal != {"Service": service}:
            bad("it does not name the one service")
        if st.get("Condition", {}).get("StringEquals", {}).get("aws:SourceAccount") != n.account:
            bad("it has no source-account condition")
    elif principal != {"AWS": "arn:aws:iam::%s:root" % n.account}:
        bad("it does not name the account, and only the account")


def _check_alarms(doc_id: str, obj: Any, n: Names) -> None:
    def bad(why: str) -> NoReturn:
        refuse("document-refused:" + doc_id, why)

    dims = {"bytes": [("DeliveryStreamName", n.stream)], "records": [("DeliveryStreamName", n.stream)],
            "shadow": [("Protocol", "MQTT")], "publish": [("Protocol", "MQTT")], "errors": [("FunctionName", n.function)]}
    want = {"alarms": list(BREAKER_ALARMS), "alarm-notice": ["errors"], "alarm-rule-count": ["rule-count"]}[doc_id]
    if n.rehearsal:
        want = ["bytes"]
    if not isinstance(obj, list) or [a.get("Key") if isinstance(a, dict) else None for a in obj] != want:
        bad("it is not the alarms %s, in that order" % ", ".join(want))
    for a in obj:
        key = a["Key"]
        fixed = {"Statistic": "Sum", "Period": 300, "EvaluationPeriods": 1, "DatapointsToAlarm": 1, "TreatMissingData": "notBreaching",
                 "ComparisonOperator": "GreaterThanOrEqualToThreshold", "ActionsEnabled": True, "AlarmName": n.alarm[key]}
        if any(a.get(k) != v or type(a.get(k)) is not type(v) for k, v in fixed.items()):
            bad("the alarm %s is not Sum over 300 s, 1 of 1, at or above its threshold, missing data not breaching, actions enabled" % key)
        if isinstance(a.get("Threshold"), bool) or not isinstance(a.get("Threshold"), int) or a["Threshold"] < 1:
            bad("the alarm %s has no whole threshold of 1 or more" % key)
        if a["Threshold"] != (1 if n.rehearsal else n.thresholds().get(key)):
            bad("the alarm %s does not carry the threshold of the thresholds file" % key)
        got = [(d.get("Name"), d.get("Value")) for d in a.get("Dimensions", []) if isinstance(d, dict)]
        if key == "failure":
            ok = len(got) == 2 and got[0] == ("RuleName", n.rule) and got[1][0] == "ActionType" and isinstance(got[1][1], str)
        elif key == "rule-count":
            ok = bool(got) and all(isinstance(x, str) and x for pair in got for x in pair)
        else:
            ok = got == dims[key]
        if not ok or len(got) != len(a.get("Dimensions", [])):
            bad("the alarm %s does not have its dimension set (gap q)" % key)
        actions = a.get("AlarmActions")
        expected = [] if n.rehearsal else ([n.topic_arn] if key == "errors" else [n.function_arn] + ([n.topic_arn] if n.notice else []))
        if actions != expected:
            bad("the alarm %s does not target what it has to (the function, and the notice topic when there is one)" % key)


def _check_function_policy(doc_id: str, obj: Any, n: Names) -> None:
    check_policy(doc_id, obj, n)
    keys = list(BREAKER_ALARMS) if doc_id == "function-policy" else ["rule-count"]
    want = canon_policy({"Version": V, "Statement": [
        {"Sid": "alarm-" + k, "Effect": "Allow", "Principal": {"Service": ALARMS_PRINCIPAL}, "Action": "lambda:InvokeFunction",
         "Resource": n.function_arn, "Condition": {"StringEquals": {"AWS:SourceAccount": n.account},
                                                   "ArnLike": {"AWS:SourceArn": n.alarm_arn(k)}}} for k in keys]})
    if canon_policy(obj) != want:
        refuse("document-refused:" + doc_id, "it is not one statement per alarm, each for the alarms' principal, this account and that "
               "one alarm's ARN")


def _check_exact(expected: Callable[[Names], Any]) -> Callable[[str, Any, Names], None]:
    def check(doc_id: str, obj: Any, n: Names) -> None:
        if obj != expected(n):
            refuse("document-refused:" + doc_id, "it is not the design value it is held to")
    return check


def _check_rule(doc_id: str, obj: Any, n: Names) -> None:
    def bad(why: str) -> NoReturn:
        refuse("document-refused:" + doc_id, why)

    if not isinstance(obj, dict) or set(obj) != {"sql", "awsIotSqlVersion", "ruleDisabled", "actions"}:
        bad("it has other fields than the SQL, its version, ruleDisabled and the actions")
    if obj["ruleDisabled"] is not True:
        bad("the rule is not created disabled")
    actions = obj["actions"]
    if not isinstance(actions, list) or len(actions) != 1 or not isinstance(actions[0], dict) or list(actions[0]) != ["firehose"]:
        bad("it does not have exactly one action, a firehose one")
    fh = actions[0]["firehose"]
    if fh != {"roleArn": n.role_arn(n.rule_role), "deliveryStreamName": n.stream, "separator": "\n", "batchMode": False}:
        bad("the firehose action is not the stream, the rule's role, a newline separator and batchMode false")
    sql = obj["sql"]
    if not isinstance(sql, str) or re.search(r"\bfrom\b", sql, re.I) or "principal(" in sql.lower() or "topic(1) AS thing" not in sql:
        bad("the SQL has a FROM, or names the principal, or does not take the thing from the topic")


def _check_bucket_policy(doc_id: str, obj: Any, n: Names) -> None:
    check_policy(doc_id, obj, n)
    b = n.bucket_arn
    want = canon_policy({"Version": V, "Statement": [
        {"Sid": "DenyRequestsWithoutTls", "Effect": "Deny", "Principal": "*", "Action": "s3:*", "Resource": [b, b + "/*"],
         "Condition": {"Bool": {"aws:SecureTransport": "false"}}},
        {"Sid": "DenyPutOutsideTheThreePrefixes", "Effect": "Deny", "Principal": "*", "Action": "s3:PutObject",
         "NotResource": [b + "/telemetry/*", b + "/errors/*", b + "/athena-results/*"]}]})
    if canon_policy(obj) != want:
        refuse("document-refused:" + doc_id, "it is not the two Deny statements: requests without TLS, and PutObject outside the three "
               "prefixes")


def _check_topic_policy(doc_id: str, obj: Any, n: Names) -> None:
    check_policy(doc_id, obj, n)
    st = obj["Statement"]
    if len(st) != 1 or st[0].get("Principal") != {"Service": "cloudwatch.amazonaws.com"} or st[0].get("Resource") != n.topic_arn \
            or st[0].get("Condition") != {"StringEquals": {"aws:SourceAccount": n.account}}:
        refuse("document-refused:" + doc_id, "it is not one statement: publish by the alarms' service, from this account")


def _check_device_policy(doc_id: str, obj: Any, n: Names) -> None:
    check_policy(doc_id, obj, n)
    t = n.topics
    iot = "arn:aws:iot:%s:%s:" % (n.region, n.account)
    by_action = {str(st.get("Action")): sorted(_listed(st.get("Resource"))) for st in obj["Statement"]}
    want = {"iot:Connect": [iot + "client/" + t.client_id], "iot:Publish": sorted(iot + "topic/" + x for x in t.publish),
            "iot:Subscribe": sorted(iot + "topicfilter/" + x for x in t.subscribe), "iot:Receive": sorted(iot + "topic/" + x for x in t.subscribe)}
    if by_action != want or len(obj["Statement"]) != 4:
        refuse("document-refused:" + doc_id, "its topics are not exactly the connector's (sdv/connector/topics.py)")
    connect = [st for st in obj["Statement"] if st.get("Action") == "iot:Connect"][0]
    if connect.get("Condition") != {"Bool": {"iot:Connection.Thing.IsAttached": "true"}}:
        refuse("document-refused:" + doc_id, "the connection is not held to an attached thing")


CHECKS: Dict[str, Callable[[str, Any, Names], None]] = {
    "device-policy": _check_device_policy, "bucket-policy": _check_bucket_policy, "topic-policy": _check_topic_policy,
    "function-policy": _check_function_policy, "function-policy-rule-count": _check_function_policy,
    "rule-payload": _check_rule, "alarms": _check_alarms, "alarm-notice": _check_alarms, "alarm-rule-count": _check_alarms,
    "bucket-public-access-block": _check_exact(lambda n: {"BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True,
                                                         "RestrictPublicBuckets": True}),
    "bucket-encryption": _check_exact(lambda n: {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
                                                           "BucketKeyEnabled": False}]}),
    "invoke-status": _check_exact(lambda n: {"manual": "status"}),
    "invoke-trip": _check_exact(lambda n: {"manual": "trip"}),
}
for _name in ("rule-role-policy", "firehose-role-policy", "iot-logging-role-policy", "breaker-role-policy", "operator-role-policy"):
    CHECKS[_name] = check_policy
for _name in TRUSTS:
    CHECKS[_name] = check_trust


def _check_lifecycle(doc_id: str, obj: Any, n: Names) -> None:
    try:
        got = sorted((r["Filter"]["Prefix"], r["Status"], r.get("Expiration", {}).get("Days"),
                      r.get("AbortIncompleteMultipartUpload", {}).get("DaysAfterInitiation")) for r in obj["Rules"])
    except (KeyError, TypeError):
        got = []
    if got != sorted([("telemetry/", "Enabled", 90, None), ("errors/", "Enabled", 30, None), ("athena-results/", "Enabled", 7, None),
                      ("", "Enabled", None, 1)]):
        refuse("document-refused:" + doc_id, "it is not telemetry/ 90 days, errors/ 30, athena-results/ 7 and incomplete uploads 1")


def _check_stream(doc_id: str, obj: Any, n: Names) -> None:
    ok = (isinstance(obj, dict) and obj.get("BufferingHints") == {"SizeInMBs": 5, "IntervalInSeconds": 300}
          and obj.get("CompressionFormat") == "UNCOMPRESSED" and obj.get("RoleARN") == n.role_arn(n.firehose_role)
          and obj.get("BucketARN") == n.bucket_arn and str(obj.get("Prefix", "")).startswith("telemetry/dt=!{timestamp:")
          and str(obj.get("ErrorOutputPrefix", "")).startswith("errors/!{firehose:error-output-type}/")
          and "ProcessingConfiguration" not in obj and "DynamicPartitioningConfiguration" not in obj
          and obj.get("CloudWatchLoggingOptions") == {"Enabled": True, "LogGroupName": n.firehose_log_group,
                                                      "LogStreamName": n.firehose_log_stream})
    if not ok:
        refuse("document-refused:" + doc_id, "it is not the one S3 destination of row 3 (the bucket, the role, the two prefixes, 300 s and "
               "5 MiB, no compression, no transform)")


def _check_workgroup(doc_id: str, obj: Any, n: Names) -> None:
    if obj != {"ResultConfiguration": {"OutputLocation": "s3://%s/athena-results/" % n.bucket}, "EnforceWorkGroupConfiguration": True,
               "PublishCloudWatchMetricsEnabled": False, "BytesScannedCutoffPerQuery": 100000000}:
        refuse("document-refused:" + doc_id, "it is not the enforced configuration with results under athena-results/ and the 100 MB cutoff")


def _check_environment(doc_id: str, obj: Any, n: Names) -> None:
    if not isinstance(obj, dict) or set(obj) != {"Variables"} or set(obj["Variables"]) != {"TWIN_CERTIFICATE_ARNS", "TWIN_CLIENT_IDS",
                                                                                           "TWIN_RULE", "TWIN_POLICY"}:
        refuse("document-refused:" + doc_id, "it does not hold exactly the four variables the function reads")


CHECKS.update({"bucket-lifecycle": _check_lifecycle, "stream-destination": _check_stream, "workgroup-configuration": _check_workgroup,
               "function-environment": _check_environment})


# --- Phase 6's documents (spec section 5, items 2 and 3): each held to the one design value it has

def _check_pull_trust(doc_id: str, obj: Any, n: Names) -> None:
    """The credential provider alone may assume the pull role, for this account and the twin's role alias only: the IoT
    developer guide's confused-deputy example for the credential provider."""
    check_trust(doc_id, obj, n)
    if obj["Statement"][0].get("Condition") != {"StringEquals": {"aws:SourceAccount": n.account},
                                                "ArnLike": {"aws:SourceArn": n.arn("iot", "rolealias/" + ROLE_ALIAS)}}:
        refuse("document-refused:" + doc_id, "it is not held to this account and to the twin's role alias alone")


def _check_pull_role_policy(doc_id: str, obj: Any, n: Names) -> None:
    check_policy(doc_id, obj, n)
    want = canon_policy({"Version": V, "Statement": [
        {"Sid": "GetTheToken", "Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
        {"Sid": "PullFromTheTwinsRepositories", "Effect": "Allow", "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
         "Resource": n.arn("ecr", "repository/%s/*" % ECR_NAMESPACE)}]})
    if canon_policy(obj) != want:
        refuse("document-refused:" + doc_id, "it is not the token on * and the two pull actions on the twin's repositories")


def _check_pull_policy(doc_id: str, obj: Any, n: Names) -> None:
    check_policy(doc_id, obj, n)
    want = canon_policy({"Version": V, "Statement": [{"Sid": "AssumeThePullRoleAlias", "Effect": "Allow", "Action": "iot:AssumeRoleWithCertificate",
                                                      "Resource": n.arn("iot", "rolealias/" + ROLE_ALIAS)}]})
    if canon_policy(obj) != want:
        refuse("document-refused:" + doc_id, "it is not iot:AssumeRoleWithCertificate on the twin's role alias and nothing else")


CHECKS.update({
    "pull-role-trust": _check_pull_trust, "pull-role-policy": _check_pull_role_policy, "pull-policy": _check_pull_policy,
    "repository-encryption": _check_exact(lambda n: {"encryptionType": "AES256"}),
    "repository-lifecycle": _check_exact(lambda n: {"rules": [{
        "rulePriority": 1, "description": "keep the newest %d images of the repository" % LIFECYCLE_KEEP, "action": {"type": "expire"},
        "selection": {"tagStatus": "any", "countType": "imageCountMoreThan", "countNumber": LIFECYCLE_KEEP}}]}),
})


def check_document(check: str, obj: Any, n: Names) -> None:
    """The check of the document's own kind; a document with none of its own only has to be JSON without a placeholder."""
    if check in CHECKS:
        CHECKS[check](check, obj, n)


# --------------------------------------------------------------------------------------------------- what a call needs under the operator role

# The IAM action of a call, where it is not the operation's own name in camel case under the CLI's word for the service.
# From memory of the service authorization reference, as the templates' own action names are: A2 is the first contact.
IAM_SERVICE = {"s3api": "s3", "s3control": "s3", "iot-data": "iot", "resourcegroupstaggingapi": "tag", "apigatewayv2": "apigateway"}
IAM_ACTION = {
    ("s3api", "list-buckets"): "s3:ListAllMyBuckets", ("s3api", "list-objects-v2"): "s3:ListBucket", ("s3api", "delete-objects"): "s3:DeleteObject",
    ("s3api", "put-public-access-block"): "s3:PutBucketPublicAccessBlock", ("s3api", "get-public-access-block"): "s3:GetBucketPublicAccessBlock",
    ("s3api", "put-bucket-encryption"): "s3:PutEncryptionConfiguration", ("s3api", "get-bucket-encryption"): "s3:GetEncryptionConfiguration",
    ("s3api", "put-bucket-lifecycle-configuration"): "s3:PutLifecycleConfiguration",
    ("s3api", "get-bucket-lifecycle-configuration"): "s3:GetLifecycleConfiguration",
    ("s3control", "get-public-access-block"): "s3:GetAccountPublicAccessBlock", ("lambda", "invoke"): "lambda:InvokeFunction",
    ("apigateway", "get-rest-apis"): "apigateway:GET", ("apigatewayv2", "get-apis"): "apigateway:GET",
    ("ecr", "get-login-password"): "ecr:GetAuthorizationToken",      # Phase 6's push: the CLI's customization over that operation
}
IAM_TAGS = {"firehose": "firehose:TagDeliveryStream"}           # a create with tags: every other service's is <service>:TagResource
# The calls that hand a role to a service (iam:PassRole): the service, and the option that carries the role when the
# role is not inside a document the call always gives.
PASSES_ROLE: Dict[Tuple[str, str], Tuple[str, Optional[str]]] = {
    ("iot", "create-topic-rule"): ("iot.amazonaws.com", None), ("iot", "set-v2-logging-options"): ("iot.amazonaws.com", "--role-arn"),
    ("firehose", "create-delivery-stream"): ("firehose.amazonaws.com", None), ("lambda", "create-function"): ("lambda.amazonaws.com", "--role"),
    # Phase 6: the role alias hands the pull role to the credential provider (wp0-facts C4: iam:PassRole on the role). Which
    # service name the call passes it to is not read anywhere: the statement that allows it names the one role and no service
    ("iot", "create-role-alias"): ("credentials.iot.amazonaws.com", "--role-arn")}


def _passes(call: "Call") -> Optional[str]:
    service, option = PASSES_ROLE.get((call.service, call.op), ("", None))
    return service if service and (option is None or option in call.args) else None


def iam_actions(call: "Call") -> Tuple[str, ...]:
    """The IAM actions one call needs: its own, and what its options add (the bucket's ownership, the tags of a create,
    the role it passes). The caller's own identity needs none."""
    if call.service == "sts":
        return ()
    service = IAM_SERVICE.get(call.service, call.service)
    out = [IAM_ACTION.get((call.service, call.op)) or "%s:%s" % (service, "".join(w.capitalize() for w in call.op.split("-")))]
    if call.service == "s3api" and "--object-ownership" in call.args:
        out.append("s3:PutBucketOwnershipControls")
    if "--tags" in call.args:
        out.append(IAM_TAGS.get(call.service, service + ":TagResource"))
    if _passes(call):
        out.append("iam:PassRole")
    return tuple(out)


def _option(call: "Call", name: str) -> Optional[str]:
    return call.args[call.args.index(name) + 1] if name in call.args[:-1] else None


def operator_gaps(policy: Any, calls: Sequence["Call"]) -> List[str]:
    """What the operator role's policy does not let through of `calls`: one line per action and call, with no value in
    it. The owner makes the role by hand from the render (A1 row 3), so a call of the driver the role refuses costs a
    second pass through the console; the first render allowed the exit's Cognito read and denied every Cognito
    action, and had no action for one read of the function.

    An explicit Deny wins; an action no Allow statement names is denied. Judged by the action's name (a pattern as
    the service matches one, without case) and by the conditions a call itself settles: the protocol of a
    subscription, the principal of an invoke grant, the service a role is passed to. A condition this function
    cannot settle counts against the call: such a Deny applies, such an Allow does not. RESOURCES ARE NOT MATCHED,
    and every action name here is from memory. So this function knows which ACTIONS a call needs and not which resource
    types an action is authorised on: a statement that names the action and lacks one of its resources passes here
    (the Glue statement had no user-defined-function resource for the database's delete; a reading of the service
    authorization reference found it, and a test of the rendered statement holds it)."""
    statements = [s for s in _listed(policy.get("Statement", []) if isinstance(policy, dict) else []) if isinstance(s, dict)]

    def applies(st: Dict[str, Any], facts: Dict[str, Optional[str]]) -> bool:
        deny = st.get("Effect") == "Deny"
        for kind, body in (st.get("Condition") or {}).items():
            for key, want in (body.items() if isinstance(body, dict) else [("", None)]):
                if key.lower() not in facts or kind not in ("StringEquals", "StringNotEquals"):
                    if not deny:
                        return False
                    continue
                wanted = [str(x) for x in _listed(want)]
                if (facts[key.lower()] in wanted) is not (kind == "StringEquals"):
                    return False
        return True

    def names(st: Dict[str, Any], action: str) -> bool:
        return any(fnmatch.fnmatchcase(action.lower(), str(a).lower()) for a in _listed(st.get("Action", [])))

    gaps: List[str] = []
    for call in calls:
        facts = {"sns:protocol": _option(call, "--protocol"), "lambda:principal": _option(call, "--principal"),
                 "iam:passedtoservice": _passes(call)}
        for action in iam_actions(call):
            denying = [st for st in statements if st.get("Effect") == "Deny" and names(st, action) and applies(st, facts)]
            if denying:
                gap = "%s (%s %s) is denied by the statement %s" % (action, call.service, call.op, denying[0].get("Sid"))
            elif not any(st.get("Effect") == "Allow" and names(st, action) and applies(st, facts) for st in statements):
                gap = "%s (%s %s) is allowed by no statement" % (action, call.service, call.op)
            else:
                continue
            if gap not in gaps:
                gaps.append(gap)
    return sorted(gaps)


# --------------------------------------------------------------------------------------------------- the CLI

class Reply(NamedTuple):
    rc: int
    obj: Any
    code: str
    missing: bool


def find_encoded(obj: Any) -> Optional[str]:
    """The name of the first field of ENCODED_REPLY_FIELDS a reply holds, at any depth."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ENCODED_REPLY_FIELDS:
                return str(k)
            found = find_encoded(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_encoded(v)
            if found:
                return found
    return None


def more_marker(obj: Any) -> Optional[str]:
    """The name of what in a reply says that the listing goes on (MORE_TOKENS, MORE_FLAGS), or None."""
    if isinstance(obj, dict):
        for key in MORE_TOKENS:
            if isinstance(obj.get(key), str) and obj[key]:
                return key
        for key in MORE_FLAGS:
            if obj.get(key) is True:
                return key
    return None


class Aws:
    """The AWS CLI, by argv, without a shell. The executable is TWIN_AWS (default: aws); a file that ends in .py is
    run with this interpreter, which is how a stub stands in. NO CALL BUT THE READ OF THE CALLER'S IDENTITY IS SENT
    until identified() was called, and a call that writes is refused until arm() was: every command that sends a
    call reads the identity first (require_caller()), `apply` and `teardown` arm the runner once it is the operator
    role's, `trip` once the account is the twin's or could not be read, `plan` never does."""

    def __init__(self, n: Names, state_dir: Path) -> None:
        exe = os.environ.get("TWIN_AWS", "") or "aws"
        self.exe = [sys.executable, exe] if exe.endswith(".py") else [exe]
        self.n = n
        self.replies = state_dir / "replies"
        self.armed = False
        self.known = False
        self.count = 0
        self.stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-%d-%09d" % (os.getpid(), time.time_ns() % 10 ** 9)

    def identified(self) -> None:
        self.known = True

    def arm(self) -> None:
        self.armed = True
        self.known = True

    def _spawn(self, argv: List[str], env: Optional[Dict[str, str]] = None) -> "subprocess.CompletedProcess[bytes]":
        for arg in argv:
            if any(arg == f or arg.startswith(f + "=") for f in FORBIDDEN_OPTIONS):
                refuse("forbidden-option", "a call asks for a reply field that carries encoded text (a function's log tail): no call "
                       "of twinctl does")
        try:
            return subprocess.run(self.exe + argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, env=env,
                                  timeout=900)
        except FileNotFoundError:
            refuse("cli-missing", "the AWS CLI is not found (TWIN_AWS names the executable)")
        except (OSError, subprocess.TimeoutExpired) as e:
            refuse("cli-failed", "the AWS CLI could not be run to its end (%s)" % type(e).__name__)

    def run(self, call: Call, label: str = "") -> Reply:
        """One call under the operator profile. Its raw reply stays in the state directory."""
        if call.write and not self.armed:
            refuse("not-armed", "a call that changes the account was reached without the step that allows it: nothing was sent")
        if not self.known and (call.service, call.op) != ("sts", "get-caller-identity"):
            refuse("caller-not-read", "a call was reached before the caller's identity was read: nothing was sent")
        region = [] if "--region" in call.args else ["--region", self.n.region]
        argv = call.argv() + region + ["--profile", self.n.profile, "--output", "json", "--no-cli-pager"]
        self.replies.mkdir(parents=True, exist_ok=True)             # before the call: an invoke's and a shadow's output file lies there
        done = self._spawn(argv)
        self.count += 1
        base = self.replies / ("%s-%04d-%s-%s%s" % (self.stamp, self.count, call.service, call.op, ("-" + label) if label else ""))
        base.with_name(base.name + ".json").write_bytes(done.stdout)
        err = done.stderr.decode("utf-8", "replace")
        if done.returncode != 0:
            base.with_name(base.name + ".err.txt").write_bytes(done.stderr)
            m = ERROR_CODE.search(err)
            code = m.group(1) if m else "exit-%d" % done.returncode
            missing = code in NOT_FOUND or NOT_FOUND_WORDS.get((call.service, code), "\0") in err
            return Reply(done.returncode, None, code, missing)
        text = done.stdout.decode("utf-8", "replace").strip()
        try:
            obj = json.loads(text) if text else {}
        except ValueError:
            refuse("reply-unreadable", "%s %s answered what is not JSON; the reply is in the state directory" % (call.service, call.op))
        return Reply(0, obj, "", False)

    def read(self, call: Call, label: str = "") -> Any:
        """A read's reply, or None when the thing is not there. Any other failure is a refusal by the service's code, and
        so is a reply that says there is more of it than it holds."""
        if call.write:
            raise AssertionError("a write is not a read")
        reply = self.run(call, label)
        if reply.rc == 0:
            more = more_marker(reply.obj)
            if more:
                refuse("listing-incomplete", "%s %s answered one page and says there is more (%s): half a listing is not judged, "
                       "and the driver follows no page; the reply is in the state directory" % (call.service, call.op, more))
            return reply.obj
        if self.gone(call, reply, label):
            return None
        refuse("read-failed", "%s %s failed (%s): what cannot be read is not judged; the reply is in the state directory"
               % (call.service, call.op, reply.code))

    def gone(self, call: Call, reply: Reply, label: str = "") -> bool:
        """Whether a call's failure says that the thing is not there: a code of NOT_FOUND, or, for a call of AMBIGUOUS,
        its one code once the listing lacks the name. A listing that is refused, or that says there is more of it,
        settles nothing."""
        if reply.missing:
            return True
        code, option, listing = AMBIGUOUS.get((call.service, call.op), ("", "", ""))
        if not code or reply.code != code or option not in call.args:
            return False
        listed = self.run(LISTINGS[listing][0], label)
        return (listed.rc == 0 and more_marker(listed.obj) is None
                and call.args[call.args.index(option) + 1] not in LISTINGS[listing][1](listed.obj or {}))

    def offline_env(self, render_dir: Path) -> Dict[str, str]:
        """An environment in which the CLI can reach neither a credential nor the network: no AWS_ variable of the
        caller, two empty files as the credentials and the configuration, no instance metadata, and proxies that
        point at the closed local port."""
        d = render_dir / "offline"
        d.mkdir(parents=True, exist_ok=True)
        for name in ("credentials", "config"):
            (d / name).write_bytes(b"")
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("AWS_")
               and k.upper() not in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY")}
        env.update({"AWS_SHARED_CREDENTIALS_FILE": str(d / "credentials"), "AWS_CONFIG_FILE": str(d / "config"),
                    "AWS_EC2_METADATA_DISABLED": "true", "AWS_PAGER": "", "AWS_MAX_ATTEMPTS": "1",
                    "HTTP_PROXY": OFFLINE_ENDPOINT, "HTTPS_PROXY": OFFLINE_ENDPOINT, "http_proxy": OFFLINE_ENDPOINT,
                    "https_proxy": OFFLINE_ENDPOINT})
        return env

    def offline_control(self, env: Dict[str, str]) -> bool:
        """Whether a real call under the offline settings FAILS, as it must: only then is anything validated."""
        done = self._spawn(["sts", "get-caller-identity", "--region", self.n.region, "--endpoint-url", OFFLINE_ENDPOINT, "--output", "json",
                            "--no-cli-pager"], env)
        return done.returncode != 0

    def validate(self, call: Call, env: Dict[str, str]) -> Tuple[str, str]:
        """The CLI's own reading of one call's arguments, with nothing sent: (verdict, what it said). The verdict is
        `read` (the arguments were read and a sample reply printed), `read, sample fails` (only the options' names, the
        required options and each value's form were read; the CLI's own sample reply then failed its own validation,
        and the model's validation of the call's own arguments never ran), `no skeleton` (the command knows none: not
        read at all) or `refused`."""
        if (call.service, call.op) in SKELETON_UNSUPPORTED:
            return "no skeleton", ""
        where = [] if "--region" in call.args else ["--region", self.n.region]     # a call that names its own region keeps it, as when it is sent
        done = self._spawn(call.argv() + ["--generate-cli-skeleton", "output"] + where + ["--endpoint-url", OFFLINE_ENDPOINT, "--no-cli-pager"],
                           env)
        said = done.stderr.decode("utf-8", "replace").strip()
        if done.returncode == 0:
            return "read", said
        return ("read, sample fails" if sample_only(call, said) else "refused"), said


# --------------------------------------------------------------------------------------------------- the step table

Judge = Callable[["Twin", Render, Dict[str, Any]], Tuple[bool, List[str]]]


class Step:
    def __init__(self, id: str, row: str, title: str, build: Callable[["Twin", Render], Built], judge: Optional[Judge] = None,
                 kind: str = "resource", needs: Sequence[str] = (), rehearse: bool = False, listing: str = "",
                 ready: Optional[Callable[["Twin", Render], Optional[str]]] = None,
                 pre: Optional[Callable[["Twin", Render], Optional[str]]] = None,
                 after: Optional[Callable[["Twin", int, Any], None]] = None) -> None:
        self.id = id
        self.row = row
        self.title = title
        self.build = build
        self.judge = judge
        self.kind = kind                # resource | owner (made by hand) | action (no resource) | appears (no create call) | empty
        #                                 | other (OTHER alone: the calls outside the table; no step of it)
        self.needs = tuple(needs)
        self.rehearse = rehearse
        self.listing = listing
        self.ready = ready              # teardown's precondition: a sentence that refuses, or None
        self.pre = pre                  # apply's precondition
        self.after = after              # what a create call's reply teaches the state


def _policy_of(reply: Any, *path: str) -> Any:
    for key in path:
        reply = reply.get(key) if isinstance(reply, dict) else None
    return reply


def _role_step(id: str, row: str, title: str, role: Callable[[Names], str], needs: Sequence[str] = (), key: str = "TWIN_OPERATOR_ROLE",
               policy: Optional[Callable[["Twin", Render, Any], Any]] = None) -> Step:
    def build(t: "Twin", r: Render) -> Built:
        if not role(t.n):
            # the operator role's step in a stop whose names file gives no usable TWIN_OPERATOR_ROLE (STOP_NEEDS_NOT): `status`
            # then says `not read (names-missing)` in its place, and never reads a role of no name. And the pull role's step that a
            # state keeps in its table with TWIN_PULL_ROLE taken out of the names file
            refuse("names-missing", "%s is not given in the form twinctl takes for it: the role's step is not rendered" % key)

        def trust(obj: Any) -> Any:
            if id == "operator-role" and not t.n.mfa:               # section 6, item 2: the owner's choice
                obj["Statement"][0].pop("Condition", None)
            return obj

        r.doc(id + "-trust", edit=trust)
        r.doc(id + "-policy", edit=None if policy is None else (lambda obj: policy(t, r, obj)))
        name = role(t.n)
        return Built(reads=[("role", R("iam", "get-role", "--role-name", name)),
                            ("policy", R("iam", "get-role-policy", "--role-name", name, "--policy-name", t.n.role_policy_name(name)))])

    def judge(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
        if got["role"] is None:
            return False, []
        diffs = []
        if canon_policy(_policy_of(got["role"], "Role", "AssumeRolePolicyDocument")) != canon_policy(r.obj(id + "-trust")):
            diffs.append("its trust policy is not the render")
        if got["policy"] is None:
            diffs.append("it has no policy of the rendered name")
        elif canon_policy(_policy_of(got["policy"], "PolicyDocument")) != canon_policy(r.obj(id + "-policy")):
            diffs.append("its policy is not the render")
        return True, diffs

    return Step(id, row, title, build, judge, kind="owner", needs=needs)


def _log_group_step(id: str, row: str, title: str, group: Callable[[Names], str], stream: Optional[Callable[[Names], str]] = None,
                    rehearse: bool = False, adopted: bool = False) -> Step:
    """A log group the driver makes. `adopted`: one that was there before the twin and that the owner chose to keep: a
    step of the owner's kind, read and held to the render, never created and never deleted here."""
    def build(t: "Twin", r: Render) -> Built:
        g = group(t.n)
        creates = [W("logs", "create-log-group", "--log-group-name", g, "--tags", "%s=%s" % (t.n.tag_key, t.n.prefix)),
                   W("logs", "put-retention-policy", "--log-group-name", g, "--retention-in-days", str(RETENTION_DAYS))]
        reads = [("groups", R("logs", "describe-log-groups", "--log-group-name-prefix", g))]
        if stream is not None:
            creates.append(W("logs", "create-log-stream", "--log-group-name", g, "--log-stream-name", stream(t.n)))
            reads.append(("streams", R("logs", "describe-log-streams", "--log-group-name", g, "--log-stream-name-prefix", stream(t.n))))
        if adopted:
            return Built([], reads, [])
        return Built(creates, reads, [W("logs", "delete-log-group", "--log-group-name", g)])

    def judge(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
        groups = [x for x in (got["groups"] or {}).get("logGroups", []) if x.get("logGroupName") == group(t.n)]
        if not groups:
            return False, []
        diffs = [] if groups[0].get("retentionInDays") == RETENTION_DAYS else ["its retention is not %d days" % RETENTION_DAYS]
        if stream is not None and not [x for x in (got.get("streams") or {}).get("logStreams", []) if x.get("logStreamName") == stream(t.n)]:
            diffs.append("its log stream is not there")
        return True, diffs

    if adopted:
        return Step(id, row, title, build, judge, kind="owner")
    return Step(id, row, title, build, judge, rehearse=rehearse, listing="log-groups")


def _alarm_step(id: str, row: str, title: str, template: str, needs: Sequence[str], rehearse: bool = False, extra: bool = False) -> Step:
    def intents(t: "Twin", r: Render) -> List[Dict[str, Any]]:
        def edit(obj: Any) -> Any:
            if t.n.rehearsal:
                obj = [dict(a, AlarmActions=[], Threshold=1) for a in obj if a.get("Key") == "bytes"]
            return obj
        r.doc("alarm-tags")
        return list(r.doc(template, edit=edit))

    def build(t: "Twin", r: Render) -> Built:
        creates, names = [], []
        for a in intents(t, r):
            names.append(a["AlarmName"])
            r.put("alarm-%s-dimensions" % a["Key"], a["Dimensions"])
            args = ["--alarm-name", a["AlarmName"], "--namespace", a["Namespace"], "--metric-name", a["MetricName"],
                    "--dimensions", r.url("alarm-%s-dimensions" % a["Key"]), "--statistic", a["Statistic"], "--period", str(a["Period"]),
                    "--evaluation-periods", str(a["EvaluationPeriods"]), "--datapoints-to-alarm", str(a["DatapointsToAlarm"]),
                    "--comparison-operator", a["ComparisonOperator"], "--threshold", str(a["Threshold"]),
                    "--treat-missing-data", a["TreatMissingData"], "--actions-enabled"]
            if a["AlarmActions"]:
                args += ["--alarm-actions"] + list(a["AlarmActions"])
            creates.append(W("cloudwatch", "put-metric-alarm", *(args + ["--tags", r.url("alarm-tags")])))
        deletes = [W("cloudwatch", "delete-alarms", "--alarm-names", *names)]
        if extra:                                                   # row 19: one more statement in the function's policy
            r.doc("function-policy-rule-count")
            n = t.n
            creates.append(W("lambda", "add-permission", "--function-name", n.function, "--statement-id", "alarm-rule-count", "--action",
                             "lambda:InvokeFunction", "--principal", ALARMS_PRINCIPAL, "--source-account", n.account, "--source-arn",
                             n.alarm_arn("rule-count")))
            deletes.insert(0, W("lambda", "remove-permission", "--function-name", n.function, "--statement-id", "alarm-rule-count"))
        return Built(creates, [("alarms", R("cloudwatch", "describe-alarms", "--alarm-names", *names))], deletes)

    def judge(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
        found = {a.get("AlarmName"): a for a in (got["alarms"] or {}).get("MetricAlarms", [])}
        wanted = r.obj(template)
        diffs = []
        for a in wanted:
            have = found.get(a["AlarmName"])
            if have is None:
                diffs.append("the alarm %s is not there" % a["Key"])
                continue
            want = {k: v for k, v in a.items() if k not in ("Key", "AlarmActions")}
            if not subset(want, have) or sorted(have.get("AlarmActions", [])) != sorted(a["AlarmActions"]):
                diffs.append("the alarm %s is not the render" % a["Key"])
            elif have.get("StateValue") == "ALARM":
                diffs.append("the alarm %s is in ALARM" % a["Key"])
        present = any(a["AlarmName"] in found for a in wanted)
        return present, diffs if present else []

    return Step(id, row, title, build, judge, needs=needs, rehearse=rehearse, listing="alarms")


def _invoke(t: "Twin", r: Render, payload: str, label: str) -> Call:
    """A function's invoke. Never with its log tail: the reply's LogResult is base64 of the function's own log, which
    names what the breaker acts on. The function's record is read through the payload's file only."""
    r.doc(payload)
    out = t.state_dir / "replies" / ("payload-%s.json" % label)
    return W("lambda", "invoke", "--function-name", t.n.function, "--cli-binary-format", "raw-in-base64-out", "--payload", r.url(payload),
             str(out.as_posix()))


def _b_bucket(t: "Twin", r: Render) -> Built:
    n, b = t.n, t.n.bucket
    for name in ("bucket-location", "bucket-public-access-block", "bucket-encryption", "bucket-lifecycle", "bucket-policy", "bucket-tagging"):
        r.doc(name)
    return Built(
        [W("s3api", "create-bucket", "--bucket", b, "--create-bucket-configuration", r.url("bucket-location"), "--object-ownership",
           "BucketOwnerEnforced"),
         W("s3api", "put-public-access-block", "--bucket", b, "--public-access-block-configuration", r.url("bucket-public-access-block")),
         W("s3api", "put-bucket-encryption", "--bucket", b, "--server-side-encryption-configuration", r.url("bucket-encryption")),
         W("s3api", "put-bucket-lifecycle-configuration", "--bucket", b, "--lifecycle-configuration", r.url("bucket-lifecycle")),
         W("s3api", "put-bucket-policy", "--bucket", b, "--policy", r.url("bucket-policy")),
         W("s3api", "put-bucket-tagging", "--bucket", b, "--tagging", r.url("bucket-tagging"))],
        [("versioning", R("s3api", "get-bucket-versioning", "--bucket", b)),
         ("block", R("s3api", "get-public-access-block", "--bucket", b)),
         ("ownership", R("s3api", "get-bucket-ownership-controls", "--bucket", b)),
         ("encryption", R("s3api", "get-bucket-encryption", "--bucket", b)),
         ("lifecycle", R("s3api", "get-bucket-lifecycle-configuration", "--bucket", b)),
         ("policy", R("s3api", "get-bucket-policy", "--bucket", b)),
         ("policy-status", R("s3api", "get-bucket-policy-status", "--bucket", b))],
        [W("s3api", "delete-bucket", "--bucket", n.bucket)])


def _j_bucket(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    if got["versioning"] is None:
        return False, []
    d = []
    if got["versioning"].get("Status") == "Enabled":
        d.append("versioning is on")
    if _policy_of(got["block"], "PublicAccessBlockConfiguration") != r.obj("bucket-public-access-block"):
        d.append("its Block Public Access is not all four")
    if _policy_of(got["ownership"], "OwnershipControls", "Rules") != [{"ObjectOwnership": "BucketOwnerEnforced"}]:
        d.append("its object ownership is not bucket owner enforced")
    if not subset(r.obj("bucket-encryption"), _policy_of(got["encryption"], "ServerSideEncryptionConfiguration")):
        d.append("its encryption is not SSE-S3")
    if not subset(r.obj("bucket-lifecycle")["Rules"], _policy_of(got["lifecycle"], "Rules")):
        d.append("its lifecycle is not the render")
    if canon_policy(_policy_of(got["policy"], "Policy")) != canon_policy(r.obj("bucket-policy")):
        d.append("its policy is not the render")
    if _policy_of(got["policy-status"], "PolicyStatus", "IsPublic") is not False:
        d.append("its policy status does not say it is not public")
    return True, d


def _objects(t: "Twin") -> Optional[List[str]]:
    """The keys the bucket lists, or None when the bucket is not there."""
    got = t.aws.read(c_objects(t))
    return None if got is None else sorted(str(o.get("Key")) for o in got.get("Contents", []) or [])


def _ready_bucket(t: "Twin", r: Render) -> Optional[str]:
    keys = _objects(t)
    if keys:
        return "the bucket holds %d object(s): emptying it is the step bucket-objects, with an approval of its own" % len(keys)
    return None


def _b_stream(t: "Twin", r: Render) -> Built:
    n = t.n
    r.doc("stream-destination")
    r.doc("stream-tags")
    return Built(
        [W("firehose", "create-delivery-stream", "--delivery-stream-name", n.stream, "--delivery-stream-type", "DirectPut",
           "--extended-s3-destination-configuration", r.url("stream-destination"), "--tags", r.url("stream-tags"))],
        [("stream", R("firehose", "describe-delivery-stream", "--delivery-stream-name", n.stream))],
        [W("firehose", "delete-delivery-stream", "--delivery-stream-name", n.stream)])


def _j_stream(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    d = _policy_of(got["stream"], "DeliveryStreamDescription")
    if d is None:
        return False, []
    diffs = []
    if d.get("DeliveryStreamStatus") != "ACTIVE":
        diffs.append("it is %s, not ACTIVE" % (d.get("DeliveryStreamStatus") if d.get("DeliveryStreamStatus") in ("CREATING", "DELETING")
                                               else "in another state"))
    dests = d.get("Destinations") or []
    want = {k: v for k, v in r.obj("stream-destination").items()}
    if d.get("DeliveryStreamType") != "DirectPut" or len(dests) != 1 or not subset(want, dests[0].get("ExtendedS3DestinationDescription")):
        diffs.append("it is not Direct PUT with the one S3 destination of the render")
    return True, diffs


def _live(t: "Twin", step: str) -> bool:
    return t.state.status(step) in OURS


def _b_rule(t: "Twin", r: Render) -> Built:
    n = t.n
    r.doc("rule-payload")
    return Built(
        [W("iot", "create-topic-rule", "--rule-name", n.rule, "--topic-rule-payload", r.url("rule-payload"), "--tags",
           "%s=%s" % (n.tag_key, n.prefix))],
        [("rule", R("iot", "get-topic-rule", "--rule-name", n.rule))],
        [W("iot", "delete-topic-rule", "--rule-name", n.rule)])


def _j_rule(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    rule = _policy_of(got["rule"], "rule")
    if rule is None:
        return False, []
    want = dict(r.obj("rule-payload"))
    want.pop("ruleDisabled")
    diffs = [] if subset(want, rule) else ["it is not the render (the SQL, the one firehose action)"]
    live = _live(t, "go-live-rule")
    if rule.get("ruleDisabled") is not (not live):
        diffs.append("it is enabled before go-live" if not live else "it is disabled (tripped, or not live)")
    return True, diffs


def _b_thing(t: "Twin", r: Render) -> Built:
    n = t.n
    return Built([W("iot", "create-thing", "--thing-name", n.thing)], [("thing", R("iot", "describe-thing", "--thing-name", n.thing))],
                 [W("iot", "delete-thing", "--thing-name", n.thing)])


def _j_thing(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    if got["thing"] is None:
        return False, []
    return True, ([] if not got["thing"].get("attributes") else ["it has attributes"])


def _shadows_listed(t: "Twin") -> Optional[List[str]]:
    got = t.aws.read(R("iot-data", "list-named-shadows-for-thing", "--thing-name", t.n.thing))
    return None if got is None else sorted(str(x) for x in got.get("results", []) or [])


def _ready_thing(t: "Twin", r: Render) -> Optional[str]:
    listed = _shadows_listed(t)
    if listed:
        return ("%d named shadow(s) are listed for the thing: they are deleted and listed empty first (the step shadows); whether "
                "deleting the thing removes them is not known, and is not tried" % len(listed))
    return None


def _shadow_names(t: "Twin") -> Tuple[str, ...]:
    return (REHEARSAL_SHADOW,) if t.n.rehearsal else SHADOWS


def _b_shadows(t: "Twin", r: Render) -> Built:
    n = t.n
    creates = []
    if n.rehearsal:                                # A2: a named shadow the operator writes on the rehearsal's thing
        r.doc("shadow-rehearsal")
        creates.append(W("iot-data", "update-thing-shadow", "--thing-name", n.thing, "--shadow-name", REHEARSAL_SHADOW,
                         "--cli-binary-format", "raw-in-base64-out", "--payload", r.url("shadow-rehearsal"),
                         (t.state_dir / "replies" / "shadow-written.json").as_posix()))
    deletes = [W("iot-data", "delete-thing-shadow", "--thing-name", n.thing, "--shadow-name", s,
                 (t.state_dir / "replies" / ("shadow-deleted-%s.json" % s)).as_posix()) for s in _shadow_names(t)]
    return Built(creates, [("listed", R("iot-data", "list-named-shadows-for-thing", "--thing-name", n.thing))], deletes)


def _j_shadows(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    listed = sorted(str(x) for x in (got["listed"] or {}).get("results", []) or [])
    if not listed:
        return False, []
    extra = [s for s in listed if s not in _shadow_names(t)]
    return True, (["%d named shadow(s) outside the twin's own" % len(extra)] if extra else [])


def _cert(t: "Twin") -> Tuple[Optional[str], Optional[str]]:
    cert = t.state.fact("certificate_id")
    return cert, (t.n.arn("iot", "cert/" + cert) if cert else None)


UNCONFIRMED = "certificate_id_unconfirmed"


def _own_cert(t: "Twin") -> Tuple[Optional[str], Optional[str]]:
    """The id the certificate's OWN step reads and deletes by: one a create's reply gave under an ARN that is not this
    account's and region's (_after_certificate() refused the reply and kept the id) before the confirmed one. No
    other step stands on an unconfirmed id: it is there so that what a create made can be read and torn down."""
    cert = t.state.fact(UNCONFIRMED) or t.state.fact("certificate_id")
    return cert, (t.n.arn("iot", "cert/" + cert) if cert else None)


def _b_certificate(t: "Twin", r: Render) -> Built:
    n = t.n
    csr = r.input("TWIN_REHEARSAL_CSR" if n.rehearsal else "TWIN_CSR", "the device's signing request, made where its key is made")
    key = "TWIN_REHEARSAL_CERTIFICATE_OUT" if n.rehearsal else "TWIN_CERTIFICATE_OUT"
    if r.strict and key not in n.v:
        refuse("input-unset", "%s is not set: where the certificate's PEM is written" % key)
    out = Path(os.path.expanduser(n.v.get(key, key.lower() + "-is-not-set")))
    if r.strict and REDACT.in_a_work_tree(out):
        refuse("inside-a-work-tree", "the certificate's file would lie inside a work tree: it goes to the device directory")
    cert, _arn = _own_cert(t)
    creates = [W("iot", "create-certificate-from-csr", "--certificate-signing-request", file_url(csr), "--no-set-as-active",
                 "--certificate-pem-outfile", out.as_posix())]
    if cert is None:
        return Built(creates, [], [])
    return Built(creates, [("certificate", R("iot", "describe-certificate", "--certificate-id", cert))],
                 [W("iot", "delete-certificate", "--certificate-id", cert)])


def _j_certificate(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    d = _policy_of(got.get("certificate"), "certificateDescription")
    if d is None:
        return False, []
    live = _live(t, "go-live-certificate")
    status = d.get("status")
    if status == ("ACTIVE" if live else "INACTIVE"):
        return True, []
    return True, ["it is ACTIVE before go-live" if status == "ACTIVE" else ("it is INACTIVE (tripped, or not live)" if status == "INACTIVE"
                                                                           else "it is neither ACTIVE nor INACTIVE")]


def _after_cert(fact: str, unconfirmed: str, step_id: str) -> Callable[["Twin", int, Any], None]:
    """What a certificate's create teaches the state: its id, under `fact` (the twin's certificate's, or the pull certificate's)."""
    def after(t: "Twin", index: int, reply: Any) -> None:
        cert, arn = (reply or {}).get("certificateId"), (reply or {}).get("certificateArn")
        known = isinstance(cert, str) and re.fullmatch(r"[0-9a-f]{64}", cert) is not None
        if not known or arn != t.n.arn("iot", "cert/" + str(cert)):
            kept = ""
            if known:
                # the create went through and something stands in the account: its id is kept, unconfirmed, for this step's own
                # read and teardown, or no command could delete what only the raw reply names (the hard review, c05)
                t.state.learn(**{unconfirmed: str(cert)})
                t.refresh_literals()
                kept = "; the id it gives is kept, unconfirmed, so that `twinctl teardown %s` reads and deletes what was made" % step_id
            refuse("reply-unreadable", "the reply to the certificate's creation names no certificate of this account and region; the reply "
                   "is in the state directory" + kept)
        t.state.learn(**{fact: str(cert)})
        t.state.forget(unconfirmed)
        t.refresh_literals()
    return after


_after_certificate = _after_cert("certificate_id", UNCONFIRMED, "certificate")
_after_pull_certificate = _after_cert("pull_certificate_id", PULL_UNCONFIRMED, "pull-certificate")


def _attached(t: "Twin") -> Tuple[bool, bool, str]:
    """(the policy is attached to the certificate, the certificate is attached to the thing, its attachment type)."""
    cert, arn = _cert(t)
    if arn is None:
        return False, False, ""
    policies = t.aws.read(R("iot", "list-attached-policies", "--target", arn)) or {}
    principals = t.aws.read(R("iot", "list-thing-principals-v2", "--thing-name", t.n.thing)) or {}
    mine = [p for p in principals.get("thingPrincipalObjects", []) or [] if p.get("principal") == arn]
    return (any(p.get("policyName") == t.n.policy for p in policies.get("policies", []) or []), bool(mine),
            str(mine[0].get("thingPrincipalType")) if mine else "")


def _ready_certificate(t: "Twin", r: Render) -> Optional[str]:
    cert, arn = _own_cert(t)
    if cert is None or arn is None:
        return None
    d = _policy_of(t.aws.read(R("iot", "describe-certificate", "--certificate-id", cert)), "certificateDescription")
    if d is None:
        return None
    if d.get("status") != "INACTIVE":
        return "the certificate is not INACTIVE: it is deactivated first (teardown go-live-certificate, or a trip)"
    policies = t.aws.read(R("iot", "list-attached-policies", "--target", arn)) or {}
    if policies.get("policies"):
        return "a policy is still attached to the certificate: it is detached first (teardown attachments)"
    principals = t.aws.read(R("iot", "list-thing-principals-v2", "--thing-name", t.n.thing)) or {}
    if any(p.get("principal") == arn for p in principals.get("thingPrincipalObjects", []) or []):
        return "the certificate is still attached to the thing: it is detached first (teardown attachments)"
    return None


def _b_policy(t: "Twin", r: Render) -> Built:
    n = t.n
    r.doc("device-policy")
    r.doc("policy-tags")
    return Built([W("iot", "create-policy", "--policy-name", n.policy, "--policy-document", r.url("device-policy"), "--tags",
                    r.url("policy-tags"))],
                 [("policy", R("iot", "get-policy", "--policy-name", n.policy))],
                 [W("iot", "delete-policy", "--policy-name", n.policy)])


def _j_policy(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    if got["policy"] is None:
        return False, []
    same = canon_policy(got["policy"].get("policyDocument")) == canon_policy(r.obj("device-policy"))
    return True, ([] if same else ["its document is not the render"])


def _ready_policy(t: "Twin", r: Render) -> Optional[str]:
    got = t.aws.read(c_policy_targets(t))
    if got and got.get("targets"):
        return "the policy is still attached to %d target(s): it is detached first (teardown attachments)" % len(got["targets"])
    return None


def _b_attachments(t: "Twin", r: Render) -> Built:
    n = t.n
    arn = r.lookup("CERT_ARN", "attachments")
    reads = [] if "certificate" in r.provisional else [
        ("policies", R("iot", "list-attached-policies", "--target", arn)),
        ("principals", R("iot", "list-thing-principals-v2", "--thing-name", n.thing))]
    return Built(
        [W("iot", "attach-policy", "--policy-name", n.policy, "--target", arn),
         W("iot", "attach-thing-principal", "--thing-name", n.thing, "--principal", arn, "--thing-principal-type", "EXCLUSIVE_THING")],
        reads,
        [W("iot", "detach-thing-principal", "--thing-name", n.thing, "--principal", arn),
         W("iot", "detach-policy", "--policy-name", n.policy, "--target", arn)])


def _j_attachments(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    _cert_id, arn = _cert(t)
    policy = any(p.get("policyName") == t.n.policy for p in (got.get("policies") or {}).get("policies", []) or [])
    mine = [p for p in (got.get("principals") or {}).get("thingPrincipalObjects", []) or [] if p.get("principal") == arn]
    if not policy and not mine:
        return False, []
    diffs = []
    if not policy:
        diffs.append("the policy is not attached to the certificate (tripped, or half made)")
    if not mine:
        diffs.append("the certificate is not attached to the thing")
    elif mine[0].get("thingPrincipalType") != "EXCLUSIVE_THING":
        diffs.append("the certificate's attachment to the thing is not exclusive")
    return True, diffs


def _b_glue(t: "Twin", r: Render) -> Built:
    n = t.n
    r.doc("glue-database")
    r.doc("glue-table")
    return Built(
        [W("glue", "create-database", "--database-input", r.url("glue-database")),
         W("glue", "create-table", "--database-name", n.glue_database, "--table-input", r.url("glue-table"))],
        [("database", R("glue", "get-database", "--name", n.glue_database)),
         ("table", R("glue", "get-table", "--database-name", n.glue_database, "--name", n.glue_table))],
        [W("glue", "delete-table", "--database-name", n.glue_database, "--name", n.glue_table),
         W("glue", "delete-database", "--name", n.glue_database)])


def _j_glue(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    if got["database"] is None and got["table"] is None:
        return False, []
    if got["table"] is None:
        return True, ["its table is not there"]
    return True, ([] if subset(r.obj("glue-table"), got["table"].get("Table")) else ["its table is not the render"])


def _b_workgroup(t: "Twin", r: Render) -> Built:
    n = t.n
    r.doc("workgroup-configuration")
    r.doc("workgroup-tags")
    return Built(
        [W("athena", "create-work-group", "--name", n.workgroup, "--configuration", r.url("workgroup-configuration"), "--tags",
           r.url("workgroup-tags"))],
        [("workgroup", R("athena", "get-work-group", "--work-group", n.workgroup))],
        [W("athena", "delete-work-group", "--work-group", n.workgroup, "--recursive-delete-option")])


def _j_workgroup(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    wg = _policy_of(got["workgroup"], "WorkGroup")
    if wg is None:
        return False, []
    return True, ([] if subset(r.obj("workgroup-configuration"), wg.get("Configuration")) else ["its configuration is not the render"])


def code_sha256(digest: str) -> str:
    """A sha256 given in hex, in the form the service reports a function's code in (CodeSha256): base64 of the digest."""
    return base64.b64encode(bytes.fromhex(digest)).decode("ascii")


def zip_bytes(source: bytes, entry: str = ZIP_ENTRY) -> bytes:
    """THE FUNCTION'S ZIP: one entry, stored (not compressed), with a fixed time (1980-01-01 00:00:00) and a fixed mode (a
    regular file, 0644, made on Unix), no extra field and no comment. The three records are written out here, not by the
    zipfile module, so that the bytes depend on the source alone: not on the interpreter that builds them, its
    version, its platform, the clock or the file's own mode. Two builds give one sha256, and it is known before the
    upload. A source with a carriage return in it is refused: a checkout that converted the line ends would give
    other bytes, and another function than the one that was tested."""
    if b"\r" in source:
        refuse("source-has-a-carriage-return", "the function's source holds a carriage return (a checkout that converts line ends): the zip "
               "is built from the bytes the tests ran on, and from no others")
    name = entry.encode("ascii")
    crc, size = zlib.crc32(source) & 0xFFFFFFFF, len(source)
    time_, date = 0, (0 << 9) | (1 << 5) | 1                        # 00:00:00 on 1980-01-01, the format's first day
    local = struct.pack("<4sHHHHHIIIHH", b"PK\x03\x04", 20, 0, 0, time_, date, crc, size, size, len(name), 0) + name
    central = struct.pack("<4sHHHHHHIIIHHHHHII", b"PK\x01\x02", (3 << 8) | 20, 20, 0, 0, time_, date, crc, size, size, len(name), 0, 0, 0, 0,
                          0o100644 << 16, 0) + name
    end = struct.pack("<4sHHHHIIH", b"PK\x05\x06", 0, 0, 1, 1, len(central), len(local) + size, 0)
    return local + source + central + end


def check_breaker_source(source: bytes) -> None:
    """What `build-breaker` refuses of the source before it is zipped: a file that does not compile or has no function of
    the handler's name at its top (the function would be created and fail at its first invoke), and one that holds a
    literal of the state (the zip would carry an identifier). By the kind and the position, never by the value."""
    wanted = HANDLER.split(".")[1]
    try:
        tree = ast.parse(source.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError, ValueError):
        tree = None
    if tree is None or not [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == wanted]:
        refuse("source-has-no-handler", "the function's source does not compile, or defines no function `%s` at its top: created from "
               "it, the function would fail at its first invoke" % wanted)
    for kind, values in sorted(OUT.kinds.items()):
        for i, value in enumerate(values, 1):
            if value.encode("utf-8") in source:
                refuse("source-holds-a-literal", "value %d of the kind %s stands in the function's source: the zip would carry an "
                       "identifier (the value is not printed)" % (i, kind))


NOT_THE_BUILD = ("the zip at TWIN_BREAKER_ZIP is NOT the build of the breaker's source as it stands (sdv/cloud/breaker/breaker.py was "
                 "changed since it was built, or the file is another zip)")


def source_build() -> str:
    """The sha256 of the zip `build-breaker` would write from the breaker's source AS IT STANDS: built in memory, from
    the bytes of the file, by the function that builds the zip. A source that is not there or that cannot be built is
    refused by the name `build-breaker` gives it."""
    try:
        source = BREAKER_SOURCE.read_bytes()
    except OSError:
        refuse("source-missing", "the function's source is not where twinctl reads it from (sdv/cloud/breaker/breaker.py)")
    return hashlib.sha256(zip_bytes(source)).hexdigest()


def _b_function(t: "Twin", r: Render) -> Built:
    n = t.n
    artefact = r.input("TWIN_BREAKER_ZIP", "the breaker function's zip, which `twinctl build-breaker` makes; the function's step is refused "
                                           "until it exists")
    if r.strict and r.inputs["TWIN_BREAKER_ZIP"] != source_build():
        # THE ZIP IS HELD TO THE SOURCE (the owner's call of 2026-10-12, left to the orchestrator and decided so). An approval
        # covers the zip's content, and nothing said whose content it is: after a fix to breaker.py and no rebuild the
        # account ran the old code with no word anywhere. The comparison is of BUILT BYTES, the hash of what lies at the
        # path against the hash of what `build-breaker` would write now: no path, no time. The render is still printed
        # (it says which it is); it is never applied, and `plan` refuses the step by the same name
        r.unfit = ("zip-not-the-source", NOT_THE_BUILD + ": the function would run code that is not the source's. `twinctl "
                   "build-breaker` builds it again; nothing was sent")
    r.doc("function-environment")
    r.doc("function-tags")
    return Built(
        [W("lambda", "create-function", "--function-name", n.function, "--runtime", "python3.12", "--architectures", "arm64", "--handler",
           HANDLER, "--role", n.role_arn(n.breaker_role), "--zip-file", file_url(artefact, binary=True), "--memory-size", "128",
           "--timeout", "30", "--environment", r.url("function-environment"), "--tags", r.url("function-tags"))],
        [("function", R("lambda", "get-function", "--function-name", n.function)),
         ("urls", R("lambda", "list-function-url-configs", "--function-name", n.function))],
        [W("lambda", "delete-function", "--function-name", n.function)])


def _j_function(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    c = _policy_of(got["function"], "Configuration")
    if c is None:
        return False, []
    n = t.n
    diffs = []
    want = {"Runtime": "python3.12", "Handler": HANDLER, "Role": n.role_arn(n.breaker_role), "MemorySize": 128, "Timeout": 30,
            "Architectures": ["arm64"]}
    if not subset(want, c):
        diffs.append("its configuration is not the render (runtime, architecture, handler, role, memory, time-out)")
    # held to the hash the state RECORDED when the function was made, which is the one the approved render printed: never to
    # whatever lies at the path when the read is made (WP6's critic, problem 5)
    recorded = recorded_input(t, "function", "TWIN_BREAKER_ZIP")
    if recorded is None:
        diffs.append("its code cannot be compared: the state records no hash of the zip it was made from")
    elif c.get("CodeSha256") != code_sha256(recorded):
        diffs.append("its code is not the zip the state records (CodeSha256 differs)")
    if _policy_of(c, "Environment", "Variables") != r.obj("function-environment")["Variables"]:
        diffs.append("its environment is not the render")
    if c.get("Layers") or _policy_of(c, "VpcConfig", "SubnetIds"):
        diffs.append("it has a layer or a VPC")
    if (got.get("urls") or {}).get("FunctionUrlConfigs"):
        diffs.append("it has a function URL")
    return True, diffs


def recorded_input(t: "Twin", step_id: str, key: str) -> Optional[str]:
    """The sha256 the state recorded for a file a step's create uploaded, or None."""
    value = (t.state.data["steps"].get(step_id, {}).get("inputs") or {}).get(key)
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None


def input_diffs(t: "Twin", rd: "Rendered") -> List[str]:
    """What a step that STANDS is not, of the render as it is printed now. A file a create uploads is in the render by its
    content, and the step was made from the content the state recorded: another file at the path is another render, and
    its approval is not answered "already made, as rendered" of a function, or a certificate, that was made from the
    first one (WP7-verify-r1's SHOULD 1: after a rebuilt zip the owner read "as rendered" under the new hash and went on
    to the dry trip with the old code). A state that records no hash for the step cannot say which file it was made
    from, and that is said too."""
    out = []
    for key, content in sorted(rd.render.inputs.items()):
        recorded = recorded_input(t, rd.step.id, key)
        if recorded is None:
            out.append("the state records no hash of the file %s names: whether it is the one this step was made from cannot be said" % key)
        elif recorded != content:
            out.append("the file %s names is not the one this step was made from (its sha256 is not the one the state records)" % key)
    return out


def source_note(t: "Twin") -> str:
    """What `status` adds to the function's line when the breaker's source has changed since the build the function was
    made from: the recorded hash of that zip against the hash of what `build-breaker` would write now. A WORD AND NO
    FAILURE: the account still runs what was approved, and the function is held to the recorded hash either way."""
    recorded = recorded_input(t, "function", "TWIN_BREAKER_ZIP")
    if recorded is None:
        return ""
    try:
        now = source_build()
    except TwinError:
        return " (the breaker's source cannot be built as it stands: whether it changed since the build this function was made from is not said)"
    return "" if now == recorded else (" (the breaker's source has changed since the build this function was made from: the account runs "
                                       "the code that was approved; `build-breaker`, then the function's step made anew, put the new one there)")


def zip_note(t: "Twin") -> str:
    """What `status` adds to the function's line when the file at the zip's path is no longer the one the function was made
    from. No difference of the function: it is held to the recorded hash either way."""
    recorded = recorded_input(t, "function", "TWIN_BREAKER_ZIP")
    if recorded is None:
        return ""
    path = Path(os.path.expanduser(t.n.v.get("TWIN_BREAKER_ZIP", "")))
    try:
        same = "TWIN_BREAKER_ZIP" in t.n.v and hashlib.sha256(path.read_bytes()).hexdigest() == recorded
    except OSError:
        return " (the zip is no longer at its path; the function is held to the sha256 the state records)"
    return "" if same else " (the zip at its path is not the one it was made from; the function is held to the sha256 the state records)"


def _b_concurrency(t: "Twin", r: Render) -> Built:
    n = t.n
    return Built([W("lambda", "put-function-concurrency", "--function-name", n.function, "--reserved-concurrent-executions", "1")],
                 [("concurrency", R("lambda", "get-function-concurrency", "--function-name", n.function))],
                 [W("lambda", "delete-function-concurrency", "--function-name", n.function)])


def _j_concurrency(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    value = (got["concurrency"] or {}).get("ReservedConcurrentExecutions")
    if value is None:
        return False, []
    return True, ([] if value == 1 else ["its reserved concurrency is not 1"])


def _b_function_policy(t: "Twin", r: Render) -> Built:
    n = t.n
    r.doc("function-policy")
    creates = [W("lambda", "add-permission", "--function-name", n.function, "--statement-id", "alarm-" + k, "--action", "lambda:InvokeFunction",
                 "--principal", ALARMS_PRINCIPAL, "--source-account", n.account, "--source-arn", n.alarm_arn(k)) for k in BREAKER_ALARMS]
    deletes = [W("lambda", "remove-permission", "--function-name", n.function, "--statement-id", "alarm-" + k) for k in BREAKER_ALARMS]
    return Built(creates, [("policy", R("lambda", "get-policy", "--function-name", n.function))], deletes)


def _j_function_policy(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    have = canon_policy(_policy_of(got["policy"], "Policy"))
    if got["policy"] is None or have is None or not have["Statement"]:
        return False, []
    want = canon_policy(r.obj("function-policy"))
    extra = set(have["Statement"]) - set(want["Statement"])
    if _live(t, "rule-count-alarm"):
        extra = {s for s in extra if json.loads(s).get("Sid") != "alarm-rule-count"}
    if extra or set(want["Statement"]) - set(have["Statement"]):
        return True, ["it is not one statement per breaker alarm and nothing else"]
    return True, []


def _b_topic(t: "Twin", r: Render) -> Built:
    """The notice topic, its explicit policy and the owner's e-mail subscription: row 15 is one row. The subscription
    has no delete call of its own: it goes with the topic (a pending one has no ARN to unsubscribe by). The
    rehearsal's topic has no subscription."""
    n = t.n
    r.doc("topic-policy")
    r.doc("topic-tags")
    creates = [W("sns", "create-topic", "--name", n.topic, "--tags", r.url("topic-tags")),
               W("sns", "set-topic-attributes", "--topic-arn", n.topic_arn, "--attribute-name", "Policy", "--attribute-value",
                 r.url("topic-policy"))]
    reads = [("topic", R("sns", "get-topic-attributes", "--topic-arn", n.topic_arn))]
    if not n.rehearsal:
        if "TWIN_NOTICE_ADDRESS" not in n.v:
            refuse("input-unset", "TWIN_NOTICE_ADDRESS is not set: the owner gives the notice's address at this step (section 6, item 6)")
        creates.append(W("sns", "subscribe", "--topic-arn", n.topic_arn, "--protocol", "email", "--notification-endpoint",
                         n.v["TWIN_NOTICE_ADDRESS"]))
        reads.append(("subscriptions", R("sns", "list-subscriptions-by-topic", "--topic-arn", n.topic_arn)))
    return Built(creates, reads, [W("sns", "delete-topic", "--topic-arn", n.topic_arn)])


def _j_topic(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    if got["topic"] is None:
        return False, []
    diffs = []
    if canon_policy(_policy_of(got["topic"], "Attributes", "Policy")) != canon_policy(r.obj("topic-policy")):
        diffs.append("its policy is not the render")
    if not t.n.rehearsal:
        subs = (got.get("subscriptions") or {}).get("Subscriptions", []) or []
        if len(subs) != 1 or subs[0].get("Protocol") != "email" or subs[0].get("Endpoint") != t.n.v.get("TWIN_NOTICE_ADDRESS"):
            diffs.append("it does not have the one e-mail subscription of the owner's address")
        elif not str(subs[0].get("SubscriptionArn", "")).startswith("arn:"):
            diffs.append("its subscription waits for the owner's confirmation (sns confirm-subscription, with authenticated unsubscribe)")
    return True, diffs


def _b_iot_logging(t: "Twin", r: Render) -> Built:
    n = t.n
    return Built([W("iot", "set-v2-logging-options", "--role-arn", n.role_arn(n.iot_logging_role), "--default-log-level", "ERROR",
                    "--no-disable-all-logs")],
                 [("logging", R("iot", "get-v2-logging-options"))],
                 [W("iot", "set-v2-logging-options", "--disable-all-logs")])


def _j_iot_logging(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    lg = got["logging"]
    if not lg or lg.get("disableAllLogs") is True or not lg.get("roleArn"):
        return False, []
    same = lg.get("roleArn") == t.n.role_arn(t.n.iot_logging_role) and lg.get("defaultLogLevel") == "ERROR"
    return True, ([] if same else ["it is not ERROR with the owner-made role"])


def _alarm_states(t: "Twin", keys: Sequence[str]) -> Dict[str, Optional[Dict[str, Any]]]:
    got = t.aws.read(R("cloudwatch", "describe-alarms", "--alarm-names", *[t.n.alarm[k] for k in keys])) or {}
    found = {a.get("AlarmName"): a for a in got.get("MetricAlarms", []) or []}
    return {k: found.get(t.n.alarm[k]) for k in keys}


def breaker_alarm_keys(t: "Twin") -> List[str]:
    return list(BREAKER_ALARMS) + (["rule-count"] if _live(t, "rule-count-alarm") else [])


def alarms_block(t: "Twin") -> Optional[str]:
    """Why the breaker is not armed: a breaker alarm that is missing, in ALARM, or has its actions disabled (gap aa)."""
    states = _alarm_states(t, breaker_alarm_keys(t))
    missing = sum(1 for a in states.values() if a is None)
    alarm = sum(1 for a in states.values() if a is not None and a.get("StateValue") == "ALARM")
    disabled = sum(1 for a in states.values() if a is not None and a.get("ActionsEnabled") is not True)
    if missing or alarm or disabled:
        return ("of %d breaker alarm(s), %d are not there, %d are in ALARM and %d have their actions disabled: an alarm acts only when it "
                "changes state, so under a standing ALARM the breaker is disarmed" % (len(states), missing, alarm, disabled))
    return None


# The two steps that are made by go-live and unmade by a trip: a rule that is disabled and a certificate that is INACTIVE
# are THERE, and "not found" was the word of a read that found them (the rehearsal of WP8, item 5).
GO_LIVE = ("go-live-rule", "go-live-certificate")
NOT_LIVE = "not live (tripped, or not made live)"
AFTER_A_TRIP = ("After a trip of a twin that was live this is what the breaker left: `twinctl restore` (sdv/cloud/README.md) gives the three "
                "calls that make it live again, and their proofs")


def _pre_go_live(t: "Twin", r: Render) -> Optional[str]:
    block = alarms_block(t)
    if block:
        return block
    policy, thing, kind = _attached(t)
    if not policy or not thing or kind != "EXCLUSIVE_THING":
        tripped = any(t.state.status(step) in OURS for step in GO_LIVE)         # recorded as made live: the cut is then a trip's
        return ("the policy or the certificate is not attached as rendered (after an alarm's test the policy is attached again first)"
                + (". " + AFTER_A_TRIP if tripped else ""))
    return None


def _b_live_rule(t: "Twin", r: Render) -> Built:
    n = t.n
    return Built([W("iot", "enable-topic-rule", "--rule-name", n.rule)], [("rule", R("iot", "get-topic-rule", "--rule-name", n.rule))],
                 [W("iot", "disable-topic-rule", "--rule-name", n.rule)])


def _j_live_rule(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    rule = _policy_of(got["rule"], "rule")
    return (rule is not None and rule.get("ruleDisabled") is False), []


def _b_live_certificate(t: "Twin", r: Render) -> Built:
    cert = r.lookup("CERT_ID", "go-live-certificate")
    reads = [] if "certificate" in r.provisional else [("certificate", R("iot", "describe-certificate", "--certificate-id", cert))]
    return Built([W("iot", "update-certificate", "--certificate-id", cert, "--new-status", "ACTIVE")], reads,
                 [W("iot", "update-certificate", "--certificate-id", cert, "--new-status", "INACTIVE")])


def _j_live_certificate(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    return _policy_of(got.get("certificate"), "certificateDescription", "status") == "ACTIVE", []


def _b_alarm_test(key: str) -> Callable[["Twin", Render], Built]:
    def build(t: "Twin", r: Render) -> Built:
        if key == "rule-count":
            r.lookup("RULE_COUNT_METRIC", "alarm-test-rule-count")
        return Built([W("cloudwatch", "set-alarm-state", "--alarm-name", t.n.alarm[key], "--state-value", "ALARM", "--state-reason",
                        "twinctl: a test of this alarm's action")])
    return build


def _b_reattach(t: "Twin", r: Render) -> Built:
    return Built([W("iot", "attach-policy", "--policy-name", t.n.policy, "--target", r.lookup("CERT_ARN", "reattach-policy"))])


# --- Phase 6 WP4: the ECR repositories (row B2) and the Orin's pull identity (rows B1 and B3); spec section 5, items 2 to 5

def _operator_policy(t: "Twin", r: Render, obj: Any) -> Any:
    """THE OPERATOR ROLE'S POLICY WITH PHASE 6'S GRANTS (D8), each part only with its key: templates/operator-role-policy-ecr.json
    with TWIN_ECR=1 (the reads with no resource type added to NoResourceType, ECR Public's writes named in DenyPublicPaths in
    place of ecr-public:*, the statement on the twin's repositories), templates/operator-role-policy-pull.json with TWIN_PULL_ROLE
    (the alias's listing added to NoResourceType, the statements on the alias and on the pull role). The new statements stand
    before the first Deny. With neither key the document is the template as it is, the one A1 row 3 made the role from."""
    n = t.n
    parts = ([r.fragment("operator-role-policy-ecr")] if n.ecr else []) + ([r.fragment("operator-role-policy-pull")] if n.pull_role else [])
    if not parts:
        return obj
    try:
        statements = obj["Statement"]
        by_sid = {s["Sid"]: s for s in statements}
        first_deny = [i for i, s in enumerate(statements) if s["Effect"] == "Deny"][0]
        added: List[Any] = []
        for part in parts:
            by_sid["NoResourceType"]["Action"] = list(by_sid["NoResourceType"]["Action"]) + list(part["NoResourceType"])
            if "DenyPublicPaths" in part:
                deny = list(by_sid["DenyPublicPaths"]["Action"])
                at = deny.index("ecr-public:*")
                by_sid["DenyPublicPaths"]["Action"] = deny[:at] + list(part["DenyPublicPaths"]) + deny[at + 1:]
            added += list(part["Statement"])
    except (KeyError, IndexError, ValueError, TypeError):
        refuse("template-invalid", "the operator policy's template, or one of its Phase 6 parts, is not in the form they are merged in")
    obj["Statement"] = statements[:first_deny] + added + statements[first_deny:]
    return obj


def c_images(repository: str) -> Call:
    return R("ecr", "list-images", "--repository-name", repository)


def c_image_by_tag(repository: str, tag: str) -> Call:
    return R("ecr", "describe-images", "--repository-name", repository, "--image-ids", "imageTag=" + tag)


def c_login_password() -> Call:
    """`push`'s login: what the CLI prints is the registry's password, which goes by a pipe into docker's stdin and into no file (the
    runner, which keeps every reply in the state directory, never sends this one: cmd_push spawns it)."""
    return R("ecr", "get-login-password")


def c_credential_endpoint() -> Call:
    return R("iot", "describe-endpoint", "--endpoint-type", "iot:CredentialProvider")


def _b_ecr_repository(t: "Twin", r: Render) -> Built:
    """One repository per app, IMMUTABLE, encryption AES256 given explicitly, the twin's tag; no scanning configuration (it is the
    registry's: wp0-facts E1) and NO REPOSITORY POLICY, ever (R2: with none, only this account's principals reach it, through IAM)."""
    r.doc("repository-encryption")
    r.doc("repository-tags")
    creates, reads, deletes = [], [], []
    for repo in t.n.repositories:
        creates.append(W("ecr", "create-repository", "--repository-name", repo, "--image-tag-mutability", "IMMUTABLE", "--encryption-configuration",
                         r.url("repository-encryption"), "--tags", r.url("repository-tags")))
        reads += [("repository:" + repo, R("ecr", "describe-repositories", "--repository-names", repo)),
                  ("policy:" + repo, R("ecr", "get-repository-policy", "--repository-name", repo))]
        deletes.append(W("ecr", "delete-repository", "--repository-name", repo))
    return Built(creates, reads, deletes)


def _j_ecr_repository(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    found, diffs = [], []
    for repo in t.n.repositories:
        listed = [x for x in (got["repository:" + repo] or {}).get("repositories", []) or []
                  if isinstance(x, dict) and x.get("repositoryName") == repo]
        if not listed:
            continue
        found.append(repo)
        if listed[0].get("imageTagMutability") != "IMMUTABLE":
            diffs.append("%s: its tags are not IMMUTABLE" % repo)
        if _policy_of(listed[0], "encryptionConfiguration", "encryptionType") != "AES256":
            diffs.append("%s: its encryption is not AES256" % repo)
        if got["policy:" + repo] is not None:
            diffs.append("%s has a repository policy" % repo)
    if not found:
        return False, []
    return True, diffs + ["the repository %s is not there" % repo for repo in t.n.repositories if repo not in found]


def _ready_ecr_repository(t: "Twin", r: Render) -> Optional[str]:
    for repo in t.n.repositories:
        images = (t.aws.read(c_images(repo)) or {}).get("imageIds", []) or []
        if images:
            return ("the repository %s holds %d image(s): they are deleted first, by hand (sdv/cloud/README.md, the ECR steps, says how); "
                    "the repository's delete takes no --force" % (repo, len(images)))
    return None


def _b_ecr_lifecycle(t: "Twin", r: Render) -> Built:
    r.doc("repository-lifecycle")
    repos = t.n.repositories
    return Built([W("ecr", "put-lifecycle-policy", "--repository-name", repo, "--lifecycle-policy-text", r.url("repository-lifecycle"))
                  for repo in repos],
                 [("lifecycle:" + repo, R("ecr", "get-lifecycle-policy", "--repository-name", repo)) for repo in repos],
                 [W("ecr", "delete-lifecycle-policy", "--repository-name", repo) for repo in repos])


def _j_ecr_lifecycle(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    present, diffs = False, []
    for repo in t.n.repositories:
        reply = got["lifecycle:" + repo]
        if reply is None:
            continue
        present = True
        try:
            text = json.loads(str(reply.get("lifecyclePolicyText")))
        except ValueError:
            text = None
        if not isinstance(text, dict) or not subset(r.obj("repository-lifecycle"), text):
            diffs.append("%s: its lifecycle policy is not the render" % repo)
    if present:
        diffs += ["%s has no lifecycle policy" % repo for repo in t.n.repositories if got["lifecycle:" + repo] is None]
    return present, diffs


def _pull_role_given(t: "Twin") -> str:
    if not t.n.pull_role:
        refuse("names-missing", "TWIN_PULL_ROLE is not given in the form twinctl takes for it: the pull steps that stand are not rendered")
    return t.n.pull_role


def _b_role_alias(t: "Twin", r: Render) -> Built:
    role = t.n.role_arn(_pull_role_given(t))
    return Built([W("iot", "create-role-alias", "--role-alias", ROLE_ALIAS, "--role-arn", role, "--credential-duration-seconds",
                    str(ROLE_ALIAS_SECONDS))],
                 [("alias", R("iot", "describe-role-alias", "--role-alias", ROLE_ALIAS))],
                 [W("iot", "delete-role-alias", "--role-alias", ROLE_ALIAS)])


def _j_role_alias(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    d = _policy_of(got["alias"], "roleAliasDescription")
    if d is None:
        return False, []
    diffs = []
    if d.get("roleArn") != t.n.role_arn(t.n.pull_role):
        diffs.append("it does not name the pull role")
    if d.get("credentialDurationSeconds") != ROLE_ALIAS_SECONDS or isinstance(d.get("credentialDurationSeconds"), bool):
        diffs.append("its credentials do not last %d s" % ROLE_ALIAS_SECONDS)
    return True, diffs


def _b_pull_policy(t: "Twin", r: Render) -> Built:
    n = t.n
    r.doc("pull-policy")
    r.doc("policy-tags")
    return Built([W("iot", "create-policy", "--policy-name", n.pull_policy, "--policy-document", r.url("pull-policy"), "--tags",
                    r.url("policy-tags"))],
                 [("policy", R("iot", "get-policy", "--policy-name", n.pull_policy))],
                 [W("iot", "delete-policy", "--policy-name", n.pull_policy)])


def _j_pull_policy(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    if got["policy"] is None:
        return False, []
    same = canon_policy(got["policy"].get("policyDocument")) == canon_policy(r.obj("pull-policy"))
    return True, ([] if same else ["its document is not the render"])


def _ready_pull_policy(t: "Twin", r: Render) -> Optional[str]:
    got = t.aws.read(R("iot", "list-targets-for-policy", "--policy-name", t.n.pull_policy))
    if got and got.get("targets"):
        return "the pull policy is still attached to %d target(s): it is detached first (teardown pull-attachment)" % len(got["targets"])
    return None


def _own_pull_cert(t: "Twin") -> Tuple[Optional[str], Optional[str]]:
    """The id the pull certificate's own step reads and deletes by, as _own_cert() is the twin's certificate's."""
    cert = t.state.fact(PULL_UNCONFIRMED) or t.state.fact("pull_certificate_id")
    return cert, (t.n.arn("iot", "cert/" + cert) if cert else None)


def _b_pull_certificate(t: "Twin", r: Render) -> Built:
    """The Orin's certificate for the credential provider, from the signing request made on the board (D2 (a): its key never
    leaves the board), created INACTIVE; `pull-active` and `pull-inactive` set it for a board day and after it."""
    n = t.n
    csr = r.input("TWIN_ORIN_CSR", "the Orin's signing request, made on the board where its key is made")
    if r.strict and "TWIN_ORIN_CERTIFICATE_OUT" not in n.v:
        refuse("input-unset", "TWIN_ORIN_CERTIFICATE_OUT is not set: where the pull certificate's PEM is written")
    out = Path(os.path.expanduser(n.v.get("TWIN_ORIN_CERTIFICATE_OUT", "twin_orin_certificate_out-is-not-set")))
    if r.strict and REDACT.in_a_work_tree(out):
        refuse("inside-a-work-tree", "the pull certificate's file would lie inside a work tree: it goes to the board's device directory")
    cert, _arn = _own_pull_cert(t)
    creates = [W("iot", "create-certificate-from-csr", "--certificate-signing-request", file_url(csr), "--no-set-as-active",
                 "--certificate-pem-outfile", out.as_posix())]
    if cert is None:
        return Built(creates, [], [])
    return Built(creates, [("certificate", R("iot", "describe-certificate", "--certificate-id", cert))],
                 [W("iot", "delete-certificate", "--certificate-id", cert)])


def _j_pull_certificate(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    d = _policy_of(got.get("certificate"), "certificateDescription")
    if d is None:
        return False, []
    return True, ([] if d.get("status") in ("ACTIVE", "INACTIVE") else ["it is neither ACTIVE nor INACTIVE"])


def _ready_pull_certificate(t: "Twin", r: Render) -> Optional[str]:
    cert, arn = _own_pull_cert(t)
    if cert is None or arn is None:
        return None
    d = _policy_of(t.aws.read(R("iot", "describe-certificate", "--certificate-id", cert)), "certificateDescription")
    if d is None:
        return None
    if d.get("status") != "INACTIVE":
        return "the pull certificate is not INACTIVE: it is set INACTIVE first (apply pull-inactive)"
    if (t.aws.read(R("iot", "list-attached-policies", "--target", arn)) or {}).get("policies"):
        return "a policy is still attached to the pull certificate: it is detached first (teardown pull-attachment)"
    if t.n.pull_thing:
        principals = t.aws.read(R("iot", "list-thing-principals-v2", "--thing-name", t.n.pull_thing)) or {}
        if any(p.get("principal") == arn for p in principals.get("thingPrincipalObjects", []) or []):
            return "the pull certificate is still attached to the pull thing: it is detached first (teardown pull-attachment)"
    return None


def _pull_thing_given(t: "Twin") -> str:
    if not t.n.pull_thing:
        refuse("names-missing", "TWIN_PULL_THING is not given in the form twinctl takes for it, and the state records the pull thing")
    return t.n.pull_thing


def _b_pull_thing(t: "Twin", r: Render) -> Built:
    thing = _pull_thing_given(t)
    return Built([W("iot", "create-thing", "--thing-name", thing)], [("thing", R("iot", "describe-thing", "--thing-name", thing))],
                 [W("iot", "delete-thing", "--thing-name", thing)])


def _b_pull_attachment(t: "Twin", r: Render) -> Built:
    n = t.n
    arn = r.lookup("PULL_CERT_ARN", "pull-attachment")
    thing = _pull_thing_given(t) if (n.pull_thing or t.state.status("pull-thing") in OURS) else ""
    creates = [W("iot", "attach-policy", "--policy-name", n.pull_policy, "--target", arn)]
    deletes = [W("iot", "detach-policy", "--policy-name", n.pull_policy, "--target", arn)]
    reads = [] if "pull-certificate" in r.provisional else [("policies", R("iot", "list-attached-policies", "--target", arn))]
    if thing:
        creates.append(W("iot", "attach-thing-principal", "--thing-name", thing, "--principal", arn, "--thing-principal-type", "EXCLUSIVE_THING"))
        deletes.insert(0, W("iot", "detach-thing-principal", "--thing-name", thing, "--principal", arn))
        reads += [] if "pull-certificate" in r.provisional else [("principals", R("iot", "list-thing-principals-v2", "--thing-name", thing))]
    return Built(creates, reads, deletes)


def _j_pull_attachment(t: "Twin", r: Render, got: Dict[str, Any]) -> Tuple[bool, List[str]]:
    _cert_id, arn = _own_pull_cert(t)
    policy = any(p.get("policyName") == t.n.pull_policy for p in (got.get("policies") or {}).get("policies", []) or [])
    thing = "principals" in got
    mine = [p for p in (got.get("principals") or {}).get("thingPrincipalObjects", []) or [] if p.get("principal") == arn]
    if not policy and not mine:
        return False, []
    diffs = [] if policy else ["the pull policy is not attached to the pull certificate"]
    if thing and not mine:
        diffs.append("the pull certificate is not attached to the pull thing")
    elif thing and mine[0].get("thingPrincipalType") != "EXCLUSIVE_THING":
        diffs.append("the pull certificate's attachment to the pull thing is not exclusive")
    return True, diffs


def _b_pull_status(status: str) -> Callable[["Twin", Render], Built]:
    def build(t: "Twin", r: Render) -> Built:
        return Built([W("iot", "update-certificate", "--certificate-id", r.lookup("PULL_CERT_ID", "pull-" + status.lower()), "--new-status", status)])
    return build


def pull_certificates(t: "Twin") -> List[str]:
    """The pull certificate, while its step stands: the set `status` says apart from the twin's data certificate."""
    cert = t.state.fact("pull_certificate_id")
    return [cert] if cert and t.state.status("pull-certificate") in OURS else []


LISTINGS: Dict[str, Tuple[Call, Callable[[Any], List[str]]]] = {
    "buckets": (R("s3api", "list-buckets"), lambda o: [str(b.get("Name")) for b in o.get("Buckets", []) or []]),
    "log-groups": (R("logs", "describe-log-groups"), lambda o: [str(g.get("logGroupName")) for g in o.get("logGroups", []) or []]),
    "streams": (R("firehose", "list-delivery-streams"), lambda o: [str(s) for s in o.get("DeliveryStreamNames", []) or []]),
    "rules": (R("iot", "list-topic-rules"), lambda o: [str(r.get("ruleName")) for r in o.get("rules", []) or []]),
    "things": (R("iot", "list-things"), lambda o: [str(x.get("thingName")) for x in o.get("things", []) or []]),
    "certificates": (R("iot", "list-certificates"), lambda o: [str(c.get("certificateId")) for c in o.get("certificates", []) or []]),
    "policies": (R("iot", "list-policies"), lambda o: [str(p.get("policyName")) for p in o.get("policies", []) or []]),
    "databases": (R("glue", "get-databases"), lambda o: [str(d.get("Name")) for d in o.get("DatabaseList", []) or []]),
    "workgroups": (R("athena", "list-work-groups"), lambda o: [str(w.get("Name")) for w in o.get("WorkGroups", []) or []]),
    "functions": (R("lambda", "list-functions"), lambda o: [str(f.get("FunctionName")) for f in o.get("Functions", []) or []]),
    "topics": (R("sns", "list-topics"), lambda o: [str(x.get("TopicArn")) for x in o.get("Topics", []) or []]),
    "alarms": (R("cloudwatch", "describe-alarms"), lambda o: [str(a.get("AlarmName")) for a in o.get("MetricAlarms", []) or []]),
}
# Phase 6's two listings, in a table only when a step of theirs is (listings_of()): a baseline taken before Phase 6 holds neither,
# so each holds the twin's own namespace only, which nothing made before Phase 6 is in (a name in it the baseline lacks is a
# leftover of the twin's, or a name taken by someone else, which `apply` refuses as not ours by the step's own read).
LISTINGS_PHASE6: Dict[str, Tuple[Call, Callable[[Any], List[str]]]] = {
    "repositories": (R("ecr", "describe-repositories"),
                     lambda o: [str(x.get("repositoryName")) for x in o.get("repositories", []) or []
                                if isinstance(x, dict) and str(x.get("repositoryName", "")).startswith(ECR_NAMESPACE + "/")]),
    "role-aliases": (R("iot", "list-role-aliases"), lambda o: [str(a) for a in o.get("roleAliases", []) or [] if str(a).startswith(ECR_NAMESPACE)]),
}


def listing_of(key: str) -> Tuple[Call, Callable[[Any], List[str]]]:
    return LISTINGS[key] if key in LISTINGS else LISTINGS_PHASE6[key]


def listings_of(t: "Twin") -> Dict[str, Tuple[Call, Callable[[Any], List[str]]]]:
    """LISTINGS, and Phase 6's of the steps the table holds: with no new key it is LISTINGS, as it was."""
    out = dict(LISTINGS)
    out.update({s.listing: LISTINGS_PHASE6[s.listing] for s in t.steps if s.listing in LISTINGS_PHASE6})
    return out


# --- the calls a command sends that are no step's own: each has one constructor, used where it is sent and in OTHER

def c_identity() -> Call:
    return R("sts", "get-caller-identity")


def c_endpoint() -> Call:
    return R("iot", "describe-endpoint", "--endpoint-type", "iot:Data-ATS")


def c_tagged(t: "Twin") -> Call:
    return R("resourcegroupstaggingapi", "get-resources", "--tag-filters", "Key=%s,Values=%s" % (t.n.tag_key, t.n.prefix))


def c_objects(t: "Twin", top: bool = False) -> Call:
    return R("s3api", "list-objects-v2", "--bucket", t.n.bucket, *(("--delimiter", "/") if top else ()))


def c_delete_objects(t: "Twin", url: str) -> Call:
    return W("s3api", "delete-objects", "--bucket", t.n.bucket, "--delete", url)


def c_policy_targets(t: "Twin") -> Call:
    return R("iot", "list-targets-for-policy", "--policy-name", t.n.policy)


def c_account_block(t: "Twin", region: Optional[str] = None) -> Call:
    return R("s3control", "get-public-access-block", "--account-id", t.n.account, *(("--region", region) if region else ()))


def c_shadow_read(t: "Twin", shadow: str) -> Call:
    return R("iot-data", "get-thing-shadow", "--thing-name", t.n.thing, "--shadow-name", shadow,
             (t.state_dir / "replies" / ("shadow-read-%s.json" % shadow)).as_posix())


C_SECURITY_GROUPS = R("ec2", "describe-security-groups")
C_AUTHORIZERS = R("iot", "list-authorizers")
C_DOMAINS = R("iot", "list-domain-configurations")
C_POOLS = R("cognito-identity", "list-identity-pools", "--max-results", "60")
C_REST_APIS = R("apigateway", "get-rest-apis")
C_HTTP_APIS = R("apigatewayv2", "get-apis")


def stop_calls(rule: str, thing: str, policy: str, cert: str, arn: str) -> List[Call]:
    """The manual stop: the trip's four calls, for when the function is broken. By the five values they are made of and not by
    a Names: the file a stop writes first is made of whatever the names file and the state give (hand_text())."""
    return [W("iot", "disable-topic-rule", "--rule-name", rule),
            W("iot", "update-certificate", "--certificate-id", cert, "--new-status", "INACTIVE"),
            W("iot-data", "delete-connection", "--client-id", thing),
            W("iot", "detach-policy", "--policy-name", policy, "--target", arn)]


def restore_calls(n: Names, cert: str, arn: str) -> Tuple[List[Call], List[Call]]:
    """By hand after a trip: the three reverse calls the owner runs, and the read that proves each."""
    return ([W("iot", "attach-policy", "--policy-name", n.policy, "--target", arn),
             W("iot", "update-certificate", "--certificate-id", cert, "--new-status", "ACTIVE"),
             W("iot", "enable-topic-rule", "--rule-name", n.rule)],
            [R("iot", "list-attached-policies", "--target", arn), R("iot", "describe-certificate", "--certificate-id", cert),
             R("iot", "get-topic-rule", "--rule-name", n.rule)])


def _b_other(t: "Twin", r: Render) -> Built:
    """THE CALLS OUTSIDE THE TABLE: what a command sends, or writes out for the owner to run, that is no step's own.
    One list, so that `plan` gives these to the CLI and holds the operator role's policy to them as to the table's,
    and so that a test can hold that no command sends a call which is in neither. The delete of the bucket's objects
    stands here with a sample key; the real one names what is listed at that moment."""
    n = t.n
    cert, arn = str(r.lookup("CERT_ID", "other")), str(r.lookup("CERT_ARN", "other"))
    r.put("delete-objects", {"Objects": [{"Key": "telemetry/a-key-that-stands-for-what-is-listed"}], "Quiet": True})
    restore, proofs = restore_calls(n, cert, arn)
    # The certificate's own delete and the read of the thing's principals stand in the table only once the state holds the
    # certificate's id; here they stand with the placeholder, so that `plan` gives them to the CLI and holds the operator
    # role's policy to them also from the state the owner makes that role from (wp8-item1, finding 3).
    writes = ([_invoke(t, r, "invoke-trip", "trip"), c_delete_objects(t, r.url("delete-objects"))]
              + stop_calls(n.rule, n.thing, n.policy, cert, arn) + restore + [W("iot", "delete-certificate", "--certificate-id", cert)])
    # the account's Block Public Access is read twice, the second time through GLOBAL_REGION: never the twin's own region
    # (names-region-not-taken), so it is always a second read
    reads = [c_identity(), c_endpoint(), c_tagged(t), c_objects(t), c_objects(t, top=True), c_policy_targets(t), c_account_block(t),
             c_account_block(t, GLOBAL_REGION)]
    reads += [C_SECURITY_GROUPS, C_AUTHORIZERS, C_DOMAINS, C_POOLS, C_REST_APIS, C_HTTP_APIS] + [c_shadow_read(t, s) for s in SHADOWS]
    reads += [R("iot", "list-thing-principals-v2", "--thing-name", n.thing)]
    if n.ecr:
        # Phase 6: `push`'s login and its read-back (with a sample tag), the repositories' image listings a teardown reads first,
        # and exit-checks' registry reads, ECR Public's through us-east-1
        reads += [c_login_password(), c_image_by_tag(n.repositories[0], "0.0.0-arm64")] + [c_images(repo) for repo in n.repositories]
        reads += [R("ecr", "get-registry-policy"), R("ecr", "describe-registry"), R("ecr", "describe-pull-through-cache-rules"),
                  R("ecr", "get-registry-scanning-configuration"), R("ecr-public", "describe-repositories", "--region", GLOBAL_REGION)]
    if n.pull_role:
        reads += [c_credential_endpoint()]                         # `ecr-config`'s one read
    reads += proofs + [call for _key, (call, _names) in sorted(listings_of(t).items())]
    return Built(writes, [("other-%d" % i, call) for i, call in enumerate(reads)], [])


OTHER = Step("other", "-", "the calls a command sends that are no step's own", _b_other, None, kind="other")


def table(t: "Twin") -> List[Step]:
    """THE STEP TABLE, in the order of the resource table. `teardown` is this list read backwards."""
    n = t.n
    notice = ["notice-topic"] if n.notice else []
    steps = [
        _role_step("operator-role", "A1.3", "the twin operator role (the owner makes it from this render)", lambda n: n.operator_role,
                   policy=_operator_policy),
        _role_step("rule-role", "A1.4", "the rule's role (the owner makes it)", lambda n: n.rule_role),
        _role_step("firehose-role", "A1.4", "the Firehose role (the owner makes it)", lambda n: n.firehose_role),
        _role_step("iot-logging-role", "A1.4", "the IoT logging role (the owner makes it)", lambda n: n.iot_logging_role),
        Step("bucket", "1", "the bucket", _b_bucket, _j_bucket, rehearse=True, listing="buckets", ready=_ready_bucket),
        Step("bucket-objects", "1", "emptying the bucket (teardown only; permanent)", lambda t, r: Built(), None, kind="empty", rehearse=True),
        _log_group_step("firehose-log", "2", "Firehose's error log group and its stream", lambda n: n.firehose_log_group,
                        lambda n: n.firehose_log_stream, rehearse=True),
        Step("stream", "3", "the Firehose stream", _b_stream, _j_stream, needs=("bucket", "firehose-log", "firehose-role"), listing="streams"),
        Step("rule", "4", "the topic rule, created disabled", _b_rule, _j_rule, needs=("stream", "rule-role"), listing="rules"),
        Step("thing", "5", "the thing", _b_thing, _j_thing, rehearse=True, listing="things", ready=_ready_thing),
        Step("shadows", "5", "the two named shadows (no create call; approved with go-live)", _b_shadows, _j_shadows, kind="appears",
             needs=("thing",), rehearse=True),
        Step("certificate", "6", "the certificate, from the device's CSR, INACTIVE", _b_certificate, _j_certificate, rehearse=True,
             listing="certificates", ready=_ready_certificate, after=_after_certificate),
        Step("policy", "7", "the device policy", _b_policy, _j_policy, rehearse=True, listing="policies", ready=_ready_policy),
        Step("attachments", "8", "the two attachments", _b_attachments, _j_attachments, needs=("thing", "certificate", "policy"),
             rehearse=True),
        Step("glue", "9", "the Glue database and table", _b_glue, _j_glue, needs=("bucket",), rehearse=True, listing="databases"),
        Step("workgroup", "10", "the Athena workgroup", _b_workgroup, _j_workgroup, needs=("bucket",), rehearse=True, listing="workgroups"),
        _log_group_step("breaker-log", "11", "the breaker's log group", lambda n: n.breaker_log_group),
        _role_step("breaker-role", "12", "the breaker's role (the owner makes it, once the certificate exists)", lambda n: n.breaker_role,
                   needs=("certificate",)),
        Step("function", "13", "the breaker function", _b_function, _j_function,
             needs=("breaker-role", "breaker-log", "rule", "policy", "certificate", "thing"), listing="functions"),
        Step("function-concurrency", "13", "the function's reserved concurrency of 1", _b_concurrency, _j_concurrency, needs=("function",)),
        Step("function-status", "13", "one invoke with the status payload: reads only",
             lambda t, r: Built([_invoke(t, r, "invoke-status", "function-status")]), None, kind="action", needs=("function",)),
        Step("function-policy", "14", "the function's resource policy: one statement per breaker alarm", _b_function_policy,
             _j_function_policy, needs=("function",)),
    ]
    if n.notice or n.rehearsal:
        steps.append(Step("notice-topic", "15", "the notice topic, its policy and the owner's e-mail subscription (the owner confirms it)",
                          _b_topic, _j_topic, rehearse=True, listing="topics"))
    steps.append(_alarm_step("alarms", "16", "the five breaker alarms", "alarms", ["function", "function-policy", "stream", "rule"] + notice,
                             rehearse=True))
    if n.notice:
        steps.append(_alarm_step("alarm-notice", "16", "the notice alarm on the function's Errors", "alarm-notice", ["function"] + notice))
    # IoT's log group has the service's own fixed name, and the service makes it itself once logging was ever on in the
    # region: then it is there before the twin, and `apply` refuses it as not ours (the hard review's NIT 6). The owner's
    # choice: delete it by hand first (its events go with it), or keep it and set TWIN_IOT_LOG_GROUP_ADOPT=1. Adopted, it is
    # a step of the owner's kind: read and held to the render (the owner sets its retention), never created and never
    # deleted here. The switch does not reach a group the state records as MADE here: that one stays the driver's to delete.
    adopt = n.v.get("TWIN_IOT_LOG_GROUP_ADOPT", "0") == "1" and not n.rehearsal and t.state.status("iot-log-group") not in OURS
    steps += [
        _log_group_step("iot-log-group", "17", "IoT's log group, which was there before the twin (adopted: read, never created or deleted)"
                        if adopt else "IoT's log group", lambda n: n.iot_log_group, adopted=adopt),
        Step("iot-logging", "17", "IoT logging at ERROR (a region-wide setting)", _b_iot_logging, _j_iot_logging,
             needs=("iot-log-group", "iot-logging-role")),
        Step("dry-trip", "17a", "the dry trip: the function's writes under its real role, before anything is live",
             lambda t, r: Built([_invoke(t, r, "invoke-trip", "dry-trip")]), None, kind="action", needs=("function", "attachments", "rule")),
    ]
    for key in BREAKER_ALARMS:
        steps.append(Step("alarm-test-" + key, "17b", "the alarm %s set to ALARM once: its action invokes the function" % key,
                          _b_alarm_test(key), None, kind="action", needs=("alarms", "function-policy", "dry-trip")))
    steps += [
        Step("reattach-policy", "17b", "the policy attached again after the tests", _b_reattach, None, kind="action",
             needs=["attachments"] + ["alarm-test-" + k for k in BREAKER_ALARMS]),
        Step("go-live-rule", "18", "go-live: the rule enabled", _b_live_rule, _j_live_rule, kind="resource",
             needs=["rule", "alarms", "iot-logging", "reattach-policy"] + (["alarm-notice"] if n.notice else []),
             pre=_pre_go_live),
        Step("go-live-certificate", "18", "go-live: the certificate ACTIVE", _b_live_certificate, _j_live_certificate,
             needs=("go-live-rule",), pre=_pre_go_live),
    ]
    # Row 19 waits for A4's readings: until then it is no step. Once its alarm is recorded as made it stays one whatever the
    # names file says: with the three keys taken out again, `teardown`, `status` and `verify-gone` would otherwise not know
    # the step (the hard review's NIT 1). Its render then refuses by the missing key's name until the keys are back.
    if any(k in n.v for k in ROW_19_KEYS) or (not n.rehearsal and t.state.status("rule-count-alarm") in OURS):
        steps += [
            _alarm_step("rule-count-alarm", "19", "the rule-side count's alarm, with its statement in the function's policy",
                        "alarm-rule-count", ["alarms", "go-live-certificate"], extra=True),
            Step("alarm-test-rule-count", "19", "the rule-side alarm set to ALARM once", _b_alarm_test("rule-count"), None, kind="action",
                 needs=("rule-count-alarm",)),
        ]
    # PHASE 6 (spec section 5): after every step of the twin's, so that a teardown removes them first. In the table with their key,
    # and, as row 19's, whatever the names file says once the state records one of them as made (a pull step as made or read).
    if not n.rehearsal and (n.ecr or any(t.state.status(s) in OURS for s in ECR_STEPS)):
        steps += [
            Step("ecr-repository", "B2", "the ECR repositories, one per app: tags IMMUTABLE, AES256, the twin's tag, no repository policy",
                 _b_ecr_repository, _j_ecr_repository, listing="repositories", ready=_ready_ecr_repository),
            Step("ecr-lifecycle", "B2", "each repository's lifecycle: one rule, the newest %d images kept" % LIFECYCLE_KEEP, _b_ecr_lifecycle,
                 _j_ecr_lifecycle, needs=("ecr-repository",)),
        ]
    if not n.rehearsal and (n.pull_role or any(t.state.status(s) in OURS + ("verified",) for s in PULL_STEPS)):
        thing = bool(n.pull_thing) or t.state.status("pull-thing") in OURS
        steps += [
            _role_step("pull-role", "B1", "the ECR pull role the credential provider assumes (the owner makes it from this render)",
                       lambda n: n.pull_role, key="TWIN_PULL_ROLE"),
            Step("role-alias", "B3", "the role alias %s: the pull role, %d s" % (ROLE_ALIAS, ROLE_ALIAS_SECONDS), _b_role_alias, _j_role_alias,
                 needs=("pull-role",), listing="role-aliases"),
            Step("pull-policy", "B3", "the pull certificate's IoT policy: iot:AssumeRoleWithCertificate on the role alias, nothing else",
                 _b_pull_policy, _j_pull_policy, listing="policies", ready=_ready_pull_policy),
        ]
        if thing:                                                   # before the certificate, as the twin's thing (row 5) is before its own
            steps.append(Step("pull-thing", "B3", "the thing the pull certificate is attached to (TWIN_PULL_THING)", _b_pull_thing, _j_thing,
                              listing="things"))
        steps += [
            Step("pull-certificate", "B3", "the Orin's pull certificate, from its signing request, INACTIVE", _b_pull_certificate,
                 _j_pull_certificate, listing="certificates", ready=_ready_pull_certificate, after=_after_pull_certificate),
            Step("pull-attachment", "B3",
                 "the pull policy attached to the pull certificate%s" % (", the certificate to the pull thing" if thing else ""),
                 _b_pull_attachment, _j_pull_attachment, needs=("pull-certificate", "pull-policy") + (("pull-thing",) if thing else ())),
            Step("pull-active", "B3", "the pull certificate ACTIVE, for a board day (by its own printed hash each time)", _b_pull_status("ACTIVE"),
                 None, kind="action", needs=("pull-attachment",)),
            Step("pull-inactive", "B3", "the pull certificate INACTIVE, after the board day", _b_pull_status("INACTIVE"), None, kind="action",
                 needs=("pull-certificate",)),
        ]
    if n.rehearsal:
        kept = [s for s in steps if s.rehearse]
        names = {s.id for s in kept}
        for s in kept:
            s.needs = tuple(x for x in s.needs if x in names)
        return kept
    return steps


# --------------------------------------------------------------------------------------------------- the driver

class Rendered(NamedTuple):
    step: Step
    render: Render
    built: Built


class Twin:
    """One run: the directories, the names, the state, the CLI. `stop` is the one-command stop's run: a state that
    cannot be read does not refuse it (it goes on with a blank one that is never written, and says so in `lacks`)."""

    def __init__(self, state_dir: Path, render_dir: Optional[Path], rehearsal: bool, stop: bool = False) -> None:
        self.top = state_dir
        values, eased = names_given(state_dir, stop=stop)
        self.n = Names(values, rehearsal)
        self.state_dir = state_dir / "rehearsal" if rehearsal else state_dir
        self.render_dir = render_dir if render_dir is not None else state_dir / "render"
        self.stop = stop
        # a stop's names file without a usable operator role (STOP_NEEDS_NOT): said by the key, with no value, and the stop goes on
        self.lacks: List[str] = ["the names file gives no usable %s (it %s): the stop needs none and goes on; every other command "
                                 "is refused until the key is given in its form" % (key, why) for key, why in sorted(eased.items())]
        self._other: Optional[State] = None
        try:
            self.top_state = State(state_dir)                       # the facts of the account: the endpoint, the canonical id
            self.state = State(self.state_dir) if rehearsal else self.top_state
        except TwinError as e:
            if not stop:
                raise
            self.lacks.append("the state cannot be read (%s): the invoke goes by the names file alone, the state is not written, and "
                              "what `status` says of the certificates stands on no state" % e.name)
            self.top_state = State(state_dir, blank=True)
            self.state = State(self.state_dir, blank=True) if rehearsal else self.top_state
        self.aws = Aws(self.n, self.state_dir)
        if not rehearsal and any(self.state.status(s) in OURS for s in ECR_STEPS):
            # TWIN_ECR FOLLOWS THE TABLE (fable#2): table() keeps an ECR step that stands whatever the names file says, as row 19's, and
            # with it go the operator policy's ECR grants, the calls of push and of the exit that plan lists, and the exit's ECR rows.
            # Read from the key alone, TWIN_ECR=0 rendered the policy without the grants the steps that stand need. The key takes
            # effect once no ECR step stands
            self.n.ecr = True
        self.steps = table(self)
        self.by_id = {s.id: s for s in self.steps}

    def step(self, step_id: str) -> Step:
        if step_id not in self.by_id:
            refuse("step-unknown", "no step of that name is in the table (twinctl plan lists them)")
        return self.by_id[step_id]

    def render(self, step: Step, strict: bool = True) -> Rendered:
        r = Render(self, step.id, strict)
        built = step.build(self, r)
        return Rendered(step, r, built)

    # --- the two states of one directory, and the names they were made under
    def other_state(self) -> State:
        """The state this run does not work on: the rehearsal's for the twin, the twin's for the rehearsal. One baseline,
        one literals file and one set of names serve both."""
        if self._other is None:
            if self.n.rehearsal:
                self._other = self.top_state
            else:
                try:
                    self._other = State(self.top / "rehearsal", blank=self.top_state.frozen)
                except TwinError:
                    if not self.stop:
                        raise
                    self._other = State(self.top / "rehearsal", blank=True)
        return self._other

    def fingerprints(self) -> Dict[str, str]:
        """The present value of each of BOUND_NAMES, salted and hashed: what a state records in place of the names."""
        values = dict(self.n.v, TWIN_REGION=self.n.region)
        s = salt(self.top)
        return {k: fingerprint(s, k, values.get(k, "")) for k in BOUND_NAMES}

    def names_changed(self) -> List[str]:
        """The keys of BOUND_NAMES whose value is no longer the one a state of this directory was made under. A state
        that records none yet takes the present ones with its first write. With the salt gone no fingerprint can be
        compared: that is refused by its own name, not as names that changed (a new salt would make every name read
        as another, with "give those names back" as the only advice)."""
        states = (self.state, self.other_state())
        if not (self.top / "salt").is_file() and any(isinstance(state.data.get("names"), dict) for state in states):
            refuse("salt-missing", "the state directory's file `salt` is gone, and its state records, salted with it, the names it was made "
                   "under: they cannot be compared with the names file's, and no approval printed before holds. Nothing is done. Put "
                   "the file back from a copy of the state directory; or, knowing that the names file is the one the state was made "
                   "under, take the entry `names` out of state.json (and out of rehearsal/state.json): the next write records the "
                   "present names under a new salt, and every render is printed again")
        now = self.fingerprints()
        changed: Set[str] = set()
        for state in (self.state, self.other_state()):
            had = state.data.get("names")
            if isinstance(had, dict):
                changed |= {k for k in BOUND_NAMES if had.get(k) != now[k]}
                # LATE_BOUND: each key held while one of its steps is on record (any record but `absent` and `deleted`), and only once a
                # state recorded its fingerprint (bind_late())
                late = self.late_fingerprints()
                changed |= {k for k, steps in LATE_BOUND.items() if k in had and had[k] != late[k]
                            and any(state.status(s) not in ("absent", "deleted") for s in steps)}
            # a stop whose names file gives no usable role (STOP_NEEDS_NOT) binds no state to "no role": the names a state
            # records with its first write are names every command can be held to
            state.bound = now if all(k in self.n.v or k == "TWIN_REGION" for k in BOUND_NAMES) else None
        return sorted(changed)

    def late_fingerprints(self) -> Dict[str, str]:
        """The present value of each of LATE_BOUND (none given is "", which is a value too), salted and hashed."""
        s = salt(self.top)
        return {k: fingerprint(s, k, self.n.v.get(k, "")) for k in LATE_BOUND}

    def bind_late(self, step_id: str) -> None:
        """BOUND ONCE RECORDED: when a step of a key of LATE_BOUND is recorded, the state records the value the key gives now (the
        pull role for every pull step, the pull thing for pull-thing). Under another value names_changed() refused the command
        already while a step of that key was on record (any record but `absent` and `deleted`), so this writes a first binding, or a
        new one once every step of the key was absent or deleted. For the pull role that is before `apply pull-role` first read the
        role: the owner's `verified` is never taken off the record by twinctl, and holds the binding for good."""
        had = self.state.data.get("names")
        if isinstance(had, dict) and not self.state.frozen:
            late = self.late_fingerprints()
            keys = [k for k, steps in LATE_BOUND.items() if step_id in steps and had.get(k) != late[k]]
            if keys:
                had.update({k: late[k] for k in keys})
                self.state.save()

    def standing(self) -> List[str]:
        """The steps either state records as made here and not yet deleted."""
        return [s for state in (self.state, self.other_state()) for s, e in state.data["steps"].items() if e.get("status") in OURS]

    # --- the literals (gap b): written by this file, read by the redactor and the scanner
    def own_literals(self) -> Dict[str, List[str]]:
        n, v = self.n, self.n.v
        kinds: Dict[str, List[str]] = {"prefix": [n.prefix], "thing": [v["TWIN_THING"]], "bucket-suffix": [v["TWIN_BUCKET_SUFFIX"]],
                                       "account": [n.account], "operator-role": [n.operator_role], "profile": [n.profile]}
        if not n.operator_role:                                     # a stop without a usable role: no literal is made of nothing
            del kinds["operator-role"]
        if "TWIN_NOTICE_ADDRESS" in v:
            kinds["notice-address"] = [v["TWIN_NOTICE_ADDRESS"]]
        if n.pull_role:                                             # Phase 6: the owner's name for the pull role, and the pull thing's
            kinds["pull-role"] = [n.pull_role]
        if n.pull_thing:
            kinds["pull-thing"] = [n.pull_thing]
        other = self.other_state()
        certs = sorted({x for state in (self.state, other) for x in (state.fact("certificate_id"), state.fact(UNCONFIRMED),
                                                                     state.fact("pull_certificate_id"), state.fact(PULL_UNCONFIRMED)) if x})
        if certs:
            kinds["certificate-id"] = certs
        for kind, fact in (("endpoint-prefix", "endpoint_prefix"), ("canonical-user-id", "canonical_user_id")):
            if self.top_state.fact(fact):
                kinds[kind] = [str(self.top_state.fact(fact))]
        return kinds

    def write_literals(self) -> None:
        """<state>/literals.json, from the names file and the state. A value under MIN_LITERAL characters, or one a
        search of this work tree finds, is refused by its position: a literal is taken out wherever its characters
        stand, so a short or a common one would cut into every record that only happens to hold it."""
        path = self.top / REDACT.LITERALS_FILE
        mine = self.own_literals()
        for kind in sorted(mine):
            for i, value in enumerate(mine[kind], 1):
                if len(value) < MIN_LITERAL:
                    refuse("literal-too-short", "value %d of the kind %s has %d character(s): a literal twinctl writes has %d or more "
                           "(the value is not printed)" % (i, kind, len(value), MIN_LITERAL))
        found = tree_search([v for kind in sorted(mine) for v in mine[kind]])
        for kind in sorted(mine):
            for i, value in enumerate(mine[kind], 1):
                if found.get(value):
                    refuse("literal-in-the-work-tree", "value %d of the kind %s is found in %d file(s) of this work tree: as a literal it "
                           "would be cut out of every record that says it, and the tree would hold an identifier (the value is not "
                           "printed)" % (i, kind, found[value]))
        merged: Dict[str, List[str]] = {}
        if path.is_file():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))["literals"]
                merged = {k: list(v) for k, v in old.items() if k not in OWN_KINDS}        # the owner's own kinds are kept as they are
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                refuse("literals-unreadable", "the state directory's literals file is not in its form: it is not overwritten blindly")
        merged.update(mine)
        REDACT.Literals(merged)                                     # its own rules: a value a mask spells, a padded one
        write_atomic(path, dump({"v": REDACT.LITERALS_VERSION, "literals": merged}).encode("ascii"))

    def refresh_literals(self) -> None:
        self.write_literals()
        self.load_literals()

    def load_literals(self) -> None:
        """Give the redactor the state's literals, and refuse to go on when the file is behind what the state knows."""
        try:
            REDACT.load_literals(self.top)
        except REDACT.LiteralsError as e:
            refuse("literals-refused", "%s. `twinctl literals` writes the file from the names file and the state" % e)
        doc = json.loads((self.top / REDACT.LITERALS_FILE).read_text(encoding="utf-8"))["literals"]
        behind = [kind for kind, values in sorted(self.own_literals().items()) if not set(values) <= set(doc.get(kind, []))]
        if behind:
            refuse("literals-behind", "the literals file does not hold every value of the kind(s) %s that the names file and the state "
                   "now give: `twinctl literals` writes it" % ", ".join(behind))
        OUT.use(doc)


OWN_KINDS = ("prefix", "thing", "bucket-suffix", "account", "operator-role", "profile", "notice-address", "certificate-id",
             "endpoint-prefix", "canonical-user-id", "pull-role", "pull-thing")
SKIP_DIRS = (".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache")


def tree_search(values: Sequence[str], root: Optional[Path] = None) -> Dict[str, int]:
    """In how many files of the work tree each value stands. Every file but git's own store and the tools' caches."""
    needles = [(v, v.encode("utf-8")) for v in values]
    found = {v: 0 for v in values}
    for d, dirs, files in os.walk(str(root or REPO)):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for name in files:
            try:
                data = Path(d, name).read_bytes()
            except OSError:
                continue
            for value, needle in needles:
                if needle in data:
                    found[value] += 1
    return found


def render_hash(t: Twin, rd: Rendered, mode: str, calls: Sequence[Call], extra: Any = None) -> str:
    """The render's sha256: the step, what is to be done, every call and every document, and the profile and the role
    the calls would be sent under (they are in no call's own arguments: the runner adds the profile, and the role is
    what the caller is held to), salted with a value that stays in the state directory (the printed hash then says
    nothing about the names it covers)."""
    place = rd.render.dir.as_posix()
    body = {"step": rd.step.id, "mode": mode, "rehearsal": t.n.rehearsal, "extra": extra, "sent_as": [t.n.profile, t.n.operator_role],
            "calls": [[a.replace(place, "<render>") for a in c.argv()] for c in calls],
            "documents": {name: hashlib.sha256(text.encode("ascii")).hexdigest() for name, text in sorted(rd.render.texts.items())}}
    body["inputs"] = dict(rd.render.inputs)                         # the CONTENT of every file a create uploads (the zip, the signing request)
    return hashlib.sha256(salt(t.top) + json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()


def show_calls(calls: Sequence[Call]) -> None:
    for c in calls:
        say("  aws " + shlex.join(c.argv()))


def show_render(t: Twin, rd: Rendered, mode: str, calls: Sequence[Call], digest: str, note: str = "", go_on: bool = True) -> None:
    say("%s %s (row %s): %s" % (mode, rd.step.id, rd.step.row, rd.step.title))
    say("%d call(s), %d document(s):" % (len(calls), len(rd.render.texts)))
    show_calls(calls)
    for name, text in sorted(rd.render.texts.items()):
        say("  document %s.json:" % name)
        say(text, as_json=True)
    for key, content in sorted(rd.render.inputs.items()):           # what the approval covers of a file: its content
        say("  input %s: sha256 %s%s" % (key, content, ("; as the service reports a function's code: " + code_sha256(content))
                                         if key == "TWIN_BREAKER_ZIP" else ""))
    if note:
        say(note)
    say("the unredacted documents: %s" % rd.render.dir)
    say("render sha256: %s" % digest)
    if go_on:                                                       # a render that is never applied names no approval
        say("to go on, once the owner said yes to this step: twinctl %s %s --approve %s:%s" % (mode, rd.step.id, rd.step.id, digest))


def approvals(t: Twin) -> List[Dict[str, Any]]:
    """The records of approvals.jsonl, in the order they were written: `shown` (a render was printed), `used` (its
    approval came back and the caller was the operator role: the trail of what was given), `spent` (it let its calls
    through). A line that cannot be read, such as one a write was cut in, is passed over: it can only fail to match."""
    path = t.top / "approvals.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        try:
            entry = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def note_approval(t: Twin, step: str, mode: str, digest: str, event: str) -> None:
    path = t.top / "approvals.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    cut = path.is_file() and path.stat().st_size > 0 and not path.read_bytes().endswith(b"\n")       # a record starts on a line of its own
    with open(str(path), "a", encoding="utf-8", newline="\n") as f:
        f.write(("\n" if cut else "") + json.dumps({"step": step, "mode": mode, "rehearsal": t.n.rehearsal, "hash": digest, "event": event,
                                                    "at": now()}, sort_keys=True) + "\n")


def spend(t: Twin, step: str, mode: str, digest: str) -> None:
    """ONE PRINTING OF A RENDER LETS ONE RUN OF ITS CALLS THROUGH. Called right before the first call that changes the
    account. A render that did not change has the same hash, so the hash alone cannot tell the approval of a second
    create (create, delete, create: three approved steps) from the first one given again, nor a second run of an
    action from the first. Reading a step again with the approval it was made with sends nothing and spends nothing;
    an approval that was refused before anything was sent is not spent either."""
    fresh = False
    for a in approvals(t):
        if a.get("step") == step and a.get("mode") == mode and a.get("hash") == digest and a.get("rehearsal") == t.n.rehearsal:
            fresh = a.get("event") == "shown" or (fresh and a.get("event") != "spent")
    if not fresh:
        refuse("approval-spent", "this approval already let its calls through once, and an approval is for ONE run of what was "
               "printed: nothing was sent. Print the render again; the owner says yes to it again")
    note_approval(t, step, mode, digest, "spent")


def approved(t: Twin, step: str, mode: str, digest: str, approve: Optional[str]) -> bool:
    """Whether `approve` is the approval of this step's render as it is now. The script cannot tell who typed it."""
    if approve is None:
        return False
    name, sep, given = approve.partition(":")
    if not sep or name != step:
        refuse("approval-for-another-step", "the approval names another step than the one asked for: nothing was done")
    if given != digest:
        refuse("approval-for-another-render", "the approval's hash is not the hash of this step's render as it is now (a template, a "
               "name or the state changed since it was printed): nothing was done; print the render again")
    if not any(a.get("step") == step and a.get("mode") == mode and a.get("hash") == digest and a.get("event") == "shown"
               and a.get("rehearsal") == t.n.rehearsal for a in approvals(t)):
        refuse("approval-never-shown", "this render was never printed: an approval is for what was shown; nothing was done")
    return True


def hold_names(t: Twin, command: str, again: bool) -> None:
    """Refuse a command under other names than the ones this state directory's records were made under. The state says
    that a step was made; the render that reads, changes or deletes it is printed with every name masked, so nothing
    the owner approves would show that the name is another (a bucket of another suffix, deleted on the word of a state
    that never made it). The way out when nothing stands: `literals`, then `baseline --again`, which takes the names.

    THE STOP IS NOT HELD TO THE ROLE OR TO THE PROFILE (the owner's decision of 2026-10-12: `trip` is held to the account
    only). Those two are bound so that no approval printed under one role or profile runs under another; a trip takes no
    approval, sends one invoke and reads, and a profile renamed in the CLI's own configuration while the twin is live
    must not cost the one-command stop. Under another role or profile than the state's the trip goes on, under the
    profile the names file gives now, and says so. The bucket's suffix and the notice's switch do not hold it either
    (the owner's A4 answers of 2026-10-16): no call of a stop is made of them. Every other name still holds it: the
    account, the region, the prefix and the thing are what its invoke and its four calls by hand are made of."""
    changed = t.names_changed()
    if command == "trip":
        # nor to Phase 6's pull role and pull thing (LATE_BOUND): no call of a stop is made of either
        not_held = STOP_NOT_HELD + tuple(LATE_BOUND)
        eased = [k for k in changed if k in not_held]
        eased = [k for k in eased if k in t.n.v]                    # one the names file gives no usable value of is said already (Twin)
        changed = [k for k in changed if k not in not_held]
        late = [what for k, what in (("TWIN_PULL_ROLE", "the pull role"), ("TWIN_PULL_THING", "the pull thing")) if k in eased]
        if eased and not changed:
            t.lacks.append("the names file gives another value than this state's records were made under for %s (no value is printed): "
                           "the stop is held to the account and not to the operator role, the profile, the bucket's suffix or "
                           "the notice's switch%s, and goes on under the "
                           "profile the names file gives now" % (", ".join(eased), " (nor to %s)" % " or ".join(late) if late else ""))
    if not changed:
        return
    standing = len(t.standing())
    if not standing and (command == "literals" or (command == "baseline" and again)):
        return
    refuse("names-changed", "the names file and the environment no longer give what this state directory's records were made under "
           "(%s; no value is printed): nothing is done under other names than the state's. %s"
           % (", ".join(changed), ("%d step(s) are recorded as standing under the state's names: give those names back" % standing)
              if standing else "Nothing is recorded as standing: give the names back, or let `twinctl literals` and then `twinctl baseline "
              "--again` take the new ones, with a baseline of their own and no step recorded"))


def require_caller(t: Twin) -> None:
    """Refuse unless the caller is an assumed session of the operator role of the names file, in its account. THE FIRST
    CALL OF EVERY COMMAND THAT SENDS ONE, the commands that only read among them: a profile is repointed in the
    CLI's own configuration without any approval, and a read that another account answers is a wrong verdict on this
    one (`verify-gone` said gone on an empty account's listings while the twin stood: the hard review's SHOULD 1).
    The reads are held to the role as the writes are: these commands use the operator profile."""
    got = t.aws.read(c_identity())
    arn, account = str((got or {}).get("Arn", "")), str((got or {}).get("Account", ""))
    if account != t.n.account:
        refuse("identity-other-account", "the caller's account is not the account of the names file: nothing was done")
    if not re.fullmatch(r"arn:aws:sts::%s:assumed-role/%s/[^/\s]+" % (re.escape(t.n.account), re.escape(t.n.operator_role)), arn):
        refuse("identity-not-the-operator-role", "the caller is not an assumed session of the operator role the names file names (an "
               "IAM user, another role, the root): nothing was done")
    t.aws.identified()


def require_operator(t: Twin) -> None:
    """The caller held as in require_caller(), and only then the runner armed for the calls that change the account."""
    require_caller(t)
    t.aws.arm()


def dependents(t: Twin, step_id: str) -> List[Step]:
    """The actions and the owner-made steps that stand on `step_id`: it is among their `needs`, followed to the end."""
    needs = {s.id: s.needs for s in t.steps}
    out = []
    for s in t.steps:
        if s.kind not in ("action", "owner"):
            continue
        seen: Set[str] = set()
        todo = list(s.needs)
        while todo:
            need = todo.pop()
            if need not in seen:
                seen.add(need)
                todo += list(needs.get(need, ()))
        if step_id in seen:
            out.append(s)
    return out


def take_back(t: Twin, step_id: str, why: str) -> None:
    """A RECORD DOES NOT OUTLIVE WHAT IT STOOD ON. An action's `done` says that the breaker ran, an owner-made step's
    `verified` that a role was read as rendered: of the function, the certificate, the alarms as they were then. When
    one of those is deleted or made anew, the records that stand on it, directly or through other steps, become
    `stale`, and a step that needs one of them is refused until it was applied again (WP6-verify-2's SHOULD 1: after
    the function was made again from another zip, go-live passed on a dry trip the new function never ran; after the
    certificate was made again, the function was created on a role whose policy named the old one)."""
    taken = [s.id for s in dependents(t, step_id) if t.state.status(s.id) in ("done", "verified")]
    for sid in taken:
        t.state.record(sid, status=STALE, stale_for=step_id)
    if taken:
        say("%s %s: %d record(s) stood on this step as it was and are taken back (%s): each is applied again before a step that "
            "needs it." % (why, step_id, len(taken), ", ".join(taken)))


def observe(t: Twin, rd: Rendered) -> Tuple[bool, List[str]]:
    """The step's proving reads, judged: (whether anything of it is there, what differs from the render)."""
    got = {key: t.aws.read(call, rd.step.id) for key, call in rd.built.reads}
    if rd.step.judge is None:
        return False, []
    return rd.step.judge(t, rd.render, got)


def need_baseline(t: Twin) -> Dict[str, List[str]]:
    path = t.top / "baseline.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return {k: [str(x) for x in v] for k, v in doc["listings"].items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        refuse("no-baseline", "the state directory holds no baseline: `twinctl baseline` stores what every listing returns before the "
               "first create")


# --- apply

# What the refusal of a step that exists and is not ours adds, for the one step the owner may adopt.
ADOPTION = {"iot-log-group": ". IoT makes this group itself once logging was ever on in the region. The owner's choice: delete it by hand "
                             "first (its events go with it), or keep it and set TWIN_IOT_LOG_GROUP_ADOPT=1 in the names file: the step "
                             "then only reads it, and the driver never creates or deletes it"}


def cmd_apply(t: Twin, step_id: str, approve: Optional[str]) -> int:
    step = t.step(step_id)
    if step.kind == "empty":
        refuse("step-teardown-only", "this step only exists in teardown")
    rd = t.render(step)
    rd.render.write()
    if step.kind == "owner":
        return apply_owner(t, rd)
    if step.kind == "appears" and not rd.built.creates:
        say("%s has no create call: the two named shadows appear with the connector's first update and the first desired write, and "
            "are approved with go-live. `status` lists them; `teardown shadows` deletes them before the thing." % step.id)
        return EXIT_OK
    if rd.render.provisional:
        refuse("render-provisional", "this step's render stands on a value the state does not hold yet (%s): the step that creates it "
               "comes first" % ", ".join(sorted(rd.render.provisional)))
    digest = render_hash(t, rd, "apply", rd.built.creates)
    if rd.render.unfit is not None:
        # printed, so that it says which it is, and refused: with an approval or without one, before anything is read or sent.
        # It is not recorded as shown: no approval is for it
        if approve is None:
            show_render(t, rd, "apply", rd.built.creates, digest, note="  " + rd.render.unfit[1], go_on=False)
        refuse(*rd.render.unfit)
    if not approved(t, step.id, "apply", digest, approve):
        show_render(t, rd, "apply", rd.built.creates, digest)
        note_approval(t, step.id, "apply", digest, "shown")
        return EXIT_SHOWN
    for need in step.needs:
        if t.state.status(need) not in ("created", "verified", "done"):
            refuse("step-needs", "the step %s is not recorded as made and proven, and this step stands on it" % need)
    need_baseline(t)
    require_operator(t)
    note_approval(t, step.id, "apply", digest, "used")
    if step.pre is not None:
        why = step.pre(t, rd.render)
        if why:
            refuse("precondition", why)
    if step.kind == "action":
        return apply_action(t, rd, digest)
    status = t.state.status(step.id)
    present, diffs = observe(t, rd)
    if present and status not in OURS:
        refuse("exists-not-ours", "something of this step already exists and the state does not record it as made here: it is not "
               "touched, and not adopted" + ADOPTION.get(step.id, ""))
    if status in ("creating", "partial"):
        refuse("half-made", "an earlier run stopped half-way in this step: `twinctl teardown %s` finishes it off, then apply again" % step.id)
    if status == "deleting":
        # found or not: a delete that was accepted may complete later, and one read that finds nothing is not yet the record
        # that it is gone (the hard review's NIT 4: the step was made again at once, although its teardown had said this)
        refuse("still-deleting", "this step is recorded as being deleted (something of it is %s): `twinctl verify-gone %s` records it "
               "as deleted once it is not found, or its teardown is run again; only then is it made again"
               % ("still read" if present else "not read any more", step.id))
    if status in ("created", "unverified"):
        if not rd.built.reads:
            # no id in the state to read it by (the certificate): "nothing of it is found" would be the word of no read at all
            refuse("nothing-to-read", "the state records this step as made and holds no id to read it by: nothing was read, so it is "
                   "neither found nor gone, and nothing is made on top of it. `twinctl recover %s` puts the id back from the reply "
                   "this state directory holds; `twinctl verify-gone` lists what the account holds beyond the baseline" % step.id)
        if not present:
            refuse("recorded-not-found", "the state records this step as made and nothing of it is found: `twinctl teardown %s` clears "
                   "the record" % step.id + (". " + AFTER_A_TRIP if step.id in GO_LIVE else ""))
        diffs = diffs + input_diffs(t, rd)                          # the render that was approved names each file by its content
        return settle(t, rd, diffs, made=False, digest=digest)
    if step.id in RECOVERABLE and step.listing:
        # A step that is read by an id only a reply gives (the certificate) cannot be read by a name before its create, as
        # every other step is ("exists and is not ours"): its listing is the one read that sees what an earlier create of it
        # made and no state names. The teardown of a create whose outcome is not known takes the record back on ONE read of
        # that listing, and a listing may not show yet what was just made (not established for the real one): read again
        # here, it refuses a second certificate on top of the first (WP7-verify-r2's NIT 4)
        stray = unknown_names(t, step)
        if stray:
            refuse("listed-not-ours", "the account lists %d name(s) of this step's kind that neither the baseline nor the state knows "
                   "(what a create whose reply was lost had made, or one made outside twinctl): nothing is created on top of it, and "
                   "it is not adopted. `twinctl verify-gone` lists what the account holds beyond the baseline; it is deleted by hand "
                   "(sdv/cloud/README.md says how), and this step is then applied again" % stray)
    spend(t, step.id, "apply", digest)
    t.state.record(step.id, status="creating", render=digest, done=[], sent=[], inputs=dict(rd.render.inputs))
    t.bind_late(step.id)                                            # a pull step: the pull role is bound from here on
    take_back(t, step.id, "apply")                                  # made anew: what stood on it stood on what it was before
    for i, call in enumerate(rd.built.creates):
        # ON RECORD BEFORE IT IS SENT, AND IT STAYS THERE HOWEVER IT ENDED. A create may go through and its reply be lost: a
        # reply that is no JSON, a CLI that does not come to its end, a run that ends there. `done` alone then said "no create
        # call went through", and the teardown of a step read by an id only a reply gives (the certificate) took the record
        # back while the account held one
        t.state.record(step.id, sent=t.state.sent(step.id) + [i])
        reply = t.aws.run(call, step.id)
        if reply.rc != 0:
            # NO ERROR CODE IS TAKEN FOR "NOTHING WAS MADE". An error the service answered was once taken off the record as a
            # call that did not go through; a 5xx does not say that (WP7-verify-r1's SHOULD 2: the certificate was made, the
            # answer was InternalFailure, the teardown took the record back unread and the next apply made a second one). Which
            # codes are certain refusals is from memory, so none is trusted: the call stays on record as sent, and the
            # teardown's one read of the listing says whether anything of it stands
            t.state.record(step.id, status="partial")
            say("apply %s: call %d of %d failed (%s %s: %s). The state records what was made; `twinctl teardown %s` finishes from it."
                % (step.id, i + 1, len(rd.built.creates), call.service, call.op, reply.code, step.id), err=True)
            return EXIT_REFUSED
        t.state.record(step.id, done=t.state.done(step.id) + [i])
        if step.after is not None:
            step.after(t, i, reply.obj)
    rd = t.render(step)                                             # with what the replies taught (the certificate's id)
    rd.render.write()
    present, diffs = observe(t, rd)
    if not present:
        diffs = ["nothing of it is found after its create calls"]
    return settle(t, rd, diffs, made=True, digest=digest)


def settle(t: Twin, rd: Rendered, diffs: List[str], made: bool, digest: str) -> int:
    step = rd.step
    if diffs:
        if made or t.state.status(step.id) != "created":
            t.state.record(step.id, status="unverified")
        say("apply %s: %s, and what is read back is not the render:" % (step.id, "made" if made else "already made"), err=True)
        for d in diffs:
            say("  - " + d, err=True)
        if not made and (t.state.data["steps"].get(step.id, {}).get("render") not in (None, digest) or input_diffs(t, rd)):
            # row 19's "the alarm made again": another ActionType or threshold is another render of a step that stands; and so
            # is another zip or signing request at the path (or one the state cannot tell from the first)
            say("this render is not the one the step was made from (a name, a template, a threshold or a file it uploads changed "
                "since): what stands is the old render's, and reading it again will not change that. To have the new one, tear the "
                "step down, with the steps that stand on it, and apply it again.", err=True)
        else:
            say("apply again with the same approval reads it once more; nothing is created twice.", err=True)
        return EXIT_REFUSED
    t.state.record(step.id, status="created")
    say("apply %s: %s; read back, as rendered; recorded." % (step.id, "made" if made else "already made, nothing was created"))
    return EXIT_OK


def apply_owner(t: Twin, rd: Rendered) -> int:
    """A step the owner makes by hand: the render is what the owner makes it from; this reads the proof."""
    step = rd.step
    say("%s (row %s): %s" % (step.id, step.row, step.title))
    if rd.render.provisional:
        say("its render stands on a value the state does not hold yet (%s): it is rendered again once that exists"
            % ", ".join(sorted(rd.render.provisional)))
    for name, text in sorted(rd.render.texts.items()):
        say("  document %s.json:" % name)
        say(text, as_json=True)
    if rd.render.texts:
        say("the unredacted documents, to make it from: %s" % rd.render.dir)
    for need in step.needs:
        if t.state.status(need) not in ("created", "verified", "done"):
            refuse("step-needs", "the step %s is not recorded as made and proven, and this step stands on it" % need)
    require_caller(t)
    present, diffs = observe(t, rd)
    if not present:
        say("it is not there yet: the owner makes it by hand; this command only reads." if step.id.endswith("-role") else
            "it is not there: nothing is adopted. Without TWIN_IOT_LOG_GROUP_ADOPT the driver makes this step itself.", err=True)
        return EXIT_REFUSED
    if diffs or rd.render.provisional:
        for d in diffs:
            say("  - " + d, err=True)
        say("it is there and is not the render.", err=True)
        return EXIT_REFUSED
    t.state.record(step.id, status="verified")
    t.bind_late(step.id)
    say("%s: read, as rendered; recorded." % step.id)
    return EXIT_OK


def apply_action(t: Twin, rd: Rendered, digest: str) -> int:
    """A step that makes nothing: an invoke, a state change. One printing of its render lets it run once (spend()): an
    approval given again is refused until the render was printed again. What it shows is read after it.
    ITS `done` IS THE RECORD OF ITS LAST RUN. A run that does not come to its end (a call that fails, an invoke that ends in
    a function error, a reply that cannot be read) takes the record of an earlier run back, with what stood on it
    (run_failed()); a first run that fails leaves none."""
    step = rd.step
    spend(t, step.id, "apply", digest)
    for i, call in enumerate(rd.built.creates):
        try:
            reply = t.aws.run(call, step.id)
        except TwinError as e:
            if e.name in OUTCOME_UNKNOWN:                           # the call was sent and how it ended is not known: no run to its end
                run_failed(t, step.id)
            raise
        if reply.rc != 0:
            say("apply %s: call %d of %d failed (%s %s: %s)." % (step.id, i + 1, len(rd.built.creates), call.service, call.op, reply.code),
                err=True)
            run_failed(t, step.id)
            return EXIT_REFUSED
        if call.service == "lambda" and call.op == "invoke":
            why = invoke_verdict(reply.obj)
            if why:
                say("apply %s: %s" % (step.id, why), err=True)
                say(error_said(Path(call.args[-1]), step.id), err=True)
                run_failed(t, step.id)
                return EXIT_REFUSED
    t.state.record(step.id, status="done", render=digest)
    t.bind_late(step.id)
    say("apply %s: done; recorded. `twinctl status` shows what it left." % step.id)
    if step.id == "function-status":
        say(status_facts(Path(rd.built.creates[0].args[-1])))
        say(ADDRESSES_NOTE)
    if step.id == "dry-trip":
        say(trip_facts(Path(rd.built.creates[0].args[-1]), step.id))
    return EXIT_OK


# The runner's refusals after which a call may have gone through: the CLI did not come to its end, or answered what is no
# JSON. Its other refusals (no CLI, a forbidden option, a runner that is not armed) are raised before anything is sent.
OUTCOME_UNKNOWN: Tuple[str, ...] = ("cli-failed", "reply-unreadable")


def run_failed(t: Twin, step_id: str) -> None:
    """AN ACTION'S `done` IS THE RECORD OF ITS LAST RUN, not of one run among several: the alarm tests and go-live stand on
    "the dry trip ran to its end", and after a run that did not they stood on the earlier one (WP7-verify-r1's NIT 8).
    So a run that does not come to its end takes that record back to `stale`, and with it every record that stands on
    it (take_back()); applied again and run to its end, the action is `done` again, and what stood on it is applied
    again, each by itself. A first run that fails has no record to take back and leaves the step as it was."""
    if t.state.status(step_id) != "done":
        return
    t.state.record(step_id, status=STALE, stale_for=step_id)
    say("apply %s: this run did not come to its end, so the record of its earlier run is taken back: the step is applied again, and "
        "runs to its end, before a step that needs it." % step_id, err=True)
    take_back(t, step_id, "apply")


WRITE_WORD = re.compile(r"ok|answered(?::[A-Za-z][A-Za-z0-9]{0,63})?|refused|failed|not-attempted|no-client-connected|unavailable")
WRITES_LISTED = 16                              # more certificates or client ids than this in a record are not printed one by one


def trip_facts(payload: Path, what: str) -> str:
    """A3 row 17a: what the function's own record of a trip says each of its WRITES was answered, from the payload's file.
    The dry trip is where each API first shows what it answers when its work is already done, and the function counts a
    write the service ANSWERED WITH AN ERROR as done when its read-back shows the cut: such a write was `done` unseen,
    its word standing in the state directory's replies only (WP7-verify-r1's NIT 5). Printed only in the form a write
    word has (ok | answered | answered:<a code in a code's form> | refused | failed | not-attempted | no-client-connected
    | unavailable), with counts: anything else in a word's place is said, and nothing of the record is printed."""
    unread = "%s: the record does not hold its write words in their form: it is read by hand, in the state directory's replies" % what
    try:
        record = json.loads(payload.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return unread
    if not isinstance(record, dict) or record.get("mode") != "trip":
        return unread
    rule, certs, clients = record.get("rule"), record.get("certificates"), record.get("connections")
    if not isinstance(rule, dict) or not isinstance(certs, list) or not isinstance(clients, list) \
            or len(certs) > WRITES_LISTED or len(clients) > WRITES_LISTED or not all(isinstance(x, dict) for x in certs + clients):
        return unread
    words = [rule.get("write")] + [c.get(k) for c in certs for k in ("write", "detach")] + [c.get("write") for c in clients]
    if not all(isinstance(w, str) and WRITE_WORD.fullmatch(w) for w in words):
        return unread
    parts = ["the rule's disable %s" % rule["write"]]
    parts += ["certificate %d of %d: deactivate %s, detach %s" % (i + 1, len(certs), c["write"], c["detach"]) for i, c in enumerate(certs)]
    parts += ["connection %d of %d: %s" % (i + 1, len(clients), c["write"]) for i, c in enumerate(clients)]
    said = "%s: the function's record of its writes: %s" % (what, "; ".join(parts))
    if any(str(w).startswith("answered") for w in words):
        said += (". A write the service ANSWERED WITH AN ERROR counts as done when its read-back shows the cut: read above which one, and "
                 "its code and HTTP status in the function's log, before go-live")
    return said


def status_facts(payload: Path) -> str:
    """A3 row 13: the two facts of the function's own status record, from the payload's file: the runtime's boto3 and
    whether its data-plane client has DeleteConnection. Printed only in the form they have (a version of digits and
    dots, a true or a false): anything else in their place is said, and nothing of it is printed."""
    try:
        record = json.loads(payload.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = None
    version, has = (record.get("boto3"), record.get("has_delete_connection")) if isinstance(record, dict) else (None, None)
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]{1,4}(?:\.[0-9]{1,4}){1,3}", version) or not isinstance(has, bool):
        return "function-status: the record does not hold the two facts in their form: it is read by hand, in the state directory's replies"
    return ("function-status: the runtime's boto3 is %s; its data-plane client has DeleteConnection: %s"
            % (version, "yes" if has else "NO (the trip's third step is unavailable in this runtime; the other three cut all the same)"))


def invoke_verdict(reply: Any) -> Optional[str]:
    """Why an invoke's reply is not a clean run of the function, or None."""
    if not isinstance(reply, dict) or reply.get("StatusCode") != 200 or reply.get("FunctionError"):
        return "the function did not run to its end (its record is in the state directory)"
    return None


# What `apply function-status` adds for the function-status reading. The function counts its time for one address per endpoint
# name, its connect time-out is per address, and how many addresses the two names resolve to is first seen where the
# account is met (the hard review of WP7, SHOULD 1; breaker.py, THE TIME IT HAS). No name stands in the sentence.
ADDRESSES_NOTE = ("function-status: for the function-status reading: how many addresses the names of the function's two endpoints resolve to (the "
                  "control plane's and the data plane's, in this region; `getent ahosts` on this machine, which is not the runtime's "
                  "resolver). The function's connect time-out is per address, and its time is counted for the number its docstring "
                  "names (breaker.py, THE TIME IT HAS): against an endpoint that is silent on more, the runtime ends it before its "
                  "later steps.")
ERROR_KIND = re.compile(r"[A-Za-z][A-Za-z0-9_.]{0,63}")                # the form an error's kind has: a class's name, with the runtime's dots
OWN_ERROR = "BreakerError"                                              # the function's own: raised at its end, when a step or a read failed
OWN_MESSAGE_MAX = 4096                                                  # a longer message is none the function writes for a twin it can act on


def _form(text: str) -> "re.Pattern[str]":
    """One sentence form of the function's as a pattern: its words as they are, <n> a count of one to three ASCII digits,
    <why> one of the two words a call's failure has, <answered> those and the third a connection's delete can have."""
    why = "(?:was refused as not authorised|got no answer)"
    return re.compile(re.escape(text).replace("<n>", "[0-9]{1,3}").replace("<why>", why)
                      .replace("<answered>", why[:-1] + "|was answered with an error)"))


# THE FUNCTION'S OWN SENTENCE FORMS: every sentence sdv/cloud/breaker/breaker.py can append to a BreakerError's message
# (_Inputs.failures and _assemble), written out here as the write words are (WRITE_WORD), and held equal to that file's
# source by tests/test_sdv_cloud.py. A message is printed only when each of its clauses is one of these, whole: they
# hold counts and fixed words, and nothing of the function's environment can be in them.
OWN_CLAUSES: Tuple["re.Pattern[str]", ...] = tuple(_form(text) for text in (
    "TWIN_RULE is not set",
    "TWIN_POLICY is not set",
    "TWIN_CLIENT_IDS is not set",
    "TWIN_CLIENT_IDS names <n> client ids, more than the <n> the function's time is counted for",
    "TWIN_CERTIFICATE_ARNS names no certificate (<n> of its entries are no certificate's ARN)",
    "<n> of the entries of TWIN_CERTIFICATE_ARNS are no certificate's ARN",
    "TWIN_CERTIFICATE_ARNS names <n> certificates, more than the <n> the function's time is counted for",
    "the rule: its disable call <why>",
    "the rule's state could not be read",
    "the rule is not disabled",
    "certificate <n> of <n>: the call that deactivates it <why>",
    "certificate <n> of <n>: its state could not be read",
    "certificate <n> of <n> is not INACTIVE",
    "certificate <n> of <n>: the call that detaches the policy <why>",
    "certificate <n> of <n>: the policy is still attached",
    "the policy's targets could not be read",
    "client <n> of <n>: the call that deletes its connection <answered>"))
OWN_HEAD = re.compile(r"the (?:trip|status) did not complete: ([0-9]{1,3}) failure\(s\): ")
# The function's one sentence for an error no step names. Its slot is the error's class, by its name: the name of an error's
# class ends in Error or Exception, and no name the driver forms for the twin does (the rule's is the prefix and `_telemetry`).
OWN_STOPPED = re.compile(r"the breaker stopped on an error no step names \((?:[A-Za-z_][A-Za-z0-9_]{0,54})?(?:Error|Exception)\): "
                         r"look at the state by hand")


def own_message(text: Any) -> Optional[str]:
    """`text` when it is a message the function's own error can carry, else None: its one sentence for an error no step
    names (with a class's name in it), or its head with as many clauses as the head counts, EACH of them one of
    OWN_CLAUSES, whole. One clause outside the table and nothing of the message is printed: whatever else stood in it
    (a value of the function's environment, a control character) stays in the payload's file.

    In the one slot of the table that is neither a fixed word nor a count, the class's name in the sentence for an error
    no step names, the table holds the form the name of an error's class has (it ends in Error or Exception): the
    rule's name, which is an identifier too, is not taken there, and an error whose class is named otherwise is read by
    hand. Behind that form, a name of the twin that had that form is held back by the redactor, through which
    everything printed goes, and not by the table; the function itself only ever writes a class's name there."""
    if not isinstance(text, str) or not 0 < len(text) <= OWN_MESSAGE_MAX:
        return None
    if OWN_STOPPED.fullmatch(text):
        return text
    head = OWN_HEAD.match(text)
    if head is None:
        return None
    clauses = text[head.end():].split("; ")
    if len(clauses) != int(head.group(1)) or not all(any(form.fullmatch(clause) for form in OWN_CLAUSES) for clause in clauses):
        return None
    return text


def error_said(payload: Path, what: str) -> str:
    """What is printed of a FUNCTION ERROR's payload: the error's KIND, in the form a kind has and in no other, and the name
    of the file its message is read in. The function's own error (BreakerError) says in its message what failed, as states
    and counts; any other kind is the runtime's, or an error from before the handler's first line, and its message is
    not the function's contract. THE FUNCTION'S OWN MESSAGE IS PRINTED (the owner's decision of 2026-10-12, on the hard
    review of WP7, NIT 3), AND ONLY IT: when the error's type is exactly the breaker's own and own_message() takes the
    message, every clause of it one of the function's own sentence forms. Any other type, and any message with one
    clause outside the table, stays the sentence that says where it is read by hand."""
    try:
        record = json.loads(payload.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = None
    kind = record.get("errorType") if isinstance(record, dict) else None
    if not isinstance(kind, str) or not ERROR_KIND.fullmatch(kind):
        return "%s: the function's error is read by hand, in the state directory's replies (%s)" % (what, payload.name)
    if kind == OWN_ERROR:
        message = own_message(record.get("errorMessage"))
        if message is not None:
            return "%s: the function's error is its own verdict (%s), and it says: %s (%s)" % (what, kind, message, payload.name)
    whose = ("its own kind, but its message is not in the function's own sentence forms" if kind == OWN_ERROR else
             "not the function's own verdict: the runtime's, or an error before its handler's first line")
    return ("%s: the function's error is of the kind %s (%s); the message is read by hand, in the state directory's replies (%s)"
            % (what, kind, whose, payload.name))


def trip_failed(t: Twin) -> None:
    """A MANUAL TRIP IS A RUN OF THE SAME INVOKE AS THE DRY TRIP'S. The alarm tests and go-live stand on "the dry trip ran
    to its end"; a `trip` that ended in a FUNCTION ERROR showed that the function, as it is now, does not, and left that
    record `done` (WP7-verify-r2's NIT 5: the case of run_failed(), reached through the other command that sends the
    same invoke). So it takes the dry trip's `done` back, with every record that stands on it, as a failed run of the
    action does. Only a function error does: an invoke the service refused says nothing of the function, and a trip
    that ran clean puts no record back (`trip` is no action, and nobody approved it as one). A state that could not be
    read knows no record, and is never written."""
    if t.state.status("dry-trip") != "done":
        return
    t.state.record("dry-trip", status=STALE, stale_for="trip")
    say("trip: the dry trip's record said that the function runs to its end: it is taken back. `twinctl apply dry-trip` runs to its "
        "end again before a step that needs it (the alarm tests, go-live).", err=True)
    take_back(t, "dry-trip", "trip")


# --- teardown

def teardown_order(t: Twin) -> List[Step]:
    return [s for s in reversed(t.steps) if s.kind not in ("action", "owner")]


def cmd_teardown(t: Twin, step_id: Optional[str], approve: Optional[str]) -> int:
    if step_id is None:
        say("teardown is the table in reverse, one approved step at a time:")
        for s in teardown_order(t):
            say("  %-22s row %-5s %-10s %s" % (s.id, s.row, t.state.status(s.id), s.title))
        say("then the owner removes the roles made by hand: %s"
            % ", ".join(s.id for s in reversed(t.steps) if s.kind == "owner" and s.id.endswith("-role")))
        kept = [s.id for s in t.steps if s.kind == "owner" and not s.id.endswith("-role")]
        if kept:
            say("what was there before the twin and was adopted stays, and is the owner's: %s" % ", ".join(kept))
        return EXIT_OK
    step = t.step(step_id)
    if step.kind in ("action", "owner"):
        refuse("step-not-torn-down", "this step made nothing twinctl deletes (an action leaves no resource; the owner removes a role "
               "made by hand; what was adopted was there before the twin and stays)")
    rd = t.render(step, strict=False)                               # a teardown sends no create: no create-time input is needed
    rd.render.write()
    if step.kind == "empty":
        return teardown_objects(t, rd, approve)
    base = "thing" if step.kind == "appears" else step.id
    status = t.state.status(base)
    if status not in OURS + ("deleted",):                           # absent; or the record of a step that was only read (adopted)
        refuse("not-ours", "the state records nothing made for this step: nothing is deleted that was not made here")
    tracked = step.kind != "appears" or t.state.status(step.id) != "absent"
    if tracked and t.state.status(step.id) == "deleted":
        if not rd.built.reads:                                      # a certificate whose id the state does not hold: nothing was read
            say("teardown %s: recorded as deleted; it has no read (the state holds no id to read it by); nothing was sent." % step.id)
            return EXIT_OK
        require_caller(t)
        present, _diffs = observe(t, rd)
        if present:
            refuse("exists-not-ours", "the state records this step as deleted and something of it is found: it was not made here, and "
                   "is not deleted")
        say("teardown %s: recorded as deleted; read, not found; nothing was sent." % step.id)
        return EXIT_OK
    later = t.steps[t.steps.index(step) + 1:]
    standing = [s.id for s in later if s.kind in ("resource",) and t.state.status(s.id) in OURS]
    if standing:
        refuse("teardown-order", "teardown is the table in reverse, and %d later step(s) still stand (%s): they go first"
               % (len(standing), ", ".join(standing)))
    if rd.render.provisional:
        # Whatever the render holds: a delete call on the placeholder is printed with its target masked, is answered "not
        # found", and was recorded as deleted while the real certificate kept its policy (the hard review's SHOULD 2)
        refuse("render-provisional", "this step's render stands on a value the state does not hold (%s): no delete call is printed or "
               "sent on a placeholder, and nothing is recorded as deleted. The state has lost what a reply gave it (a state.json "
               "put back from an older copy): `twinctl recover certificate` puts the id back from the reply in the state "
               "directory's replies" % ", ".join(sorted(rd.render.provisional)))
    if not rd.built.reads:
        # Nothing of this step can be read: the certificate, when the state holds no id of it. "Deleted; read back, not
        # found" would stand on no read at all.
        if rd.built.deletes or t.state.done(step.id) or t.state.sent(step.id):
            # The one read that can see what such a create made is the step's listing. Less the baseline, less the ids either
            # state knows: what is left is a resource no state can name. Nothing left: nothing of this step stands, and the
            # record is taken back on that read (the owner deleted by hand what a lost create had made, or it made nothing).
            require_caller(t)
            stray = unknown_names(t, step) if step.listing else 1       # a kind with no listing has no such read: refused
            if stray:
                refuse("nothing-to-read", "a create call of this step was sent, and the state holds no id of what it made (its reply "
                       "gave none, was lost, or was an error, which does not say that nothing was made). The account lists %d name(s) "
                       "of this kind that neither the baseline nor the state knows: twinctl can neither read nor delete what it has "
                       "no id of, and nothing is recorded as deleted. `twinctl recover %s` puts the id back when a reply in the state "
                       "directory's replies holds it; else what was made is deleted by hand (sdv/cloud/README.md says how), and this "
                       "teardown then takes the record back" % (stray, step.id))
            t.state.drop(step.id)
            say("teardown %s: a create call of it was sent and the state holds no id; the account's listing of this kind holds no name "
                "beyond the baseline and what the state knows, so nothing of it stands: the record is taken back, and nothing was "
                "sent that changes the account. This rests on ONE read of the listing, and whether a listing shows at once what "
                "was just made is not established: `twinctl apply %s` reads it again before it creates, and refuses a name nobody "
                "knows; `twinctl verify-gone` reads it too." % (step.id, step.id))
            return EXIT_OK
        # no call on the record at all: the run ended before its first create call was put there, so none was sent
        t.state.drop(step.id)
        say("teardown %s: no create call of it is on record as sent, and without an id it has nothing to read or to delete: "
            "the record is taken back, and nothing was sent. `twinctl verify-gone` lists what the account holds beyond the "
            "baseline." % step.id)
        return EXIT_OK
    digest = render_hash(t, rd, "teardown", rd.built.deletes)
    if not approved(t, step.id, "teardown", digest, approve):
        show_render(t, rd, "teardown", rd.built.deletes, digest)
        note_approval(t, step.id, "teardown", digest, "shown")
        return EXIT_SHOWN
    require_operator(t)
    note_approval(t, step.id, "teardown", digest, "used")
    if step.ready is not None:
        why = step.ready(t, rd.render)
        if why:
            refuse("precondition", why)
    spend(t, step.id, "teardown", digest)
    if tracked:
        t.state.record(step.id, status="deleting")
        take_back(t, step.id, "teardown")                           # from the first delete call on, it is no longer what they stood on
    for i, call in enumerate(rd.built.deletes):
        reply = t.aws.run(call, step.id)
        if reply.rc != 0 and not t.aws.gone(call, reply, step.id):
            say("teardown %s: call %d of %d failed (%s %s: %s). Nothing after it was sent; the step can be run again."
                % (step.id, i + 1, len(rd.built.deletes), call.service, call.op, reply.code), err=True)
            return EXIT_REFUSED
    present, _diffs = observe(t, rd)
    if present:
        say("teardown %s: the delete calls were accepted and something of it is still read (a delete that completes later, or one that "
            "did not take): `twinctl verify-gone %s` before anything is made again." % (step.id, step.id), err=True)
        return EXIT_REFUSED
    if tracked:
        record_deleted(t, step.id)
    say("teardown %s: deleted; read back, not found; recorded." % step.id)
    return EXIT_OK


def unknown_names(t: Twin, step: Step) -> int:
    """How many names the step's listing holds that neither the baseline nor either state knows. A listing that says it
    goes on, or that is refused, is a refusal of the read as everywhere."""
    call, names = listing_of(step.listing)
    known = set(need_baseline(t).get(step.listing, []))
    for state in (t.state, t.other_state()):
        known |= {x for fact, unconfirmed in CERT_FACTS.values() for x in (state.fact(fact), state.fact(unconfirmed)) if x}
    return len(set(names(t.aws.read(call, step.id) or {})) - known)


def record_deleted(t: Twin, step_id: str) -> None:
    """A step that was read and not found after its delete calls: recorded as deleted, with what goes with it."""
    t.state.record(step_id, status="deleted", done=[], sent=[])
    take_back(t, step_id, "teardown")
    if step_id in CERT_FACTS:
        t.state.forget(CERT_FACTS[step_id][1])                      # the id a refused reply gave: what it named is gone


def teardown_objects(t: Twin, rd: Rendered, approve: Optional[str]) -> int:
    """Emptying the bucket: permanent, so a step of its own, approved for exactly what is listed at that moment."""
    if t.state.status("bucket") == "deleted":
        say("teardown bucket-objects: the bucket is recorded as deleted; nothing was sent.")
        return EXIT_OK
    if t.state.status("bucket") not in OURS:
        refuse("not-ours", "the state does not record the bucket as made here: nothing in it is deleted")
    require_caller(t)                                               # the listing that is printed and approved is this account's
    keys = _objects(t)
    if not keys:
        say("teardown bucket-objects: the bucket %s; nothing is deleted." % ("is not there" if keys is None else "lists no object"))
        return EXIT_OK
    listed = hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()
    digest = render_hash(t, rd, "teardown", [], {"objects": len(keys), "listing": listed})
    if not approved(t, rd.step.id, "teardown", digest, approve):
        say("teardown bucket-objects (row 1): %d object(s) are listed in the bucket. Deleting them is PERMANENT: the telemetry is gone "
            "for good. It is the owner's explicit yes, each time, for this listing." % len(keys))
        say("render sha256: %s" % digest)
        say("to go on, once the owner said yes to this: twinctl teardown bucket-objects --approve bucket-objects:%s" % digest)
        note_approval(t, rd.step.id, "teardown", digest, "shown")
        return EXIT_SHOWN
    require_operator(t)
    note_approval(t, rd.step.id, "teardown", digest, "used")
    spend(t, rd.step.id, "teardown", digest)
    for start in range(0, len(keys), 1000):
        name = "delete-%04d" % (start // 1000)
        rd.render.put(name, {"Objects": [{"Key": k} for k in keys[start:start + 1000]], "Quiet": True})
        rd.render.write()
        reply = t.aws.run(c_delete_objects(t, rd.render.url(name)), "bucket-objects")
        if reply.rc != 0 or (reply.obj or {}).get("Errors"):
            say("teardown bucket-objects: a batch was refused (%s); the step can be run again, with a new approval for what is then "
                "listed." % (reply.code or "errors in the reply"), err=True)
            return EXIT_REFUSED
    left = _objects(t)
    if left:
        say("teardown bucket-objects: %d object(s) are still listed." % len(left), err=True)
        return EXIT_REFUSED
    say("teardown bucket-objects: %d object(s) deleted; the bucket lists none." % len(keys))
    return EXIT_OK


# --- the read-only commands

def cmd_baseline(t: Twin, again: bool) -> int:
    """One baseline serves the twin's state and the rehearsal's: it is taken while NEITHER records a step as made, or
    the names of the set that stands would be in it and its `verify-gone` could no longer see them as leftovers."""
    path = t.top / "baseline.json"
    made = t.standing()
    if made:
        refuse("baseline-too-late", "%d step(s) are recorded as made, in the twin's state or the rehearsal's: a baseline is what the "
               "listings return BEFORE the first create" % len(made))
    if path.is_file() and not again:
        refuse("baseline-exists", "a baseline is stored already; --again replaces it (nothing is recorded as made yet)")
    if t.names_changed():                                           # nothing stands (above): the states take the new names, with no step recorded
        for state in (t.state, t.other_state()):
            if state is t.top_state or state.path.is_file():
                state.data["names"] = t.fingerprints()
                state.data["steps"] = {}
                state.save()
    listings = {}
    for key, (call, names) in sorted(listings_of(t).items()):
        got = t.aws.read(call, "baseline")
        listings[key] = sorted(names(got or {}))
        if key == "buckets" and isinstance((got or {}).get("Owner", {}).get("ID"), str):
            t.top_state.learn(canonical_user_id=got["Owner"]["ID"])
    endpoint = t.aws.read(c_endpoint(), "baseline") or {}
    host = str(endpoint.get("endpointAddress", ""))
    if host:
        label = host.split(".")[0]
        t.top_state.learn(endpoint=host, endpoint_prefix=label[:-4] if label.endswith("-ats") else label)
    t.refresh_literals()
    write_atomic(path, dump({"v": 1, "at": now(), "listings": listings}).encode("ascii"))
    say("baseline: %d listing(s) stored (%s names in all); the endpoint and the account's canonical id are in the state, and are "
        "literals now." % (len(listings), sum(len(v) for v in listings.values())))
    return EXIT_OK


def plan_calls(rd: Rendered) -> List[Tuple[str, Call]]:
    out = [("create", c) for c in rd.built.creates] + [("read", c) for _k, c in rd.built.reads] + [("delete", c) for c in rd.built.deletes]
    if rd.step.listing:
        out.append(("listing", listing_of(rd.step.listing)[0]))
    return out


def cmd_plan(t: Twin, no_cli: bool) -> int:
    """Render everything, check every document, validate every call offline. Executes nothing: no call of this
    command reaches the account, and the CLI is only asked to read arguments."""
    env = None
    if not no_cli:
        env = t.aws.offline_env(t.render_dir)
        if not t.aws.offline_control(env):
            refuse("offline-control", "a real call under the offline settings did not fail: the settings are not offline, so no call is "
                   "given to the CLI at all")
    record: List[Dict[str, Any]] = []
    bad, pending = 0, 0
    seen: Dict[Tuple[str, ...], Tuple[str, str]] = {}
    listed: List[Call] = []                                         # every call this plan lists: what the operator role's policy is held to
    operator: Any = None
    for step in t.steps + [OTHER]:                                  # the table, then the calls a command sends outside it
        try:
            rd = t.render(step)
            rd.render.write()
            if rd.render.unfit is not None:                         # what `apply` would print and refuse: refused here by the same name
                refuse(*rd.render.unfit)
        except TwinError as e:
            pending += 1
            say("  %-22s row %-5s REFUSED %s: %s" % (step.id, step.row, e.name, e.detail))
            record.append({"id": step.id, "row": step.row, "kind": step.kind, "refused": e.name})
            continue
        calls = plan_calls(rd)
        listed += [call for _mode, call in calls]
        if step.id == "operator-role":
            operator = rd.render.obj("operator-role-policy")
        failed = 0
        for _mode, call in calls:
            if env is None:
                continue
            key = tuple(call.argv())
            if key not in seen:
                seen[key] = t.aws.validate(call, env)
            if seen[key][0] == "refused":
                failed += 1
                say("  %s %s: the CLI refuses its arguments: %s" % (call.service, call.op, seen[key][1][-600:]), err=True)
        bad += 1 if failed else 0
        note = " provisional (%s)" % ", ".join(sorted(rd.render.provisional)) if rd.render.provisional else ""
        say("  %-22s row %-5s %-8s %2d call(s) %2d document(s) %s%s"
            % (step.id, step.row, step.kind, len(calls), len(rd.render.texts), "REFUSED BY THE CLI" if failed else "ok", note))
        record.append({"id": step.id, "row": step.row, "kind": step.kind, "provisional": sorted(rd.render.provisional),
                       "documents": sorted(rd.render.texts), "inputs": dict(rd.render.inputs),
                       "creates": [c.argv() for c in rd.built.creates], "reads": [c.argv() for _k, c in rd.built.reads],
                       "deletes": [c.argv() for c in rd.built.deletes]})
    other = record.pop()                                            # OTHER's entry: no step of the table
    if operator is None and t.n.rehearsal:
        # THE REHEARSAL'S CALLS ARE SENT UNDER THE OPERATOR ROLE TOO (A2), and its table holds no role: one call stands in its
        # plan alone (the shadow's update) and was held to the policy by nothing. The twin's policy is rendered here from
        # the same names, written nowhere, and held to every call this plan lists. A policy that cannot be rendered holds
        # nothing: that is said and fails the plan.
        try:
            twin = Twin(t.top, t.render_dir, False)
            operator = twin.render(twin.step("operator-role")).render.obj("operator-role-policy")
        except TwinError as e:
            pending += 1
            say("  the operator role's policy could not be rendered for the rehearsal's calls (%s): they are held to nothing" % e.name,
                err=True)
    # the operator role's policy, held to every call listed above: the owner makes the role from this render by hand
    gaps = operator_gaps(operator, listed) if operator is not None else []
    for gap in gaps:
        say("  the operator role's policy: %s" % gap, err=True)
    # THE CALLS WHOSE SAMPLE REPLY FAILED ITS OWN VALIDATION: the CLI read their options' names, the required options and each
    # value's form, and never ran the service model's validation of the call's own arguments. Named by service and operation.
    names_only = sorted({"%s %s" % (key[0], key[1]) for key, (verdict, _said) in seen.items() if verdict == "read, sample fails"})
    write_atomic(t.render_dir / ("rehearsal-plan.json" if t.n.rehearsal else "plan.json"),
                 dump({"v": 1, "validated_by_the_cli": env is not None, "steps": record, "other": other,
                       "listings": [call.argv() for _key, (call, _names) in sorted(listings_of(t).items())],
                       "read_names_and_forms_only": names_only,
                       "operator_policy_gaps": gaps}).encode("ascii"))
    verdicts = [v for v, _said in seen.values()]
    read = ("Of %d distinct call(s) the CLI read %d offline; for %d of them its own sample reply then failed its own validation, so "
            "only the options' names, the required options and each value's form were read and the model's validation of the call's "
            "own arguments never ran; %d take an output file and know no skeleton, so their arguments were read by nothing"
            % (len(seen), verdicts.count("read") + verdicts.count("read, sample fails"), verdicts.count("read, sample fails"),
               verdicts.count("no skeleton")))
    if names_only:
        say("  read by option names and value forms only (service and operation, no value): %s" % ", ".join(names_only))
    say("plan: %d step(s); %d refused for an input that is not there or not fit; %d refused by the CLI; %d gap(s) in the operator role's policy%s. "
        "%s. Nothing was executed. The renders: %s"
        % (len(t.steps), pending, bad, len(gaps), "" if operator is not None else " (the role's policy is not rendered here: not held)",
           read if env is not None else "The calls were NOT given to the CLI (--no-cli): the documents only", t.render_dir))
    return EXIT_OK if not bad and not pending and not gaps else EXIT_REFUSED


def twin_certificates(t: Twin) -> List[str]:
    cert = t.state.fact("certificate_id")
    return [cert] if cert else []


def cmd_status(t: Twin) -> int:
    """The proving reads of every step, as states. Never a value."""
    failed = 0
    say("status (%s):" % ("the rehearsal's set" if t.n.rehearsal else "the twin"))
    for step in t.steps:
        recorded = t.state.status(step.id)
        if step.kind in ("action", "empty"):
            if step.kind == "action":
                say("  %-22s row %-5s %-10s (an action: nothing to read)" % (step.id, step.row, recorded))
            continue
        try:
            rd = t.render(step, strict=False)
            if not rd.built.reads:
                # the certificate without its id, and the steps whose render stands on it: "not found" would be the word of no
                # read at all (WP6's critic, problem 3)
                say("  %-22s row %-5s %-10s no read: the state holds no id to read it by%s"
                    % (step.id, step.row, recorded, " (`twinctl recover certificate` puts it back from a reply)" if recorded in OURS else ""))
                continue
            present, diffs = observe(t, rd)
        except TwinError as e:
            say("  %-22s row %-5s %-10s not read (%s)" % (step.id, step.row, recorded, e.name))
            continue
        found = "not found" if not present else ("as rendered" if not diffs else "DIFFERS: " + "; ".join(diffs))
        if not present and step.id in GO_LIVE:
            found = NOT_LIVE                                        # the rule and the certificate are read, and are not live
        if rd.render.provisional and present:
            found += " (the render is provisional)"
        if step.id == "function" and present:
            found += zip_note(t) + source_note(t)
        say("  %-22s row %-5s %-10s %s" % (step.id, step.row, recorded, found))
    # Phase 6: every push the state records that is not `pushed` (cmd_push records one before it is sent): said, never a failure
    for key, push in sorted((t.state.data.get("pushes") or {}).items()):
        status = str(push.get("status", "pushed")) if isinstance(push, dict) else "?"
        if status != "pushed":
            say("push %s: %s" % (key, PUSH_SAID.get(status, "%s: a record twinctl does not write" % status)))
    if t.n.rehearsal:
        return EXIT_OK
    n = t.n
    certs = twin_certificates(t)

    def tried(what: str, read: Callable[..., Any], *args: Any) -> Any:
        """A read of status's own that neither assertion stands on: refused, it is said in its place, and nothing after it
        is kept from being read (the first render of the operator role's policy lacked one read, and the denial hid
        both assertions). The result is the reply, or the refusal itself."""
        try:
            return read(*args)
        except TwinError as e:
            say("%s: not read (%s)" % (what, e.name))
            return e

    def traffic(cert: str) -> Any:
        return _policy_of(t.aws.read(R("iot", "describe-certificate", "--certificate-id", cert)), "certificateDescription"), _attached(t)

    rule = tried("traffic: the rule", lambda: _policy_of(t.aws.read(R("iot", "get-topic-rule", "--rule-name", n.rule)), "rule"))
    if not isinstance(rule, TwinError):
        say("traffic: the rule is %s" % ("not there" if rule is None else ("DISABLED" if rule.get("ruleDisabled") else "enabled")))
    for cert in certs:
        got = tried("traffic: the certificate", traffic, cert)
        if isinstance(got, TwinError):
            continue
        d, (policy, thing, kind) = got
        say("traffic: the certificate is %s; the policy is %s; the thing is %s"
            % ("not there" if d is None else str(d.get("status")), "attached" if policy else "NOT attached",
               ("attached (%s)" % ("exclusive" if kind == "EXCLUSIVE_THING" else "not exclusive")) if thing else "NOT attached"))
    keys = breaker_alarm_keys(t) + (["errors"] if n.notice else [])
    states = tried("the alarms", lambda: _alarm_states(t, keys))
    for key, a in sorted(({} if isinstance(states, TwinError) else states).items()):
        if a is None:
            say("alarm %-10s not there" % key)
            continue
        targets = []
        for action in a.get("AlarmActions", []) or []:
            targets.append("the function" if action == n.function_arn else ("the notice topic" if action == n.topic_arn else "SOMETHING ELSE"))
        say("alarm %-10s %s; actions %s; targets: %s" % (key, a.get("StateValue"), "enabled" if a.get("ActionsEnabled") is True
                                                         else "DISABLED", ", ".join(targets) or "nothing"))
    # The file the alarms' steps above are held to (`as rendered`, or how they differ), by its sha256: what the burst tool is
    # given, so that a burst is sized on the file the alarms stand on and on no other (sdv/cloud/burst, decision 6). A hash
    # of the file's bytes, never a count of it.
    digest = tried("thresholds: the file the alarms are rendered from", n.thresholds_sha256)
    if not isinstance(digest, TwinError):
        say("thresholds: the file the alarms are rendered from has sha256 %s (the burst tool takes it as --thresholds-sha256)" % digest)
    # THE TWO ASSERTIONS. A read one of them stands on that is refused FAILS it: what cannot be read is no pass.
    try:
        fn = _policy_of(t.aws.read(R("lambda", "get-function", "--function-name", n.function)), "Configuration")
    except TwinError as e:
        fn = None
        failed += 1
        say("FAIL: the function could not be read (%s: %s): its certificates are not compared" % (e.name, e.detail), err=True)
    else:
        if fn is None:
            say("the function is not there: its certificates cannot be compared")
    if fn is not None:
        conc = tried("the function's reserved concurrency",
                     lambda: t.aws.read(R("lambda", "get-function-concurrency", "--function-name", n.function)) or {})
        if not isinstance(conc, TwinError):
            say("the function's reserved concurrency: %s" % conc.get("ReservedConcurrentExecutions", "none"))
        named = sorted(x for x in str(_policy_of(fn, "Environment", "Variables", "TWIN_CERTIFICATE_ARNS") or "").split(",") if x)
        want = sorted(n.arn("iot", "cert/" + c) for c in certs)
        if named != want:
            failed += 1
            say("FAIL: the certificates in the function's environment are not exactly the twin's (%d named, %d of the twin): a "
                "certificate outside the function is outside the breaker" % (len(named), len(want)), err=True)
        else:
            say("ok: the function's environment names exactly the twin's %d certificate(s)" % len(want))
    try:
        listed = (t.aws.read(LISTINGS["certificates"][0]) or {}).get("certificates", []) or []
    except TwinError as e:
        failed += 1
        say("FAIL: the account's certificates could not be listed (%s: %s): whether an ACTIVE one is outside the twin's set is not "
            "known" % (e.name, e.detail), err=True)
        return EXIT_REFUSED
    # TWO SETS since Phase 6 (spec 5 item 4): the twin's data certificate, which the function's environment names (above, unchanged),
    # and the pull certificate, which holds no IoT data permission and is outside the breaker by design. An ACTIVE certificate
    # outside the union fails; the pull certificate ACTIVE is said, and is no failure.
    pull = pull_certificates(t)
    outside_set = [c for c in listed if c.get("status") == "ACTIVE" and c.get("certificateId") not in certs and c.get("certificateId") not in pull]
    union = "the twin's set and the pull certificate" if pull else "the twin's set"
    if outside_set:
        failed += 1
        say("FAIL: %d ACTIVE certificate(s) of the account are outside %s: the breaker does not act on them"
            % (len(outside_set), union), err=True)
    else:
        say("ok: no ACTIVE certificate of the account is outside %s (%d listed)" % (union, len(listed)))
    for cert in pull:
        state = [str(c.get("status")) for c in listed if c.get("certificateId") == cert]
        say("the pull certificate is ACTIVE: active: a board day (`twinctl apply pull-inactive` ends it)" if state == ["ACTIVE"] else
            "the pull certificate is INACTIVE" if state == ["INACTIVE"] else "the pull certificate is not listed in its one state")
    return EXIT_REFUSED if failed else EXIT_OK


# --- the stop's four calls by hand: written out FIRST, for this twin, as far as the names file and the state give them

# What stands in a call by hand for a value that is not there. A value's place is never left empty and never filled
# with a guess: the slot stays, the line it stands in is written as a comment (it runs nothing), and the key the value
# comes from is said.
SLOT_RULE, SLOT_THING, SLOT_POLICY, SLOT_CERT, SLOT_ARN = "<RULE>", "<THING>", "<POLICY>", "<CERT_ID>", "<the certificate's ARN>"
SLOT_REGION, SLOT_PROFILE = "<REGION>", "<PROFILE>"
# The manual stop's four calls with no name in them: all that is ever PRINTED of them. The values are
# in the file, never on the terminal.
STOP_BY_HAND = tuple("aws " + " ".join(c.argv()) for c in stop_calls(SLOT_RULE, SLOT_THING, SLOT_POLICY, SLOT_CERT, SLOT_ARN))
# What each slot is made of, by its KEY: printed when no file could be written, so that a stop is never left with
# placeholders that nothing explains. The two endings are stop_names()' own, with the key's name where the prefix goes.
HAND_KEYS = ("What each placeholder is made of, by its key: %s is `%s` and %s is `%s`, with the value of TWIN_PREFIX where the key's name "
             "stands; %s is the value of TWIN_THING; %s is the state's fact certificate_id (state.json), and the certificate's ARN is "
             "that id after `cert/`, in the IoT service of TWIN_REGION and TWIN_ACCOUNT; each call also takes --region with TWIN_REGION "
             "and --profile with TWIN_PROFILE."
             % ((SLOT_RULE, stop_names("TWIN_PREFIX", "", False)[0], SLOT_POLICY, stop_names("TWIN_PREFIX", "", False)[1], SLOT_THING,
                 SLOT_CERT)))
HAND_FILE = "trip-by-hand.txt"                  # in the state directory, UNREDACTED: the four calls with this twin's own values
HAND: Optional[Path] = None                     # this run's file of them, once it is written: main() resets it, hand_first() sets it
HAND_FOR = "this twin"                          # whose calls that file holds: the twin's, or the rehearsal's set's (hand_first() sets it)
# What a call by hand says of a profile the names file does not give in its form. The manual stop writes the four calls with no
# --profile (the operator profile is the shell's): a profile that is not there costs no call its other values.
PROFILE_LEFT_OFF = (": --profile is left off the calls, which then run under the shell's own profile; run them under the operator profile "
                    "(AWS_PROFILE, or --profile NAME on each line)")
# The read that finds the certificate's id where the state does not give it: a comment of the file, never a line of its own
# to run among the four (they stay the manual stop's and nothing else).
FIND_CERT = ("# TO FIND THE CERTIFICATE'S ID where the state does not give it, a read that changes nothing (each target it lists is a "
             "certificate's ARN, and the id is what follows `cert/`; with it the two calls above are whole):")
INVOKED = False                                 # whether this run's trip reached its invoke: main() sets it, cmd_trip raises it
THROTTLED = "TooManyRequestsException"          # what the service answers an invoke it has no concurrency for (from memory)


def stop_certificate(state_dir: Path, rehearsal: bool, given: Dict[str, str]) -> Tuple[Optional[str], str]:
    """THE CERTIFICATE'S ID FOR THE CALLS BY HAND: (the id the state records, "") when the state is THIS twin's, else
    (None, why it is not put in: a sentence with no value in it). The id is a fact of the state, and the names beside it
    in the file are the names file's. A state that was made under another account, region, prefix or thing recorded
    ANOTHER TWIN'S certificate: that id beside this twin's names would send the owner's own deactivation and detach to
    it. So the id is taken only from a state whose recorded names (STOP_NAMES, as salted fingerprints) are the names
    file's now. A state that records no names yet (one made before its first write, or one whose entry `names` was
    taken out on the salt-missing advice) gives its certificate with no comparison: it is taken as the driver takes
    it everywhere, bound with its next write. Reads only: no salt is made here, and nothing is written."""
    try:
        state = State(state_dir / "rehearsal" if rehearsal else state_dir)
    except TwinError as e:
        return None, "the state cannot be read (%s)" % e.name
    cert = state.fact("certificate_id")
    if not cert:
        return None, "the state records no certificate: none was made from this state directory, or the state lost its id"
    if not re.fullmatch(r"[0-9a-f]{64}", cert):                     # the form the driver itself records one in (_after_certificate())
        return None, "what the state records as its certificate has not the form of a certificate's id: it is not put into a call"
    had = state.data.get("names")
    if isinstance(had, dict):
        try:
            s = (state_dir / "salt").read_bytes()
        except OSError:
            return None, ("the state directory's file `salt` is gone, so the names the state was made under cannot be compared with the "
                          "names file's: its certificate is not put beside them")
        other = [k for k in STOP_NAMES if k not in given or had.get(k) != fingerprint(s, k, given[k])]
        if other:
            return None, ("the state's records were made under names the names file does not give now (%s): its certificate may be "
                          "another twin's, and is not put beside these names" % ", ".join(other))
    return cert, ""


def hand_text(state_dir: Path, rehearsal: bool) -> Tuple[str, List[str]]:
    """THE FILE OF SECTION 8'S FOUR CALLS BY HAND: (its text; what is not filled in, each by the key its value comes from
    and with no value in it). Made from the names file as the stop reads it (names_given(), lenient: one fault in it
    does not cost the values that are in order) and from the state's one fact, the certificate's id, when the state
    is this twin's (stop_certificate()). FOR THIS TWIN AND NO OTHER, AS FAR AS THE TWO GIVE IT: a call whose every value
    is there is a line to run; a call that lacks one is a comment with the slot left in it, so nothing half filled can
    be run, and under the calls each open slot is said by its key. Nothing is guessed: a thing that does not begin with
    the prefix leaves both out, as Names refuses the pair."""
    given, unfit = names_given(state_dir, lenient=True)
    if "TWIN_REGION" not in given and "TWIN_REGION" not in unfit:
        given["TWIN_REGION"] = REGION_DEFAULT                       # as Names takes it when the key is not set, from names read whole
    absent = {k: "%s %s" % (k, unfit.get(k, "is not given")) for k in STOP_NAMES + ("TWIN_PROFILE",) if k not in given}
    prefix, thing = given.get("TWIN_PREFIX"), given.get("TWIN_THING")
    if prefix is not None and thing is not None and not thing.startswith(prefix):
        absent["TWIN_PREFIX"] = absent["TWIN_THING"] = ("TWIN_THING does not begin with TWIN_PREFIX: one of the two is not this twin's, "
                                                        "and neither is put in")
        prefix = thing = None
    rule = policy = client = None
    if prefix is not None:
        rule, policy, named = stop_names(prefix, thing or "", rehearsal)
        client = named or None
    elif not rehearsal:
        client = thing
    region, account, profile = given.get("TWIN_REGION"), given.get("TWIN_ACCOUNT"), given.get("TWIN_PROFILE")
    cert, no_cert = stop_certificate(state_dir, rehearsal, given)
    arn = arn_of("iot", region, account, "cert/" + cert) if cert and region and account else None
    filled: Dict[str, Optional[str]] = {SLOT_RULE: rule, SLOT_THING: client, SLOT_POLICY: policy, SLOT_CERT: cert, SLOT_ARN: arn,
                                        SLOT_REGION: region, SLOT_PROFILE: profile}
    reason: Dict[str, str] = {}
    for slot, key in ((SLOT_RULE, "TWIN_PREFIX"), (SLOT_THING, "TWIN_PREFIX" if rehearsal else "TWIN_THING"), (SLOT_POLICY, "TWIN_PREFIX"),
                      (SLOT_REGION, "TWIN_REGION"), (SLOT_PROFILE, "TWIN_PROFILE")):
        if filled[slot] is None:
            reason[slot] = absent[key] + (PROFILE_LEFT_OFF if slot == SLOT_PROFILE else "")
    if cert is None:
        reason[SLOT_CERT] = "certificate_id, a fact of the state: " + no_cert
    if arn is None:
        reason[SLOT_ARN] = "it is made of certificate_id, TWIN_REGION and TWIN_ACCOUNT: " + "; ".join(
            x for x in (no_cert, absent.get("TWIN_REGION"), absent.get("TWIN_ACCOUNT")) if x)
    lines = []
    for call in stop_calls(rule or SLOT_RULE, client or SLOT_THING, policy or SLOT_POLICY, cert or SLOT_CERT, arn or SLOT_ARN):
        # the profile is the shell's for the manual stop: where the names file gives none in its form, the call keeps every other value
        # and is written WITHOUT --profile, never as a comment for that slot alone (the tail says so)
        argv = call.argv() + ["--region", region or SLOT_REGION] + (["--profile", profile] if profile else [])
        left = [a for a in argv if a in reason]
        lines.append(("# NOT FILLED IN (%s): aws %s" % (", ".join(left), " ".join(argv))) if left else "aws " + shlex.join(argv))
    lacks: List[str] = []
    for why in dict.fromkeys(reason.values()):                      # each reason once, in the slots' order
        lacks.append("%s: %s" % (", ".join(slot for slot in filled if reason.get(slot) == why), why))
    whose = "THE REHEARSAL'S SET (--rehearsal) and NOT the twin" if rehearsal else "this twin"
    head = ["# twinctl trip: the manual stop's four calls by hand, written at %s as this trip's first act, before any of its "
            "checks." % now(),
            "# For %s, as far as the names file and the state give them. They are for when the function did not make the cut:" % whose,
            "# under the operator profile, in this order; `twinctl status` afterwards is the proof."]
    tail = []
    if lacks:
        tail = ["# NOT FILLED IN, each by the key its value comes from. A call that lacks a value is a comment above: it runs nothing."]
        tail += ["#   " + lack for lack in lacks]
    if cert is None and region and (policy or client):
        # the two calls that keep the device out wait for the id alone: the account itself gives it, by the policy's name (or
        # the thing's) that the names file gives. Both reads are in the operator role's policy.
        find = (R("iot", "list-targets-for-policy", "--policy-name", policy) if policy else
                R("iot", "list-thing-principals-v2", "--thing-name", str(client)))
        tail += [FIND_CERT, "#   aws " + shlex.join(find.argv() + ["--region", region] + (["--profile", profile] if profile else []))]
    return "\n".join(head + lines + tail) + "\n", lacks


def hand_first(state_value: str, rehearsal: bool) -> None:
    """THE STOP'S FIRST ACT, BEFORE ANYTHING OF IT CAN BE REFUSED (the owner's decision of 2026-10-12): the file of the four
    calls by hand is written into the state directory and its place is said. Whatever ends the trip afterwards (a key
    nobody knows, a names file with a fault, other names than the state's, the salt gone, a caller of another account,
    a render that cannot be made, a reply that cannot be written), the owner already holds the calls, and the refusal
    comes after them. Stopping is the safe direction: no ending of a trip leaves only a refusal.

    IT NEVER RAISES AND NEVER REFUSES: a stop is not ended by its own second net. Where no file can be written (no state
    directory is named, it would lie in a work tree, the write fails), the four calls are printed with their slots and
    the key each slot is made of. NOTHING OF THE FILE IS PRINTED: it holds the twin's own names, unredacted, and lies
    in the state directory; the terminal gets its place, the slots that stayed open and the keys' names."""
    global HAND, HAND_FOR
    HAND = None
    HAND_FOR = "the rehearsal's set" if rehearsal else "this twin"
    why = ""
    lacks: List[str] = []
    text = ""
    tmp: Optional[Path] = None
    try:
        if not state_value:
            why = "no state directory is named"
        else:
            state_dir = Path(os.path.abspath(os.path.expanduser(state_value)))
            if REDACT.in_a_work_tree(state_dir / "x"):
                why = "the state directory would lie inside a work tree, where nothing of a twin is written"
            else:
                OUT.name(state_dir, "<state>")
                text, lacks = hand_text(state_dir, rehearsal)
                tmp = state_dir / (HAND_FILE + ".tmp")              # where write_atomic() writes before it takes the file's place
                write_atomic(state_dir / HAND_FILE, text.encode("utf-8"))
                HAND = state_dir / HAND_FILE
    except Exception as e:                                           # noqa: BLE001 - the stop goes on whatever its own file could not do
        why = "an error no check names (%s)" % type(e).__name__
    if HAND is None:
        say("trip: the file of the four calls by hand could NOT be written (%s); a file of that name from an earlier trip is not "
            "this run's. The four calls (sdv/cloud/README.md), under the operator profile:" % why, err=True)
        for line in STOP_BY_HAND:
            say("  " + line, err=True)
        say(HAND_KEYS, err=True)
        # The write may have got as far as its own first file and failed to put it in the file's place (the place is taken,
        # or an earlier trip's file cannot be replaced). That first file then holds THIS run's calls, whole: it is named, and
        # is the run's file from here on. One that does not hold them whole is nobody's, and is taken away.
        try:
            if tmp is not None and text and tmp.is_file():
                if tmp.read_bytes() == text.encode("utf-8"):
                    HAND = tmp
                else:
                    tmp.unlink()
        except Exception:                                            # noqa: BLE001 - as above: the stop goes on
            HAND = None
        if HAND is None:
            return
        say("trip: THIS RUN'S four calls, for %s, are whole in %s all the same: the write got as far as that file and could not put "
            "it in the file's place." % (HAND_FOR, HAND), err=True)
    else:
        say("trip: the four calls by hand (sdv/cloud/README.md), for when the function does not make the cut, are written out for %s "
            "before anything else: %s" % (HAND_FOR, HAND))
    for lack in lacks:
        say("trip: by hand, NOT FILLED IN there: %s" % lack, err=True)
    if FIND_CERT in text:
        say("trip: by hand: where the certificate's id is not filled in, the file gives the read that finds it in the account.", err=True)


def write_calls(t: Twin, name: str, calls: Sequence[Call]) -> Path:
    """The calls as lines the owner can run, unredacted, in the render directory."""
    common = ["--region", t.n.region, "--profile", t.n.profile]
    path = t.render_dir / name
    write_atomic(path, ("\n".join("aws " + shlex.join(c.argv() + common) for c in calls) + "\n").encode("utf-8"))
    return path


WITHHELD_MESSAGE = ("(withheld from the capture: not the function's own failure message in its own sentence forms; it is read by hand, in "
                    "the state directory's replies)")
NO_KIND = "(not in the form an error's kind has)"


def captured_payload(obj: Any, data: bytes) -> bytes:
    """WHAT OF A FUNCTION'S PAYLOAD GOES INTO A CAPTURE: the rule of the terminal (error_said()), held for the copy too. A
    record of a run (no errorType) goes as it is, and so does a function error whose type is the breaker's own and whose
    message is, whole, in the function's own sentence forms (own_message()). Of ANY OTHER function error only the KIND
    goes, in the form a kind has: its message is not the function's contract (the runtime's, or an error from before the
    handler's first line, whose text may quote the environment), the redactor knows shapes and the literals it is given
    and nothing else, and a capture is what leaves the state directory. The whole payload stays in the state directory."""
    if not isinstance(obj, dict) or "errorType" not in obj:
        return data
    kind = obj.get("errorType")
    if kind == OWN_ERROR and own_message(obj.get("errorMessage")) is not None:
        return data
    return dump({"errorType": kind if isinstance(kind, str) and ERROR_KIND.fullmatch(kind) else NO_KIND,
                 "errorMessage": WITHHELD_MESSAGE}).encode("ascii")


def capture_replies(t: Twin, replies: Sequence[Tuple[str, str, Path, str]], capture: Path) -> None:
    """Replies into a capture directory, redacted: (service, operation, the reply's file, its name in the capture). Only
    replies of COPIED_REPLIES, and none that holds a field of ENCODED_REPLY_FIELDS: that is refused before anything is
    copied. All of them or none: they are staged in the state directory and copied as one."""
    staging = t.state_dir / "capture-staging"
    if staging.exists():
        for old in staging.iterdir():
            old.unlink()
    for service, op, src, name in replies:
        if (service, op) not in COPIED_REPLIES:
            refuse("reply-not-copied", "the replies of %s %s are not among those twinctl ever copies into a capture" % (service, op))
        try:
            data = src.read_bytes()
            obj = json.loads(data.decode("utf-8"))
        except (OSError, ValueError):
            refuse("reply-unreadable", "a reply that is to be copied is not JSON; it stays in the state directory")
        field = find_encoded(obj)
        if field:
            refuse("reply-holds-encoded-text", "a reply holds the field %s, which carries encoded text: nothing was copied. It stays in "
                   "the state directory, to be looked at; the field is left out, never decoded in place or masked" % field)
        write_atomic(staging / name, captured_payload(obj, data) if (service, op) == ("lambda", "invoke-payload") else data)
    try:
        REDACT.copy_tree(staging, capture, OUT.literals)
    except REDACT.RedactError as e:
        refuse("capture-refused", "the redactor refuses the copy (%s): a stop, not a retry; nothing was written" % e)


ACCOUNT_ID = re.compile(r"[0-9]{12}")
# The refusals of the runner that certainly sent nothing: no CLI to run, an argv it refuses, a write before it was armed, a
# call before the caller was read. Every other error of the invoke's own call leaves its outcome unknown (cmd_trip()).
INVOKE_NOT_SENT = ("cli-missing", "forbidden-option", "not-armed", "caller-not-read")
# With no CLI that runs, the manual stop's four calls cannot be run either: its fourth way is what is left, and is named.
NO_CLI = ("cli-missing", "cli-failed")
CONSOLE_WAY = ("With no AWS CLI that runs, the four calls cannot be run from here either: the manual stop's fourth way is the console "
               "(IoT Core: the certificate deactivated, the rule disabled; its labels from memory of the console).")


def console_way(refusal: str) -> str:
    """What is said after the four calls by hand when the refusal says that no CLI runs: the one way that needs none."""
    return CONSOLE_WAY if refusal in NO_CLI else ""


def trip_status(t: Twin) -> int:
    """`status` AS A TRIP'S PROOF, HELD TO THE ACCOUNT ONCE MORE. The caller is read again right before it. A profile
    repointed between two calls of one command (the CLI's own configuration, edited meanwhile; twinctl cannot cause it)
    would make the status ANOTHER account's: `not found` for every step and `ok: no ACTIVE certificate ...`, a wrong
    all-clear where the manual stop reads its proof (the hard review of WP8's fixes, NIT 3). When the profile now answers
    for another account, no status is printed, that is said, and the trip ends as a refusal. An identity that cannot
    be read now keeps no status back, as it stops no trip: its lines then say what could not be read."""
    try:
        got = t.aws.read(c_identity(), "trip")
    except TwinError:
        got = None
    account = str(got.get("Account", "")) if isinstance(got, dict) else ""
    if ACCOUNT_ID.fullmatch(account) and account != t.n.account:
        say("trip: THE PROFILE NOW ANSWERS FOR ANOTHER ACCOUNT than the names file's: `status` is NOT read here, because it would be "
            "that account's and no proof for this twin (this trip's invoke went under the identity that was read first). Look at "
            "the CLI's configuration, then run `twinctl status`; if the cut is not there, RUN THE FOUR CALLS BY HAND.", err=True)
        return EXIT_REFUSED
    return cmd_status(t)


def cmd_trip(t: Twin, capture: Optional[Path]) -> int:
    """The one-command stop. No approval: stopping is the safe direction, and the script cannot tell who asks anyway.
    For the same reason it goes on with what it has: `t.lacks` says what it could not load. The file of the four calls
    by hand is written already, before this was reached and before anything could refuse (hand_first())."""
    global INVOKED
    for lack in t.lacks:
        say("trip: " + lack, err=True)
    rd = t.render(Step("trip", "8", "the manual trip", lambda t, r: Built([_invoke(t, r, "invoke-trip", "trip")])))
    rd.render.write()
    # The caller. The stop is held to the ACCOUNT alone, not to the role (whoever may invoke the function may stop the
    # twin), and an identity that cannot be read does not stop it. An identity of ANOTHER account does: its function of the
    # same name is not this twin's breaker, and the `status` that follows would be that account's (the hard review's
    # SHOULD 1). main() then names the four calls by hand once more, after the refusal.
    try:
        got = t.aws.read(c_identity(), "trip")
        if not isinstance(got, dict) or not ACCOUNT_ID.fullmatch(str(got.get("Account", ""))):
            # A reply that names no account (an empty one, one in another shape) is an identity that COULD NOT BE READ, like a
            # read that was denied or cut off: the stop goes on. It is not "another account": only a reply that names one is.
            refuse("identity-unreadable", "the reply to the read of the caller names no account")
    except TwinError as e:
        say("trip: the caller's identity could not be read (%s): the stop goes on, under whatever account the profile answers "
            "for" % e.name, err=True)
    else:
        if str((got or {}).get("Account", "")) != t.n.account:
            refuse("identity-other-account", "the caller's account is not the account of the names file: another account's function "
                   "is not invoked, and nothing was sent")
    t.aws.arm()
    call = rd.built.creates[0]
    sent = t.aws.count
    try:
        reply = t.aws.run(call, "trip")
    except Exception as e:                                           # noqa: BLE001 - told apart below; what was not sent is raised again
        # AN INVOKE THAT WAS SENT AND WHOSE ANSWER IS NOT KNOWN is no trip "refused before the function was invoked": the CLI
        # printed what is no JSON after the function did its work, was cut off, or its reply could not be written. The
        # function MAY HAVE RUN. Said so, and `status` follows as it follows a failed invoke: it is the proof. Only what
        # certainly sent nothing (INVOKE_NOT_SENT, or an error from before the CLI was run) stays a refusal before the invoke.
        if (e.name in INVOKE_NOT_SENT) if isinstance(e, TwinError) else (t.aws.count == sent):
            raise
        INVOKED = True
        name = e.name if isinstance(e, TwinError) else type(e).__name__
        say("trip: THE INVOKE WAS SENT AND ITS ANSWER IS NOT KNOWN (%s): THE FUNCTION MAY HAVE RUN. Read `status` below first; if the "
            "cut is not there, RUN THE FOUR CALLS BY HAND." % name, err=True)
        trip_status(t)
        if HAND is not None:
            say("trip: the four calls by hand, with %s's own values, are in %s" % (HAND_FOR, HAND), err=True)
        no_cli = console_way(name)
        if no_cli:
            say(no_cli, err=True)
        return EXIT_REFUSED
    INVOKED = True
    if reply.rc != 0:
        if reply.code == THROTTLED:
            # the function's reserved concurrency is 1 (row 13's second step): a throttled invoke is one that met a run of
            # the function, an alarm's own. The calls by hand would then run beside it; the read that shows a cut in progress
            # comes first
            say("trip: the invoke failed (%s): under its reserved concurrency the function runs one invoke at a time, so A RUN OF "
                "THE FUNCTION MAY BE UNDER WAY (an alarm's own). Read `status` below first; if the cut is not there, RUN THE FOUR "
                "CALLS BY HAND." % reply.code, err=True)
        else:
            say("trip: the invoke failed (%s). RUN THE FOUR CALLS BY HAND." % reply.code, err=True)
        # the manual stop's proof for the calls by hand: `status` follows a failed invoke as it follows a function error
        # (the runner is armed already, and the reads change nothing)
        trip_status(t)
        return EXIT_REFUSED
    why = invoke_verdict(reply.obj)
    if why:
        say("trip: %s. Look at `status` below; if the cut is not there, RUN THE FOUR CALLS BY HAND." % why, err=True)
        say(error_said(Path(call.args[-1]), "trip"), err=True)
    else:
        say("trip: the function ran. Its record is in the state directory.")
        say(trip_facts(Path(call.args[-1]), "trip"))
    rc = trip_status(t)
    if why:
        trip_failed(t)                                              # after the status: bookkeeping never hides it
    if capture is not None:                                         # last: a refusal here must not hide the status
        reply_file = t.state_dir / "replies" / "trip-reply.json"
        write_atomic(reply_file, dump(reply.obj).encode("ascii"))
        capture_replies(t, [("lambda", "invoke", reply_file, "trip-reply.json"),
                            ("lambda", "invoke-payload", Path(call.args[-1]), "trip-record.json")], capture)
        say("trip: the reply and the function's record are copied, redacted, into %s" % capture)
    return EXIT_REFUSED if why else rc


def cmd_build_breaker(t: Twin) -> int:
    """The function's zip, built from sdv/cloud/breaker/breaker.py into the file TWIN_BREAKER_ZIP names: outside every work
    tree. No call is sent. What it prints is what `apply function` prints again and the function is held to."""
    if "TWIN_BREAKER_ZIP" not in t.n.v:
        refuse("input-unset", "TWIN_BREAKER_ZIP is not set: where the function's zip is written")
    target = Path(os.path.abspath(os.path.expanduser(t.n.v["TWIN_BREAKER_ZIP"])))
    if REDACT.in_a_work_tree(target):
        refuse("inside-a-work-tree", "the function's zip would lie inside a work tree: it is built outside every one (nothing was written)")
    try:
        source = BREAKER_SOURCE.read_bytes()
    except OSError:
        refuse("source-missing", "the function's source is not where twinctl reads it from (sdv/cloud/breaker/breaker.py)")
    data = zip_bytes(source)
    check_breaker_source(source)
    write_atomic(target, data)
    digest = hashlib.sha256(data).hexdigest()
    say("build-breaker: one entry (%s, %d bytes), stored, with a fixed time and mode: the same bytes on every build." % (ZIP_ENTRY, len(source)))
    say("the zip: %s" % target)
    say("sha256 %s" % digest)
    say("as the service reports a function's code (CodeSha256): %s" % code_sha256(digest))
    say("`twinctl apply function` prints this hash again; the approval covers it, and the function is held to it afterwards.")
    return EXIT_OK


# --- recover: a fact a reply gave, put back into the state from the reply itself

RECOVERABLE = {"certificate": ("iot", "create-certificate-from-csr"), "pull-certificate": ("iot", "create-certificate-from-csr")}
# The fact each certificate's step records its id under, and the one it keeps an id under that a refused reply gave (Phase 6
# adds the pull certificate beside the twin's data certificate).
CERT_FACTS = {"certificate": ("certificate_id", UNCONFIRMED), "pull-certificate": ("pull_certificate_id", PULL_UNCONFIRMED)}


def _pem(text: Any) -> str:
    return "".join(text.split()) if isinstance(text, str) else ""


def reply_candidates(t: Twin, step_id: str) -> Tuple[Dict[str, str], int]:
    """What the replies of THIS state directory give for the step's create call: {a certificate's id: the PEM that same
    reply holds}, and how many reply files there are. Only a file the runner itself wrote (its name ends in the call
    and the step), only a reply that names a certificate of this account and region with its PEM, and no id the
    baseline already listed: that one was there before the twin."""
    service, op = RECOVERABLE[step_id]
    baseline = set(need_baseline(t).get("certificates", []))
    replies = t.state_dir / "replies"
    files = sorted(replies.glob("*-%s-%s-%s.json" % (service, op, step_id))) if replies.is_dir() else []
    found: Dict[str, str] = {}
    for path in files:
        try:
            reply = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(reply, dict):
            continue
        cert, arn, pem = reply.get("certificateId"), reply.get("certificateArn"), reply.get("certificatePem")
        if isinstance(cert, str) and re.fullmatch(r"[0-9a-f]{64}", cert) and arn == t.n.arn("iot", "cert/" + cert) and _pem(pem) \
                and cert not in baseline:
            found[cert] = str(pem)
    return found, len(files)


def cmd_recover(t: Twin, step_id: str, approve: Optional[str]) -> int:
    """THE WAY BACK FOR THE ONE FACT A REPLY GIVES AND THE STATE CAN LOSE: the certificate's id (a state.json put back
    from an older copy; a run that ended between the reply and its record). Without it every render that stands on the
    id is refused, on a live twin too. The id is NEVER TYPED: it is taken from a reply file the runner itself wrote
    under this state directory, and it is recorded only after the account showed exactly one certificate the replies
    name, with that reply's own PEM, and (when the state records the attachments as made) attached to the twin's thing.
    Printed and approved like a step; held to the caller and to the names like `apply`; it sends reads only."""
    step = t.step(step_id)
    if step_id not in RECOVERABLE:
        refuse("recover-not-this-step", "only the certificate's id is a fact a reply gives: no other step has anything to put back")
    if t.state.fact(CERT_FACTS[step_id][0]) is not None:
        refuse("nothing-to-recover", "the state holds the certificate's id: nothing is put back over it")
    if t.state.status(step_id) not in OURS:
        refuse("not-ours", "the state records nothing made for this step: nothing is put back for what was not made here")
    candidates, files = reply_candidates(t, step_id)
    if not candidates:
        refuse("no-reply-to-recover-from", "of %d reply file(s) of this step's create call in the state directory, none names a certificate "
               "of this account and region that the baseline lacks (a reply that was lost holds no id). By hand: `twinctl verify-gone` "
               "lists what the account holds beyond the baseline; what a lost create made is deleted there by hand, and `twinctl "
               "teardown %s` then takes the record back" % (files, step_id))
    # the thing the certificate is held to: the twin's, once the attachments are recorded; the pull thing's, once the pull
    # attachment is recorded and the names give one (Phase 6); none otherwise
    if step_id == "certificate":
        thing, whose = (t.n.thing if t.state.status("attachments") in OURS else ""), "the twin's thing"
    else:
        thing, whose = (t.n.pull_thing if t.state.status("pull-attachment") in OURS else ""), "the pull thing"
    attached = bool(thing)
    reads = [R("iot", "describe-certificate", "--certificate-id", cert) for cert in sorted(candidates)]
    reads += [R("iot", "list-thing-principals-v2", "--thing-name", thing)] if attached else []
    rd = t.render(step, strict=False)
    digest = render_hash(t, rd, "recover", reads, {"replies": files, "pems": sorted(hashlib.sha256(_pem(p).encode("ascii", "replace")).hexdigest()
                                                                                    for p in candidates.values())})
    if not approved(t, step_id, "recover", digest, approve):
        say("recover %s (row %s): %d reply file(s) of this step's create call in the state directory name %d certificate(s) of this "
            "account and region that the baseline lacks." % (step_id, step.row, files, len(candidates)))
        say("%d read(s) of the account, and no call that changes it: describe-certificate for each%s. The id is put back into the state "
            "only when exactly one of them stands and holds the PEM its own reply holds%s; it is never typed."
            % (len(reads), (", list-thing-principals-v2 for %s" % whose) if attached else "",
               (", attached to %s (the state records the attachments as made)" % whose) if attached else ""))
        say("render sha256: %s" % digest)
        say("to go on, once the owner said yes to this: twinctl recover %s --approve %s:%s" % (step_id, step_id, digest))
        note_approval(t, step_id, "recover", digest, "shown")
        return EXIT_SHOWN
    need_baseline(t)
    require_caller(t)                                               # reads only: the runner is not armed
    note_approval(t, step_id, "recover", digest, "used")
    spend(t, step_id, "recover", digest)
    standing, own = [], []
    for cert in sorted(candidates):
        d = _policy_of(t.aws.read(R("iot", "describe-certificate", "--certificate-id", cert), "recover"), "certificateDescription")
        if d is None:
            continue
        standing.append(cert)
        if d.get("certificateId") == cert and d.get("certificateArn") == t.n.arn("iot", "cert/" + cert) and _pem(d.get("certificatePem")) == _pem(
                candidates[cert]):
            own.append(cert)
    if len(standing) != 1 or own != standing:
        refuse("recover-not-decided", "of the %d certificate(s) the replies name, %d stand in the account and %d of those hold their own "
               "reply's PEM: the id is put back only when exactly one stands and is its reply's own. Nothing was put back"
               % (len(candidates), len(standing), len(own)))
    cert = own[0]
    if attached:
        principals = t.aws.read(R("iot", "list-thing-principals-v2", "--thing-name", thing), "recover") or {}
        if not any(p.get("principal") == t.n.arn("iot", "cert/" + cert) for p in principals.get("thingPrincipalObjects", []) or []):
            refuse("recover-not-decided", "the state records the attachments as made, and the certificate the reply names is not attached "
                   "to %s: it is not shown to be the twin's own. Nothing was put back" % whose)
    t.state.learn(**{CERT_FACTS[step_id][0]: cert})
    t.refresh_literals()
    if t.state.status(step_id) in ("creating", "partial"):          # the create went through, as the account shows: read it again to prove it
        t.state.record(step_id, status="unverified", done=[0], sent=[0])
    say("recover %s: one certificate a reply of this state directory names stands in the account with that reply's own PEM%s. Its id "
        "is a fact of the state again, and a literal. `twinctl apply %s` reads the step again; `twinctl status` shows it."
        % (step_id, (", attached to %s" % whose) if attached else "", step_id))
    return EXIT_OK


def cmd_restore(t: Twin) -> int:
    """Render the three reverse calls, for the owner to run by hand. Refused while the breaker is not armed."""
    block = alarms_block(t)
    if block:
        refuse("restore-refused", block + ". Wait until every breaker alarm is back in OK with its actions enabled (the manual stop)")
    n = t.n
    cert, arn = _cert(t)
    if cert is None or arn is None:
        refuse("render-provisional", "the state holds no certificate: there is nothing to restore")
    calls, proofs = restore_calls(n, cert, arn)
    path = write_calls(t, "restore.txt", [c for pair in zip(calls, proofs) for c in pair])
    say("restore: every breaker alarm is in OK or INSUFFICIENT_DATA with its actions enabled. The owner runs these three, each read "
        "before the next, then `twinctl status`:")
    for call, proof in zip(calls, proofs):
        say("  run:   aws " + shlex.join(call.argv()))
        say("  proof: aws " + shlex.join(proof.argv()))
    say("as lines to run, unredacted: %s" % path)
    return EXIT_OK


def cmd_verify_gone(t: Twin, step_id: Optional[str]) -> int:
    """Read-only. Passes only when nothing recorded is found by name, no listing holds a name the baseline lacks, and
    the tag query is empty."""
    if step_id and t.step(step_id).kind != "resource":
        refuse("step-not-a-resource", "verify-gone reads what the state records as made here, and this step is no resource the driver "
               "makes (an action, a role the owner makes, a log group that was adopted, the shadows, whose check is in teardown): "
               "it would be called gone on no read")
    baseline = need_baseline(t)
    steps = [t.step(step_id)] if step_id else [s for s in t.steps if s.kind == "resource"]
    found = 0
    for step in steps:
        if step.kind != "resource":
            continue
        if t.state.status(step.id) == "absent" and not step_id:
            continue
        try:
            rd = t.render(step, strict=False)
            if not rd.built.reads:
                # No read at all: a certificate whose id the state does not hold, a render on a value the state lost. "Not
                # found" would be the word of no read (the hard review's NIT 2); a step the state records as made is then
                # not settled, and nothing is recorded as deleted. The listings are what see such a resource.
                unsettled = t.state.status(step.id) in OURS
                say("  by name   %-22s no read: the state holds no id to read it by%s"
                    % (step.id, "; it records the step as made, so this is NOT settled" if unsettled else ""))
                found += 1 if unsettled else 0
                continue
            present, _diffs = observe(t, rd)
        except TwinError as e:
            say("  by name   %-22s not read (%s)" % (step.id, e.name), err=True)
            found += 1
            continue
        say("  by name   %-22s %s" % (step.id, "FOUND" if present else (NOT_LIVE if step.id in GO_LIVE else "not found")))
        if present:
            found += 1
        elif t.state.status(step.id) == "deleting":
            record_deleted(t, step.id)
    extra = 0
    for key in sorted({s.listing for s in steps if s.listing}):
        call, names = listing_of(key)
        listed = names(t.aws.read(call, "verify-gone") or {})
        new = sorted(set(listed) - set(baseline.get(key, [])))
        say("  listing   %-22s %d name(s), %d not in the baseline" % (key, len(listed), len(new)))
        extra += len(new)
    tagged = 0
    if not step_id:
        got = t.aws.read(c_tagged(t), "verify-gone") or {}
        tagged = len(got.get("ResourceTagMappingList", []) or [])
        say("  tag query %-22s %d resource(s)" % ("", tagged))
    if found or extra or tagged:
        say("verify-gone: NOT gone: %d found by name, %d name(s) the baseline lacks, %d tagged." % (found, extra, tagged), err=True)
        return EXIT_REFUSED
    say("verify-gone: gone. A named shadow is seen by none of these three (its check is in teardown, before the thing); metric history "
        "and the account's event trail remain and cannot be deleted.")
    return EXIT_OK


# --- push (Phase 6, spec section 5 item 7): an image into the twin's repository by digest, its config digest proved first

APP_VERSION = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
INDEX_TYPES = ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json")
MANIFEST_TYPES = ("application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json")
SAVED_BLOB_MAX = 4 << 20                        # a manifest or a config is a few kilobytes; a layer is never read (as sdv/arm64's reader)
DOCKER_TIMEOUT = 1800
# What `status` says of a push the state records that is not `pushed` (fable#4)
PUSH_SAID = {"sending": "sending: it was sent, and how it ended is not known; the repository's image listing says whether it stands",
             "unverified": "unverified: its read-back did not give the store ID; the repository's image listing says what stands under the tag"}


def docker_path(prefix: Sequence[str], path: Path) -> str:
    """A local directory as the docker the prefix runs sees it: WSL's (a prefix whose first word is wsl or wsl.exe) sees a drive
    path X:\\... as /mnt/x/...; any other docker, the path as it is."""
    p = os.path.abspath(str(path))
    if prefix and os.path.basename(prefix[0]).lower() in ("wsl", "wsl.exe") and re.match(r"^[A-Za-z]:[\\/]", p):
        return "/mnt/" + p[0].lower() + p[2:].replace("\\", "/")
    return p


def docker_run(argv: List[str], what: str) -> None:
    """One docker command, its words not printed (a push's and a tag's name the registry, which holds the account)."""
    try:
        done = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=DOCKER_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        refuse("docker-failed", "%s could not be run to its end (%s; the --docker prefix names the command)" % (what, type(e).__name__))
    if done.returncode != 0:
        refuse("docker-failed", "%s exited %d (nothing of docker's words is printed: they name the registry)" % (what, done.returncode))


def other_names(prefix: List[str], store_id: str, ref: str) -> List[str]:
    """The names the image the store ID names has besides the registry's reference, by `docker image inspect` (its RepoTags; nothing
    of docker's words is printed: a name may hold the registry). `docker rmi <ref>` removes an image whose only name it is."""
    try:
        done = subprocess.run(prefix + ["image", "inspect", store_id], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              stdin=subprocess.DEVNULL, timeout=DOCKER_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        refuse("docker-failed", "docker image inspect could not be run to its end (%s; the --docker prefix names the command)" % type(e).__name__)
    if done.returncode != 0:
        refuse("docker-failed", "docker image inspect of the store ID exited %d (nothing of its words is printed)" % done.returncode)
    try:
        doc = json.loads(done.stdout.decode("utf-8"))
        tags = doc[0].get("RepoTags") or []
        if len(doc) != 1 or not isinstance(tags, list):
            raise TypeError
    except (UnicodeDecodeError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        refuse("docker-failed", "docker image inspect of the store ID gave no one image's names in their form: nothing was tagged or sent")
    return [str(x) for x in tags if str(x) != ref]


def proved_config(prefix: List[str], store_id: str) -> Tuple[str, Dict[str, Any]]:
    """The config digest and the config of the image the store ID names, from a `docker save` stream, as sdv/arm64's reader proves
    one: the blob of the store ID hashes to it and is ONE platform's manifest (an index is refused: the push would send it and
    its attestations, wp0-facts D2, D4), and the config blob hashes to the digest the manifest names."""
    blobs: Dict[str, bytes] = {}
    try:
        p = subprocess.Popen(prefix + ["save", store_id], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    except OSError as e:
        refuse("docker-failed", "docker save could not be run (%s; the --docker prefix names the command)" % type(e).__name__)
    assert p.stdout is not None
    try:
        with tarfile.open(fileobj=p.stdout, mode="r|") as tf:
            for m in tf:
                if m.isreg() and m.name.startswith("blobs/sha256/") and m.size <= SAVED_BLOB_MAX:
                    f = tf.extractfile(m)
                    if f is not None:
                        blobs["sha256:" + m.name.rsplit("/", 1)[1]] = f.read()
        for _chunk in iter(lambda: p.stdout.read(1 << 20), b""):   # type: ignore[union-attr]
            pass
    except (tarfile.TarError, OSError):
        blobs = {}
    finally:
        rc = p.wait(timeout=DOCKER_TIMEOUT)
    if rc != 0:
        refuse("docker-failed", "docker save of the store ID exited %d (nothing of its words is printed)" % rc)

    def blob(digest: Any) -> Any:
        raw = blobs.get(str(digest))
        if raw is None or "sha256:" + hashlib.sha256(raw).hexdigest() != digest:
            refuse("save-stream-unreadable", "the save stream holds no blob that hashes to a digest it names: nothing was tagged or sent")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            refuse("save-stream-unreadable", "a blob of the save stream that a digest names is no JSON: nothing was tagged or sent")

    manifest = blob(store_id)
    kind = manifest.get("mediaType") if isinstance(manifest, dict) else None
    if kind in INDEX_TYPES or (isinstance(manifest, dict) and "manifests" in manifest):
        refuse("store-id-names-an-index", "the store ID names an image index, not one platform's manifest: a push sends what it names, "
               "and a pulling host proves one manifest's config (build with --provenance=false --sbom=false, or give the platform "
               "manifest's ID); nothing was tagged or sent")
    if kind not in MANIFEST_TYPES or not isinstance(manifest.get("config"), dict):
        refuse("save-stream-unreadable", "the store ID names no single-platform image manifest: nothing was tagged or sent")
    digest = str(manifest["config"].get("digest"))
    config = blob(digest)
    if not isinstance(config, dict):
        refuse("save-stream-unreadable", "the manifest's config is no JSON object: nothing was tagged or sent")
    return digest, config


def docker_login(t: Twin, prefix: List[str], config_dir: Path) -> None:
    """`aws ecr get-login-password` piped into `docker --config <config_dir> login --username AWS --password-stdin <registry>`: the
    password goes by the pipe between the two processes, on no argv, into no reply file and through no line of this process; the
    only file that holds it is docker's own in that directory, which cmd_push removes."""
    n = t.n
    cli = t.aws.exe + list(c_login_password().argv()) + ["--region", n.region, "--profile", n.profile, "--no-cli-pager"]
    login = prefix + ["--config", docker_path(prefix, config_dir), "login", "--username", "AWS", "--password-stdin", n.registry]
    try:
        source = subprocess.Popen(cli, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        try:
            sink = subprocess.Popen(login, stdin=source.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            if source.stdout is not None:
                source.stdout.close()
        docker_rc, cli_rc = sink.wait(timeout=DOCKER_TIMEOUT), source.wait(timeout=DOCKER_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        refuse("login-failed", "the CLI's get-login-password or docker login could not be run to its end (%s)" % type(e).__name__)
    if cli_rc != 0:
        refuse("login-failed", "the CLI's get-login-password exited %d (nothing of its words is printed)" % cli_rc)
    if docker_rc != 0:
        refuse("login-failed", "docker login exited %d (nothing of its words is printed)" % docker_rc)


def cmd_push(t: Twin, app: str, version: str, arch: str, store_id: str, config_digest: str, docker: str, approve: Optional[str]) -> int:
    """An image into sdv-twin/<app> under the tag <version>-<arch>, printed and approved like a step. Then: the config digest proved
    from the save stream (an index refused), the store ID tagged, a login whose password goes by a pipe into a temporary docker
    directory, the push, the tag and the directory removed whatever happened, the registry's digest for the tag read back and held to
    the store ID, and the push recorded (tag, manifest digest, config digest)."""
    n = t.n
    if app not in ECR_APPS:
        refuse("push-app-unknown", "the app is not one of the twin's repositories (ECR_APPS)")
    if not APP_VERSION.fullmatch(version):
        refuse("push-version-invalid", "the version is not X.Y.Z")
    if not DIGEST.fullmatch(store_id) or not DIGEST.fullmatch(config_digest):
        refuse("push-digest-invalid", "the store ID and the config digest are each sha256: and 64 lower-case hex digits")
    if t.state.status("ecr-repository") != "created":
        refuse("push-needs-repository", "the step ecr-repository is not recorded as made and proven (TWIN_ECR=1, then apply ecr-repository): "
               "there is no repository to push to")
    try:
        prefix = shlex.split(docker)
    except ValueError:
        prefix = []
    if not prefix:
        refuse("push-docker-invalid", "--docker names no command")
    repo, tag = "%s/%s" % (ECR_NAMESPACE, app), "%s-%s" % (version, arch)
    ref = "%s/%s:%s" % (n.registry, repo, tag)
    calls = [c_login_password(), c_image_by_tag(repo, tag)]
    rd = t.render(Step("push", "B4", "an image into the twin's repository", lambda t, r: Built(calls), None, kind="other"))
    digest = render_hash(t, rd, "push", calls, {"repository": repo, "tag": tag, "store_id": store_id, "config_digest": config_digest,
                                                "docker": prefix})
    if not approved(t, "push", "push", digest, approve):
        say("push (row B4): %s:%s, the image by its store ID; its config digest is proved from the save stream first" % (repo, tag))
        for what, value in (("repository", repo), ("tag", tag), ("store ID", store_id), ("config digest", config_digest),
                            ("docker", shlex.join(prefix))):
            say("  %s: %s" % (what, value))
        say("%d call(s) of the CLI (the password goes by a pipe into docker's stdin; docker's save, tag, login, push and rmi are not "
            "the CLI's):" % len(calls))
        show_calls(calls)
        say("render sha256: %s" % digest)
        say("to go on, once the owner said yes to this push: twinctl push --app %s --version %s --arch %s --store-id %s --config-digest %s "
            "--docker %s --approve push:%s" % (app, version, arch, store_id, config_digest, shlex.quote(docker), digest))
        note_approval(t, "push", "push", digest, "shown")
        return EXIT_SHOWN
    require_operator(t)
    note_approval(t, "push", "push", digest, "used")
    proved, config = proved_config(prefix, store_id)
    if proved != config_digest:
        refuse("config-digest-differs", "the image the store ID names has another config digest than the one given: nothing was tagged or sent")
    if config.get("architecture") != arch or config.get("os") != "linux":
        refuse("image-not-the-arch", "the image the store ID names is not linux/%s: nothing was tagged or sent" % arch)
    if not other_names(prefix, store_id, ref):
        # fable#8: the tag goes by `docker rmi <ref>` after the push, and in the `finally` after a login or a push that failed; an
        # image whose only name that is goes with it (one loaded or built with no name), pushed or not
        refuse("push-image-unnamed", "the image the store ID names has no name of its own (docker image inspect gives it none but the "
               "registry's reference): the tag is removed after the push by `docker rmi`, which would remove the image with it. Give it "
               "a name first (docker tag <store ID> <a local name>); nothing was tagged or sent")
    key = "%s:%s" % (repo, tag)
    # the approval is spent here, by the first thing done under it, as cmd_apply spends after its reads (fable#5): a push refused by the
    # save stream's proof or for the image's want of a name sent and tagged nothing, and its printing still stands
    spend(t, "push", "push", digest)
    tagged, config_dir = False, None
    try:
        docker_run(prefix + ["tag", store_id, ref], "docker tag")
        tagged = True
        config_dir = Path(tempfile.mkdtemp(prefix="twinctl-docker-"))
        if REDACT.in_a_work_tree(config_dir / "x"):
            refuse("inside-a-work-tree", "the temporary docker directory would lie inside a work tree (TMPDIR): nothing was sent")
        docker_login(t, prefix, config_dir)
        # ON RECORD BEFORE IT IS SENT, AND IT STAYS THERE HOWEVER IT ENDED (cmd_apply's rule for a create; fable#4): a push that ended in
        # an error, or whose read-back failed or gave another digest, may have put the image, and the state then still knows of it
        t.state.data.setdefault("pushes", {})[key] = {"tag": tag, "store_id": store_id, "config_digest": proved, "status": "sending", "at": now()}
        t.state.save()
        try:
            docker_run(prefix + ["--config", docker_path(prefix, config_dir), "push", ref], "docker push")
        except TwinError as e:
            refuse(e.name, "%s; the push stays on record as sent (`sending`): one that ended in an error may still have put the image, "
                   "and `twinctl status` lists it" % e.detail)
    finally:
        if config_dir is not None:
            shutil.rmtree(str(config_dir), ignore_errors=True)
            if config_dir.exists():
                say("push: the temporary docker directory could not be removed; it holds the registry's login: remove it by hand (%s)"
                    % config_dir, err=True)
        if tagged:
            try:
                docker_run(prefix + ["rmi", ref], "docker rmi")
            except TwinError as e:
                say("push: the local tag could not be removed (%s): it names the registry; remove it by hand" % e.detail, err=True)
    record = t.state.data["pushes"][key]
    try:
        got = t.aws.read(c_image_by_tag(repo, tag), "push") or {}
    except TwinError:
        record.update(status="unverified", at=now())                # a read that failed is no read-back: on record, unverified
        t.state.save()
        raise
    details = [d for d in got.get("imageDetails", []) or [] if isinstance(d, dict)]
    pushed = details[0].get("imageDigest") if len(details) == 1 else None
    if pushed != store_id:
        record.update(status="unverified", at=now())
        t.state.save()
        refuse("pushed-digest-differs", "the registry's manifest digest for the tag is not the store ID: the tag %s stands in the repository "
               "with another digest, or with none the read shows (the repository is IMMUTABLE: the image is deleted by hand, "
               "sdv/cloud/README.md, before the tag is pushed again); the push stays on record as `unverified`" % tag)
    record.update(manifest_digest=pushed, status="pushed", at=now())
    t.state.save()
    say("push: %s:%s pushed; the registry's manifest digest is the store ID; recorded." % (repo, tag))
    return EXIT_OK


# --- ecr-config (Phase 6, spec section 5 item 8): the pulling host's one root-only file (D7)

CREDENTIAL_HOST = re.compile(r"[A-Za-z0-9-]{1,63}\.credentials\.iot\.[a-z0-9-]{1,32}\.amazonaws\.com")


def write_private(path: Path, data: bytes) -> None:
    """`data` into `path` by write-then-rename, the file made with mode 0600 (on Windows a mode is only the read-only flag: the file is
    copied to the pulling host, which keeps it root-only)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(str(tmp), 0o600)
    os.replace(str(tmp), str(path))


def cmd_ecr_config(t: Twin, out_value: str) -> int:
    """The pulling host's file for sdv/cloud/ecrlogin.py and the updater's --registry-file: the credential endpoint, the role alias,
    the region and the registry host, as JSON, outside every work tree, mode 0600. Nothing of its content is printed: the endpoint's
    prefix and the registry's account are identifiers (D7: the account id stands in this one file per pulling host)."""
    n = t.n
    out = Path(os.path.abspath(os.path.expanduser(out_value)))
    why = REDACT.in_a_work_tree(out)
    if why:
        refuse("inside-a-work-tree", "the pulling host's file would lie %s: it stays outside every work tree (nothing was read or written)" % why)
    if t.state.status("role-alias") != "created":
        refuse("ecr-config-needs-role-alias", "the step role-alias is not recorded as made and proven (TWIN_PULL_ROLE, then apply role-alias): "
               "the file would name an alias that nothing stands behind; nothing was read or written")
    require_caller(t)
    host = str((t.aws.read(c_credential_endpoint(), "ecr-config") or {}).get("endpointAddress", ""))
    if not CREDENTIAL_HOST.fullmatch(host):
        refuse("endpoint-unreadable", "the reply names no host of the credential provider's form (<prefix>.credentials.iot.<region>."
               "amazonaws.com); the value is not printed; nothing was written")
    doc = {"credential_endpoint": host, "role_alias": ROLE_ALIAS, "region": n.region, "registry": n.registry}
    write_private(out, (json.dumps(doc, indent=1) + "\n").encode("ascii"))
    say("ecr-config: the pulling host's file is written, mode 0600, at %s; its content is not printed (the credential endpoint, the role "
        "alias, the region and the registry host, which holds the account): copy it to the host, root-only." % out)
    return EXIT_OK


# --- branch-scan (gap ab): the one command that runs git

def _git(repo: Path, *args: str) -> bytes:
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    try:
        done = subprocess.run(["git", "-C", str(repo), "-c", "core.quotepath=off"] + list(args), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, env=env, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as e:
        refuse("git-failed", "git could not be run (%s); in WSL it is never run on this work tree" % type(e).__name__)
    if done.returncode != 0:
        refuse("git-failed", "git %s failed (exit %d)" % (args[0], done.returncode))
    return done.stdout


def cmd_branch_scan(state_dir: Path, repo: Path, base: str, rev: str, record: Optional[str]) -> int:
    """Each literal of the state: in the files git tracks or does not ignore; in the patches of base..rev; in their
    commit messages; and in the record commit, when one is named. Prints kinds, positions and counts, never a value."""
    for name in (base, rev, record or "HEAD"):
        if not re.fullmatch(r"[A-Za-z0-9._/~^-]{1,200}", name) or name.startswith("-"):
            refuse("revision-invalid", "a revision is not a name git takes here")
    REDACT.load_literals(state_dir)
    kinds = json.loads((state_dir / REDACT.LITERALS_FILE).read_text(encoding="utf-8"))["literals"]
    OUT.use(kinds)
    needles = [(kind, i, value.encode("utf-8")) for kind in sorted(kinds) for i, value in enumerate(kinds[kind], 1)]
    hits: Dict[Tuple[str, int, str], Set[str]] = {}

    def look(where: str, what: str, data: bytes) -> None:
        for kind, i, needle in needles:
            if needle in data:
                hits.setdefault((kind, i, where), set()).add(what)

    files = [f for f in _git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard").decode("utf-8", "replace").split("\0") if f]
    for rel in files:
        try:
            look("files", rel, (repo / rel).read_bytes())
        except OSError:
            continue
        look("file names", rel, rel.encode("utf-8"))
    commits = [c for c in _git(repo, "rev-list", "%s..%s" % (base, rev)).decode("ascii", "replace").split() if c]
    if record:
        commits += [c for c in _git(repo, "rev-list", "-1", record).decode("ascii", "replace").split() if c and c not in commits]
    for commit in commits:
        look("commit messages", commit[:12], _git(repo, "show", "-s", "--format=%B%n%an%n%ae%n%cn%n%ce", commit))
        look("history", commit[:12], _git(repo, "show", "--format=", "--no-color", "--no-ext-diff", "--no-textconv", "-m", "--text", commit))
    say("branch-scan: %d literal(s) of %d kind(s); %d file(s); %d commit(s) of %s..%s%s"
        % (len(needles), len(kinds), len(files), len(commits), base, rev, " and the record commit" if record else ""))
    for (kind, i, where), what in sorted(hits.items()):
        say("  FOUND value %d of the kind %s in %s: %d (%s)" % (i, kind, where, len(what), ", ".join(sorted(what)[:8])), err=True)
    if hits:
        say("branch-scan: NOT clean. A literal that one commit added and the next removed is still in the history.", err=True)
        return EXIT_REFUSED
    say("branch-scan: clean (the files, the history's patches, the commit messages).")
    return EXIT_OK


# --- exit-checks (A5)

def _monitor_prefix() -> str:
    """The excluded branch's prefix, from the stack's own module: it is spelled in no file of this directory."""
    return str(_by_file("_sdv_stack_attribution", REPO / "sdv" / "stack" / "attribution.py").MONITOR_PREFIX)


def _allowlist() -> Tuple[Set[str], Set[str]]:
    doc = json.loads((REPO / "sdv" / "connector" / "twin_allowlist.json").read_text(encoding="utf-8"))
    paths = {str(e["path"]) for e in doc["entries"]}
    return paths, {str(e["path"]) for e in doc["entries"] if "S" in e.get("channels", [])}


def exit_checks(t: Twin, min_vss_keys: int, athena_paths: Optional[Path]) -> List[Tuple[str, str, Dict[str, Any]]]:
    """A5's table: (check, pass | FAIL | not-run, the result as counts and shapes). Read-only."""
    n, aws = t.n, t.aws
    out: List[Tuple[str, str, Dict[str, Any]]] = []

    def add(name: str, ok: Optional[bool], **shape: Any) -> None:
        out.append((name, "not-run" if ok is None else ("pass" if ok else "FAIL"), shape))

    block = _policy_of(aws.read(c_account_block(t)), "PublicAccessBlockConfiguration") or {}
    shape = {"true": sum(1 for v in block.values() if v is True)}
    # The check passes only on the twin's own region. The second read is there so that a late region is not taken for
    # a setting that is absent. The twin's region is never GLOBAL_REGION (names-region-not-taken), so the second read
    # is always another read. This is a read strategy, not a consistency or propagation-time guarantee.
    east = _policy_of(aws.read(c_account_block(t, GLOBAL_REGION)), "PublicAccessBlockConfiguration") or {}
    shape["true_read_through_us_east_1"] = sum(1 for v in east.values() if v is True)
    add("account-level Block Public Access", len(block) == 4 and all(v is True for v in block.values()), **shape)
    status = aws.read(R("s3api", "get-bucket-policy-status", "--bucket", n.bucket))
    add("the bucket's policy status", _policy_of(status, "PolicyStatus", "IsPublic") is False, read=status is not None)
    groups = (aws.read(C_SECURITY_GROUPS) or {}).get("SecurityGroups", []) or []
    world, cidr_rules, ssh32 = 0, 0, 0
    for g in groups:
        for p in g.get("IpPermissions", []) or []:
            ranges = [str(x.get("CidrIp")) for x in p.get("IpRanges", []) or []] + [str(x.get("CidrIpv6")) for x in p.get("Ipv6Ranges", []) or []]
            for c in ranges:
                cidr_rules += 1
                world += 1 if c in ("0.0.0.0/0", "::/0") else 0
                ssh32 += 1 if (c.endswith("/32") and p.get("IpProtocol") == "tcp" and p.get("FromPort") == 22 and p.get("ToPort") == 22) else 0
    add("security groups", world == 0 and cidr_rules == 1 and ssh32 == 1, groups=len(groups), cidr_rules=cidr_rules, open_to_the_world=world,
        tcp_22_from_one_address=ssh32)
    authorizers = (aws.read(C_AUTHORIZERS) or {}).get("authorizers", []) or []
    add("IoT authorizers", not authorizers, count=len(authorizers))
    domains = (aws.read(C_DOMAINS) or {}).get("domainConfigurations", []) or []
    # The default endpoints have configurations of their own: A5 (2026-10-16) listed iot:Data-ATS and
    # iot:CredentialProvider in an account with no custom domain. A name with a colon is one no customer can make:
    # CreateDomainConfiguration takes [\w.-]+, while a listing's names are [\w.:-]+ (the API reference). So a custom
    # domain is a listed configuration whose name has no colon; an entry without a name of its own counts as one.
    custom = [d for d in domains if not (isinstance(d, dict) and isinstance(d.get("domainConfigurationName"), str)
                                         and ":" in d["domainConfigurationName"])]
    add("IoT domain configurations", not custom, listed=len(domains), custom=len(custom))
    pools = (aws.read(C_POOLS) or {}).get("IdentityPools", []) or []
    add("Cognito identity pools", not pools, count=len(pools))
    fp = t.render(t.step("function-policy"), strict=False)
    present, diffs = observe(t, fp)
    urls = (aws.read(R("lambda", "list-function-url-configs", "--function-name", n.function)) or {}).get("FunctionUrlConfigs", []) or []
    add("the function: no URL, one statement per breaker alarm", present and not diffs and not urls, urls=len(urls), policy_as_rendered=present
        and not diffs)
    rule = _policy_of(aws.read(R("iot", "get-topic-rule", "--rule-name", n.rule)), "rule") or {}
    actions = rule.get("actions", []) or []
    add("the rule's actions", len(actions) == 1 and list(actions[0]) == ["firehose"], actions=len(actions),
        kinds=sorted({k for a in actions for k in a}))
    roles_ok, roles = True, 0
    for step in t.steps:
        if step.kind != "owner" or not step.id.endswith("-role"):  # the owner-made roles: an adopted log group has no trust policy
            continue
        roles += 1
        rd = t.render(step, strict=False)
        got = aws.read(rd.built.reads[0][1])
        roles_ok = roles_ok and canon_policy(_policy_of(got, "Role", "AssumeRolePolicyDocument")) == canon_policy(rd.render.obj(step.id + "-trust"))
    topic_ok: Optional[bool] = None
    if n.notice:
        present, diffs = observe(t, t.render(t.step("notice-topic"), strict=False))
        topic_ok = present and not diffs
    rest = (aws.read(C_REST_APIS) or {}).get("items", []) or []
    http = (aws.read(C_HTTP_APIS) or {}).get("Items", []) or []
    add("the topic's policy, the roles' trust policies, no API", roles_ok and topic_ok is not False and not rest and not http,
        roles_read=roles, trusts_as_rendered=roles_ok, topic_policy_as_rendered=topic_ok, apis=len(rest) + len(http))
    top = aws.read(c_objects(t, top=True)) or {}
    prefixes = sorted(str(p.get("Prefix")) for p in top.get("CommonPrefixes", []) or [])
    loose = len(top.get("Contents", []) or [])
    add("the bucket's top-level prefixes", set(prefixes) <= {"telemetry/", "errors/", "athena-results/"} and not loose, prefixes=prefixes,
        objects_outside_a_prefix=loose)
    # S11: first the reads are not empty, then every key is on the allowlist and none lies under the excluded branch
    paths, shadow_paths = _allowlist()
    excluded = _monitor_prefix()
    keys: Dict[str, List[str]] = {}
    for shadow in SHADOWS:
        call = c_shadow_read(t, shadow)
        outfile = Path(call.args[-1])
        if outfile.exists():
            outfile.unlink()
        got = aws.read(call)
        try:
            reported = json.loads(outfile.read_text(encoding="utf-8"))["state"]["reported"] if got is not None else {}
        except (OSError, ValueError, KeyError, TypeError):
            reported = {}
        keys[shadow] = sorted(str(k) for k in reported) if shadow == "vss" else sorted(str(p) for p in reported.get("paths", []) or [])
    everything = keys["vss"] + keys["config"]
    under = sum(1 for k in everything if k.startswith(excluded))
    s11 = (len(keys["vss"]) >= max(1, min_vss_keys) and set(keys["vss"]) <= shadow_paths and set(keys["config"]) <= paths
           and not under)
    add("S11: the shadows' keys", s11, vss_keys=len(keys["vss"]), config_paths=len(keys["config"]), least_expected=max(1, min_vss_keys),
        outside_the_allowlist=len(set(keys["vss"]) - shadow_paths) + len(set(keys["config"]) - paths),
        under_the_excluded_branch=under)
    if athena_paths is None:
        add("S11: Athena's distinct paths", None, why="the session's query result was not given (--athena-paths)")
    else:
        try:
            distinct = [str(x) for x in json.loads(athena_paths.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError):
            distinct = []
        add("S11: Athena's distinct paths", bool(distinct) and set(distinct) <= paths and not [p for p in distinct if p.startswith(excluded)],
            paths=len(distinct), outside_the_allowlist=len(set(distinct) - paths),
            under_the_excluded_branch=sum(1 for p in distinct if p.startswith(excluded)))
    if n.ecr:
        out += ecr_exit_checks(t)
    if n.pull_role:
        out += pull_exit_checks(t)
    return out


def ecr_exit_checks(t: Twin) -> List[Tuple[str, str, Dict[str, Any]]]:
    """Phase 6's ECR rows of the exit (spec 5 item 6; prep section 7: ECR's repository policy gives no cross-account or anonymous
    access, and ECR Public holds nothing): read-only, each a count or a shape."""
    n, aws = t.n, t.aws
    out: List[Tuple[str, str, Dict[str, Any]]] = []

    def add(name: str, ok: bool, **shape: Any) -> None:
        out.append((name, "pass" if ok else "FAIL", shape))

    ours = [x for x in (aws.read(listing_of("repositories")[0]) or {}).get("repositories", []) or []
            if isinstance(x, dict) and str(x.get("repositoryName", "")).startswith(ECR_NAMESPACE + "/")]
    names = sorted(str(x.get("repositoryName")) for x in ours)
    with_policy = sum(1 for name in names if aws.read(R("ecr", "get-repository-policy", "--repository-name", name)) is not None)
    add("ECR: no repository policy on a sdv-twin/ repository", not with_policy, repositories=len(names), with_a_policy=with_policy)
    registry_policy = aws.read(R("ecr", "get-registry-policy"))
    add("ECR: no registry policy", registry_policy is None, policy=registry_policy is not None)
    rules = _policy_of(aws.read(R("ecr", "describe-registry")), "replicationConfiguration", "rules") or []
    cache = (aws.read(R("ecr", "describe-pull-through-cache-rules")) or {}).get("pullThroughCacheRules", []) or []
    scan = _policy_of(aws.read(R("ecr", "get-registry-scanning-configuration")), "scanningConfiguration", "scanType")
    add("ECR: no replication rule and no pull-through cache rule", not rules and not cache, replication_rules=len(rules),
        pull_through_cache_rules=len(cache), scan_type=scan if isinstance(scan, str) and re.fullmatch(r"[A-Z_]{1,32}", scan) else "(not in its form)")
    public = (aws.read(R("ecr-public", "describe-repositories", "--region", GLOBAL_REGION)) or {}).get("repositories", []) or []
    add("ECR Public holds no repository", not public, count=len(public))
    immutable = sum(1 for x in ours if x.get("imageTagMutability") == "IMMUTABLE")
    aes = sum(1 for x in ours if _policy_of(x, "encryptionConfiguration", "encryptionType") == "AES256")
    add("ECR: the repositories are exactly the expected ones, IMMUTABLE, AES256",
        names == sorted(n.repositories) and immutable == len(ours) and aes == len(ours), expected=len(n.repositories), listed=len(names),
        immutable=immutable, aes256=aes)
    return out


def pull_exit_checks(t: Twin) -> List[Tuple[str, str, Dict[str, Any]]]:
    """Phase 6's pull-identity rows of the exit (spec 5 item 6): the pull role's trust and policy, the alias, the pull policy, each
    as rendered (their steps' own judges), and the pull certificate carrying the pull policy and no other."""
    n = t.n
    out: List[Tuple[str, str, Dict[str, Any]]] = []

    def judged(name: str, step_id: str) -> None:
        present, diffs = observe(t, t.render(t.step(step_id), strict=False))
        out.append((name, "pass" if present and not diffs else "FAIL", {"read": present, "as_rendered": present and not diffs}))

    judged("the pull role: its trust and its policy as rendered", "pull-role")
    judged("the role alias: the pull role, %d s" % ROLE_ALIAS_SECONDS, "role-alias")
    judged("the pull policy as rendered", "pull-policy")
    cert = t.state.fact("pull_certificate_id")
    if cert is None:
        out.append(("the pull certificate carries the pull policy and no other", "not-run", {"why": "the state holds no pull certificate"}))
    else:
        attached = sorted(str(p.get("policyName")) for p in
                          (t.aws.read(R("iot", "list-attached-policies", "--target", n.arn("iot", "cert/" + cert))) or {}).get("policies", []) or [])
        out.append(("the pull certificate carries the pull policy and no other", "pass" if attached == [n.pull_policy] else "FAIL",
                    {"policies": len(attached), "the_pull_policy": n.pull_policy in attached}))
    return out


def cmd_exit_checks(t: Twin, capture: Path, min_vss_keys: int, athena_paths: Optional[Path]) -> int:
    if capture.exists() and any(capture.iterdir()):
        refuse("capture-not-empty", "the capture directory holds something: captures are not mixed")
    results = exit_checks(t, min_vss_keys, athena_paths)
    staging = t.state_dir / "exit-checks"
    if staging.exists():
        for old in staging.iterdir():
            old.unlink()
    summary = {"v": 1, "at": now(), "checks": [{"check": name, "result": verdict, "shape": shape} for name, verdict, shape in results],
               "separate": ["the tree-side test (tests/test_no_real_identifiers.py)", "twinctl branch-scan"]}
    write_atomic(staging / "exit-checks.json", dump(summary).encode("ascii"))
    try:
        REDACT.copy_tree(staging, capture, OUT.literals)
        left = REDACT.scan(capture, OUT.literals)
    except REDACT.RedactError as e:
        refuse("capture-refused", "the redactor refuses the capture (%s): a stop, not a retry" % e)
    for name, verdict, shape in results:
        say("  %-8s %s  %s" % (verdict, name, json.dumps(shape, sort_keys=True)))
    say("  %-8s the leak scan of the capture (%d finding(s))" % ("pass" if not left else "FAIL", len(left)))
    bad = [name for name, verdict, _shape in results if verdict != "pass"]
    if bad or left:
        say("exit-checks: NOT met: %d check(s) did not pass or did not run. The tree-side test and `twinctl branch-scan` are separate."
            % (len(bad) + (1 if left else 0)), err=True)
        return EXIT_REFUSED
    say("exit-checks: every read-only check passed; the capture is %s. The tree-side test and `twinctl branch-scan` are separate." % capture)
    return EXIT_OK


# --------------------------------------------------------------------------------------------------- the command line

class _Unreadable(Exception):
    pass


def typed_state(words: Sequence[str]) -> str:
    """The state directory a command line names by `--state DIR` or `--state=DIR`, read from its words: for a line that
    could not be read as a whole (an option after the command's word, a misspelt one beside it), whose options argparse
    gives nobody. The last one typed, as argparse takes it; "" when there is none."""
    found = ""
    for i, word in enumerate(words):
        if word == "--state" and i + 1 < len(words):
            found = words[i + 1]
        elif word.startswith("--state="):
            found = word[len("--state="):]
    return found


UNRECOGNIZED = "unrecognized arguments: "
AMBIGUOUS_OPTION = "ambiguous option: "
# a word argparse quotes as Python does (in single quotes, or in double ones when it holds a single quote; a backslash escapes),
# after the two forms that quote one: a value it calls invalid, and an argument given by `=` to an option that takes none
QUOTED_WORD = re.compile(r"(invalid [A-Za-z ]{1,40}: |ignored explicit argument )(?:'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")")


def said_unreadable(message: str) -> str:
    """What is printed of argparse's own message for a line it could not read. It quotes the words that were typed, and at
    this point no literal is loaded that could mask one (a state directory typed after the command's word, a profile's
    name after an option nobody knows). Of `unrecognized arguments: ...` the OPTIONS' names stay, cut at `=`, and every
    other word is counted and not printed; of `ambiguous option: ...` the option as typed is cut at `=` too; a word it
    calls invalid, and an argument it says an option ignored, are not printed either. The command's own words (the
    choices it lists, the options an ambiguous one could match) stay."""
    if message.startswith(UNRECOGNIZED):
        words = message[len(UNRECOGNIZED):].split(" ")
        options = [w.split("=", 1)[0] for w in words if w.startswith("-")]
        rest = len(words) - len(options)
        return (UNRECOGNIZED + " ".join(options) + (" and " if options and rest else "")
                + ("%d word(s) that are not printed" % rest if rest else "") + "; no value typed is printed")
    if message.startswith(AMBIGUOUS_OPTION):
        # the option as typed, " could match ", the options' names: what follows its `=` may hold those words too
        said = message[len(AMBIGUOUS_OPTION):]
        typed, sep, matches = said.rpartition(" could match ")
        name = re.split(r"[=\s]", said, maxsplit=1)[0]
        if sep and typed == name:
            return message
        return AMBIGUOUS_OPTION + name + "=(the word is not printed)" + (" could match " + matches if sep else "")
    return QUOTED_WORD.sub(lambda m: m.group(1) + "(the word is not printed)", message)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _Unreadable(message)


def parser() -> argparse.ArgumentParser:
    ap = _Parser(prog="twinctl.py", description="The twin's create and teardown driver. Everything it prints is redacted; state, renders "
                                                "and captures live outside every work tree.")
    ap.add_argument("--state", metavar="DIR", help="the state directory (default: TWIN_STATE)")
    ap.add_argument("--render", metavar="DIR", help="the render directory (default: TWIN_RENDER, else <state>/render)")
    ap.add_argument("--rehearsal", action="store_true", help="A2's set: the kinds that need no service role, under rehearsal names")
    sub = ap.add_subparsers(dest="command", required=True, parser_class=_Parser)
    sub.add_parser("literals")
    sub.add_parser("build-breaker")
    rc = sub.add_parser("recover")
    rc.add_argument("step")
    rc.add_argument("--approve", metavar="STEP:HASH")
    b = sub.add_parser("baseline")
    b.add_argument("--again", action="store_true")
    p = sub.add_parser("plan")
    p.add_argument("--no-cli", action="store_true", help="check the documents only; the calls are not given to the CLI")
    a = sub.add_parser("apply")
    a.add_argument("step")
    a.add_argument("--approve", metavar="STEP:HASH")
    sub.add_parser("status")
    tr = sub.add_parser("trip")
    tr.add_argument("--capture", metavar="DIR")
    sub.add_parser("restore")
    td = sub.add_parser("teardown")
    td.add_argument("step", nargs="?")
    td.add_argument("--approve", metavar="STEP:HASH")
    vg = sub.add_parser("verify-gone")
    vg.add_argument("step", nargs="?")
    bs = sub.add_parser("branch-scan")
    bs.add_argument("--repo", metavar="DIR", help="the checkout to search (default: this one)")
    bs.add_argument("--base", default="fb407adc", help="the history is searched after this commit")
    bs.add_argument("--rev", default="HEAD")
    bs.add_argument("--record", help="the record commit, on its own branch")
    ec = sub.add_parser("exit-checks")
    ec.add_argument("--capture", metavar="DIR", required=True)
    ec.add_argument("--min-vss-keys", type=int, default=1)
    ec.add_argument("--athena-paths", metavar="FILE")
    pu = sub.add_parser("push", help="an image into the twin's repository by digest (Phase 6)")
    pu.add_argument("--app", required=True, choices=list(ECR_APPS))
    pu.add_argument("--version", required=True, metavar="X.Y.Z")
    pu.add_argument("--arch", required=True, choices=["arm64"])
    pu.add_argument("--store-id", required=True, metavar="ID")
    pu.add_argument("--config-digest", required=True, metavar="CFG")
    pu.add_argument("--docker", default="docker", metavar="PREFIX", help="docker's argv prefix, split as a POSIX shell splits words")
    pu.add_argument("--approve", metavar="push:HASH")
    ecf = sub.add_parser("ecr-config", help="the pulling host's file (Phase 6)")
    ecf.add_argument("--out", metavar="FILE", required=True)
    return ap


def stop_literals(t: Twin) -> Dict[str, List[str]]:
    """What a stop is redacted with when the literals file cannot be used: the names file's and the state's own values,
    LESS ANY THE REDACTOR CANNOT TAKE AS A LITERAL (a value one of its masks spells, the kinds' own among them: a role
    renamed to `operator-role`). `twinctl literals` refuses such a name when a twin is set up; a stop is not held to
    the role or the profile, so it can meet one that never went through that check, and it is not ended by a name it
    only has to keep off the terminal. Such a value is a word the redactor itself writes: it is not masked."""
    own = t.own_literals()
    try:
        # A FILE THAT CAN BE READ AND IS ONLY BEHIND STILL GIVES ITS KINDS, the owner's own among them (a name that must never
        # leave this machine, a kind added by hand: neither the names file nor the state holds those). Under another role
        # or profile the file is always behind, and a stop then printed such a value. A file the redactor does not take
        # gives nothing.
        REDACT.load_literals(t.top)
        held = json.loads((t.top / REDACT.LITERALS_FILE).read_text(encoding="utf-8"))["literals"]
        for kind in sorted(held):
            own[kind] = list(dict.fromkeys(own.get(kind, []) + [v for v in held[kind] if isinstance(v, str)]))
    except (REDACT.RedactError, OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    masks = set(REDACT.MASKS) | {"<%s>" % kind for kind in own} | {"<local>"}
    kept = {kind: [v for v in values if _usable_literal(v, masks)] for kind, values in own.items()}
    return {kind: values for kind, values in kept.items() if values}


# The commands whose every run reads the account and changes nothing in it: the caller's identity is their first call.
# `apply`, `teardown`, `recover` and `trip` read it themselves, before their first call, and only where they send one (a
# render that is only printed sends nothing); `plan`, `literals`, `build-breaker` and `branch-scan` send no call at all.
READS_THE_CALLER_FIRST = ("baseline", "status", "restore", "verify-gone", "exit-checks")


def run(args: argparse.Namespace) -> int:
    state_value = args.state or os.environ.get("TWIN_STATE", "")
    if args.command == "trip":
        # THE STOP'S FILE COMES FIRST: before the first line below that can refuse, so that no ending of a trip leaves the
        # owner with a refusal and no calls. It never refuses and never raises.
        hand_first(state_value, bool(args.rehearsal))
    if not state_value:
        refuse("state-unset", "no state directory: --state DIR or TWIN_STATE, a directory outside every work tree")
    state_dir = outside(state_value, "state directory")
    OUT.name(state_dir, "<state>")
    render_value = args.render or os.environ.get("TWIN_RENDER", "")
    render_dir = outside(render_value, "render directory") if render_value else None
    OUT.name(render_dir if render_dir is not None else state_dir / "render", "<render>")
    if args.command == "branch-scan":
        return cmd_branch_scan(state_dir, Path(args.repo) if args.repo else REPO, args.base, args.rev, args.record)
    capture = None
    if getattr(args, "capture", None):
        capture = outside(args.capture, "capture directory")
        OUT.name(capture, "<capture>")
    state_dir.mkdir(parents=True, exist_ok=True)
    t = Twin(state_dir, render_dir, args.rehearsal, stop=args.command == "trip")
    for key in PATH_KEYS:
        if key in t.n.v:
            OUT.name(os.path.expanduser(t.n.v[key]), "<%s>" % key.lower().replace("twin_", "").replace("_", "-"))
    hold_names(t, args.command, bool(getattr(args, "again", False)))
    if args.command == "literals":
        t.write_literals()
        return EXIT_OK
    try:
        t.load_literals()
    except TwinError as e:
        if args.command != "trip":
            raise
        # the stop is not refused for a literals file: what it prints is redacted with the names file's and the state's own
        # values, which is what the file would hold of them; the file itself is `twinctl literals`' to write
        OUT.use(stop_literals(t))
        t.lacks.append("the literals file is missing or behind (%s): this stop goes on with the names file's and the state's own "
                       "values; `twinctl literals` writes the file" % e.name)
    if args.command in READS_THE_CALLER_FIRST:
        require_caller(t)
    if args.command == "build-breaker":
        return cmd_build_breaker(t)
    if args.command == "recover":
        return cmd_recover(t, args.step, args.approve)
    if args.command == "baseline":
        return cmd_baseline(t, args.again)
    if args.command == "plan":
        return cmd_plan(t, args.no_cli)
    if args.command == "apply":
        return cmd_apply(t, args.step, args.approve)
    if args.command == "status":
        return cmd_status(t)
    if args.command == "trip":
        return cmd_trip(t, capture)
    if args.command == "restore":
        return cmd_restore(t)
    if args.command == "teardown":
        return cmd_teardown(t, args.step, args.approve)
    if args.command == "verify-gone":
        return cmd_verify_gone(t, args.step)
    if args.command == "exit-checks":
        assert capture is not None
        return cmd_exit_checks(t, capture, args.min_vss_keys, Path(args.athena_paths) if args.athena_paths else None)
    if args.command == "push":
        return cmd_push(t, args.app, args.version, args.arch, args.store_id, args.config_digest, args.docker, args.approve)
    if args.command == "ecr-config":
        return cmd_ecr_config(t, args.out)
    raise _Unreadable("no such command")


def stop_by_hand(command: str, refusal: str = "") -> None:
    """A trip that ended before its invoke: the manual stop's four calls once more, LAST, so that the stop is never only a
    refusal. The file of them was written, and its place said, before the refusal was said (hand_first()); here it is
    named again. With no file (hand_first() said why, or the command line could not be read at all) the keys the slots
    are made of are said instead. Nothing printed here holds a value."""
    if command == "trip" and not INVOKED:
        say("trip was refused before the function was invoked. THE SAME FOUR CALLS BY HAND (sdv/cloud/README.md), under the operator "
            "profile, with the twin's own names:", err=True)
        for line in STOP_BY_HAND:
            say("  " + line, err=True)
        if HAND is not None:
            say("With %s's own values, as far as the names file and the state give them, they are in %s (written before this "
                "refusal was said)." % (HAND_FOR, HAND), err=True)
        else:
            say(HAND_KEYS, err=True)
        no_cli = console_way(refusal)
        if no_cli:
            say(no_cli, err=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    global OUT, INVOKED, HAND
    OUT = Out()
    INVOKED = False
    HAND = None
    state_dir = None
    command = ""
    try:
        args = parser().parse_args(argv)
        command = str(args.command)
        state_dir = args.state or os.environ.get("TWIN_STATE", "")
        return run(args)
    except _Unreadable as e:
        # A STOP THAT WAS MISTYPED is not left with a refusal alone either: a command line that names `trip` and cannot be read
        # gets the file first, as far as the environment names a state directory (an option of a line that cannot be read is
        # not read), then the refusal, then the four calls once more.
        words = [str(a) for a in (sys.argv[1:] if argv is None else argv)]
        typed = typed_state(words)                                  # the line's own state directory comes before the environment's
        if "trip" in words:
            hand_first(typed or os.environ.get("TWIN_STATE", ""), "--rehearsal" in words)
        say("twinctl: the command line cannot be read (%s); --help lists the commands" % said_unreadable(str(e)), err=True)
        if "trip" in words:
            stop_by_hand("trip")
        return EXIT_USAGE
    except TwinError as e:
        say("twinctl: refused: %s: %s" % (e.name, e.detail), err=True)
        stop_by_hand(command, e.name)
        return e.status
    except REDACT.RedactError as e:
        say("twinctl: refused: redaction: %s" % e, err=True)
        stop_by_hand(command)
        return EXIT_REFUSED
    except Exception as e:                                           # noqa: BLE001 - the last net: a refusal, and no trace on the terminal
        where = ""
        try:
            if state_dir and not REDACT.in_a_work_tree(Path(os.path.abspath(os.path.expanduser(state_dir))) / "x"):
                log = Path(os.path.abspath(os.path.expanduser(state_dir))) / "twinctl-error.log"
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text(traceback.format_exc(), encoding="utf-8")
                where = "; its trace is in the state directory (twinctl-error.log)"
        except OSError:
            pass
        say("twinctl: stopped on an error no check names (%s)%s. Nothing more was done." % (type(e).__name__, where), err=True)
        stop_by_hand(command)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
