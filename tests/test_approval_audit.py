"""Approval audit facts in temporary repositories, without changing authorization."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.dont_write_bytecode = True
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "skills/forvynx/scripts"))

from forvynx_lib.apply import apply_plan, journal_path, rollback
from forvynx_lib.boundary import state_directory
from forvynx_lib.domain import ForvynxError
from forvynx_lib.plan import build_plan
from forvynx_lib.probe import probe


class ApprovalAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="forvynx-audit-")
        self.workspace = Path(self.temp.name).resolve()
        self.git_env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}

    def tearDown(self):
        folder = state_directory(self.workspace)
        expected = Path(tempfile.gettempdir()).resolve() / "forvynx-state"
        if folder.parent == expected and folder.exists():
            shutil.rmtree(folder)
        self.temp.cleanup()

    def repo(self, name):
        folder = self.workspace / name
        folder.mkdir()
        subprocess.run(["git", "-C", str(folder), "init", "-q"], env=self.git_env, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        return folder

    def plan(self, paths, **options):
        return build_plan(probe(self.workspace), {"repositories": [{"path": p, **options} for p in paths]})

    def journal(self, value):
        folder, name = journal_path(value)
        return folder / name

    def snapshot(self, folder):
        return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}

    def test_new_journal_records_actual_utc_time_and_exact_selected_scope(self):
        self.repo("a")
        self.repo("b")
        value = self.plan(("b", "a"), ci=True)
        earliest = datetime.now(timezone.utc)
        result = apply_plan(value, value["digest"])
        latest = datetime.now(timezone.utc)
        self.assertEqual(result["status"], "applied")
        report = json.loads(self.journal(value).read_bytes())
        approval = report["approval"]
        recorded = datetime.fromisoformat(approval["recorded_at"])
        self.assertIsNotNone(recorded.tzinfo)
        self.assertEqual(recorded.utcoffset(), timedelta(0))
        self.assertLessEqual(earliest, recorded)
        self.assertLessEqual(recorded, latest)
        self.assertNotIn("approved_at", approval)
        self.assertIn("not the time of human approval", approval["recorded_at_notice"])
        self.assertEqual(approval["digest"], value["digest"])
        self.assertEqual(approval["source"], "manual_digest_confirmation")
        self.assertEqual(approval["scope"], value["scope"])
        self.assertEqual(approval["repository_ids"], sorted(r["repo_id"] for r in value["repositories"]))

    def test_new_scope_and_selection_do_not_expand_previous_approval(self):
        first_root, second_root = self.repo("a"), self.repo("b")
        first = self.plan(("a",))
        apply_plan(first, first["digest"])
        first_journal = self.journal(first).read_bytes()
        second = self.plan(("b",), ci=True)
        apply_plan(second, second["digest"])
        first_approval = json.loads(first_journal)["approval"]
        second_approval = json.loads(self.journal(second).read_bytes())["approval"]
        self.assertFalse(first_approval["scope"]["ci_generation"])
        self.assertTrue(second_approval["scope"]["ci_generation"])
        for value, approval in ((first, first_approval), (second, second_approval)):
            self.assertEqual(approval["scope"], value["scope"])
            self.assertEqual(approval["repository_ids"], [value["repositories"][0]["repo_id"]])
            for permission in ("install_skill", "install_hooks", "network"):
                self.assertFalse(approval["scope"][permission])
        self.assertNotEqual(first_approval["repository_ids"], second_approval["repository_ids"])
        self.assertEqual(self.journal(first).read_bytes(), first_journal)
        self.assertFalse((first_root / ".github/workflows/forvynx.yml").exists())
        self.assertTrue((second_root / ".github/workflows/forvynx.yml").is_file())

    def test_no_change_replay_preserves_journal_bytes_and_recording_time(self):
        self.repo("a")
        value = self.plan(("a",))
        apply_plan(value, value["digest"])
        journal = self.journal(value)
        before, modified = journal.read_bytes(), journal.stat().st_mtime_ns
        state_before = self.snapshot(journal.parent)
        workspace_before = self.snapshot(self.workspace)
        self.assertEqual(apply_plan(value, value["digest"])["status"], "no_change")
        self.assertEqual(journal.read_bytes(), before)
        self.assertEqual(journal.stat().st_mtime_ns, modified)
        self.assertEqual(self.snapshot(journal.parent), state_before)
        self.assertEqual(self.snapshot(self.workspace), workspace_before)

    def test_new_no_change_plan_does_not_create_an_audit(self):
        self.repo("a")
        first = self.plan(("a",))
        apply_plan(first, first["digest"])
        second = self.plan(("a",))
        self.assertNotEqual(first["digest"], second["digest"])
        self.assertFalse(self.journal(second).exists())
        before = self.snapshot(self.journal(first).parent)
        self.assertEqual(apply_plan(second, second["digest"])["status"], "no_change")
        self.assertFalse(self.journal(second).exists())
        self.assertEqual(self.snapshot(self.journal(first).parent), before)

    def test_missing_confirmation_writes_no_targets_or_audit(self):
        self.repo("a")
        value = self.plan(("a",))
        before = self.snapshot(self.workspace)
        with self.assertRaises(ForvynxError) as error:
            apply_plan(value, None)
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(self.snapshot(self.workspace), before)
        self.assertFalse(state_directory(self.workspace).exists())

    def test_rollback_keeps_the_original_approval_record(self):
        self.repo("a")
        value = self.plan(("a",))
        apply_plan(value, value["digest"])
        original = json.loads(self.journal(value).read_bytes())["approval"]
        self.assertEqual(rollback(value, value["digest"])["status"], "rolled_back")
        self.assertEqual(json.loads(self.journal(value).read_bytes())["approval"], original)
        before = self.journal(value).read_bytes()
        self.assertEqual(rollback(value, value["digest"])["status"], "no_change")
        self.assertEqual(self.journal(value).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
