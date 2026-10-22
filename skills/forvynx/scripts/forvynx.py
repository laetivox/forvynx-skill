#!/usr/bin/env python3
"""Forvynx v0.1: bounded discovery, exact plans, scoped application, verification."""

import argparse
import json
import sys

sys.dont_write_bytecode = True

from forvynx_lib import VERSION
from forvynx_lib.apply import apply_plan, rollback
from forvynx_lib.domain import ForvynxError
from forvynx_lib.hooks import preview_hook
from forvynx_lib.plan import build_plan
from forvynx_lib.probe import probe
from forvynx_lib.verify import verify


def read_json(path):
    with open(path, encoding="utf-8-sig") as source:
        return json.load(source)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("probe")
    p.add_argument("--workspace", required=True)
    p.add_argument("--max-depth", type=int, default=3)
    p.add_argument("--max-dirs", type=int, default=5000)
    p = commands.add_parser("plan")
    p.add_argument("--inventory", required=True)
    p.add_argument("--selection", required=True)
    p = commands.add_parser("hook-preview")
    p.add_argument("--plan", required=True)
    p.add_argument("--repo-id", required=True)
    for command in ("apply", "verify", "rollback"):
        p = commands.add_parser(command)
        p.add_argument("--plan", required=True)
        if command == "verify":
            p.add_argument("--execute", nargs="*", default=[])
            p.add_argument("--confirm-execution")
        else:
            p.add_argument("--confirm", help="Exact reviewed digest; local audit convention, not authentication")
    args = parser.parse_args(argv)
    try:
        if args.command == "probe":
            result = probe(args.workspace, args.max_depth, args.max_dirs)
            code = 0 if result["complete"] else 2
        elif args.command == "plan":
            result = build_plan(read_json(args.inventory), read_json(args.selection))
            code = 0
        elif args.command == "apply":
            result = apply_plan(read_json(args.plan), args.confirm)
            code = 0
        elif args.command == "rollback":
            result = rollback(read_json(args.plan), args.confirm)
            code = 0 if result["status"] != "conflict" else 3
        elif args.command == "hook-preview":
            result = preview_hook(read_json(args.plan), args.repo_id)
            code = 0
        else:
            result = verify(read_json(args.plan), args.execute, args.confirm_execution)
            statuses = {c["status"] for c in result["checks"] if c["required"]}
            code = 4 if "failed" in statuses else (5 if "unsupported" in statuses else (0 if result["ready"] else 2))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except ForvynxError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc), "exit_code": exc.code}, ensure_ascii=False))
        return exc.code
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(json.dumps({"status": "error", "reason": str(exc), "exit_code": 5}, ensure_ascii=False))
        return 5


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
