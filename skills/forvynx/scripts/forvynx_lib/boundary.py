"""Filesystem and read-only Git adapter. All repository reads use this boundary."""

import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from .domain import ForvynxError, content_state, sha

MAX_FILE = 2 * 1024 * 1024
GIT = shutil.which("git")


def is_link(path):
    try:
        info = path.lstat()
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def absolute(path):
    path = Path(os.path.abspath(path))
    for parent in reversed((path, *path.parents)):
        if is_link(parent):
            raise ForvynxError(f"Link/reparse path is not supported: {parent}")
    return path.resolve()


def relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise ForvynxError("Expected a portable relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..", ".git") for p in value.split("/")):
        raise ForvynxError(f"Unsafe path: {value}")
    for part in path.parts:
        if part.endswith((".", " ")) or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part, re.I):
            raise ForvynxError(f"Reserved path: {value}")
    return path


def within(root, path):
    try:
        path.relative_to(root)
    except ValueError:
        return False
    # samefile handles case-sensitive Windows directories and aliases correctly.
    return any(p.exists() and os.path.samefile(p, root) for p in (path, *path.parents))


def guarded(root, relative):
    root = absolute(root)
    path = absolute(root.joinpath(*relative_path(relative).parts))
    if not within(root, path):
        raise ForvynxError(f"Path escapes root: {relative}")
    return path


def read_bytes(root, relative):
    path = guarded(root, relative)
    try:
        if path.stat().st_size > MAX_FILE:
            raise ForvynxError(f"File exceeds {MAX_FILE} bytes: {path}", 5)
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ForvynxError(f"Cannot read {path}: {exc}", 5) from exc


def state(root, relative):
    return content_state(read_bytes(root, relative))


def git(directory, *args, check=True):
    if not GIT:
        raise ForvynxError("Git is unavailable", 5)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", LC_ALL="C", LANG="C")
    try:
        result = subprocess.run(
            [GIT, "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-C", str(directory), *args],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ForvynxError(f"Git query failed: {exc}", 5) from exc
    if check and result.returncode:
        raise ForvynxError(result.stderr.decode("utf-8", "replace").strip(), 5)
    return result


def identity(directory):
    directory = absolute(directory)
    while not directory.exists():
        directory = directory.parent
    if directory.is_file():
        directory = directory.parent
    result = git(directory, "rev-parse", "--show-toplevel", check=False)
    if result.returncode:
        if b"not a git repository" in result.stderr:
            if (directory / ".git").exists() or is_link(directory / ".git"):
                raise ForvynxError(f"Invalid Git metadata at {directory / '.git'}", 5)
            return None
        raise ForvynxError(result.stderr.decode("utf-8", "replace").strip(), 5)
    root = absolute(os.fsdecode(result.stdout.strip()))
    meta = git(directory, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir")
    git_dir, common_dir = meta.stdout.decode("utf-8").strip().splitlines()
    return {"root": str(root), "git_dir": str(Path(git_dir).resolve()), "common_dir": str(Path(common_dir).resolve())}


def assert_owner(root, relative, expected):
    target = guarded(root, relative)
    actual = identity(target.parent)
    if actual != expected:
        raise ForvynxError(f"Checkout boundary changed at {target}")
    return target


def atomic_write(root, relative, data):
    path = guarded(root, relative)
    if data is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path = guarded(root, relative)
    fd, name = tempfile.mkstemp(prefix=".forvynx-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if path.exists():
            os.chmod(name, stat.S_IMODE(path.stat().st_mode))
        os.replace(name, guarded(root, relative))
    finally:
        if os.path.exists(name):
            # Preserving a Windows target's mode may leave staging read-only.
            info = os.lstat(name)
            if (os.name == "nt" and stat.S_ISREG(info.st_mode)
                    and not getattr(info, "st_file_attributes", 0) & 0x400):
                os.chmod(name, stat.S_IREAD | stat.S_IWRITE)
            os.unlink(name)


def state_directory(workspace):
    # Machine-specific receipts and backups never enter a repository or its index.
    return absolute(Path(tempfile.gettempdir()) / "forvynx-state" / sha(str(absolute(workspace)).encode()))


def private_directory(path):
    """Create runtime state beneath OS temp without exposing POSIX audit data."""
    base = absolute(tempfile.gettempdir())
    path = absolute(path)
    relative = path.relative_to(base)
    if not relative.parts or relative.parts[0] not in ("forvynx-state", "forvynx-locks"):
        raise ForvynxError("Unexpected runtime state root")
    current = base
    for part in relative.parts:
        current = absolute(current / part)
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        info = current.stat()
        if not stat.S_ISDIR(info.st_mode):
            raise ForvynxError("Runtime state must be a directory")
        if os.name == "posix" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
            raise ForvynxError("Runtime state must be private to the current user")
