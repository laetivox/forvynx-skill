"""Preview manual hook integration; never install or change Git configuration."""

import shlex
import sys
from pathlib import Path

from .boundary import git
from .domain import ForvynxError, Plan, encode, sha
from .plan import CHECKER, validate_boundaries


def preview_hook(value, repo_id):
    Plan(value).validate()
    validate_boundaries(value)
    repo = next((r for r in value["repositories"] if r["repo_id"] == repo_id), None)
    if repo is None:
        raise ForvynxError("Unknown selected repository ID", 2)
    root = repo["identity"]["root"]
    configured = git(root, "config", "--get", "core.hooksPath", check=False)
    active = git(root, "rev-parse", "--path-format=absolute", "--git-path", "hooks/pre-commit").stdout.decode().strip()
    snapshot = Path(value["state_directory"]) / "hooks" / repo_id / "check.py"
    expected = sha(CHECKER.read_bytes())
    code = ("import hashlib,pathlib,runpy,sys;"
            f"p=pathlib.Path({str(snapshot)!r});"
            f"actual=hashlib.sha256(p.read_bytes()).hexdigest();"
            f"sys.exit('Forvynx checker changed; review integration') if actual!={expected!r} else None;"
            f"sys.argv=[str(p),'--root',{root!r},'--source','index'];"
            "runpy.run_path(str(p),run_name='__main__')")
    script = "#!/bin/sh\n# Forvynx preview: review existing hooks; do not overwrite blindly.\nexec " + " ".join(shlex.quote(x) for x in [sys.executable.replace("\\", "/"), "-I", "-B", "-c", code]) + "\n"
    return {"status": "preview_only", "repo_id": repo_id, "active_hook_path": active,
            "existing_hook": Path(active).exists(), "core_hooks_path": configured.stdout.decode().strip() or None,
            "shared_metadata": repo["identity"]["git_dir"] != repo["identity"]["common_dir"],
            "checker_snapshot_path": str(snapshot), "checker_content_b64": encode(CHECKER.read_bytes()),
            "checker_sha256": expected, "hook_script": script,
            "activation": "manual integration and execution test required; no files written; no Git configuration changed"}
