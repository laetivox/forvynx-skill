# Controller usage and limits

Use Python 3.11+ and Git. `python` below means the interpreter actually available
in the host, including a bundled absolute path. No pip installation is required.
The controller uses the same CLI in any agent or terminal with those capabilities;
it does not call a vendor API. Install/discover the Skill using the target host's
own conventions. `agents/openai.yaml` is optional presentation metadata, not a
dependency of the portable Skill or controller. If the host does not auto-load
`AGENTS.md`, explicitly load the relevant `.forvynx/workflow.md` through the Skill.
Run from this Skill directory, or supply the absolute path to `scripts/forvynx.py`.
Write JSON outputs only to explicitly selected scratch files; probe/plan themselves
never write their workspace. In PowerShell, use UTF-8 when redirecting JSON.

## Discovery and a concrete proposal

```text
python -B scripts/forvynx.py probe --workspace <chosen-directory>
python -B scripts/forvynx.py plan --inventory <inventory.json> --selection <selection.json>
```

Probe reports bounded metadata discovery, including nested checkouts within the
scan budget. Default depth is 3, with independent global budgets of 5,000 visited
directories and 5,000 raw entries across all directories. `--max-depth`,
`--max-dirs` and `--max-entries` set these limits. Pending and visited directories
share the directory budget; files, excluded names and links also consume entries.
An entry budget fully consumed is conservatively incomplete without a lookahead.
The report includes `enumerated_entries` and `peak_pending_directories`. These
limits cover tree discovery, not every Git query or recovery-log read. An incomplete
inventory can still support an explicitly selected, positively identified checkout;
it must not be presented as exhaustive. Evidence symlinks, invalid config and
permission errors do not count as an absent project. No Git initialization occurs.

A minimal selection JSON is `{"repositories":[{"path":"service-a"}]}`. Use `.`
for a checkout equal to the workspace root. Select only checkouts in the inventory.
Example with a reviewed standard-library check and optional CI generation:

```json
{
  "repositories": [{
    "path": "service-a",
    "ci": true,
    "checks": [{
      "id": "unit",
      "argv": ["$PYTHON", "-m", "unittest", "discover", "-s", "tests"],
      "cwd": ".",
      "timeout": 60,
      "required": true,
      "env": {},
      "sources": ["pyproject.toml"]
    }]
  }]
}
```

`$PYTHON` is replaced by the currently executing Python interpreter. It is not
shell interpolation. Command definitions are never run during probe or plan.
`sources` binds files that define a command; do not use this as an exhaustive
list of every code file tested. Review argv, cwd, environment, side effects,
dependencies, source contents and CI behavior before authorization.

Each check may include a `review` declaration. New plans explicitly supply the
following unknown values when it is omitted; older configs without it remain
readable without being rewritten by validation:

```json
{
  "dependencies": null,
  "network": "unknown",
  "writes": "unknown",
  "notes": []
}
```

All four keys are required in an explicit object; unknown keys are rejected.
`dependencies: null` means unevaluated. An empty list declares no additional
prerequisites, while a nonempty list names reviewed prerequisites; neither proves
that tools are installed. `network` and `writes` accept `none`, `possible` or
`unknown`. They describe the Agent's review, not a sandbox guarantee or execution
permission. Dependency and note lists have at most 16 unique, nonempty printable
single-line strings of at most 800 characters each. Review declarations are bound
to the same digest as the command and must agree in the plan and repo config.
Replanning without a new checks list preserves existing declarations.

The plan's `scope.network: false` describes onboarding itself. It is independent
of possible effects from subsequently authorized engineering checks. Declarations
do not install prerequisites, authorize networking, or change checkout scope.

### Project-specific workflow proposals

For onboarding that needs project-specific decisions, add an optional `workflow`
to the selected repository. The Agent proposes the decisions after reading the
applicable guidance; the controller validates their structure and renders them
as prose with a fixed template. For example, when `AGENTS.md` requests focused
standard-library tests and the reviewed `unit` check above is selected:

```json
{
  "schema_version": 1,
  "decisions": [{
    "id": "focused-validation",
    "applies_to": "small_change",
    "guidance": "Run focused standard-library tests for the changed behavior.",
    "reason": "The repository guidance requests focused tests without new dependencies.",
    "confidence": "medium",
    "sources": ["AGENTS.md"],
    "check_ids": ["unit"]
  }],
  "unknowns": ["The available integration-test environment has not been verified."]
}
```

All fields shown are required. `applies_to` accepts `all`, `small_change`,
`substantial_change`, or `cross_repository`; it scopes the recommendation, not
checkout authorization. `confidence` is the Agent's declared `high`, `medium`,
or `low` assessment. High/medium proposals need a source; unsupported proposals
must be low. Unknowns must be stated rather than supplied as invented facts.

Each list is limited to 16 entries. Decision IDs match `[a-z][a-z0-9_-]{0,63}`;
guidance, reasons and unknowns are nonempty printable single-line text up to
800 characters. Unknown fields, duplicate IDs/references, and unknown check IDs
are rejected. `sources` accepts only this checkout's evidence paths reported
by probe; generated Forvynx components are excluded. This first version does
not support arbitrary additional evidence paths or module-specific workflows.

The plan binds evidence bytes and the rendered workflow to its digest. A source
reference proves neither that the recommendation follows from it nor that the
Agent respected all existing rules. Review those semantic choices with the diff.
Applicable rules remain authoritative; proposal text never grants execution,
installation, hook, network, or other-checkout permission. Referenced check IDs
do not execute checks. Commands remain in the separate reviewed `checks` list.

New onboarding without `workflow` keeps the generic template. Replanning an
existing adaptive repository without that field preserves its saved decisions;
an explicit object replaces them through the normal diff. Older repo configs
without the optional field remain readable. A plan carrying an older checker
template needs a new plan under the current product baseline.

The plan contains complete base64 write payloads, before/after hashes, human-readable
diffs, checkout identities, commands, scope flags, and a digest. Machine-local audit
records/backups are under the OS temporary directory `forvynx-state/<workspace-hash>`;
coordination locks use `forvynx-locks/<resource-hash>.lock`. These explicit locations
are outside the repository and are shown with the plan. OS cleanup may remove audit
records; preserve a needed journal in an approved local backup location before cleanup.

## Apply and verify

```text
python -B scripts/forvynx.py apply --plan <plan.json> --confirm <exact-reviewed-digest>
python -B scripts/forvynx.py verify --plan <plan.json>
python -B scripts/forvynx.py verify --plan <plan.json> --execute <repo-id:check-id> --confirm-execution <digest>
```

`--confirm` and `--confirm-execution` record an externally obtained authorization
convention; a digest itself is not proof of a human approval. The assistant must
not fabricate it or use a plan alone as permission. Existing scoped task approval
may cover normal checks; do not ask again when it already does.
When a new application journal is created, its approval record includes UTC
`recorded_at`, the plan scope and selected repository IDs. This is the controller's
receipt-recording time, not an authenticated human approval time. A `no_change`
result leaves the original audit bytes and time untouched; rollback keeps that
record. This receipt concerns the application, not separate check or installation
authorization.

Required checks not executed keep `ready=false`; an empty check list means only
the generated workflow is ready, not that business code has been tested. Missing
tools, failure, timeout and unverified remote protection remain explicit. Child
process trees are not sandboxed; timeout kills the direct process and reports that
spawned children may need host cleanup. Output is discarded to avoid retaining
secrets or unbounded logs; rerun an authorized failing check in the host terminal
when its diagnostic output is needed.

Check reports use the same fields across all four statuses: `id`, `key`, `root`,
`argv`, `cwd`, `required`, `status`, `exit_code`, `duration_ms`, `reason`, `output`,
`log_ref`, `review` and `definition_sha256`. Arguments show the effective Python
interpreter and directories are local absolute paths. `key` comes from the plan
or the portable config's repo ID; the bare helper has no key unless one is given.
Unselected checks are `not_run`; missing directories/tools or denied process
startup are `unsupported`. Both have null exit codes and zero execution duration.
Launched checks report actual duration and completion/failure/timeout reasons.
Required unsupported checks return exit code 5; required failures return 4, and
required unselected checks return 2. Index mode remains a structural gate.

`definition_sha256` covers the portable command definition, including the original
`$PYTHON` token, explicit environment overrides, source path list and effective
review. It excludes local roots/keys and source bytes; it is not a digest of every
business input. The controller's plan digest and source preconditions remain the
binding for reviewed inputs. Portable checks have no local approval plan.
Output remains `not_recorded`, and `log_ref` is null because no output log exists;
these fields do not claim a log was archived. Host environment values are not
repeated in reports.

Verification uses the product's own fixed checker implementation and template
baseline. Never import/execute a target's checker to perform static verification.
The target's `.forvynx/check.py` is a portable quality gate for CI, not a proof
of human approval or an adversarial security boundary.
For adaptive workflows it checks the data shape and source/check references;
product verification also reconstructs the rendered Markdown. Portable checks
confirm that referenced sources exist in the selected snapshot, not that their
current content still supports a planning-time recommendation.

## Recovery

```text
python -B scripts/forvynx.py rollback --plan <original-plan.json> --confirm <digest>
```

Inspect the machine-local journal first. Compensation restores only attempted
files whose current content still matches this transaction's after state.
Subsequent edits survive and are reported as conflicts. Probe reports unresolved
journals even if the workspace index was restored. New applies stop until recovery
is resolved. No reset, clean, checkout or stash is used. Empty directories can
remain after compensation. Stale locks are not deleted automatically; verify
the recorded process is gone and obtain appropriate scope before manual recovery.

## Optional gates

`hook-preview --plan <plan.json> --repo-id <id>` returns a reviewed checker snapshot
and a POSIX Git hook snippet, with its active hook path, existing hook and shared
worktree information. It writes nothing. Integrate manually with the existing hook
manager only after authorization; never blindly replace a hook or `core.hooksPath`.
The snippet hashes its installed checker snapshot before running it with isolated
Python. Its config, component references and rules come from one Git index snapshot,
including the active `GIT_INDEX_FILE`; it does not execute engineering commands.
Changed checker versions require a new reviewed snapshot and snippet.

`ci: true` adds a separate GitHub Actions workflow with pinned action commits,
read-only permissions and no dependency installation. Checks needing dependencies
will fail until the user approves explicit setup changes. Never claim CI ran or
branch protection is enabled merely because this file was generated. Other CI
platforms can call `python -B .forvynx/check.py --source worktree --execute` after
their own reviewed environment setup.

Local development files are not an installed user-level Skill. Installation needs
an explicit destination and conflict preview; this controller does not auto-install
itself or write host settings. Clone or download the source repository and install
the entire `skills/forvynx` directory; no build step is required.
