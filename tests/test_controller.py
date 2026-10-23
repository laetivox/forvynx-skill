"""Observable invariants in temporary repositories; never touch real projects."""

import base64
import difflib
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
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

    def workflow(self, sources=("AGENTS.md",), check_ids=(), guidance="Use the existing focused checks.",
                 unknowns=("Tool availability has not been verified.",)):
        return {"schema_version": 1, "decisions": [{"id": "focused-validation", "applies_to": "small_change",
                "guidance": guidance, "reason": "The cited project evidence defines the existing convention.",
                "confidence": "medium", "sources": list(sources), "check_ids": list(check_ids)}],
                "unknowns": list(unknowns)}

    def tree_bytes(self, root, exclude=()):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
                if p.is_file() and not any(p.relative_to(root).is_relative_to(name) for name in exclude)}

    def submodule_fixture(self):
        source = self.repo("source")
        (source / "library.txt").write_bytes(b"Local-only submodule source\r\n")
        self.git(source, "add", ".")
        self.git(source, "commit", "-qm", "submodule source")
        main = self.repo("main")
        (main / "README.md").write_bytes(b"Parent repository\n")
        self.git(main, "add", ".")
        self.git(main, "commit", "-qm", "parent source")
        self.git(main, "-c", "protocol.file.allow=always", "submodule", "add", str(source), "module")
        self.git(main, "commit", "-qam", "local submodule")
        module = main / "module"
        metadata = Path(identity(module)["git_dir"])
        self.assertTrue((module / ".git").is_file())
        self.assertTrue(metadata.is_relative_to(main / ".git/modules"))
        self.assertFalse(metadata.is_relative_to(module))
        return main, module, metadata

    def process_event(self, process):
        events = queue.Queue()
        reader = threading.Thread(target=lambda: events.put(process.stdout.readline()), daemon=True)
        reader.start()
        try:
            line = events.get(timeout=20)
        except queue.Empty:
            self.fail("Fixture process did not complete its pipe handshake within 20 seconds")
        self.assertTrue(line, "Fixture process exited before its pipe handshake")
        return json.loads(line)

    def stop_fixture_process(self, process, message=None):
        try:
            output = process.communicate(input=message, timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            output = process.communicate(timeout=15)
        return output

    def remove_exited_fixture_locks(self, process, value):
        # Test-only recovery: prove the exact fixture owner exited before unlinking its own locks.
        self.assertIsNotNone(process.poll())
        self.assertEqual(Path(value["workspace"]), self.ws)
        resources = {value["workspace"], *(r["identity"]["root"] for r in value["repositories"])}
        lock_folder = Path(tempfile.gettempdir()).resolve() / "forvynx-locks"
        removed = []
        for resource in resources:
            self.assertTrue(Path(resource).is_relative_to(self.ws))
            path = lock_folder / (sha(os.path.normcase(resource).encode()) + ".lock")
            self.assertEqual(path.resolve().parent, lock_folder)
            if path.exists():
                self.assertEqual(path.read_text(), str(process.pid))
                path.unlink()
                removed.append(path)
        return removed

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

    def test_real_submodule_parent_onboarding_preserves_child_and_modules_metadata(self):
        main, module, metadata = self.submodule_fixture()
        value = self.plan(("main",))
        module_before, metadata_before = self.tree_bytes(module), self.tree_bytes(metadata)
        self.assertEqual([r["identity"]["root"] for r in value["repositories"]], [str(main)])
        self.assertEqual(apply_plan(value, value["digest"])["status"], "applied")
        self.assertEqual(self.tree_bytes(module), module_before)
        self.assertEqual(self.tree_bytes(metadata), metadata_before)
        self.assertFalse((module / ".forvynx").exists())
        self.assertEqual(verify(value)["structure"], "passed")

    def test_real_submodule_child_onboarding_preserves_unselected_parent(self):
        main, module, metadata = self.submodule_fixture()
        value = self.plan(("main/module",))
        main_before = self.tree_bytes(main, exclude=("module",))
        module_pointer, metadata_before = (module / ".git").read_bytes(), self.tree_bytes(metadata)
        self.assertEqual([r["identity"]["root"] for r in value["repositories"]], [str(module)])
        self.assertEqual(apply_plan(value, value["digest"])["status"], "applied")
        self.assertEqual(self.tree_bytes(main, exclude=("module",)), main_before)
        self.assertEqual((module / ".git").read_bytes(), module_pointer)
        self.assertEqual(self.tree_bytes(metadata), metadata_before)
        self.assertFalse((main / ".forvynx").exists())
        self.assertFalse((main / "AGENTS.md").exists())
        self.assertEqual(verify(value)["structure"], "passed")

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

    def test_independent_process_lock_blocks_apply_without_target_writes_then_releases(self):
        self.repo()
        value = self.plan()
        plan_path = self.ws / "process-plan.json"
        plan_path.write_bytes(json_bytes(value))
        script = ("import json,os,sys;from pathlib import Path;"
                  "sys.path.insert(0,sys.argv[1]);from forvynx_lib.apply import resource_locks;"
                  "value=json.loads(Path(sys.argv[2]).read_bytes());\n"
                  "with resource_locks(value):\n"
                  " print(json.dumps({'status':'held','pid':os.getpid()}),flush=True)\n"
                  " assert sys.stdin.readline().strip()=='release'\n")
        process = subprocess.Popen([sys.executable, "-B", "-c", script, str(CLI.parent), str(plan_path)],
                                   env=self.git_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(self.process_event(process), {"status": "held", "pid": process.pid})
            before = self.snapshot()
            denied = subprocess.run([sys.executable, "-B", str(CLI), "apply", "--plan", str(plan_path),
                                     "--confirm", value["digest"]], env=self.git_env, timeout=30,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            report = json.loads(denied.stdout)
            self.assertNotEqual(denied.returncode, 0, denied.stdout)
            self.assertEqual(report["status"], "blocked")
            self.assertIn("Resource locked", report["reason"])
            self.assertEqual(self.snapshot(), before)
            self.assertFalse(state_directory(self.ws).exists())
            stdout, stderr = self.stop_fixture_process(process, b"release\n")
            self.assertEqual(process.returncode, 0, stdout + stderr)
            applied = subprocess.run([sys.executable, "-B", str(CLI), "apply", "--plan", str(plan_path),
                                      "--confirm", value["digest"]], env=self.git_env, timeout=30,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            self.assertEqual(json.loads(applied.stdout)["status"], "applied")
        finally:
            self.stop_fixture_process(process)
            self.remove_exited_fixture_locks(process, value)

    def test_independent_process_exit_leaves_recovery_and_rollback_preserves_later_edit(self):
        self.repo()
        value = self.plan()
        plan_path = self.ws / "crash-plan.json"
        plan_path.write_bytes(json_bytes(value))
        before = self.snapshot()
        script = ("import json,os,sys;from pathlib import Path;"
                  "sys.path.insert(0,sys.argv[1]);from forvynx_lib.apply import apply_plan;"
                  "from forvynx_lib.boundary import atomic_write;"
                  "value=json.loads(Path(sys.argv[2]).read_bytes());\n"
                  "def crash_after_write(root,name,data):\n"
                  " atomic_write(root,name,data)\n"
                  " print(json.dumps({'status':'wrote','pid':os.getpid(),'root':str(root),'path':name}),flush=True)\n"
                  " os._exit(73)\n"
                  "apply_plan(value,value['digest'],writer=crash_after_write)\n")
        process = subprocess.Popen([sys.executable, "-B", "-c", script, str(CLI.parent), str(plan_path)],
                                   env=self.git_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = self.stop_fixture_process(process)
            self.assertEqual(process.returncode, 73, stdout + stderr)
            event = json.loads(stdout)
            first = value["actions"][0]
            self.assertEqual(event, {"status": "wrote", "pid": process.pid,
                                    "root": first["root"], "path": first["path"]})
            folder, name = journal_path(value)
            journal = json.loads((folder / name).read_bytes())
            self.assertEqual(journal["status"], "applying")
            self.assertEqual(journal["completed"], [])
            self.assertEqual(journal["attempting"], {"root": first["root"], "path": first["path"]})
            self.assertEqual(probe(self.ws)["recovery"], [{"journal": str(folder / name), "status": "applying"}])
            after_crash = self.snapshot()
            changed = {path for path in before.keys() | after_crash.keys() if before.get(path) != after_crash.get(path)}
            written = Path(first["root"]) / first["path"]
            self.assertEqual(changed, {str(written.relative_to(self.ws))})
            denied = subprocess.run([sys.executable, "-B", str(CLI), "apply", "--plan", str(plan_path),
                                     "--confirm", value["digest"]], env=self.git_env, timeout=30,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertNotEqual(denied.returncode, 0, denied.stdout)
            self.assertEqual(json.loads(denied.stdout)["status"], "blocked")
            self.assertEqual(self.snapshot(), after_crash)
            # The child is reaped above; this only clears locks naming its PID in this fixture.
            self.assertEqual(len(self.remove_exited_fixture_locks(process, value)), 2)
            with self.assertRaises(ForvynxError):
                apply_plan(value, value["digest"])
            self.assertEqual(self.snapshot(), after_crash)
            later = b"Later user edit after the fixture process exited\n"
            written.write_bytes(later)
            before_recovery = self.snapshot()
            recovered = rollback(value, value["digest"])
            self.assertEqual(recovered["status"], "conflict")
            self.assertEqual(written.read_bytes(), later)
            self.assertEqual(recovered["conflicts"], [{"path": str(written), "reason": "subsequent edit preserved"}])
            self.assertEqual(self.snapshot(), before_recovery)
            self.assertEqual(probe(self.ws)["recovery"][0]["status"], "conflict")
        finally:
            self.stop_fixture_process(process)
            self.remove_exited_fixture_locks(process, value)

    def test_discovery_does_not_execute_package_scripts(self):
        root = self.repo()
        sentinel = root / "SENTINEL"
        (root / "package.json").write_text(json.dumps({"scripts": {"test": "echo pwned > SENTINEL"}}), encoding="utf-8")
        value = self.plan()
        apply_plan(value, value["digest"])
        verify(value)
        self.assertFalse(sentinel.exists())

    def test_adaptive_workflows_reflect_distinct_evidence_without_execution(self):
        python_root = self.repo("a")
        generic_root = self.repo("b")
        original = b"# Existing rules\r\nUse unittest; do not add dependencies.\r\n"
        (python_root / "AGENTS.md").write_bytes(original)
        (python_root / "pyproject.toml").write_text('[project]\nname="stdlib-app"\nversion="0.0.0"\n', encoding="utf-8")
        (python_root / "entry.py").write_text("from pathlib import Path;Path('SENTINEL').write_text('executed')", encoding="utf-8")
        (generic_root / "AGENTS.md").write_text("Preserve the existing manual acceptance procedure.\n", encoding="utf-8")
        (generic_root / "package.json").write_text(json.dumps({"scripts": {"test": "echo executed > SENTINEL"}}), encoding="utf-8")
        workflows = [self.workflow(check_ids=("unit",), guidance="Use unittest for focused Python changes."),
                     self.workflow(sources=("AGENTS.md", "package.json"), guidance="Follow the existing manual acceptance procedure.",
                                   unknowns=("The package test command has not been reviewed or executed.",))]
        selection = {"repositories": [
            {"path": "a", "workflow": workflows[0], "checks": [{"id": "unit", "argv": ["$PYTHON", "entry.py"], "sources": ["entry.py"]}]},
            {"path": "b", "workflow": workflows[1]}]}
        before = self.snapshot()
        value = build_plan(probe(self.ws), selection)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(apply_plan(value, value["digest"])["status"], "applied")
        rendered = [(root / ".forvynx/workflow.md").read_text(encoding="utf-8") for root in (python_root, generic_root)]
        self.assertNotEqual(rendered[0], rendered[1])
        for root, declared, text in zip((python_root, generic_root), workflows, rendered):
            self.assertEqual(json.loads((root / ".forvynx/repo.json").read_bytes())["workflow"], declared)
            self.assertIn(declared["decisions"][0]["guidance"], text)
            self.assertIn(declared["unknowns"][0], text)
            self.assertIn("AGENTS.md", text)
            self.assertFalse((root / "SENTINEL").exists())
        self.assertTrue((python_root / "AGENTS.md").read_bytes().startswith(original))
        self.assertEqual({repo["profile"] for repo in value["repositories"]}, {"python", "generic"})
        report = verify(value)
        self.assertFalse(report["ready"])
        self.assertEqual(report["checks"][0]["status"], "not_run")
        generic_plan = self.plan(("b",))
        self.assertEqual(verify(generic_plan)["engineering_verification"], "not_configured")
        self.assertFalse((python_root / "SENTINEL").exists())
        self.assertFalse((generic_root / "SENTINEL").exists())

    def test_adaptive_workflow_rejects_invalid_data_and_references(self):
        root = self.repo()
        (root / "AGENTS.md").write_text("Use existing checks.\n", encoding="utf-8")
        (root / "untracked.txt").write_text("Not discovered engineering evidence.", encoding="utf-8")
        invalid = []
        for field, value in (("schema_version", 2), ("schema_version", True), ("unknowns", ["unknown"] * 17),
                             ("authorization", "approved")):
            data = self.workflow()
            data[field] = value
            invalid.append((field + repr(value), data))
        for field, value in (("id", "Invalid"), ("applies_to", "always_execute"), ("confidence", "verified"),
                             ("guidance", "line one\nline two"), ("reason", "x" * 801),
                             ("sources", ["../outside.txt"]), ("sources", ["untracked.txt"]),
                             ("sources", ["missing.toml"]), ("sources", [".forvynx/repo.json"]),
                             ("sources", []), ("sources", ["AGENTS.md", "AGENTS.md"]),
                             ("check_ids", ["missing-check"]), ("check_ids", ["unit", "unit"]), ("approved", True)):
            data = self.workflow()
            data["decisions"][0][field] = value
            invalid.append((field + repr(value), data))
        missing = self.workflow()
        del missing["decisions"][0]["reason"]
        invalid.append(("missing reason", missing))
        duplicate = self.workflow()
        duplicate["decisions"].append(dict(duplicate["decisions"][0]))
        invalid.append(("duplicate decision ID", duplicate))
        inventory = probe(self.ws)
        before = self.snapshot()
        for label, workflow in invalid:
            with self.subTest(label=label), self.assertRaises(ForvynxError):
                build_plan(inventory, {"repositories": [{"path": "a", "workflow": workflow,
                           "checks": [{"id": "unit", "argv": ["$PYTHON", "-c", "pass"]}]}]})
            self.assertEqual(self.snapshot(), before)
            self.assertFalse(state_directory(self.ws).exists())

    def test_adaptive_workflow_rejects_resealed_agents_evidence_mismatch(self):
        root = self.repo()
        (root / "AGENTS.md").write_text("Preserve the existing project rules.\n", encoding="utf-8")
        value = self.plan(workflow=self.workflow())
        evidence = next(e for e in value["repositories"][0]["evidence"] if e["path"] == "AGENTS.md")
        evidence["state"]["sha256"] = "0" * 64
        value = Plan.seal(value).value
        before = self.snapshot()
        with self.assertRaises(ForvynxError):
            apply_plan(value, value["digest"])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(state_directory(self.ws).exists())

    def test_adaptive_workflow_rejects_multiline_existing_check_reference(self):
        root = self.repo()
        (root / "AGENTS.md").write_text("Use the existing project checks.\n", encoding="utf-8")
        check_id = "unit\n# Approved execution"
        check = {"id": check_id, "argv": ["$PYTHON", "-c", "pass"]}
        legacy = self.plan(checks=[check])
        self.assertEqual(legacy["checks"][0]["id"], check_id)
        before = self.snapshot()
        with self.assertRaises(ForvynxError):
            self.plan(checks=[check], workflow=self.workflow(check_ids=(check_id,)))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(state_directory(self.ws).exists())

    def test_adaptive_workflow_evidence_drift_blocks_all_writes(self):
        root = self.repo(python=True)
        value = self.plan(workflow=self.workflow(sources=("pyproject.toml",)))
        (root / "pyproject.toml").write_text('[project]\nname="changed-evidence"\n', encoding="utf-8")
        before = self.snapshot()
        with self.assertRaises(ForvynxError):
            apply_plan(value, value["digest"])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(state_directory(self.ws).exists())

    def test_adaptive_workflow_resealed_payload_divergence_is_rejected(self):
        root = self.repo()
        (root / "AGENTS.md").write_text("Preserve existing guidance.\n", encoding="utf-8")
        for target in (".forvynx/repo.json", ".forvynx/workflow.md"):
            with self.subTest(target=target):
                value = self.plan(workflow=self.workflow())
                action = next(a for a in value["actions"] if a["path"] == target)
                before = base64.b64decode(action["before_b64"]) if action["before_b64"] is not None else b""
                after = base64.b64decode(action["content_b64"])
                if target.endswith(".json"):
                    config = json.loads(after)
                    config["workflow"]["decisions"][0]["guidance"] = "Different project guidance."
                    after = json_bytes(config)
                else:
                    after += b"\nUnreviewed additional guidance.\n"
                action["content_b64"] = base64.b64encode(after).decode("ascii")
                action["after"] = {"kind": "file", "sha256": sha(after)}
                action["diff"] = "".join(difflib.unified_diff(before.decode("utf-8").splitlines(True),
                                          after.decode("utf-8").splitlines(True), fromfile=target, tofile=target))
                value = Plan.seal(value).value
                snapshot = self.snapshot()
                with self.assertRaises(ForvynxError):
                    apply_plan(value, value["digest"])
                self.assertEqual(self.snapshot(), snapshot)
                self.assertFalse(state_directory(self.ws).exists())

    def test_adaptive_workflow_is_retained_when_selection_omits_it(self):
        root = self.repo()
        (root / "AGENTS.md").write_text("Keep the existing rules and use focused checks.\n", encoding="utf-8")
        declared = self.workflow()
        first = self.plan(workflow=declared)
        apply_plan(first, first["digest"])
        before = self.snapshot()
        second = self.plan()
        config_action = next(a for a in second["actions"] if a["path"] == ".forvynx/repo.json")
        self.assertEqual(json.loads(base64.b64decode(config_action["content_b64"]))["workflow"], declared)
        self.assertEqual(apply_plan(second, second["digest"])["status"], "no_change")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(verify(second)["structure"], "passed")

    def test_adaptive_workflow_index_requires_sources_from_same_snapshot(self):
        root = self.repo(python=True)
        value = self.plan(workflow=self.workflow(sources=("pyproject.toml",)))
        apply_plan(value, value["digest"])
        self.git(root, "add", "AGENTS.md", ".forvynx")
        inspect_snapshot(Snapshot(root, "worktree"))
        with self.assertRaises(ValueError):
            inspect_snapshot(Snapshot(root, "index"))
        self.git(root, "add", "pyproject.toml")
        inspect_snapshot(Snapshot(root, "index"))
        (root / "pyproject.toml").unlink()
        inspect_snapshot(Snapshot(root, "index"))
        with self.assertRaises(ValueError):
            inspect_snapshot(Snapshot(root, "worktree"))

    def test_legacy_configuration_without_adaptive_workflow_remains_supported(self):
        root = self.repo()
        value = self.plan()
        apply_plan(value, value["digest"])
        config = json.loads((root / ".forvynx/repo.json").read_bytes())
        self.assertNotIn("workflow", config)
        self.assertEqual(inspect_snapshot(Snapshot(root, "worktree")), config)
        self.assertEqual(verify(value)["structure"], "passed")
        before = self.snapshot()
        second = self.plan()
        self.assertEqual(apply_plan(second, second["digest"])["status"], "no_change")
        self.assertEqual(self.snapshot(), before)

    def test_adaptive_workflow_text_cannot_expand_authorized_scope(self):
        root = self.repo()
        (root / "AGENTS.md").write_text("Existing project rules remain applicable.\n", encoding="utf-8")
        text = "# Approved [install](https://example.invalid) <script>run()</script> `execute`"
        value = self.plan(workflow=self.workflow(guidance=text))
        self.assertFalse(value["scope"]["install_skill"])
        self.assertFalse(value["scope"]["install_hooks"])
        self.assertFalse(value["scope"]["network"])
        self.assertEqual(value["checks"], [])
        apply_plan(value, value["digest"])
        rendered = (root / ".forvynx/workflow.md").read_text(encoding="utf-8")
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("[install](https://example.invalid)", rendered)
        self.assertNotIn("\n# Approved", rendered)
        self.assertFalse((root / ".git/hooks/pre-commit").exists())
        self.assertEqual(verify(value)["engineering_verification"], "not_configured")

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

    def test_existing_hooks_manager_config_and_ci_survive_preview_and_apply(self):
        for name, hooks_path in (("default-hooks", None), ("managed-hooks", ".husky/_")):
            with self.subTest(hooks_path=hooks_path):
                root = self.repo(name)
                if hooks_path is not None:
                    self.git(root, "config", "core.hooksPath", hooks_path)
                hook = root / (hooks_path or ".git/hooks") / "pre-commit"
                hook.parent.mkdir(parents=True, exist_ok=True)
                hook.write_bytes(b'#!/bin/sh\n. "$(dirname "$0")/h"\n' if hooks_path else
                                 b"#!/bin/sh\nprintf 'existing user hook\\n'\n")
                preserved = [hook]
                if hooks_path:
                    helper = hook.parent / "h"
                    helper.write_bytes(b"#!/bin/sh\n# Existing manager dispatch; fixture never executes it.\nexit 0\n")
                    user_hook = root / ".husky/pre-commit"
                    user_hook.write_bytes(b"#!/bin/sh\n# Existing user-managed checks\nexit 0\n")
                    preserved.extend((helper, user_hook))
                ci = root / ".github/workflows/existing.yml"
                ci.parent.mkdir(parents=True)
                ci.write_bytes(b"name: Existing CI\r\non: [push]\r\njobs: {}\r\n")
                other_ci = root / ".gitlab-ci.yml"
                other_ci.write_bytes(b"stages: [existing]\n")
                preserved.extend((ci, other_ci, root / ".git/config"))
                original = {p: p.read_bytes() for p in preserved}
                value = self.plan((name,), ci=True)
                before = self.snapshot()
                preview = preview_hook(value, value["repositories"][0]["repo_id"])
                self.assertEqual(preview["status"], "preview_only")
                self.assertTrue(preview["existing_hook"])
                self.assertEqual(preview["core_hooks_path"], hooks_path)
                self.assertEqual(Path(preview["active_hook_path"]).resolve(), hook.resolve())
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(Path(preview["checker_snapshot_path"]).exists())
                self.assertEqual({p: p.read_bytes() for p in preserved}, original)
                self.assertEqual(apply_plan(value, value["digest"])["status"], "applied")
                self.assertEqual({p: p.read_bytes() for p in preserved}, original)
                self.assertTrue((root / ".github/workflows/forvynx.yml").is_file())
                self.assertFalse(Path(preview["checker_snapshot_path"]).exists())
                report = verify(value)
                self.assertEqual(report["structure"], "passed")
                self.assertEqual(report["ci_execution"], "not_run")

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
