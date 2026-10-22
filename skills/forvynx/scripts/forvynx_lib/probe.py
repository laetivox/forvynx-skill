"""Bounded discovery of checkouts in a possibly non-Git workspace."""

import json
import os
from collections import deque

from . import VERSION
from .adapters import inspect_repo
from .boundary import GIT, absolute, git, identity, is_link, read_bytes, state_directory, within
from .domain import ForvynxError

EXCLUDED = {".git", ".forvynx", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "vendor", ".cache", ".tox"}


def probe(workspace, max_depth=3, max_dirs=5000):
    if max_depth < 0 or max_dirs < 1:
        raise ForvynxError("Invalid scan limits", 2)
    root = absolute(workspace)
    if not root.is_dir():
        raise ForvynxError("Workspace must be an accessible directory", 5)
    result = {"schema_version": 1, "version": VERSION, "workspace": str(root),
              "limits": {"max_depth": max_depth, "max_dirs": max_dirs}, "complete": True,
              "repositories": [], "external_repository": None, "errors": [], "skipped_links": [],
              "capabilities": {"git": bool(GIT)}}
    result["recovery"] = []
    state_root = state_directory(root)
    if state_root.exists():
        for journal in state_root.glob("*.json"):
            try:
                record = json.loads(read_bytes(state_root, journal.name))
                if record.get("status") in ("applying", "partial", "conflict"):
                    result["recovery"].append({"journal": str(journal), "status": record["status"]})
            except (OSError, ValueError, ForvynxError) as exc:
                result["errors"].append({"path": str(journal), "reason": str(exc)})
                result["complete"] = False
    if not GIT:
        result["complete"] = False
        result["errors"].append({"path": str(root), "reason": "Git unavailable"})
        return result
    found, queue, visited = set(), deque([(root, 0)]), 0
    while queue:
        if visited >= max_dirs:
            result["complete"] = False
            break
        folder, depth = queue.popleft()
        visited += 1
        try:
            if folder == root or (folder / ".git").exists():
                repo = identity(folder)
                if repo and not within(root, absolute(repo["root"])):
                    result["external_repository"] = repo
                elif repo and repo["root"] not in found:
                    found.add(repo["root"])
                    details = inspect_repo(repo["root"])
                    dirty = git(repo["root"], "status", "--porcelain=v1", "--untracked-files=normal").stdout
                    result["repositories"].append({"identity": repo, "relative_path": absolute(repo["root"]).relative_to(root).as_posix(),
                                                   "dirty": bool(dirty), **details})
            with os.scandir(folder) as entries:
                children = []
                for entry in entries:
                    if len(children) == max_dirs:
                        result["complete"] = False
                        break
                    children.append(entry)
                children.sort(key=lambda p: p.name)
            for child in children:
                if child.name in EXCLUDED:
                    continue
                if is_link(folder / child.name):
                    result["skipped_links"].append(str(folder / child.name))
                    continue
                if not child.is_dir(follow_symlinks=False):
                    continue
                if depth == max_depth:
                    result["complete"] = False
                else:
                    queue.append((folder / child.name, depth + 1))
        except (OSError, ForvynxError) as exc:
            result["complete"] = False
            result["errors"].append({"path": str(folder), "reason": str(exc)})
    result["visited_directories"] = visited
    result["repositories"].sort(key=lambda r: r["relative_path"])
    return result
