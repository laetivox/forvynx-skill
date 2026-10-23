"""Small real fixtures for discovery budgets and observable read-only behavior."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/forvynx/scripts"))

from forvynx_lib.boundary import GIT, state_directory
from forvynx_lib.probe import probe

CLI = ROOT / "skills/forvynx/scripts/forvynx.py"


@unittest.skipUnless(GIT, "Git is required for real discovery fixtures")
class ProbeLimitsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="forvynx-probe-limits-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve() / "workspace"
        self.workspace.mkdir()
        self.empty_template = Path(self.temp.name) / "empty-git-template"
        self.empty_template.mkdir()
        self.git_env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }

    @staticmethod
    def snapshot(root):
        """Capture names, bytes and write timestamps, including Git metadata."""
        if not root.exists():
            return None
        result = {}
        for path in [root, *root.rglob("*")]:
            relative = path.relative_to(root).as_posix()
            info = path.stat()
            if path.is_dir():
                result[relative] = ("directory", info.st_mtime_ns, info.st_mode)
            else:
                result[relative] = (
                    "file", info.st_mtime_ns, info.st_mode,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
        return result

    def read_only_call(self, action):
        state_root = state_directory(self.workspace)
        workspace_before = self.snapshot(self.workspace)
        state_before = self.snapshot(state_root)
        try:
            return action()
        finally:
            self.assertEqual(self.snapshot(self.workspace), workspace_before,
                             "Discovery changed fixture paths, bytes or write timestamps")
            self.assertEqual(self.snapshot(state_root), state_before,
                             "Discovery changed its local state directory")

    def make_repo(self, relative):
        root = self.workspace / relative
        root.mkdir(parents=True, exist_ok=True)
        self.git(root, "init", "-q", "--template", str(self.empty_template))
        (root / "README.md").write_text("Small local discovery fixture.\n", encoding="utf-8")
        self.git(root, "add", "README.md")
        return root

    def git(self, root, *args):
        return subprocess.run(
            [GIT, "-C", str(root), *args], env=self.git_env, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
        )

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", str(CLI), "probe", "--workspace", str(self.workspace), *args],
            cwd=self.temp.name, env=self.git_env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )

    def test_raw_entry_budget_is_shared_across_directories(self):
        for name in ("a", "b"):
            folder = self.workspace / name
            folder.mkdir()
            for index in range(4):
                (folder / f"file-{index}.txt").write_bytes(b"fixture\n")
        excluded = self.workspace / "node_modules"
        excluded.mkdir()
        (excluded / "must-not-be-enumerated.txt").write_bytes(b"excluded subtree\n")

        limited = self.read_only_call(
            lambda: probe(self.workspace, max_dirs=20, max_entries=5)
        )
        self.assertFalse(limited["complete"])
        self.assertEqual(limited["limits"]["max_entries"], 5)
        self.assertEqual(limited["enumerated_entries"], 5)
        self.assertLess(limited["visited_directories"], 20)
        self.assertEqual(limited["errors"], [])

        enough = self.read_only_call(
            lambda: probe(self.workspace, max_dirs=20, max_entries=20)
        )
        self.assertTrue(enough["complete"])
        # Three root entries (including node_modules), plus four files in each
        # eligible child directory. The excluded subtree itself is not scanned.
        self.assertEqual(enough["enumerated_entries"], 11)
        self.assertEqual(enough["visited_directories"], 3)

    def test_wide_tree_keeps_pending_directories_within_directory_budget(self):
        for branch in range(8):
            folder = self.workspace / f"branch-{branch}"
            folder.mkdir()
            for leaf in range(8):
                (folder / f"leaf-{leaf}").mkdir()

        inventory = self.read_only_call(
            lambda: probe(self.workspace, max_depth=3, max_dirs=6, max_entries=200)
        )
        self.assertFalse(inventory["complete"])
        self.assertEqual(inventory["visited_directories"], 6)
        self.assertGreater(inventory["peak_pending_directories"], 0)
        self.assertLessEqual(inventory["peak_pending_directories"], 6)
        self.assertLess(inventory["enumerated_entries"], 200)
        self.assertEqual(inventory["errors"], [])

    def test_sufficient_budgets_keep_nested_repositories_as_separate_candidates(self):
        parent = self.make_repo("parent")
        nested = self.make_repo("parent/nested")

        inventory = self.read_only_call(
            lambda: probe(self.workspace, max_depth=3, max_dirs=20, max_entries=200)
        )
        self.assertTrue(inventory["complete"])
        self.assertEqual(inventory["errors"], [])
        self.assertEqual(
            [repo["relative_path"] for repo in inventory["repositories"]],
            ["parent", "parent/nested"],
        )
        self.assertEqual(
            {repo["identity"]["root"] for repo in inventory["repositories"]},
            {str(parent), str(nested)},
        )
        self.assertLess(inventory["enumerated_entries"], 200)
        self.assertLessEqual(inventory["peak_pending_directories"], 20)

    def test_cli_entry_limit_reports_incomplete_and_rejects_zero(self):
        for index in range(3):
            (self.workspace / f"file-{index}.txt").write_bytes(b"fixture\n")

        limited = self.read_only_call(lambda: self.cli("--max-entries", "1"))
        self.assertEqual(limited.returncode, 2, limited.stderr.decode(errors="replace"))
        inventory = json.loads(limited.stdout)
        self.assertFalse(inventory["complete"])
        self.assertEqual(inventory["limits"]["max_entries"], 1)
        self.assertEqual(inventory["enumerated_entries"], 1)

        invalid = self.read_only_call(lambda: self.cli("--max-entries", "0"))
        self.assertEqual(invalid.returncode, 2, invalid.stderr.decode(errors="replace"))
        blocked = json.loads(invalid.stdout)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["exit_code"], 2)
        self.assertIn("limit", blocked["reason"].lower())
        self.assertNotIn("repositories", blocked)


if __name__ == "__main__":
    unittest.main()
