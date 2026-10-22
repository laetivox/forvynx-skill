"""Build an exact, reviewable proposal. This module never writes targets."""

import difflib
import json
from pathlib import Path

from . import VERSION
from .adapters import inspect_repo, workflow
from .boundary import absolute, assert_owner, guarded, identity, read_bytes, relative_path, state_directory, within
from .domain import ForvynxError, Plan, canonical, content_state, decode, encode, json_bytes, sha
from .portable import BEGIN, END, validate_config

PACKAGE = Path(__file__).resolve().parents[2]
CHECKER = Path(__file__).with_name("portable.py")
REPO_PATHS = {"AGENTS.md", ".forvynx/repo.json", ".forvynx/workflow.md", ".forvynx/check.py", ".github/workflows/forvynx.yml"}


def load_config(root, path):
    data = read_bytes(root, path)
    if data is None:
        return None
    try:
        config = json.loads(data)
        if config.get("schema_version") != 1 or config.get("generator") != "forvynx":
            raise ValueError("unknown owner/version")
        return config
    except (ValueError, AttributeError) as exc:
        raise ForvynxError(f"Existing {path} is not compatible Forvynx configuration") from exc


def managed_agents(data):
    try:
        text = (data or b"").decode("utf-8")
    except UnicodeError as exc:
        raise ForvynxError("AGENTS.md must be UTF-8; no encoding conversion attempted") from exc
    newline = "\r\n" if "\r\n" in text else "\n"
    block = newline.join((BEGIN, "Use .forvynx/workflow.md for the scoped AI coding workflow.", END))
    if BEGIN in text or END in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1 or text.index(BEGIN) >= text.index(END):
            raise ForvynxError("Malformed/duplicate managed block")
        start, end = text.index(BEGIN), text.index(END) + len(END)
        return (text[:start] + block + text[end:]).encode("utf-8")
    return (text + (newline if text and not text.endswith("\n") else "") + (newline if text else "") + block + newline).encode("utf-8")


def validate_registry(workspace):
    config = load_config(workspace, ".forvynx/workspace.json")
    if config is None:
        return
    seen = set()
    for entry in config["repositories"]:
        relative = entry["path"]
        if relative in seen or entry.get("status") != "managed":
            raise ForvynxError("Workspace registry has duplicate/unfinished entries")
        seen.add(relative)
        root = workspace if relative == "." else guarded(workspace, relative)
        owner = identity(root)
        repo = load_config(root, ".forvynx/repo.json")
        if owner is None or owner["root"] != str(root) or repo is None or repo.get("repo_id") != entry["repo_id"] or sha(canonical(owner))[:16] != entry["repo_id"]:
            raise ForvynxError("Workspace index and checkout config disagree; inspect recovery state")


def build_plan(inventory, selection):
    if inventory.get("schema_version") != 1:
        raise ForvynxError("Unsupported inventory", 5)
    workspace = absolute(inventory["workspace"])
    validate_registry(workspace)
    chosen = selection.get("repositories", [])
    if not chosen:
        raise ForvynxError("Select at least one known checkout; no automatic Git initialization", 2)
    known = {item["identity"]["root"]: item for item in inventory["repositories"]}
    actions, repositories, checks, seen = [], [], [], set()
    workspace_owner = identity(workspace)
    index = load_config(workspace, ".forvynx/workspace.json") or {"schema_version": 1, "generator": "forvynx", "repositories": []}
    index = json.loads(json.dumps(index))
    for item in chosen:
        rel = item["path"]
        root = workspace if rel == "." else guarded(workspace, rel)
        if str(root) not in known or str(root) in seen:
            raise ForvynxError("Selection must name unique checkouts from inventory")
        seen.add(str(root))
        repo = identity(root)
        if repo != known[str(root)]["identity"] or repo["root"] != str(root):
            raise ForvynxError("Checkout changed since discovery")
        details = inspect_repo(root)
        if details["warnings"]:
            raise ForvynxError("Unreadable/invalid engineering evidence: " + str(details["warnings"]))
        if details["evidence"] != known[str(root)]["evidence"]:
            raise ForvynxError("Evidence changed since discovery")
        repo_id = sha(canonical(repo))[:16]
        old = load_config(root, ".forvynx/repo.json")
        if old:
            try:
                validate_config(old)
            except (ValueError, TypeError, KeyError) as exc:
                raise ForvynxError("Existing repo config is invalid") from exc
            for name, expected in old["components"].items():
                if content_state(read_bytes(root, name)) != {"kind": "file", "sha256": expected}:
                    raise ForvynxError(f"Existing component drift: {name}")
        definitions = item.get("checks", old["checks"] if old else [])
        definitions = [{"id": c["id"], "argv": c["argv"], "cwd": c.get("cwd", "."),
                        "timeout": c.get("timeout", 60), "env": c.get("env", {}),
                        "required": c.get("required", True), "sources": c.get("sources", [])} for c in definitions]
        components = {".forvynx/check.py": CHECKER.read_bytes(), ".forvynx/workflow.md": workflow(details["profile"])}
        use_ci = item.get("ci", old.get("ci", False) if old else False)
        if not isinstance(use_ci, bool):
            raise ForvynxError("ci must be a boolean", 2)
        if old and old.get("ci") and not use_ci:
            raise ForvynxError("Onboarding cannot remove an existing CI integration; review removal separately", 2)
        if use_ci:
            components[".github/workflows/forvynx.yml"] = (PACKAGE / "assets/github-ci.yml").read_bytes()
        config = {"schema_version": 1, "generator": "forvynx", "version": VERSION, "repo_id": repo_id,
                  "profile": details["profile"], "components": {k: sha(v) for k, v in components.items()}, "checks": definitions, "ci": use_ci}
        try:
            validate_config(config)
        except (ValueError, TypeError, KeyError) as exc:
            raise ForvynxError(str(exc), 2) from exc
        for check in definitions:
            source_states = [{"path": p, "state": content_state(read_bytes(root, p))} for p in check["sources"]]
            if any(s["state"]["kind"] != "file" for s in source_states):
                raise ForvynxError("Check source does not exist", 2)
            checks.append({**check, "key": repo_id + ":" + check["id"], "root": str(root), "source_states": source_states})
        desired = {**components, ".forvynx/repo.json": json_bytes(config), "AGENTS.md": managed_agents(read_bytes(root, "AGENTS.md"))}
        for name, data in desired.items():
            before = read_bytes(root, name)
            if before is not None and name != "AGENTS.md" and not old:
                raise ForvynxError(f"Unmanaged existing file: {root / name}")
            if before is not None and name in components and old and name not in old["components"]:
                raise ForvynxError(f"Unmanaged component: {name}")
            actions.append(make_action(root, name, before, data, repo))
        evidence = [{"path": e["path"], "state": {"kind": "file", "sha256": e["sha256"]}} for e in details["evidence"]]
        # Missing evidence is also a precondition (e.g. pyproject added later).
        from .adapters import EVIDENCE_FILES
        evidence.extend({"path": p, "state": {"kind": "absent"}} for p in EVIDENCE_FILES if all(e["path"] != p for e in evidence))
        repositories.append({"identity": repo, "repo_id": repo_id, "profile": details["profile"], "evidence": evidence})
        index["repositories"] = [r for r in index["repositories"] if r["path"] != root.relative_to(workspace).as_posix()]
        index["repositories"].append({"path": root.relative_to(workspace).as_posix(), "repo_id": repo_id, "status": "managed"})
    if workspace_owner and workspace_owner["root"] not in seen:
        raise ForvynxError("Workspace index belongs to an unselected checkout; expand scope explicitly")
    index["repositories"].sort(key=lambda r: r["path"])
    actions.append(make_action(workspace, ".forvynx/workspace.json", read_bytes(workspace, ".forvynx/workspace.json"), json_bytes(index), workspace_owner))
    value = {"schema_version": 1, "kind": "onboard", "version": VERSION, "workspace": str(workspace), "workspace_owner": workspace_owner,
             "repositories": sorted(repositories, key=lambda r: r["identity"]["root"]),
             "actions": sorted(actions, key=lambda a: (a["root"], a["path"])), "checks": checks,
             "state_directory": str(state_directory(workspace)),
             "scope": {"install_skill": False, "install_hooks": False, "network": False,
                       "ci_generation": any(a["path"] == ".github/workflows/forvynx.yml" for a in actions)},
             "approval_notice": "Digest confirmation is a local audit convention, not proof of human approval."}
    return Plan.seal(value).validate().value


def make_action(root, name, before, after, owner):
    assert_owner(root, name, owner)
    diff = "".join(difflib.unified_diff((before or b"").decode("utf-8").splitlines(True), (after or b"").decode("utf-8").splitlines(True), fromfile=name, tofile=name))
    return {"root": str(root), "path": name, "owner": owner, "before": content_state(before), "after": content_state(after),
            "before_b64": encode(before), "content_b64": encode(after), "diff": diff}


def validate_boundaries(value, check_evidence=True):
    Plan(value).validate()
    workspace = absolute(value["workspace"])
    if str(state_directory(workspace)) != value["state_directory"]:
        raise ForvynxError("Unexpected local state directory")
    roots = {r["identity"]["root"]: r["identity"] for r in value["repositories"]}
    for root, expected in roots.items():
        if not within(workspace, absolute(root)) or identity(root) != expected:
            raise ForvynxError("Repository identity/scope changed")
    for action in value["actions"]:
        if action["root"] == str(workspace) and action["path"] == ".forvynx/workspace.json":
            expected = value["workspace_owner"]
        elif action["root"] in roots and action["path"] in REPO_PATHS:
            expected = roots[action["root"]]
        else:
            raise ForvynxError("Action is outside supported scope")
        if action["owner"] != expected:
            raise ForvynxError("Action owner does not match scope")
        assert_owner(action["root"], action["path"], expected)
    if check_evidence:
        validate_rendered(value)
    for check in value["checks"]:
        if check["root"] not in roots:
            raise ForvynxError("Check is outside selected checkouts")
        repo_action = next(a for a in value["actions"] if a["root"] == check["root"] and a["path"] == ".forvynx/repo.json")
        config = validate_config(json.loads(decode(repo_action["content_b64"])))
        expected = next((c for c in config["checks"] if c["id"] == check["id"]), None)
        if expected is None or any(check.get(k) != v for k, v in expected.items()):
            raise ForvynxError("Plan checks do not match proposed repository configuration")
    if not check_evidence:
        return workspace
    validate_registry(workspace)
    for check in value["checks"]:
        for source in check["source_states"]:
            planned = next((a for a in value["actions"] if a["root"] == check["root"] and a["path"] == source["path"]), None)
            actual = content_state(read_bytes(check["root"], source["path"]))
            if actual not in ([planned["before"], planned["after"]] if planned else [source["state"]]):
                raise ForvynxError("Check source changed since planning")
    for repo in value["repositories"]:
        for evidence in repo["evidence"]:
            # Planned writes use the action before/after states instead.
            if any(a["root"] == repo["identity"]["root"] and a["path"] == evidence["path"] for a in value["actions"]):
                continue
            if content_state(read_bytes(repo["identity"]["root"], evidence["path"])) != evidence["state"]:
                raise ForvynxError("Engineering evidence changed")
    return workspace


def validate_rendered(value):
    """Check the proposed bundle before any target write, not just after it."""
    by_root = {}
    for action in value["actions"]:
        by_root.setdefault(action["root"], {})[action["path"]] = action
        before, after = decode(action["before_b64"]), decode(action["content_b64"])
        if after is None:
            raise ForvynxError("Onboarding does not support file deletion")
        try:
            expected_diff = "".join(difflib.unified_diff((before or b"").decode("utf-8").splitlines(True), after.decode("utf-8").splitlines(True), fromfile=action["path"], tofile=action["path"]))
        except UnicodeError as exc:
            raise ForvynxError("Proposed bundle must preserve supported UTF-8 encoding") from exc
        if action["diff"] != expected_diff:
            raise ForvynxError("Review diff does not match proposed bytes")
    check_keys = set()
    for repo in value["repositories"]:
        root = repo["identity"]["root"]
        actions = by_root.get(root, {})
        required = {"AGENTS.md", ".forvynx/repo.json", ".forvynx/check.py", ".forvynx/workflow.md"}
        if not required <= set(actions):
            raise ForvynxError("Incomplete proposed repository bundle")
        config = validate_config(json.loads(decode(actions[".forvynx/repo.json"]["content_b64"])))
        if config["repo_id"] != repo["repo_id"] or config["profile"] != repo["profile"]:
            raise ForvynxError("Repository bundle identity/profile mismatch")
        expected_components = {".forvynx/check.py": CHECKER.read_bytes(), ".forvynx/workflow.md": workflow(repo["profile"])}
        if config.get("ci"):
            expected_components[".github/workflows/forvynx.yml"] = (PACKAGE / "assets/github-ci.yml").read_bytes()
        expected_paths = required | ({".github/workflows/forvynx.yml"} if config.get("ci") else set())
        if root == value["workspace"]:
            expected_paths.add(".forvynx/workspace.json")
        if set(actions) != expected_paths:
            raise ForvynxError("Unexpected/missing component in proposed bundle")
        if config["components"] != {k: sha(v) for k, v in expected_components.items()}:
            raise ForvynxError("Proposed components are not current product templates")
        for name, data in expected_components.items():
            if name not in actions or decode(actions[name]["content_b64"]) != data:
                raise ForvynxError("Proposed component bytes do not match product template")
        agents = actions["AGENTS.md"]
        if decode(agents["content_b64"]) != managed_agents(decode(agents["before_b64"])):
            raise ForvynxError("Proposed guidance would modify unmanaged text")
        planned_checks = [c for c in value["checks"] if c["root"] == root]
        if len(planned_checks) != len(config["checks"]):
            raise ForvynxError("Missing or duplicate planned checks")
        for check in planned_checks:
            key = repo["repo_id"] + ":" + check["id"]
            if check.get("key") != key or key in check_keys or [s["path"] for s in check["source_states"]] != check["sources"]:
                raise ForvynxError("Invalid planned check binding")
            check_keys.add(key)
    index = by_root.get(value["workspace"], {}).get(".forvynx/workspace.json")
    if index is None:
        raise ForvynxError("Missing workspace registry action")
    before = decode(index["before_b64"])
    expected_index = json.loads(before) if before is not None else {"schema_version": 1, "generator": "forvynx", "repositories": []}
    workspace = Path(value["workspace"])
    for repo in value["repositories"]:
        relative = Path(repo["identity"]["root"]).relative_to(workspace).as_posix()
        expected_index["repositories"] = [entry for entry in expected_index["repositories"] if entry["path"] != relative]
        expected_index["repositories"].append({"path": relative, "repo_id": repo["repo_id"], "status": "managed"})
    expected_index["repositories"].sort(key=lambda entry: entry["path"])
    if decode(index["content_b64"]) != json_bytes(expected_index):
        raise ForvynxError("Proposed registry would alter unrelated onboarding entries")
