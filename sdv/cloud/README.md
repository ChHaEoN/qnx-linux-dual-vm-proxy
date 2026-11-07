# sdv/cloud: the twin's account side

SDV Phase 4, the minimal cloud twin. This directory is the account side of
the twin: what creates, checks and removes the cloud resources the device side (`sdv/connector`) sends to.

Labels such as A3 row 13, B2, C9, D8 and the gap letters are the project's internal plan items; they are kept so that
the code and its tests can be read against that plan.

## What it is

The redactor, the driver and the breaker function. The work packages that filled it:

| file | state | what it is |
|---|---|---|
| `redact.py` | here (WP4) | What the driver prints and what it copies into a capture goes through it. It also runs the leak scanner over a capture, with the state directory's literals. |
| `twinctl.py`, `templates/`, `.env.example` | here (WP6, WP7) | The create and teardown driver: standard-library Python over the AWS CLI, one step per resource, a dry run that executes nothing, each step applied only with the approval the owner gave for that step. It builds the function's zip. |
| `breaker/breaker.py` | here (WP7) | The function an alarm invokes to cut the twin's traffic: one file, the standard library and the runtime's own SDK. It never restores. |
| `breaker/requirements-dev.lock` | here (WP7) | The SDK for the function's second test tier, pinned by hash, for one dev venv outside every work tree. Never CI's venv, an image or the zip. |
| `burst/burst.py`, `burst/burst_link.py`, `burst/Dockerfile` | here (the burst package) | The breaker's burst tool, test only: its own image, never pinned; `burst/README.md` says what it does and is bounded by. |
| `twinctl.py` (the ECR and pull steps, `push`, `ecr-config`), `ecrlogin.py` | here (Phase 6 WP4) | The account side of the image transport: the twin's private repositories, the Orin's pull identity through the IoT credential provider, the push by digest, and the pulling host's login. Below, "Phase 6: the image transport". |

The Phase 4 CI recipe type-checks this directory.

## The driver (`twinctl.py`)

Every call is an argv list handed to the AWS CLI with no shell. Every JSON document a call needs is a file
of `templates/` with `@@NAME@@` placeholders: rendered, parsed back, checked, written to the render
directory and passed as `file://`. **One step table** drives every command: per step its id and its row of
the plan, the create calls, the reads that prove it, the delete calls, what it stands on, its listing, and
whether the owner makes it by hand (the five roles). One step can be adopted instead of made: IoT's own
log group, which the service makes itself once logging was ever on in the region. If it is there before the
twin, `apply` refuses it as not ours and names the owner's choice: delete it by hand, or keep it and set
`TWIN_IOT_LOG_GROUP_ADOPT=1`, after which the step only reads it and the driver never creates or deletes it.

| command | what it does |
|---|---|
| `literals` | Writes `<state>/literals.json` for the redactor. Prints nothing. Refuses a value under 8 characters and one that a search of this work tree already finds, by its position. |
| `build-breaker` | Builds the function's zip from `breaker/breaker.py` into the file `TWIN_BREAKER_ZIP` names, outside every work tree: one entry under the name the handler asks for, stored, with a fixed time and mode, so two builds give the same bytes under any Python. Prints its sha256, in hex and in the form the service reports a function's code in. Refuses a source with a carriage return, one with no handler and one that holds a literal of the state. Sends no call. The zip is held to the source: `apply function` refuses one that is not this build of the source as it stands. |
| `baseline` | Stores what every listing returns, before the first create. |
| `plan [--no-cli]` | Renders every call of every step and every call a command sends outside the table, checks every document, and gives each call to the CLI to read offline. Holds the operator role's rendered policy to every call it lists; with `--rehearsal`, whose table holds no role, the twin's policy is rendered from the same names, written nowhere, and held to the rehearsal's calls, which are sent under that role too. For a call whose sample reply fails the CLI's own validation only the options' names, the required options and each value's form were read, and `plan` names such calls by service and operation. Executes nothing. A step whose zip is not the build of the source as it stands is refused by the name `zip-not-the-source`, as apply refuses it. |
| `apply STEP` | Prints the step's calls and documents, redacted, with the render's sha256, and stops. With `--approve STEP:HASH`: the caller must be an assumed session of the operator role; read (what exists and is not ours is refused); create; read back and compare; record. One printing lets one run of the calls through. A step recorded as being deleted is not made again before `verify-gone STEP`, or its teardown run again, recorded it as deleted. Before a certificate is created its listing is read: a name there that neither the baseline nor a state knows, and nothing is created. |
| `status` | The proving reads of every step as states, never values; each alarm's state, whether its actions are enabled and what they target; the function's reserved concurrency. Fails when the function's certificates are not exactly the twin's, or an ACTIVE certificate of the account is outside the twin's set. A read that is denied is said in its place and stops neither assertion; a read an assertion stands on, denied, fails it. A step that has no read at all (no id in the state) is said so, never "not found". A go-live step whose rule or certificate is read and is not live says `not live (tripped, or not made live)`: what a trip leaves is there. The function's code is held to the sha256 the state recorded when it was made. Says beside the function's line when the breaker's source has changed since the build the function was made from, or cannot be built: a word, no failure (the account runs what was approved). After the alarms' lines it prints the sha256 of the thresholds file the alarms are rendered from (`TWIN_THRESHOLDS`, as it stands): the burst tool is given that hash as `--thresholds-sha256` and refuses any other file (`burst/README.md`). A hash of the file's bytes, never a count of it. |
| `trip` | Invokes the function with the manual trip, then `status`. No approval: stopping is the safe direction. Its first act is the file of the four calls by hand, `<state>/trip-by-hand.txt`, written before anything of the trip can be refused: for this twin, as far as the names file and the state give them. A call that lacks a value is a comment there, each open slot is said by the key its value comes from, and the certificate's id is taken from the state only when the state was made under the account, region, prefix and thing the names file gives now (a state that records no names yet, one made before its first write or one whose entry `names` was taken out on the salt-missing advice, gives its certificate with no comparison). The file's place is printed; its content, which is unredacted, never is. It is not stopped by a literals file that is missing or behind, by a state that cannot be read, by an identity that cannot be read, or by another operator role or profile than the state was made under: it is held to the account only, and a caller of another account is refused. Nor is it stopped by another bucket suffix or notice's switch (the owner's A4 answers of 2026-10-16): no call of a stop is made of either. No ending of a trip is only a refusal: one that ends before its invoke holds the file already, the four calls are named once more after the refusal, and where no file could be written they are printed with their slots and the keys the slots are made of. A trip that ran prints what its record says each write was answered (below). `status` follows also when the invoke failed or ended in a function error: it is the proof for the calls by hand. An invoke that was throttled is said to have met a run of the function, which runs one invoke at a time: `status` is read first. An invoke that was sent and whose answer is not known (a reply that is no JSON, a CLI cut off) is said so: the function may have run, `status` follows, and the trip is not called refused before its invoke. The caller is read once more before a trip's status: when the profile now answers for another account, no status is printed (it would be that account's all-clear) and the trip ends as a refusal. The stop needs no operator role: a names file that lost `TWIN_OPERATOR_ROLE`, or gives it in a form the driver does not take, is said by the key and the trip goes on. In the file a call is written without `--profile` where the names file gives none in its form (the profile is then the shell's, as in the plan's own four calls), a comment gives the read that finds the certificate's id where the state does not give it, and a rehearsal's trip says in the file's head and on the terminal that the file is the rehearsal's set's (one file name serves both: a trip of the twin writes the twin's again). When the write could not take the file's place, the file it got as far as (`trip-by-hand.txt.tmp`) is named if it holds this run's calls whole. A command line that names `trip` and cannot be read gets the file too, in the state directory it names by `--state` or by `TWIN_STATE`; of the words it could not read only the options' names are printed, each as typed up to its `=`. With no CLI that runs, the plan's console way is named after the calls. |
| `restore` | Renders the three reverse calls and their proofs for the owner to run. Refused while a breaker alarm is missing, in ALARM, or has its actions disabled. |
| `teardown [STEP]` | The table in reverse, one approved step at a time, each with its precondition. Emptying the bucket is the step `bucket-objects`, approved for exactly what is listed at that moment. No file a create took its content from has to be there still. A render that stands on a value the state has lost (the certificate's id) is refused whatever it holds, and a step with nothing to read is never called "read back, not found". A create call whose reply was lost, or was an error, is not taken for one that never went through (below). |
| `recover STEP` | Puts the certificate's id back into a state that lost it, from a reply file the driver itself wrote under the state directory: never a typed id. Printed and approved like a step; it sends reads only. |
| `verify-gone [STEP]` | Read-only: nothing recorded is found by name, no listing holds a name the baseline lacks, the tag query is empty. A listing that says there is more of it is refused, here as in every read. A step that has no read at all is said so, never "not found". |
| `branch-scan` | Each literal of the state searched in the files git tracks or does not ignore, in the history's patches and in the commit messages. The one command that runs git. |
| `exit-checks` | The exit's read-only checks, each reduced to a count or a shape, redacted into a capture directory. |

`--rehearsal` gives the same commands the rehearsal's set: the kinds that need no service role, under the
prefix and two more letters, in a state of their own.

**The script cannot tell who typed an approval.** It checks that the approval names this step, that its
hash is the hash of the render as it is now, that this render was printed before, and that it has let no
run of calls through since it was last printed. A render that did not change has the same hash, so a step
that is created, deleted and created again is printed three times: the first approval, given again, is
refused, and so is a second run of an action. Reading a step again with the approval it was made with
sends nothing and is allowed. The rule stays outside the script: `--approve` is passed for a step only
after the owner said yes to that step.

**The files a create uploads.** The function's zip and the certificate's signing request are covered by their
content, not by their path: the file's sha256 is in the render's hash, is printed with the render and is
recorded in the state when the step is made. A file replaced after the printing is another render, and the
approval that was given is refused. The zip is also held to the source: when its sha256 is not that of the zip
`build-breaker` would write from `breaker/breaker.py` as it stands (built bytes against built bytes: no path,
no time), `apply function` prints the render with that word and without an approval line, records nothing as
shown, and refuses `zip-not-the-source`, with an approval or without; `twinctl build-breaker` builds it again.
The function is afterwards held to the recorded hash, whatever lies at the path then; `status` says beside it
when the zip at the path is no longer that one. A step that stands, printed and approved again with another
file at the path, is not answered "already made, as rendered": the render that was approved names a file the
step was not made from, `apply` says so and refuses, and the way to the new file is the step's teardown and a
new apply (after a rebuilt zip, the function's teardown comes before `function-status` and the dry trip are
run again). Not held: the file is read once for the hash and again by the CLI inside the one run that sends
the call. For the zip the read-back catches a change in between; for the signing request nothing does.

**A create whose reply is lost, or is an error.** Every create call is on record before it is sent, and it
stays there however it ended. A call whose reply was lost (a reply that is no JSON, a CLI that was cut off,
a run that ended there) is therefore not taken for one that never went through, and neither is a call the
service answered with an error: an error does not say that nothing was made (a 5xx can come after the work
was done), and which error codes are certain refusals is written from memory, so none is trusted. This
matters for the certificate alone, which is read by an id only a reply gives. With such a call on record
and no id:

- `apply certificate` is refused (half made), so no second certificate is made on top of the first;
- `teardown certificate` reads the certificates' listing. A name there that neither the baseline nor the
  state knows, and it is refused (`nothing-to-read`); none, and the record is taken back on that read. So a
  create that was only throttled costs two calls, the caller's identity and the listing, before its record
  is taken back; no record with a call on it is taken back unread;
- that verdict rests on one read of a listing, and whether a listing shows at once what was just made is
  not established. So `apply certificate` reads the same listing before it creates, and refuses
  (`listed-not-ours`) while it holds a name neither the baseline nor a state knows: no second certificate
  is made on top of one a lost create had made. What that one made is deleted by hand (below) before the
  step is applied again;
- when a reply file in the state directory holds the id (the state was put back from an older copy; the run
  ended between the reply and its record), `recover certificate` puts it back. The id comes from that file
  and from nowhere else, and it is recorded only once the account showed exactly one certificate the replies
  name, with its own reply's PEM, not in the baseline, and attached to the twin's thing when the state
  records the attachments;
- when no reply holds it, by hand: `verify-gone` lists what the account holds beyond the baseline; the
  certificate a lost create made is INACTIVE and attached to nothing, and is deleted in the console; the
  teardown above then takes the record back. `state.json` is not edited for this.

**Where things live.** The names file (`names.env`; `.env.example` here is its template), the literals,
the state, the baseline, the approvals, every raw reply, the renders and the file of the four calls by hand
that a trip writes (`trip-by-hand.txt`, unredacted) are in the state directory, outside every work tree. A
state, render or capture directory inside one is refused before anything is made, found by walking up for
`.git` and never by running git. `TWIN_REGION` is any region but one: `us-east-1` is refused where the
names are read (`names-region-not-taken`), by the key and never by the value, because the bucket's create
passes a LocationConstraint, which the service refuses for that region, and the exit's check of the
account's Block Public Access reads a second time through it.

**The caller.** Every command that sends a call reads the caller's identity first and is refused unless it
is an assumed session of the operator role the names file names, in the names file's account. That holds for
the commands that only read (`baseline`, `status`, `restore`, `verify-gone`, `exit-checks`, an owner-made
step's reads) as for the ones that write: a profile is repointed in the CLI's own configuration without any
approval, and a read that another account answers is a wrong verdict on this one. `trip` alone is held to
the account only and goes on when the identity cannot be read. The runner itself sends nothing but that one
read until it was made.

**The names a state was made under.** A render is printed with every name masked, so nothing the owner
approves shows which bucket a delete goes to. The state therefore records, as salted fingerprints, the
account, the region, the prefix, the thing and the bucket's suffix it was made under, and with them the
operator role, the profile and the notice's switch. Under any other value every command is refused by the
key's name, never by a value. One exception, the owner's decision of 2026-10-12: `trip` is not held to the
role or to the profile. Under another of either it goes on, under the profile the names file gives now, and
says so. Since the owner's A4 answers of 2026-10-16 the same holds for the bucket's suffix and the notice's
switch, of which no call of a stop is made. Under another account, region, prefix or thing it is refused like
every command, with its file of the four calls written first. After a trip under a renamed profile or role, `trip`
is the only command that runs: `status`, `restore` and `teardown` stay refused (`names-changed`) until the
names file gives the names of the state again, which for a profile means that the CLI's own configuration
answers under the old profile name once more. Until then the status that the trip itself printed is the one
proof at hand. When nothing is recorded as standing, `literals`
and then `baseline --again`
take new names, with a baseline of their own and no step recorded; the role and the profile are also in
every render's hash, so an approval printed under one is none under another. Row 19's three keys are not
bound, since they are given while the twin stands: once its alarm is recorded as made, its steps stay in
the table whatever the names file says. With the state directory's `salt` gone, every command is refused as
`salt-missing`; the driver's docstring says the way back.

**A record does not outlive what it stood on.** An action's `done` and an owner-made step's `verified` are
records of the function, the certificate and the alarms as they were then. When a step is deleted or made
anew, every such record that stands on it, directly or through other steps, becomes `stale`, and a step
that needs it is refused until it was applied again: go-live does not pass on a dry trip that another
function ran. An action's `done` is the record of its last run: applied again, a run that does not come to
its end (a call that fails, an invoke that ends in a function error, a reply that cannot be read) takes the
earlier record back to `stale`, with every record that stands on it, until the action ran to its end again.
A manual `trip` whose invoke ends in a function error takes the dry trip's `done` back the same way: it is a
run of the same invoke. An invoke the service refused changes no record, and a trip that ran clean puts none
back: `apply dry-trip` does.

**What a trip's record says of its writes.** `apply dry-trip` and `trip` print, from the function's own record
in the state directory, what each write was answered: the rule's disable, each certificate's deactivation and
detach, each connection's delete. Only a write word is printed (`ok`, `answered`, `answered:<code>`,
`refused`, `failed`, `not-attempted`, `no-client-connected`, `unavailable`), with counts; a record that holds
anything else in a word's place is said to be read by hand. The dry trip is where each API first shows what it
answers when its work is already done, and the function counts a write the service answered with an error as
done when its read-back shows the cut: that line is where it is seen. A run that ends in a function error is
said by the error's kind (the function's own `BreakerError`, or the runtime's) and by the name of the file its
message is read in. The function's own failure message is printed too, and only it: when the error's type is
exactly `BreakerError` and every clause of the message is, whole, one of the function's own sentence forms (a
table in `twinctl.py`, held equal to `breaker.py`'s source by a test), with as many clauses as its head
counts. Any other type, and any message with one clause outside the table, stays the sentence that says where
it is read by hand: no value of the function's environment and no control character reaches the terminal by
that road. In the one slot of the table that is neither a fixed word nor a count, the class's name in the
sentence for an error no step names, the table holds the form the name of an error's class has (it ends in
`Error` or `Exception`), which no name the driver forms for the twin has; a name of the twin that had that
form is held back by the redactor, through which everything printed goes, and not by the table.

**The operator role's policy and the driver's own calls.** The owner makes the operator role by hand from
the render, so `plan` holds that render to every call it lists: each call needs an action the policy allows
and no Deny statement names. An explicit Deny wins; a condition is judged where the call itself settles it
(the protocol of a subscription, the principal of an invoke grant, the service a role is passed to), and a
condition that cannot be settled counts against the call. Resources are not matched, and every action name
is written from memory, as the templates' own are: `plan` knows which actions a call needs, not which
resources an action is authorised on. So the Glue statement passed it without the user-defined-function
resource that the delete of the database is authorised on; a reading of the service authorization
reference found that, and a test of the rendered statement holds it. A test holds that no command sends a
call `plan` does not list.

**What the offline validation is, and is not.** `plan` asks the CLI itself to read each call
(`--generate-cli-skeleton output`) with no AWS variable of the caller, two empty credential files, instance
metadata off, and the endpoint and the proxies pointed at a closed local port, and only after a real call
under those settings failed. That catches a missing or unknown argument, a wrong type and a parameter file
that is not there. It does not catch a bad enum value or broken JSON inside a string argument, which is why
`plan` checks each document itself: its action set is the expected one, and no Allow statement holds a
wildcard that is not on the one list of exceptions in the driver. Two limits of the CLI were seen: the
commands that take an output file (a function's invoke, a shadow's read or delete) know no skeleton, so
their arguments are read by nothing before the account does; and for many calls the CLI's own sample reply
fails the CLI's own validation, which the driver tells from a refusal of the arguments line by line (a member
that is missing or unknown in a document the call gave by file or as a structure is the call's own refusal).
For such a call only the options' names, the required options and each value's form were read: the service
model's validation of the call's own arguments never ran, whatever documents the call carries. `plan` names
these calls by service and operation, no value, on a line before its summary and in `plan.json`
(`read_names_and_forms_only`).

**A listing is whole or it is refused.** The CLI follows the pages of most listings by itself. For three of
the driver's it has no paginator (Firehose's streams, Athena's workgroups, a thing's named shadows), and
the driver follows no page. A reply that carries a token or a flag that says there is more is refused
wherever it is read: `verify-gone` does not say "gone" on half a listing.

**Encoded reply fields.** No call asks a function's invoke for its log tail: the runner refuses any argv
that holds `--log-type`. `ENCODED_REPLY_FIELDS` in the driver is the one list of reply fields that carry
encoded text (`LogResult` first); a reply that holds one is refused before anything of it is copied into a
capture, and only the replies on the driver's own list are ever copied. A refusal of the redactor for
encoded text is a stop, not a retry. Of a function error only its kind goes into a capture, unless its
message is the function's own in its own sentence forms: the rule of the terminal, held for the copy. The
whole payload stays in the state directory.

**The tests** (`tests/test_sdv_cloud.py`) drive a stand-in for the CLI written in Python
(`tests/twin_stub_aws.py`): one account in a JSON file, three logs of what arrived. Its replies are
written from memory of the service's documentation, so the tests show the driver consistent with that
reading, never the reading itself. An invoke of the function runs the handler of `breaker/breaker.py` out
of the zip the function was created from, over fake clients that act on the stand-in's own account.

## The breaker (`breaker/breaker.py`)

Owner decision S10: on a rate alarm the function disables the topic rule, sets every twin certificate
INACTIVE, deletes the client's connection and detaches the device policy, and it never restores. No call
that enables, attaches or activates exists in the file. Its role allows no enabling and no attaching; it
must hold iot:UpdateCertificate to deactivate, which IAM cannot narrow to INACTIVE, so that the function
never activates is held by this code (the one literal INACTIVE) and by a test. Restoring is the owner's,
by hand, with `twinctl restore`.

- **What it acts on** comes from four environment variables the driver sets when it creates the function
  (`TWIN_CERTIFICATE_ARNS`, `TWIN_CLIENT_IDS`, `TWIN_RULE`, `TWIN_POLICY`) and from nowhere else. IAM scopes
  the detach to the certificate, never to the policy, so the code selects the policy, by the environment's
  name alone. A test holds the operations the file calls to exactly the role's actions, each on the
  resource its call names.
- **When it acts.** On the manual trip, on an alarm in ALARM in either documented shape, and on any event it
  cannot parse: it fails closed. That includes an event its own rules stop on: whatever error reading the
  event ends in, it is the trip, never an error before the first call. A cleanly parsed OK or
  INSUFFICIENT_DATA does nothing, and the manual status makes the read-backs only. The table is in the file's
  docstring, and a test holds every row. Both alarm fixtures are written from the documentation. The direct
  shape supplies `alarmData.state.value` and `alarmData.alarmName`, with no `Records` or `manual` field.
  The function logs its own record rather than retaining the event. The templates connect the breaker
  alarms directly to the function; nothing leads from the notice topic to the function.

- **Every step is attempted whatever happened to the others,** and the function raises at the end when
  anything failed. A missing environment value stops no step whose own inputs are there.
- **The read-backs give the verdict, not a call's error code.** What each call answers when its work is
  already done is not known, so a cut step counts as done when its read-back shows the cut, also when the
  service answered its write with an error. A write that was refused as not authorised, or that got no
  answer, is a failure whatever is read back: a function that may not write is no breaker. A cut whose
  read-back does not show it is a failure although every call was accepted, and so is a read-back that
  could not be made.
- **Its time is counted, for one address per endpoint name.** Each client has short time-outs and one attempt.
  That bounds no call by itself: the connect time-out is per address (the SDK tries every address an
  endpoint's name resolves to in turn, each with the whole time-out), and the read time-out is per read, not
  per reply. The file's docstring has the arithmetic: it holds for the largest set the function is counted for
  when each name resolves to one address. Against an endpoint that is silent on several addresses the runtime
  ends the function at its time-out before the later steps: those are not attempted, no log record of the end
  state is written, and the function's `Errors` metric is the sign that is left (with the notice topic, its
  alarm notifies the owner). How many addresses the two names resolve to is recorded by the function-status reading,
  and the function's time-out is the owner's to raise for it (the file, and the driver's create call and
  read-back). These are design values; nothing was measured.
- **What it returns and raises holds states and counts,** never a value of its environment, of the event
  or of the request: the payload lands in the driver's state directory and `trip --capture` copies it. Its
  log record, inside the account, names what was acted on, what invoked the function and the request.
  The deployed function is held to the zip it was made from. A source edit changes the zip and
  `status` reports the difference. Reapplying the function requires a rebuild and the owner's approval.
- **Two test tiers.** `tests/test_sdv_breaker.py` gives the function hand-written clients and runs in CI,
  where no SDK is installed. `tests/test_sdv_breaker_model.py` is opt-in: in one dev venv outside every
  work tree, installed from `breaker/requirements-dev.lock`, botocore's own clients stand in with a Stubber
  in front of each, offline, so that every call's argument names and types are held to that pin's service
  model. The pinned SDK is not the runtime's.

## Redaction (`redact.py`)

The account's replies name the account. The raw replies stay in the state directory. What leaves it, a line on
the terminal or a file of a capture, is redacted on the way out:

0. A terminal's colour codes are taken out, as the scanner takes them out before it looks.
1. **The literals first**, the longest first: the exact local values of the state directory's `literals.json`,
   each replaced by its kind in angle brackets (`<thing>`, `<account>`).
2. **A PEM block**, with its body. A block that is cut short takes the rest of the text with it.
3. **ARNs**, whole; then the data endpoint, its host whole (the labels in front of the one next to `iot`, and
   a `.cn` after `.com`, go with it), a registry host that starts with an account id, and `cert/` with the 64
   hex characters after it. The endpoint is found from where the run of letters, digits and hyphens in front
   of `.iot` begins, so a host glued to an option or to a diff's minus goes too; where the prefix went as a
   literal, what is left glued to `.iot` goes here (`<endpoint-prefix><endpoint>`).
4. **The scanner's other shapes**: an e-mail address, an IAM unique id, an EC2 host name, a resource id, a
   UUID, an address that is not the project's own.
5. **A standalone 12-digit run**, last.

The shapes are `scripts/aws/leakscan.py`'s own patterns, read from that file. After the last step the result is
given to the scanner, and what it would still flag is refused: the output is clean by the scanner, or there is
none. A `.json` file changes in its strings only, keys included, and every other byte stays; a number is never
rewritten. A `.jsonl` file gets that rule line by line. A copy into a capture directory is all or nothing: every
file is redacted before the first is written, a destination that holds something is refused, and when the file
system stops a copy part-way, what it had written is taken back.

**Encoded text is refused, never masked.** A block of 64 or more base64 characters (`undecoded data`), and
whatever is found only once a text's percent escapes are decoded, have no mask: no rule sees what such text
holds, and a mask in its place would call the copy clean. The text, the document or the whole copy is refused
by the finding's name, so that the reply is looked at and the field left out. A sha256, an image id, a path
with one in it and a PEM block's body are not taken for encoded data. A function's invoke with its log tail
carries such a field (`LogResult`); the driver never asks for it (WP6).

**What a refusal says.** Never where anything lies on this machine: not the state directory, not the source's
or the destination's place, and not the system's own message, which would name one (its reason alone is passed
on). A copy names the file it stops at by its place inside the source (`iot/reply.json`), which a copy that
succeeds would write into the capture anyway, and only once that name itself passed the redactor. A name the
redactor would change is not printed: that file is told as "file N of M".

**A sha256 is kept.** A certificate id is 64 hex characters, and so is a sha256, which a capture holds by the
hundred. Only `cert/` and 64 hex characters are a shape. A certificate id that stands alone, like an S3
canonical user id, goes only as a literal.

### The literals file

`<state directory>/literals.json`, written by hand or by the driver, never kept here:

```json
{"v": 1, "literals": {"thing": ["example-thing"], "account": ["123456789012"]}}
```

- A kind is a short lower-case label. Its values are exact strings of 3 characters or more.
- A value that is part of a mask the redactor writes (`arn`, `host`, `account`, a kind's own label) is refused
  when the file is read: in the output it could not be told from the mask. The kind can be given another
  label; a chosen name that one of the fixed masks spells cannot be a literal.
- The kinds the plan names: the chosen names, the endpoint's prefix, the certificate id, the account id, the
  owner's notice address, the canonical user id. A name that must never leave this machine goes here too.
- The file is read from the state directory and from nowhere inside a work tree: not this repository's tree,
  and not any other checkout (a `.git` above the file, found by walking up; git is never run).
- A state directory with no literals file is refused. It is not read as "no literals".
- No message prints a literal, a kind or the directory.
- **The region is no literal of the driver's.** The redactor does not treat a region as an identifier, so the
  one document that holds nothing else, the bucket's location (`apply bucket`, `teardown bucket`), prints the
  value of `TWIN_REGION`, and so does a hash of that document's bytes. An owner who keeps the region off the
  terminal and out of a capture adds a kind `region` with that value to `literals.json` by hand:
  `twinctl literals` keeps a kind that is not its own, every command then prints `<region>`, and a stop whose
  literals file is behind (another role or profile than the state's) still takes the kinds the file holds.
  Whether the region is kept so is the owner's to say before the first step in the account.

```
python sdv/cloud/redact.py --state <state directory> filter [--json]    stdin to stdout
python sdv/cloud/redact.py --state <state directory> copy SRC DST       a file or a directory
python sdv/cloud/redact.py --state <state directory> scan DIR           the scanner, with the literals
```

`--no-literals` in place of `--state` masks the shapes only. It has to be said; it is never the default.
**A capture is called clean only by a scan with the state's literals** (`redact.py --state ... scan`, which
gives them to the scanner; `leakscan.py DIR` by itself knows the shapes only): a file that holds names and no
shape (the file of the four calls by hand, a listing of names) is flagged by the literals alone, and a scan
without them passes it. Both scan commands list the first 50 findings and, when there are more, a count of
every shape, so that a finding of a kind a copy refuses (encoded data, a document that does not parse) is
seen although it lies past those 50.

## Phase 6: the image transport

Phase 6 WP4: private image transport with a separate pull identity. **Nothing of it is there until its key is
given**: with `TWIN_ECR` unset or `0` and no `TWIN_PULL_ROLE`, every render, every hash, `status` and `exit-checks` are the ones the
twin stands on, the operator role's policy among them (`tests/test_sdv_cloud.py` holds each existing step's
render to the baseline recorded before Phase 6 WP4). The keys (`.env.example` has them):

| key | what it adds |
|---|---|
| `TWIN_ECR=1` | the steps `ecr-repository` and `ecr-lifecycle` (row B2), the operator policy's ECR grants, `push`, and the exit's ECR rows. `TWIN_ECR=0` takes effect only once no ECR step stands: while one does, the steps that stand keep all four |
| `TWIN_PULL_ROLE` | the pull steps (rows B1 and B3), the operator policy's grants on the alias and the pull role, `ecr-config`, the exit's pull rows; bound once a pull step is recorded and held while any pull step is on record: once `apply pull-role` has read the role, for good (twinctl never deletes it) |
| `TWIN_ORIN_CSR`, `TWIN_ORIN_CERTIFICATE_OUT` | the Orin's signing request (made on the board, where its key stays) and where the pull certificate's PEM is written |
| `TWIN_PULL_THING` | only if B3 finds that a certificate attached to no thing gets no credentials (wp0-facts C9): the thing it is attached to; bound once `pull-thing` is recorded, while that step is on record |

A key that is bound (the pull role, the pull thing) refuses every command but `trip` under another value, or none, while its steps
are on record in any form but absent or deleted (`names-changed`, by the key's name and never by a value). For the pull role that
is for good once the owner's read of it is recorded, as for `TWIN_OPERATOR_ROLE`, and the way out is the twin's own: once nothing
stands, `twinctl literals` and then `twinctl baseline --again` take new names. The pull thing is free again once `pull-thing` is
torn down.

**The steps** come after every step of the twin's, so that a teardown removes them first, and a state that records one keeps it in
its table whatever the names file says, as row 19's.

- `ecr-repository`: one repository per app, `sdv-twin/<app>` (`sdv-twin/hard-brake-hazard` now), a constant namespace with no
  names-file value in it. Tags `IMMUTABLE`, encryption `AES256` given explicitly, the twin's tag, no scanning configuration, and
  never a repository policy (with none, only this account's principals reach it, through IAM). One that is there and not ours is
  refused. Its tag is made and not read back by the step, as no step of the twin reads its tag back: `verify-gone`'s tag query is
  where a tag is read, and the repositories' listing finds a leftover that carries none. Its teardown is refused while the
  repository holds an image (the delete takes no `--force`): emptying it is by hand,
  `aws ecr list-images --repository-name sdv-twin/<app>` and then `aws ecr batch-delete-image --repository-name sdv-twin/<app>
  --image-ids imageDigest=<digest>` for each, under the operator profile.
- `ecr-lifecycle`: one rule, priority 1, any tag status, the newest 10 images kept (a design value: v1-v3 of a few apps fit).
- `pull-role` (B1, the owner's kind): the role the IoT credential provider assumes, trusted by `credentials.iot.amazonaws.com`
  alone, for this account and the role alias (the IoT developer guide's confused-deputy example for the credential provider). Its
  policy is `ecr:GetAuthorizationToken` on `*` and `ecr:BatchGetImage` and `ecr:GetDownloadUrlForLayer` on the twin's
  repositories, and nothing else: not the `ecr:BatchImportUpstreamImage` of AWS's pull-only managed policy (no pull-through cache).
- `role-alias`: `sdv-twin-ecr-pull`, the pull role, credentials of 3600 s.
- `pull-policy`: `<prefix>-ecr-pull`, `iot:AssumeRoleWithCertificate` on that alias and nothing else; no IoT data permission, so
  the pull certificate is outside the breaker by design.
- `pull-thing` (only with `TWIN_PULL_THING`), `pull-certificate` (from the Orin's request, INACTIVE), `pull-attachment`.
- `pull-active` and `pull-inactive`: actions that set the pull certificate ACTIVE for a board day and INACTIVE after it, each run
  by its own printed hash, every time.

**The operator role's policy** (D8) gains, only with `TWIN_ECR=1`, the reads with no resource type on `*` (the token, the
registry's description, policy, pull-through cache rules and scanning, the repositories' listing, and ECR Public's
`DescribeRepositories`), every repository action of the twin's (management, lifecycle, the repository policy's read, image listing
and deletion, push) on `repository/sdv-twin/*`, and a Deny that names ECR Public's write actions in place of `ecr-public:*`, so
that the exit can read that ECR Public holds nothing. Only with `TWIN_PULL_ROLE`, it gains the alias's create, describe and
delete on that alias, its listing on `*`, and `iam:GetRole`, `iam:GetRolePolicy` and `iam:PassRole` on the pull role alone. The
owner remakes the policy from the render (B1) only when a key is given. The Service Authorization Reference's pages for ECR, ECR
Public, IoT and IAM were read for the action list (2026-10-17); the listing of every repository is on `*` because a listing names
no repository, so no repository's ARN can hold it. A narrower `repository/*` of the twin's region and account would need a
wildcard exception of its own, which spec 5 item 5 does not give (`repository/sdv-twin/*` and nothing else); whether ECR answers
that listing to this policy is first seen at B2, under the remade policy (`exit-checks` and `verify-gone` read it).

**`status`** knows two certificate sets: the function's environment is held to the twin's data certificate alone, as before; an
ACTIVE certificate outside the data set and the pull certificate fails; the pull certificate ACTIVE is said ("active: a board
day") and is no failure. **`exit-checks`** adds, with `TWIN_ECR=1`, no repository policy on a `sdv-twin/` repository, no registry
policy, no replication rule and no pull-through cache rule (the registry's scan type as a shape), nothing in ECR Public (read
through `us-east-1`), and the repositories exactly the expected ones, `IMMUTABLE`, `AES256`; with `TWIN_PULL_ROLE`, the pull role,
the alias and the pull policy as rendered, and the pull certificate carrying the pull policy and no other.

**`twinctl push --app NAME --version X.Y.Z --arch arm64 --store-id ID --config-digest CFG [--docker PREFIX] [--approve push:HASH]`**
prints its render (the repository, the tag `<version>-<arch>`, the store ID, the config digest, docker's prefix, the CLI's two
calls) and its hash, and is refused without the approval, or while `ecr-repository` is not recorded as made and proven. Then the
config digest is proved from a `docker save` stream (an index is refused, and the config must be `linux/<arch>`) before anything
is tagged; the store ID is tagged; `aws ecr get-login-password` is piped into `docker --config <a temporary directory> login
--password-stdin`, so that the password is on no argv, in no reply file and in no file but that directory's, which is removed with
the tag whatever happened; the image is pushed; `describe-images` by the tag must give the store ID as `imageDigest`. The push
is on record before it is sent (sending), and stays there however it ended, as a create of the driver does: `pushed` with the
manifest digest once the read-back gives the store ID, `unverified` when the read-back fails or gives another digest, and still
`sending` when docker's push ended in an error; the last two may have put the image, and `status` lists each push that is not
`pushed`. The state's `pushes` holds each tag's latest push (its store ID, config digest and status). Docker's words are never
printed: they name the registry, which holds the account. For WSL's docker the prefix is `wsl.exe -d Ubuntu-24.04 -- docker`, and
the temporary directory is given to it as `/mnt/<drive>/...`. The local tag goes by `docker rmi <the registry's reference>`,
which removes an image whose only name that is. An image with no other name than the registry's reference is refused before
anything is tagged (push-image-unnamed), so that the rmi only ever untags: `docker image inspect` reads its names, and a build or
load of its own name comes first. A push refused by the proof of the image, or for its want of a name, tagged nothing and spends no
approval: its printing still stands for the retry, and the approval is spent when the tag is made.

**`twinctl ecr-config --out FILE`** writes the pulling host's one root-only file (D7): `credential_endpoint` (from
`describe-endpoint --endpoint-type iot:CredentialProvider`), `role_alias`, `region` and `registry`, as JSON, outside every work
tree, mode 0600, and prints nothing of its content. It is refused until `role-alias` is recorded as made and proven. The file goes
to the host, root-only; it is the updater's `--registry-file` and `ecrlogin.py`'s `--config`.

**`ecrlogin.py login --config FILE --device DIR [--docker-config DIR] [--docker PREFIX]`** (the standard library only, for the
board's own Python) fetches the role alias's credentials over mutual TLS with the device directory's `device.crt` and `device.key`
(the connector's file names), the server held to its `ca.pem` and named by SNI; signs one SigV4 call of ECR's
`GetAuthorizationToken` with them, the session token signed as `x-amz-security-token`; refuses a token whose proxy endpoint is not
the file's registry; and logs docker in by stdin under `--docker-config` (default `/run/sdv-local/ota/docker`, the updater's,
which must be mode 0700). It prints one line, the token's expiry, and no host, key id, token or path. `ecrlogin.py logout
[--docker-config DIR]` runs docker's logout for each registry docker's file names and removes the file whatever docker answered: a
logout that docker refused is said (exit 1), and the file with the token is gone all the same. Its signature is held to
botocore 1.43.111's for the same request (`tests/test_sdv_ecrlogin.py`).

**The redactor and the scanner** needed no new shape: the credential provider's host
(`<prefix>.credentials.iot.<region>.amazonaws.com`) is a form of the endpoint's shape and goes whole, and a role alias's ARN is an
ARN and goes whole as one. Tests hold both in the forms the pull side meets them.

What these Phase 6 WP4 unit tests do **not** demonstrate: the account configuration or a deployment; that the credential provider gives credentials to a certificate attached to no thing (C9),
or the exchange end to end (B3 and the PC rehearsal); that ECR answers a listing of every repository to this policy; which
service name `CreateRoleAlias` passes the pull role to (the statement names the one role and no service); that a push from
Docker's containerd store keeps the manifest's bytes (the read-back settles it, D4); that `aws ecr get-login-password` takes no
skeleton (`plan` takes it so, from memory); anything on the Orin or on a1.metal; secure OTA (no image signing, no root of trust: a
token and a key on a host are files); or any timing.

## What it is not

- **Not the device side.** The connector, its locks and its probes are `sdv/connector`.
- **Not `scripts/twin/`.** That directory is the old same-image comparison tooling, kept under its name; a
  second directory called "twin" would invite a wrong edit, so the account side lives here.
- **Not `scripts/aws/`.** That is the bare-metal session tooling (self-terminating instances). The twin's
  resources are always-on and are created one by one, each approved by the owner. The leak scanner lives
  there and is shared: its twin shapes apply to a bare-metal session's capture too.
- **Not a store of identifiers.** Chosen names, ARNs, the endpoint, the certificate id, thresholds, approvals,
  raw replies, renders and the literals file live in a state directory outside every repo. Files here hold
  placeholders and documentation values only: `123456789012`, `example-thing`, `example_rule`, RFC 5737
  addresses, the endpoint `aexample000000-ats.iot.us-east-1.amazonaws.com`, a certificate id that is the hex
  digits in order. `tests/test_no_real_identifiers.py` holds this directory to its allowlist.
- **Not a proof that nothing leaks.** The redactor and the scanner know shapes and the literals they are
  given. A name that is not in the literals file passes both. So does one written in another case, split
  across a line, or in an encoding the scanner does not read: a base64 block under 64 characters, the
  URL-safe alphabet, hex, text encoded twice. A literal is taken out wherever its characters stand, so a
  chosen name that is a common word, or a short one, also cuts into records that only happen to hold it;
  which values may be literals is the driver's to settle (WP6).
  A JSON number is kept even when it equals a literal. A secret access key and a session token have no
  shape, and an IAM unique id is known by four prefixes only (a group's, a policy's or an instance profile's
  begins otherwise): a reply that holds one passes both unless the value is a literal, so which replies are
  ever copied is the driver's to settle (WP6).
- **Not an account verification record.** Files here hold templates and documentation values. Live
  configuration, credentials and run records stay outside every work tree. Unit tests use a CLI stand-in;
  its reply shapes, error codes, action names and resource forms do not establish the service's behaviour.
- **Not a proof that a call is authorised,** that a name is free, that a role is accepted at once, or of
  what a call costs. A policy can be read, not proven minimal.
- **Not an account-side breaker test.** The unit tests use fakes and a pinned service model:
  IAM's reading of its role, whether an alarm reaches it, the event's real shape, what each call answers
  when its work is already done, and which SDK its runtime holds are first seen in the account, before
  anything is live. Its log is read by hand: the driver has no read of it. Nor is it known whether the
  policy's targets still list a certificate for a while after an accepted detach: the function judges the
  detach by that listing at once, so a first trip would then raise although the cut is under way. The first
  dry trip's record is read for it, and the verdict on the detach is decided then. Nor how many addresses
  the function's two endpoint names resolve to, on which its counted time rests: `apply function-status`
  names the reading that records it.
- **Not a cost or timing record.** A figure in this directory is a design value and is labelled as one.
- **Not a fleet platform, not production-grade update delivery, not real time, not certified.**
