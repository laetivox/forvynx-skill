"""Journaled, scoped writes and conditional compensation."""

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .boundary import absolute, assert_owner, atomic_write, guarded, private_directory, read_bytes, state, state_directory
from .domain import ForvynxError, Plan, content_state, decode, json_bytes, sha
from .plan import validate_boundaries


@contextmanager
def resource_locks(value):
    resources = {value["workspace"], *(r["identity"]["root"] for r in value["repositories"])}
    folder = absolute(Path(tempfile.gettempdir()) / "forvynx-locks")
    private_directory(folder)
    held = []
    try:
        for resource in sorted(resources):
            name = sha(os.path.normcase(resource).encode()) + ".lock"
            path = guarded(folder, name)
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError as exc:
                raise ForvynxError(f"Resource locked; inspect owning process before recovery: {path}") from exc
            held.append(path)
            with os.fdopen(fd, "w") as output:
                output.write(str(os.getpid()))
        yield
    finally:
        for path in reversed(held):
            path.unlink(missing_ok=True)


def journal_path(value):
    return state_directory(value["workspace"]), value["digest"] + ".json"


def write_journal(value, report):
    root, name = journal_path(value)
    private_directory(root)
    atomic_write(root, name, json_bytes(report))


def check_recovery(value):
    folder = state_directory(value["workspace"])
    if not folder.exists():
        return
    for path in folder.glob("*.json"):
        data = json.loads(read_bytes(folder, path.name))
        if data.get("status") in ("applying", "partial", "conflict"):
            raise ForvynxError(f"Unresolved recovery journal: {path}")


def restore(value, report):
    conflicts = []
    attempted = {(a["root"], a["path"]) for a in report.get("completed", [])}
    if report.get("attempting"):
        attempted.add((report["attempting"]["root"], report["attempting"]["path"]))
    for action in reversed(value["actions"]):
        if (action["root"], action["path"]) not in attempted:
            continue
        try:
            assert_owner(action["root"], action["path"], action["owner"])
            current = state(action["root"], action["path"])
            if current == action["before"]:
                continue
            if current != action["after"]:
                conflicts.append({"path": str(Path(action["root"]) / action["path"]), "reason": "subsequent edit preserved"})
                continue
            atomic_write(action["root"], action["path"], decode(action["before_b64"]))
        except (OSError, ForvynxError) as exc:
            conflicts.append({"path": action["path"], "reason": str(exc)})
    report["status"] = "conflict" if conflicts else "rolled_back"
    report["conflicts"] = conflicts
    report["residual_state_notice"] = "A conflict journal remains authoritative even if workspace index was restored."
    write_journal(value, report)
    return report


def apply_plan(value, confirmation, approval_source="manual_digest_confirmation", writer=None):
    plan = Plan(value).validate()
    plan.require_confirmation(confirmation)
    validate_boundaries(value)
    classification = plan.classify([state(a["root"], a["path"]) for a in value["actions"]])
    # No lock or journal write is needed for a read-only, already applied result.
    if classification == "no_change":
        check_recovery(value)
        return {"status": "no_change", "digest": value["digest"]}
    with resource_locks(value):
        validate_boundaries(value)
        check_recovery(value)
        classification = plan.classify([state(a["root"], a["path"]) for a in value["actions"]])
        if classification == "no_change":
            return {"status": "no_change", "digest": value["digest"]}
        report = {"schema_version": 1, "status": "applying", "plan": value, "completed": [],
                  "approval": {"digest": confirmation, "source": approval_source,
                               "security_notice": "Audit convention; not independently authenticated human approval."}}
        write_journal(value, report)
        writer = writer or atomic_write
        try:
            for action in value["actions"]:
                assert_owner(action["root"], action["path"], action["owner"])
                if state(action["root"], action["path"]) != action["before"]:
                    raise ForvynxError("File changed during transaction")
                report["attempting"] = {"root": action["root"], "path": action["path"]}
                write_journal(value, report)
                writer(action["root"], action["path"], decode(action["content_b64"]))
                report["completed"].append({"root": action["root"], "path": action["path"]})
                report.pop("attempting", None)
                write_journal(value, report)
            if any(state(a["root"], a["path"]) != a["after"] for a in value["actions"]):
                raise ForvynxError("Post-write mismatch")
            report["status"] = "applied"
            write_journal(value, report)
            return {"status": "applied", "digest": value["digest"], "journal": str(journal_path(value)[0] / journal_path(value)[1]),
                    "files": report["completed"]}
        except (OSError, ForvynxError) as exc:
            report["failure"] = str(exc)
            report["status"] = "partial"
            write_journal(value, report)
            restored = restore(value, report)
            raise ForvynxError(f"Application failed; recovery={restored['status']}; journal={journal_path(value)[0] / journal_path(value)[1]}", 4) from exc


def rollback(value, confirmation):
    Plan(value).validate().require_confirmation(confirmation)
    validate_boundaries(value, check_evidence=False)
    with resource_locks(value):
        root, name = journal_path(value)
        data = read_bytes(root, name)
        if data is None:
            raise ForvynxError("Recovery journal unavailable; no files changed", 2)
        report = json.loads(data)
        if report.get("plan") != value:
            raise ForvynxError("Journal does not match this plan")
        if report.get("status") == "rolled_back":
            return {"status": "no_change", "digest": value["digest"]}
        result = restore(value, report)
        return {"status": result["status"], "conflicts": result["conflicts"], "journal": str(root / name)}
