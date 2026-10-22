"""Evidence-driven profile selection; no repository code is executed."""

import json
import tomllib
from pathlib import Path

from .boundary import read_bytes
from .domain import ForvynxError, sha

EVIDENCE_FILES = (
    "AGENTS.md", "pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini", "ruff.toml",
    ".ruff.toml", "package.json", "uv.lock", "poetry.lock", "requirements.txt", ".gitmodules",
)


def inspect_repo(root):
    evidence, warnings, findings = [], [], {}
    candidates = list(EVIDENCE_FILES)
    workflows = Path(root) / ".github" / "workflows"
    if workflows.exists():
        # The guarded reader rejects linked directories/files before reading them.
        from .boundary import guarded
        guarded(root, ".github/workflows")
        candidates.extend(p.relative_to(root).as_posix() for p in sorted(workflows.iterdir())[:16] if p.suffix in (".yml", ".yaml"))
    for name in candidates:
        try:
            data = read_bytes(root, name)
            if data is None:
                continue
            evidence.append({"path": name, "sha256": sha(data)})
            if name == "pyproject.toml":
                findings["python"] = tomllib.loads(data.decode("utf-8"))
            if name == "package.json":
                findings["package"] = json.loads(data)
        except (ForvynxError, UnicodeError, ValueError) as exc:
            warnings.append({"path": name, "reason": str(exc)})
    python = findings.get("python")
    suggestions = []
    if python is not None:
        tools = python.get("tool", {})
        for name, argv in (("pytest", ["$PYTHON", "-m", "pytest"]), ("ruff", ["$PYTHON", "-m", "ruff", "check", "."]), ("mypy", ["$PYTHON", "-m", "mypy", "."])):
            if name in tools:
                suggestions.append({"tool": name, "argv": argv, "source": "pyproject.toml", "status": "candidate_only"})
    return {"profile": "python" if python is not None else "generic", "evidence": evidence,
            "suggested_checks": suggestions, "warnings": warnings,
            "notes": ["No scripts or dependencies executed; suggestions require review."]}


def workflow(profile):
    return ("# AI coding workflow\n\n"
            "Read the applicable engineering guidance and task-relevant files.\n"
            "For substantial features or structural changes, agree on goals, boundaries,\n"
            "interfaces, tradeoffs, and acceptance criteria before implementation.\n"
            "For small changes, keep the process proportional and run relevant checks.\n"
            "Preserve dirty work and existing conventions; do not add dependencies,\n"
            "onboard other checkouts, or enable hooks without scoped authorization.\n"
            "Report checks as passed, failed, not_run, or unsupported; skipped required\n"
            "checks are not success. Multi-repository changes need per-checkout results.\n\n"
            f"Detected profile: {profile}. Use the reviewed commands in repo.json;\n"
            "discovery does not authorize their execution.\n").encode("utf-8")
