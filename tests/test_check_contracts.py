"""Independent check declaration/report contracts in small local Git fixtures."""

import base64
import copy
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/forvynx/scripts"))

from forvynx_lib import portable
from forvynx_lib.apply import apply_plan, journal_path
from forvynx_lib.boundary import GIT, atomic_write, state_directory
from forvynx_lib.domain import ForvynxError, Plan
from forvynx_lib.plan import build_plan
from forvynx_lib.probe import probe
from forvynx_lib.verify import verify

DEFAULT_REVIEW = {
    "dependencies": None, "network": "unknown", "writes": "unknown", "notes": [],
}
REPORT_FIELDS = {
    "id", "key", "root", "argv", "cwd", "required", "status", "exit_code",
    "duration_ms", "reason", "output", "log_ref", "review", "definition_sha256",
}


@unittest.skipUnless(GIT, "Git is required for local contract fixtures")
class CheckContractsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="forvynx-contracts-")
        self.workspace = Path(self.temp.name).resolve() / "workspace"
        self.repo = self.workspace / "repo"
        self.repo.mkdir(parents=True)
        template = Path(self.temp.name) / "empty-template"
        template.mkdir()
        self.git_env = {
            **os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull, "GIT_TERMINAL_PROMPT": "0",
        }
        subprocess.run(
            [GIT, "-C", str(self.repo), "init", "-q", "--template", str(template)],
            env=self.git_env, check=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=20,
        )
        (self.repo / "README.md").write_text("Local fixture.\n", encoding="utf-8")
        self.addCleanup(self.cleanup_fixture)

    def cleanup_fixture(self):
        state_root = state_directory(self.workspace)
        expected_parent = Path(tempfile.gettempdir()).resolve() / "forvynx-state"
        if state_root.parent != expected_parent:
            raise AssertionError("Refusing cleanup outside the fixture state root")
        if state_root.exists():
            shutil.rmtree(state_root)
        self.temp.cleanup()

    @staticmethod
    def check(check_id="unit", **changes):
        value = {
            "id": check_id, "argv": ["$PYTHON", "-B", "-c", "pass"],
            "cwd": ".", "timeout": 2, "env": {}, "required": True, "sources": [],
        }
        value.update(changes)
        return value

    def plan(self, checks=None):
        selection = {"path": "repo"}
        if checks is not None:
            selection["checks"] = checks
        return build_plan(probe(self.workspace), {"repositories": [selection]})

    @staticmethod
    def proposed_config(value):
        action = next(a for a in value["actions"] if a["path"] == ".forvynx/repo.json")
        return json.loads(base64.b64decode(action["content_b64"]))

    @staticmethod
    def replace_proposed_config(value, config):
        """Rebuild payload/hash/diff independently, then let the caller re-seal."""
        action = next(a for a in value["actions"] if a["path"] == ".forvynx/repo.json")
        payload = (json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        before = base64.b64decode(action["before_b64"]) if action["before_b64"] else b""
        action["content_b64"] = base64.b64encode(payload).decode("ascii")
        action["after"] = {"kind": "file", "sha256": hashlib.sha256(payload).hexdigest()}
        action["diff"] = "".join(difflib.unified_diff(
            before.decode().splitlines(True), payload.decode().splitlines(True),
            fromfile=action["path"], tofile=action["path"],
        ))

    @staticmethod
    def snapshot(root, files_only=False):
        if not root.exists():
            return None
        return {
            path.relative_to(root).as_posix(): (
                ("file", hashlib.sha256(path.read_bytes()).hexdigest())
                if path.is_file() else ("directory",)
            )
            for path in root.rglob("*") if not files_only or path.is_file()
        }

    def assert_report(self, result, check, status, key=None):
        self.assertTrue(REPORT_FIELDS <= result.keys(), REPORT_FIELDS - result.keys())
        self.assertEqual(result["id"], check["id"])
        self.assertEqual(result["key"], key)
        self.assertEqual(result["root"], str(self.repo))
        self.assertEqual(result["argv"], [sys.executable if a == "$PYTHON" else a for a in check["argv"]])
        expected_cwd = self.repo if check["cwd"] == "." else self.repo / check["cwd"]
        self.assertEqual(result["cwd"], str(expected_cwd))
        self.assertEqual(result["required"], check["required"])
        self.assertEqual(result["status"], status)
        self.assertIsInstance(result["duration_ms"], int)
        self.assertGreaterEqual(result["duration_ms"], 0)
        self.assertEqual(result["output"], "not_recorded")
        self.assertIsNone(result["log_ref"])
        self.assertEqual(result["review"], check.get("review", DEFAULT_REVIEW))
        self.assertRegex(result["definition_sha256"], r"^[0-9a-f]{64}$")
        if status in ("not_run", "unsupported"):
            self.assertIsNone(result["exit_code"])
            self.assertEqual(result["duration_ms"], 0)

    def test_default_legacy_validation_and_omitted_selection_preserve_review(self):
        default_plan = self.plan([self.check()])
        config = self.proposed_config(default_plan)
        self.assertEqual(default_plan["checks"][0]["review"], DEFAULT_REVIEW)
        self.assertEqual(config["checks"][0]["review"], DEFAULT_REVIEW)
        legacy = copy.deepcopy(config)
        del legacy["checks"][0]["review"]
        before_validation = copy.deepcopy(legacy)
        portable.validate_config(legacy)
        self.assertEqual(legacy, before_validation, "Legacy validation mutated its input")

        declared = {
            "dependencies": ["Python 3.11+", "Local fixture files"],
            "network": "none", "writes": "possible", "notes": ["Writes only in the fixture."],
        }
        custom_plan = self.plan([self.check(review=declared)])
        apply_plan(custom_plan, custom_plan["digest"])
        inherited = self.plan()
        self.assertEqual(inherited["checks"][0]["review"], declared)
        self.assertEqual(self.proposed_config(inherited)["checks"][0]["review"], declared)

    def test_invalid_review_schema_is_rejected_before_target_writes(self):
        baseline = self.plan([self.check()])
        valid = copy.deepcopy(DEFAULT_REVIEW)
        boundary_valid = self.proposed_config(baseline)
        boundary_valid["checks"][0]["review"] = {
            "dependencies": [f"{i:02d}" + "d" * 798 for i in range(16)],
            "network": "possible", "writes": "none",
            "notes": [f"{i:02d}" + "n" * 798 for i in range(16)],
        }
        portable.validate_config(boundary_valid)
        empty_valid = self.proposed_config(baseline)
        empty_valid["checks"][0]["review"] = {**valid, "dependencies": []}
        portable.validate_config(empty_valid)
        invalid_reviews = [None, [], {}, {**valid, "extra": "unknown"}]
        missing = copy.deepcopy(valid)
        del missing["notes"]
        invalid_reviews.append(missing)
        for field in ("dependencies", "notes"):
            for invalid in ("scalar", [""], [" "], ["line\nbreak"], ["tab\tvalue"], [7],
                            ["x" * 801], [str(i) for i in range(17)], ["duplicate", "duplicate"]):
                invalid_reviews.append({**valid, field: invalid})
        invalid_reviews.extend([
            {**valid, "notes": None}, {**valid, "network": "yes"},
            {**valid, "network": True}, {**valid, "writes": "sometimes"},
        ])
        before = self.snapshot(self.workspace)
        state_before = self.snapshot(state_directory(self.workspace))
        for review in invalid_reviews:
            with self.subTest(review=review):
                config = self.proposed_config(baseline)
                config["checks"][0]["review"] = copy.deepcopy(review)
                with self.assertRaises((ValueError, TypeError)):
                    portable.validate_config(config)
                with self.assertRaises(ForvynxError):
                    self.plan([self.check(review=review)])

                malformed = copy.deepcopy(baseline)
                malformed["checks"][0]["review"] = copy.deepcopy(review)
                self.replace_proposed_config(malformed, config)
                malformed = Plan.seal(malformed).validate().value
                writer = Mock(side_effect=AssertionError("Invalid review reached target writes"))
                with self.assertRaises(ForvynxError):
                    apply_plan(malformed, malformed["digest"], writer=writer)
                writer.assert_not_called()
                self.assertEqual(self.snapshot(self.workspace), before)
                self.assertEqual(self.snapshot(state_directory(self.workspace)), state_before)

        empty_env = {"": "value"}
        config = self.proposed_config(baseline)
        config["checks"][0]["env"] = empty_env
        with self.assertRaises((ValueError, TypeError)):
            portable.validate_config(config)
        with self.assertRaises(ForvynxError):
            self.plan([self.check(env=empty_env)])
        malformed = copy.deepcopy(baseline)
        malformed["checks"][0]["env"] = empty_env
        self.replace_proposed_config(malformed, config)
        malformed = Plan.seal(malformed).validate().value
        writer = Mock(side_effect=AssertionError("Empty environment name reached target writes"))
        with self.assertRaises(ForvynxError):
            apply_plan(malformed, malformed["digest"], writer=writer)
        writer.assert_not_called()
        self.assertEqual(self.snapshot(self.workspace), before)
        self.assertEqual(self.snapshot(state_directory(self.workspace)), state_before)

    def test_one_sided_review_change_is_rejected_even_after_resealing(self):
        baseline = self.plan([self.check()])
        before = self.snapshot(self.workspace)
        for changed_side in ("plan", "configuration"):
            with self.subTest(changed_side=changed_side):
                tampered = copy.deepcopy(baseline)
                changed = {**DEFAULT_REVIEW, "network": "possible", "notes": ["Changed declaration."]}
                if changed_side == "plan":
                    tampered["checks"][0]["review"] = changed
                else:
                    config = self.proposed_config(tampered)
                    config["checks"][0]["review"] = changed
                    self.replace_proposed_config(tampered, config)
                tampered = Plan.seal(tampered).validate().value
                writer = Mock(side_effect=AssertionError("Mismatched declaration reached writes"))
                with self.assertRaises(ForvynxError):
                    apply_plan(tampered, tampered["digest"], writer=writer)
                writer.assert_not_called()
                self.assertEqual(self.snapshot(self.workspace), before)

    def test_static_verify_returns_complete_not_run_without_engineering_spawn(self):
        value = self.plan([self.check()])
        apply_plan(value, value["digest"])
        before = self.snapshot(self.workspace)
        state_before = self.snapshot(state_directory(self.workspace))
        real_popen = subprocess.Popen
        forbidden = []

        def only_git(argv, *args, **kwargs):
            if Path(argv[0]).name.lower() not in ("git", "git.exe"):
                forbidden.append(argv)
                raise AssertionError("Static verification attempted an engineering command")
            return real_popen(argv, *args, **kwargs)

        with patch("forvynx_lib.portable.subprocess.Popen", side_effect=only_git):
            report = verify(value)
        self.assertEqual(forbidden, [])
        self.assertFalse(report["ready"])
        result = report["checks"][0]
        self.assert_report(result, value["checks"][0], "not_run", value["checks"][0]["key"])
        self.assertEqual(result["reason"], "not selected for execution")
        self.assertEqual(self.snapshot(self.workspace), before)
        self.assertEqual(self.snapshot(state_directory(self.workspace)), state_before)

    def test_execution_reports_cover_pass_fail_missing_executable_cwd_and_timeout(self):
        cases = [
            (self.check("pass"), "passed", 0),
            (self.check("fail", argv=["$PYTHON", "-B", "-c", "raise SystemExit(7)"]), "failed", 7),
            (self.check("missing", argv=[str(Path(self.temp.name) / "missing-tool-883.exe")]), "unsupported", None),
            (self.check("cwd", cwd="missing-directory"), "unsupported", None),
            (self.check("timeout", argv=["$PYTHON", "-B", "-c", "import time;time.sleep(5)"], timeout=0.05), "failed", None),
        ]
        before = self.snapshot(self.workspace)
        for check, status, exit_code in cases:
            with self.subTest(check=check["id"]):
                result = portable.run_check(self.repo, check)
                self.assert_report(result, check, status)
                self.assertEqual(result["exit_code"], exit_code)
                if check["id"] == "timeout":
                    self.assertIn("timeout", result["reason"].lower())
                self.assertEqual(self.snapshot(self.workspace), before)

    def test_injected_launch_errors_preserve_other_check_reports(self):
        denied = self.check("denied", argv=["$PYTHON", "-B", "-c", "pass", "DENIED_START"])
        value = self.plan([denied, self.check("healthy")])
        apply_plan(value, value["digest"])
        real_popen = subprocess.Popen
        for injected in (PermissionError("injected launch denial"), OSError("injected launch error")):
            with self.subTest(error=type(injected).__name__):
                def launch(argv, *args, **kwargs):
                    if "DENIED_START" in argv:
                        raise injected
                    return real_popen(argv, *args, **kwargs)

                with patch("forvynx_lib.portable.subprocess.Popen", side_effect=launch):
                    report = verify(value, [c["key"] for c in value["checks"]], value["digest"])
                self.assertFalse(report["ready"])
                self.assertEqual(len(report["checks"]), 2)
                for definition, result, status in zip(value["checks"], report["checks"], ("unsupported", "passed")):
                    self.assert_report(result, definition, status, definition["key"])

    def test_injected_error_after_process_start_is_failed_not_not_run(self):
        check = self.check()
        process = Mock()
        process.wait.side_effect = [OSError("injected wait failure after launch"), 0]
        process.poll.return_value = None
        with patch("forvynx_lib.portable.subprocess.Popen", return_value=process) as launch:
            result = portable.run_check(self.repo, check)
        launch.assert_called_once()
        self.assert_report(result, check, "failed")
        self.assertNotEqual(result["status"], "not_run")

    def test_portable_cli_static_execute_and_host_output_sentinel(self):
        sentinel = "contract-host-env-output-must-be-discarded-9df8"
        check = self.check(argv=[
            "$PYTHON", "-B", "-c",
            "import os,sys;v=os.environ['FORVYNX_CONTRACT_SENTINEL'];print(v);print(v,file=sys.stderr)",
        ])
        value = self.plan([check])
        apply_plan(value, value["digest"])
        key = value["repositories"][0]["repo_id"] + ":unit"
        before = self.snapshot(self.workspace)
        state_before = self.snapshot(state_directory(self.workspace))
        for execute, expected_status, expected_code in ((False, "not_run", 2), (True, "passed", 0)):
            with self.subTest(execute=execute):
                argv = [sys.executable, "-B", str(self.repo / ".forvynx/check.py"), "--root", str(self.repo)]
                if execute:
                    argv.append("--execute")
                process = subprocess.run(
                    argv, env={**self.git_env, "FORVYNX_CONTRACT_SENTINEL": sentinel},
                    cwd=self.temp.name, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
                )
                self.assertEqual(process.returncode, expected_code, process.stderr.decode(errors="replace"))
                self.assertNotIn(sentinel.encode(), process.stdout + process.stderr)
                report = json.loads(process.stdout)
                self.assertEqual(report["structure"], "passed")
                self.assert_report(report["checks"][0], check, expected_status, key)
                self.assertEqual(self.snapshot(self.workspace), before)
                self.assertEqual(self.snapshot(state_directory(self.workspace)), state_before)
        for root in (self.workspace, state_directory(self.workspace)):
            for path in root.rglob("*"):
                if path.is_file():
                    self.assertNotIn(sentinel.encode(), path.read_bytes(), str(path))

    def test_definition_digest_binds_definition_not_business_bytes_or_context(self):
        check = self.check(sources=["README.md"])
        original = portable.check_result(self.repo, check)
        self.assert_report(original, check, "not_run")
        self.assertEqual(original["reason"], "not selected for execution")
        (self.repo / "README.md").write_text("Business input changed.\n", encoding="utf-8")
        context = {**check, "key": "other-plan:unit", "root": "ignored-context-root",
                   "source_states": [{"path": "README.md", "state": {"kind": "file", "sha256": "a" * 64}}]}
        self.assertEqual(portable.check_result(self.repo, context)["definition_sha256"], original["definition_sha256"])
        changed_review = {**check, "review": {**DEFAULT_REVIEW, "network": "none"}}
        changed_argv = {**check, "argv": ["$PYTHON", "-B", "-c", "pass # changed command"]}
        for changed in (changed_review, changed_argv):
            self.assertNotEqual(portable.check_result(self.repo, changed)["definition_sha256"], original["definition_sha256"])
        other_python = str(Path(self.temp.name) / "another-host-python.exe")
        with patch.object(portable.sys, "executable", other_python):
            other_host = portable.check_result(self.repo, check)
        self.assertEqual(other_host["argv"][0], other_python)
        self.assertEqual(other_host["definition_sha256"], original["definition_sha256"])

    def test_injected_late_permission_error_compensates_completed_writes(self):
        """Injected PermissionError tests compensation, not actual Windows ACLs."""
        (self.repo / "AGENTS.md").write_text("Existing user guidance.\n", encoding="utf-8")
        value = self.plan([self.check()])
        before = self.snapshot(self.workspace, files_only=True)
        written = []

        def late_denial(root, name, data):
            atomic_write(root, name, data)
            written.append(name)
            if len(written) == len(value["actions"]):
                raise PermissionError("injected late denial after an actual target write")

        with self.assertRaises(ForvynxError) as raised:
            apply_plan(value, value["digest"], writer=late_denial)
        self.assertEqual(raised.exception.code, 4)
        self.assertGreater(len(written), 1)
        # Compensation restores files; newly created empty parent directories
        # are outside this assertion and may remain after recovery.
        self.assertEqual(self.snapshot(self.workspace, files_only=True), before)
        folder, name = journal_path(value)
        journal = json.loads((folder / name).read_bytes())
        self.assertEqual(journal["status"], "rolled_back")
        self.assertIn("injected late denial", journal["failure"])


if __name__ == "__main__":
    unittest.main()
