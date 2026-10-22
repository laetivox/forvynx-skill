"""Verify targets using the product baseline, never importing target code."""

from .boundary import read_bytes, state
from .domain import ForvynxError, Plan, content_state, decode
from .plan import CHECKER, validate_boundaries
from .portable import Snapshot, inspect_snapshot, run_check


def verify(value, execute=(), confirmation=None):
    Plan(value).validate()
    validate_boundaries(value)
    mismatches = [a["path"] for a in value["actions"] if state(a["root"], a["path"]) != a["after"]]
    if mismatches:
        raise ForvynxError("Target does not match plan: " + ", ".join(mismatches))
    for action in value["actions"]:
        if action["path"] == ".forvynx/check.py" and decode(action["content_b64"]) != CHECKER.read_bytes():
            raise ForvynxError("Checker is not the current product template")
    for repo in value["repositories"]:
        try:
            inspect_snapshot(Snapshot(repo["identity"]["root"], "worktree"))
        except (ValueError, TypeError, KeyError) as exc:
            raise ForvynxError(f"Generated structure failed: {exc}", 4) from exc
    selected = set(execute)
    available = {c["key"] for c in value["checks"]}
    if not selected <= available:
        raise ForvynxError("Unknown check IDs; use the keys from the approved plan", 2)
    if selected:
        Plan(value).require_confirmation(confirmation)
    checks = []
    for check in value["checks"]:
        if check["key"] not in selected:
            checks.append({"key": check["key"], "required": check["required"], "status": "not_run"})
            continue
        for source in check["source_states"]:
            expected = source["state"]
            for action in value["actions"]:
                if action["root"] == check["root"] and action["path"] == source["path"]:
                    expected = action["after"]
            if state(check["root"], source["path"]) != expected:
                raise ForvynxError("Check definition source changed")
        result = run_check(check["root"], check)
        checks.append({**result, "key": check["key"]})
    ready = all(not c["required"] or c["status"] == "passed" for c in checks)
    return {"schema_version": 1, "digest": value["digest"], "structure": "passed", "plan_consistency": "passed",
            "ready": ready, "ready_scope": "generated_workflow_only", "checks": checks,
            "engineering_verification": "configured" if checks else "not_configured",
            "hooks": "not_installed", "ci_execution": "not_run", "remote_protection": "unverified"}
