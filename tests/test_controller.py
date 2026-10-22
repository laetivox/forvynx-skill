"""Observable invariants in temporary repositories; never touch real projects."""

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/forvynx/scripts"))

from forvynx_lib.apply import apply_plan, journal_path, resource_locks, rollback
from forvynx_lib.boundary import absolute, atomic_write, guarded, identity, read_bytes, state_directory
from forvynx_lib.domain import ForvynxError, Plan, json_bytes, sha
from forvynx_lib.hooks import preview_hook
from forvynx_lib.plan import build_plan
from forvynx_lib.portable import Snapshot, inspect_snapshot, run_check
from forvynx_lib.probe import probe
from forvynx_lib.verify import verify

CLI = ROOT / "skills/forvynx/scripts/forvynx.py"


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="forvynx-test-")
        self.ws = Path(self.temp.name).resolve()
        self.git_env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                        "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                        "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}

    def tearDown(self):
        # Exact temporary state directory only; no recursive removal outside fixtures.
        for workspace in getattr(self, "state_workspaces", [self.ws]):
            folder = state_directory(workspace)
            expected = Path(tempfile.gettempdir()).resolve() / "forvynx-state"
            if folder.parent == expected and folder.exists():
                shutil.rmtree(folder)
        self.temp.cleanup()

    def git(self, root, *args):
        return subprocess.run(["git", "-C", str(root), *args], env=self.git_env, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    def repo(self, name="a", python=False):
        root = self.ws / name
        root.mkdir(parents=True, exist_ok=True)
        self.git(root, "init", "-q")
        self.git(root, "config", "core.autocrlf", "false")
        if python:
            (root / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0.0.0"\n[tool.pytest.ini_options]\ntestpaths=["tests"]\n', encoding="utf-8")
        return root

    def plan(self, paths=("a",), **options):
        inventory = probe(self.ws)
        return build_plan(inventory, {"repositories": [{"path": p, **options} for p in paths]})

    def snapshot(self):
        return {str(p.relative_to(self.ws)): p.read_bytes() for p in self.ws.rglob("*") if p.is_file() and ".git" not in p.parts}

    def test_empty_workspace_probe_is_read_only(self):
        before = self.snapshot()
        value = probe(self.ws)
        self.assertTrue(value["complete"])
        self.assertEqual(value["repositories"], [])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.ws / ".git").exists())

    def test_multi_repo_select_one_preserves_other(self):
        self.repo("a", python=True)
        b = self.repo("b")
        before = self.snapshot()
        inventory = probe(self.ws)
        self.assertEqual([r["relative_path"] for r in inventory["repositories"]], ["a", "b"])
        value = self.plan()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(apply_plan(value, value["digest"])["status"], "applied")
        self.assertFalse((b / ".forvynx").exists())
        self.assertEqual(verify(value)["structure"], "passed")

    def test_no_confirmation_does_not_write_or_create_state(self):
        self.repo()
        value = self.plan()
        before = self.snapshot()
        with self.assertRaises(ForvynxError) as error:
            apply_plan(value, None)
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(state_directory(self.ws).exists())

    def test_plan_tamper_is_rejected(self):
        self.repo()
        value = self.plan()
        value["actions"][0]["content_b64"] = base64.b64encode(b"tampered").decode()
        with self.assertRaises(ForvynxError):
            apply_plan(value, value["digest"])
        self.assertFalse((self.ws / "a/.forvynx").exists())

    def test_idempotent_replay(self):
        self.repo()
        value = self.plan()
        apply_plan(value, value["digest"])
        before = self.snapshot()
        self.assertEqual(apply_plan(value, value["digest"])["status"], "no_change")
        self.assertEqual(self.snapshot(), before)

    def test_existing_agents_bytes_preserved(self):
        root = self.repo()
        original = "# 我的约定\r\n保留这段内容。\r\n".encode()
        (root / "AGENTS.md").write_bytes(original)
        value = self.plan()
        apply_plan(value, value["digest"])
        self.assertTrue((root / "AGENTS.md").read_bytes().startswith(original))
        self.assertEqual((root / "AGENTS.md").read_bytes().count(b"forvynx:begin"), 1)

    def test_file_drift_before_apply_refuses_all_writes(self):
        root = self.repo()
        value = self.plan()
        (root / "AGENTS.md").write_text("User work", encoding="utf-8")
        before = self.snapshot()
        with self.assertRaises(ForvynxError):
            apply_plan(value, value["digest"])
        self.assertEqual(self.snapshot(), before)

    def test_new_evidence_invalidates_plan(self):
        root = self.repo()
        value = self.plan()
        (root / "pyproject.toml").write_text('[project]\nname="new"\n', encoding="utf-8")
        with self.assertRaises(ForvynxError):
            apply_plan(value, value["digest"])

    def test_nested_checkout_appearing_after_plan_blocks(self):
        root = self.repo()
        value = self.plan()
        self.git(root, "init", "-q", str(root / ".forvynx"))
        with self.assertRaises(ForvynxError):
            apply_plan(value, value["digest"])
        self.assertFalse((root / "AGENTS.md").exists())

    def test_nested_repo_is_separate_candidate(self):
        self.repo()
        self.repo("a/nested")
        inventory = probe(self.ws)
        self.assertEqual([r["relative_path"] for r in inventory["repositories"]], ["a", "a/nested"])

    def test_scan_limits_report_incomplete(self):
        self.repo("a/deeper")
        self.assertFalse(probe(self.ws, max_depth=0)["complete"])
        self.assertFalse(probe(self.ws, max_dirs=1)["complete"])

    def test_external_root_reported_without_reading_evidence(self):
        root = self.repo()
        sub = root / "module"
        sub.mkdir()
        inventory = probe(sub)
        self.assertEqual(inventory["repositories"], [])
        self.assertEqual(inventory["external_repository"]["root"], str(root))

    def test_read_guard_blocks_escape_and_similar_prefix(self):
        root = self.repo()
        for name in ("../a2/secret", "folder/../../escape", "C:/secret", "file:stream", ".git/config", "NUL"):
            with self.subTest(name=name), self.assertRaises(ForvynxError):
                guarded(root, name)

    def test_linked_evidence_is_not_read(self):
        root = self.repo()
        outside = self.ws / "external.toml"
        outside.write_text('[project]\nname="external"\n', encoding="utf-8")
        try:
            (root / "pyproject.toml").symlink_to(outside)
        except OSError:
            self.skipTest("File symlinks require OS permission")
        inventory = probe(self.ws)
        self.assertTrue(inventory["repositories"][0]["warnings"])
        with self.assertRaises(ForvynxError):
            build_plan(inventory, {"repositories": [{"path": "a"}]})

    def test_worktree_identity_and_common_metadata(self):
        root = self.repo()
        (root / "file.txt").write_text("fixture", encoding="utf-8")
        self.git(root, "add", ".")
        self.git(root, "commit", "-qm", "fixture")
        linked = self.ws / "linked"
        self.git(root, "worktree", "add", "--detach", str(linked))
        first, second = identity(root), identity(linked)
        self.assertEqual(first["common_dir"], second["common_dir"])
        self.assertNotEqual(first["git_dir"], second["git_dir"])
        before = (root / ".git/config").read_bytes()
        value = self.plan(("linked",))
        apply_plan(value, value["digest"])
        self.assertEqual((root / ".git/config").read_bytes(), before)
        self.assertFalse((root / ".forvynx").exists())

    def test_recovery_preserves_subsequent_edit(self):
        root = self.repo()
        value = self.plan()
        apply_plan(value, value["digest"])
        target = root / ".forvynx/workflow.md"
        target.write_bytes(b"User's later work\n")
        result = rollback(value, value["digest"])
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(target.read_bytes(), b"User's later work\n")
        self.assertTrue(Path(result["journal"]).exists())

    def test_partial_failure_compensates(self):
        self.repo("a")
        self.repo("b")
        value = self.plan(("a", "b"))
        calls = []
        def failing_writer(root, name, data):
            calls.append(name)
            if len(calls) == 5:
                raise OSError("injected write failure")
            atomic_write(root, name, data)
        before = self.snapshot()
        with self.assertRaises(ForvynxError):
            apply_plan(value, value["digest"], writer=failing_writer)
        self.assertEqual(self.snapshot(), before)
        folder, name = journal_path(value)
        self.assertEqual(json.loads((folder / name).read_bytes())["status"], "rolled_back")

    def test_rollback_can_be_repeated(self):
        self.repo()
        value = self.plan()
        before = self.snapshot()
        apply_plan(value, value["digest"])
        self.assertEqual(rollback(value, value["digest"])["status"], "rolled_back")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(rollback(value, value["digest"])["status"], "no_change")

    def test_workspace_resource_lock_is_shared(self):
        self.repo("a")
        self.repo("b")
        a, b = self.plan(("a",)), self.plan(("b",))
        with resource_locks(a):
            with self.assertRaises(ForvynxError):
                with resource_locks(b):
                    self.fail("Both transactions acquired workspace lock")

    def test_discovery_does_not_execute_package_scripts(self):
        root = self.repo()
        sentinel = root / "SENTINEL"
        (root / "package.json").write_text(json.dumps({"scripts": {"test": "echo pwned > SENTINEL"}}), encoding="utf-8")
        value = self.plan()
        apply_plan(value, value["digest"])
        verify(value)
        self.assertFalse(sentinel.exists())

    def test_required_check_is_not_passed_when_not_run(self):
        self.repo()
        check = {"id": "unit", "argv": ["$PYTHON", "-c", "pass"], "required": True}
        value = self.plan(checks=[check])
        apply_plan(value, value["digest"])
        self.assertFalse(verify(value)["ready"])
        key = value["checks"][0]["key"]
        with self.assertRaises(ForvynxError):
            verify(value, [key])
        self.assertTrue(verify(value, [key], value["digest"])["ready"])

    def test_failed_check_is_not_passed(self):
        self.repo()
        value = self.plan(checks=[{"id": "bad", "argv": ["$PYTHON", "-c", "raise SystemExit(7)"]}])
        apply_plan(value, value["digest"])
        result = verify(value, [value["checks"][0]["key"]], value["digest"])
        self.assertFalse(result["ready"])
        self.assertEqual(result["checks"][0]["exit_code"], 7)

    def test_check_source_drift_blocks_execution(self):
        root = self.repo()
        (root / "entry.py").write_text("pass", encoding="utf-8")
        value = self.plan(checks=[{"id": "entry", "argv": ["$PYTHON", "entry.py"], "sources": ["entry.py"]}])
        apply_plan(value, value["digest"])
        (root / "entry.py").write_text("raise SystemExit(3)", encoding="utf-8")
        with self.assertRaises(ForvynxError):
            verify(value, [value["checks"][0]["key"]], value["digest"])

    def test_checker_reads_index_not_fixed_worktree(self):
        root = self.repo()
        value = self.plan()
        apply_plan(value, value["digest"])
        config_path = root / ".forvynx/repo.json"
        good = config_path.read_bytes()
        config_path.write_bytes(b"invalid JSON")
        self.git(root, "add", "AGENTS.md", ".forvynx")
        config_path.write_bytes(good)
        inspect_snapshot(Snapshot(root, "worktree"))
        with self.assertRaises(ValueError):
            inspect_snapshot(Snapshot(root, "index"))

    def test_ci_is_optional_and_never_reports_remote_enabled(self):
        root = self.repo()
        value = self.plan(ci=True)
        apply_plan(value, value["digest"])
        self.assertTrue((root / ".github/workflows/forvynx.yml").exists())
        report = verify(value)
        self.assertEqual(report["remote_protection"], "unverified")
        self.assertEqual(report["ci_execution"], "not_run")

    def test_cli_reports_json_and_no_approval(self):
        self.repo()
        value = self.plan()
        plan_path = self.ws / "plan.json"
        plan_path.write_bytes(json_bytes(value))
        result = subprocess.run([sys.executable, "-B", str(CLI), "apply", "--plan", str(plan_path)], stdout=subprocess.PIPE)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "blocked")

    def test_same_workspace_as_single_repository(self):
        self.repo(".")
        value = self.plan((".",))
        apply_plan(value, value["digest"])
        self.assertEqual(verify(value)["plan_consistency"], "passed")
        self.assertEqual(apply_plan(value, value["digest"])["status"], "no_change")

    def test_unicode_and_space_repository_names(self):
        root = self.repo("中文 repo")
        value = self.plan(("中文 repo",))
        apply_plan(value, value["digest"])
        self.assertTrue((root / "AGENTS.md").exists())
        self.assertTrue(verify(value)["ready"])

    def test_windows_junction_is_rejected(self):
        if os.name != "nt":
            self.skipTest("Windows junction scenario")
        root = self.repo()
        target = self.ws / "outside"
        target.mkdir()
        (target / "sentinel").write_bytes(b"unchanged")
        link = root / "redirect"
        proc = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode:
            self.skipTest("OS rejected junction creation")
        with self.assertRaises(ForvynxError):
            read_bytes(root, "redirect/sentinel")
        self.assertIn(str(link), probe(self.ws)["skipped_links"])
        self.assertEqual((target / "sentinel").read_bytes(), b"unchanged")

    def test_corrupt_git_metadata_is_error_not_empty_repo(self):
        broken = self.ws / "broken"
        (broken / ".git").mkdir(parents=True)
        value = probe(self.ws)
        self.assertFalse(value["complete"])
        self.assertTrue(value["errors"])
        self.assertFalse((broken / "AGENTS.md").exists())

    def test_missing_git_reports_capability(self):
        with patch("forvynx_lib.probe.GIT", None):
            value = probe(self.ws)
        self.assertFalse(value["capabilities"]["git"])
        self.assertFalse(value["complete"])

    def test_unknown_plan_version_refused(self):
        self.repo()
        value = self.plan()
        value["schema_version"] = 2
        value = Plan.seal(value).value
        with self.assertRaises(ForvynxError):
            apply_plan(value, value["digest"])

    def test_unmanaged_files_are_not_overwritten(self):
        root = self.repo()
        (root / ".forvynx").mkdir()
        (root / ".forvynx/workflow.md").write_bytes(b"Mine")
        with self.assertRaises(ForvynxError):
            self.plan()
        self.assertEqual((root / ".forvynx/workflow.md").read_bytes(), b"Mine")

    def test_missing_executable_and_timeout_are_not_success(self):
        root = self.repo()
        for argv, status in ((["forvynx-missing-tool-718824"], "unsupported"), (["$PYTHON", "-c", "import time;time.sleep(10)"], "failed")):
            result = run_check(root, {"id": "example", "argv": argv, "cwd": ".", "required": True, "env": {}, "timeout": 0.1})
            self.assertEqual(result["status"], status)

    def test_conflict_journal_is_visible_in_probe(self):
        root = self.repo()
        value = self.plan()
        apply_plan(value, value["digest"])
        (root / "AGENTS.md").write_bytes(b"Later edit")
        rollback(value, value["digest"])
        inventory = probe(self.ws)
        self.assertEqual(inventory["recovery"][0]["status"], "conflict")

    def test_hook_preview_writes_nothing(self):
        root = self.repo()
        value = self.plan()
        before = self.snapshot()
        result = preview_hook(value, value["repositories"][0]["repo_id"])
        self.assertEqual(result["status"], "preview_only")
        self.assertIn("--source", result["hook_script"])
        self.assertFalse((root / ".git/hooks/pre-commit").exists())
        self.assertEqual(self.snapshot(), before)

    def test_active_alternate_index_is_used(self):
        root = self.repo()
        value = self.plan()
        apply_plan(value, value["digest"])
        self.git(root, "add", "AGENTS.md", ".forvynx")
        alternate = self.ws / "alternate.index"
        shutil.copyfile(root / ".git/index", alternate)
        config_path = root / ".forvynx/repo.json"
        good = config_path.read_bytes()
        config_path.write_bytes(b"invalid")
        subprocess.run(["git", "-C", str(root), "add", ".forvynx/repo.json"], env={**self.git_env, "GIT_INDEX_FILE": str(alternate)}, check=True)
        config_path.write_bytes(good)
        inspect_snapshot(Snapshot(root, "index"))
        with patch.dict(os.environ, {"GIT_INDEX_FILE": str(alternate)}):
            with self.assertRaises(ValueError):
                inspect_snapshot(Snapshot(root, "index"))

    def test_mismatched_registry_blocks_new_onboarding(self):
        root = self.repo("a")
        self.repo("b")
        value = self.plan(("a",))
        apply_plan(value, value["digest"])
        (root / ".forvynx/repo.json").unlink()
        with self.assertRaises(ForvynxError):
            self.plan(("b",))

    def test_plan_check_cannot_diverge_from_config(self):
        self.repo()
        value = self.plan(checks=[{"id": "unit", "argv": ["$PYTHON", "-c", "pass"]}])
        value["checks"][0]["argv"] = ["$PYTHON", "-c", "raise SystemExit(42)"]
        value = Plan.seal(value).value
        with self.assertRaises(ForvynxError):
            apply_plan(value, value["digest"])

    def test_untracked_files_are_dirty(self):
        root = self.repo()
        (root / "new.txt").write_bytes(b"not tracked")
        self.assertTrue(probe(self.ws)["repositories"][0]["dirty"])

    def test_real_fixture_hook_rejects_bad_staged_config(self):
        root = self.repo()
        self.git(root, "config", "core.hooksPath", str(root / ".git/hooks"))
        value = self.plan()
        apply_plan(value, value["digest"])
        preview = preview_hook(value, value["repositories"][0]["repo_id"])
        snapshot = Path(preview["checker_snapshot_path"])
        snapshot.parent.mkdir(parents=True)
        snapshot.write_bytes(base64.b64decode(preview["checker_content_b64"]))
        hook = Path(preview["active_hook_path"])
        self.assertEqual(hook.resolve().parent, (root / ".git/hooks").resolve())
        hook.write_bytes(preview["hook_script"].encode("utf-8"))
        hook.chmod(0o755)
        self.git(root, "add", "AGENTS.md", ".forvynx")
        self.git(root, "commit", "-qm", "hook-valid-snapshot")
        config_path = root / ".forvynx/repo.json"
        good = config_path.read_bytes()
        config_path.write_bytes(b"invalid staged JSON")
        self.git(root, "add", ".forvynx/repo.json")
        config_path.write_bytes(good)
        proc = subprocess.run(["git", "-C", str(root), "commit", "-qm", "must-be-blocked"], env=self.git_env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.git(root, "log", "--format=%s", "-1").strip(), b"hook-valid-snapshot")

    def test_static_verify_never_executes_target_checker(self):
        root = self.repo()
        value = self.plan()
        apply_plan(value, value["digest"])
        (root / ".forvynx/check.py").write_text("from pathlib import Path;Path('SENTINEL').write_text('executed')", encoding="utf-8")
        with self.assertRaises(ForvynxError):
            verify(value)
        self.assertFalse((root / "SENTINEL").exists())

    def test_unmerged_index_is_rejected(self):
        root = self.repo()
        (root / "entry.txt").write_bytes(b"example")
        oid = self.git(root, "hash-object", "-w", "entry.txt").strip()
        info = b"100644 " + oid + b" 1\tentry.txt\n100644 " + oid + b" 2\tentry.txt\n"
        subprocess.run(["git", "-C", str(root), "update-index", "--index-info"], env=self.git_env, input=info, check=True)
        with self.assertRaisesRegex(ValueError, "multi-stage"):
            Snapshot(root, "index")

    def test_python_candidates_use_current_interpreter_token(self):
        self.repo(python=True)
        candidate = probe(self.ws)["repositories"][0]["suggested_checks"][0]
        self.assertEqual(candidate["argv"], ["$PYTHON", "-m", "pytest"])

    def test_incomplete_bundle_cannot_be_applied(self):
        self.repo()
        value = self.plan()
        value["actions"] = [a for a in value["actions"] if a["path"] != ".forvynx/check.py"]
        value = Plan.seal(value).value
        before = self.snapshot()
        with self.assertRaises(ForvynxError):
            apply_plan(value, value["digest"])
        self.assertEqual(self.snapshot(), before)

    def test_misleading_diff_cannot_be_applied(self):
        self.repo()
        value = self.plan()
        value["actions"][0]["diff"] = "Nothing will change"
        value = Plan.seal(value).value
        with self.assertRaises(ForvynxError):
            apply_plan(value, value["digest"])


class SkillPortabilityTest(unittest.TestCase):
    def test_portable_skill_does_not_require_openai_metadata(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from validate_skill import validate
        with tempfile.TemporaryDirectory(prefix="forvynx-neutral-") as folder:
            target = Path(folder) / "forvynx"
            shutil.copytree(ROOT / "skills/forvynx", target)
            (target / "agents/openai.yaml").unlink()
            report = validate(target)
            self.assertEqual(report["status"], "passed")
            self.assertFalse(report["optional_openai_metadata"])

    def test_metadata_references_and_syntax(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from validate_skill import validate
        self.assertEqual(validate()["status"], "passed")

    def test_copied_skill_runs_without_source_tree_or_host_metadata(self):
        with tempfile.TemporaryDirectory(prefix="forvynx-standalone-") as folder:
            base = Path(folder).resolve()
            target = base / "copied/forvynx"
            shutil.copytree(ROOT / "skills/forvynx", target)
            (target / "agents/openai.yaml").unlink()
            workspace = base / "workspace"
            repo = workspace / "app"
            repo.mkdir(parents=True)
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            entry = target / "scripts/forvynx.py"
            def run(*args):
                proc = subprocess.run([sys.executable, "-B", str(entry), *args], cwd=base,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8") + proc.stderr.decode("utf-8", "replace"))
                return json.loads(proc.stdout)
            inventory = run("probe", "--workspace", str(workspace))
            (base / "inventory.json").write_bytes(json_bytes(inventory))
            (base / "selection.json").write_bytes(json_bytes({"repositories": [{"path": "app"}]}))
            plan = run("plan", "--inventory", str(base / "inventory.json"), "--selection", str(base / "selection.json"))
            (base / "plan.json").write_bytes(json_bytes(plan))
            try:
                run("apply", "--plan", str(base / "plan.json"), "--confirm", plan["digest"])
                report = run("verify", "--plan", str(base / "plan.json"))
                self.assertEqual(report["structure"], "passed")
                self.assertEqual(report["engineering_verification"], "not_configured")
            finally:
                state_folder = state_directory(workspace)
                if state_folder.parent == Path(tempfile.gettempdir()).resolve() / "forvynx-state" and state_folder.exists():
                    shutil.rmtree(state_folder)


if __name__ == "__main__":
    unittest.main()
