"""Build the local Forvynx Skill as a deterministic, inspectable ZIP."""

import hashlib
import json
import stat
import zipfile
from pathlib import Path


def build(output=None):
    root = Path(__file__).resolve().parents[1]
    skill = root / "skills/forvynx"
    output = Path(output) if output else root / "dist/forvynx-0.1.0.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(skill.rglob("*")):
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError("Skill package must not contain links")
            if not path.is_file():
                continue
            info = zipfile.ZipInfo("forvynx/" + path.relative_to(skill).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, path.read_bytes())
    return {"path": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "bytes": output.stat().st_size}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
