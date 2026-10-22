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
scan budget. Default depth is 3 and directory/entry budget is 5,000. An incomplete
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

Required checks not executed keep `ready=false`; an empty check list means only
the generated workflow is ready, not that business code has been tested. Missing
tools, failure, timeout and unverified remote protection remain explicit. Child
process trees are not sandboxed; timeout kills the direct process and reports that
spawned children may need host cleanup. Output is discarded to avoid retaining
secrets or unbounded logs; rerun an authorized failing check in the host terminal
when its diagnostic output is needed.

Verification uses the product's own fixed checker implementation and template
baseline. Never import/execute a target's checker to perform static verification.
The target's `.forvynx/check.py` is a portable quality gate for CI, not a proof
of human approval or an adversarial security boundary.

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
