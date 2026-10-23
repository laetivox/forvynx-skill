"""Real Windows read-only attribute failures in isolated temporary fixtures."""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/forvynx/scripts"))

from forvynx_lib.apply import apply_plan, journal_path, rollback
from forvynx_lib.boundary import state_directory
from forvynx_lib.domain import ForvynxError
from forvynx_lib.plan import build_plan
from forvynx_lib.probe import probe
from forvynx_lib.verify import verify


@unittest.skipUnless(os.name == "nt", "Windows read-only attribute scenario")
class WindowsReadOnlyTest(unittest.TestCase):
    def test_readonly_agents_failure_compensates_and_retry_leaves_no_temporary_files(self):
        temp = tempfile.TemporaryDirectory(prefix="forvynx-windows-readonly-")
        workspace = Path(temp.name).resolve()
        root = workspace / "repo"
        root.mkdir()
        agents = root / "AGENTS.md"
        agents_mode = None
        try:
            git_env = {
                **os.environ,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull,
            }
            subprocess.run(
                ["git", "-C", str(root), "init", "-q"],
                env=git_env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            agents.write_bytes(b"# Existing project rules\nKeep user-owned guidance.\n")
            (root / "user-sentinel.txt").write_bytes(b"User-owned bytes must survive.\n")
            check = {"id": "unit", "argv": ["$PYTHON", "-c", "pass"]}

            def plan(definition):
                return build_plan(probe(workspace), {
                    "repositories": [{"path": "repo", "checks": [definition]}],
                })

            def snapshot():
                return {
                    path.relative_to(workspace).as_posix(): path.read_bytes()
                    for path in workspace.rglob("*")
                    if path.is_file() and ".git" not in path.relative_to(workspace).parts
                }

            first = plan(check)
            self.assertEqual(apply_plan(first, first["digest"])["status"], "applied")
            before = snapshot()
            second = plan({**check, "argv": ["$PYTHON", "-c", "print('updated check')"]})
            config_action = next(
                action for action in second["actions"]
                if action["root"] == str(root) and action["path"] == ".forvynx/repo.json"
            )
            self.assertNotEqual(config_action["before"], config_action["after"])
            agents_action = next(action for action in second["actions"] if action["path"] == "AGENTS.md")
            self.assertEqual(agents_action["before"], agents_action["after"])

            # Attribute changes occur after planning; file contents remain unchanged.
            agents_mode = stat.S_IMODE(agents.stat().st_mode)
            agents.chmod(stat.S_IREAD)
            self.assertTrue(agents.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY)
            self.assertEqual(snapshot(), before)

            with self.assertRaises(ForvynxError) as error:
                apply_plan(second, second["digest"])
            self.assertEqual(error.exception.code, 4)
            self.assertIsInstance(error.exception.__cause__, PermissionError)
            folder, name = journal_path(second)
            journal = json.loads((folder / name).read_bytes())
            after_failure = snapshot()
            residuals = sorted(workspace.rglob(".forvynx-*"))
            observation = {
                "scenario": "windows_readonly_attribute_after_plan",
                "failure_type": type(error.exception.__cause__).__name__,
                "failure": str(error.exception),
                "underlying_failure": str(error.exception.__cause__),
                "journal_status": journal["status"],
                "journal_failure": journal.get("failure"),
                "journal_completed": journal.get("completed"),
                "journal_attempting": journal.get("attempting"),
                "preexisting_bytes_preserved": all(after_failure.get(path) == data for path, data in before.items()),
                "residual_temporary_files": [
                    {
                        "path": path.relative_to(workspace).as_posix(),
                        "readonly": bool(path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                    for path in residuals
                ],
            }
            print(json.dumps(observation, ensure_ascii=False), flush=True)
            self.assertEqual(journal["status"], "rolled_back")
            self.assertEqual(journal.get("conflicts"), [])
            self.assertEqual(
                {path: after_failure.get(path) for path in before}, before,
                "Compensation must preserve every preexisting file's bytes",
            )

            # Restore only the fixture's attribute, then exercise normal recovery/retry.
            agents.chmod(agents_mode)
            self.assertEqual(rollback(second, second["digest"])["status"], "no_change")
            retried = apply_plan(second, second["digest"])
            self.assertEqual(retried["status"], "applied")
            self.assertEqual(verify(second)["structure"], "passed")
            remaining = sorted(workspace.rglob(".forvynx-*"))
            print(json.dumps({
                "retry_status": retried["status"],
                "structure": "passed",
                "remaining_temporary_files": [path.relative_to(workspace).as_posix() for path in remaining],
            }, ensure_ascii=False), flush=True)
            self.assertEqual(
                remaining, [],
                "Failed atomic replacement must not leave temporary files in the checkout",
            )
        finally:
            if agents_mode is not None and agents.exists():
                agents.chmod(agents_mode)
            # Observe leftovers above before making fixture-owned files removable.
            for path in workspace.rglob(".forvynx-*"):
                resolved = path.resolve()
                self.assertTrue(resolved.is_relative_to(workspace))
                if path.is_file():
                    path.chmod(stat.S_IREAD | stat.S_IWRITE)
            folder = state_directory(workspace)
            expected_parent = Path(tempfile.gettempdir()).resolve() / "forvynx-state"
            self.assertEqual(folder.parent, expected_parent)
            if folder.exists():
                shutil.rmtree(folder)
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
