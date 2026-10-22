---
name: forvynx
description: "Bootstrap or adjust an AI coding workflow for software development: inspect workspace and Git boundaries, preview repository onboarding, and verify generated components. Bypass ordinary translation, writing, and non-development tasks."
---

# Forvynx

Establish only the workflow the current engineering task needs. Use the bundled
controller for deterministic boundary, drift, and verification checks; do not
replace those checks with a statement that you followed these instructions.

## Route the request

- Non-development tasks: complete the request directly, without discovery,
  state files, onboarding questions, or installation.
- Code explanation/review: read only relevant material; no onboarding by default.
- Small development task: follow existing engineering guidance and relevant checks.
  Do not force a new workflow or repeat an already settled design review.
- New feature or structural change: agree on a proportionate design and acceptance
  criteria before substantial implementation. Existing user approval remains valid.
- Workflow setup or explicit onboarding: use the procedure below.

An installed Skill can be selected implicitly, but cannot guarantee interception
of every conversation. Explicit `$forvynx` is also supported. If the user declines
onboarding, continue the original authorized task under existing conventions.

## Discover, preview, confirm, apply, verify

Use Python 3.11+ to run `scripts/forvynx.py` (paths below are relative to this
skill). The controller uses only the standard library and local Git. Read
[workflow.md](references/workflow.md) for commands, selection format, and recovery.

1. Determine the user-selected workspace and applicable instructions. A workspace
   may have no Git repository or contain multiple independent repositories.
2. Run `probe` only for development/setup work. Report incomplete discovery and
   errors honestly. Never initialize Git, follow external links, run repository
   scripts, or install dependencies during discovery.
3. Select only the intended checkouts. Nested repositories, submodules, linked
   worktrees, and newly discovered repositories are separate boundaries.
4. Generate a `plan`. Read its complete scope, diff, commands, and state location.
   Preserve existing guidance, dirty work, hooks, and CI. Keep design and workflow
   suggestions proportional to the evidence; no mandatory DDD/TDD/multi-agent stack.
5. Before installation, first onboarding, or extending an existing scope, obtain
   explicit user authorization for that concrete plan, unless existing direct
   authorization already covers it. Do useful preparation before asking. A local
   receipt or digest is an audit convention, not proof of human consent. Never
   fabricate approval or treat Skill invocation as installation permission.
6. Apply only that plan, then run static `verify`. Run only separately authorized
   checks bound to that plan. Do not install missing tools automatically.
7. Report `passed`, `failed`, `not_run`, and `unsupported` separately. Required
   checks not run prevent a ready result. Report partial writes and recovery
   conflicts; do not reset, stash, or overwrite subsequent user edits.

Generated hook snippets require manual integration with an existing hook manager;
the controller does not enable hooks or change `core.hooksPath`. CI configuration
generation is optional and does not mean CI has run or merge protection is active.
Do not install global host hooks, publish, or change remote rules by default.
