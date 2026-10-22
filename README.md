# Forvynx

English | [简体中文](README.zh-CN.md)

A portable Agent Skill that bootstraps a right-sized, verifiable AI coding workflow.

**v0.1.0 · Prototype** — works with agents that support [Agent Skills](https://agentskills.io/specification) and local file/command access.

## Features

- **Right-sized workflows:** keep small tasks lightweight and skip setup for non-development requests.
- **Multi-repo workspaces:** handle independent checkouts, even when their parent directory is not a Git repository.
- **Preview before onboarding:** review scoped changes before applying them; preserve existing guidance and user edits.
- **Verifiable results:** deterministic checks, conditional recovery, and optional CI/hook integration.

## Install

Requirements: **Python 3.11+** and **Git**. No third-party Python runtime dependencies.

Install the entire [`skills/forvynx`](skills/forvynx) directory using your agent's Skill installer, or copy it into that agent's supported skills location. Confirm the destination and any existing-file conflicts first. Host-specific metadata is optional.

## Use

Ask your agent to load Forvynx by name or by its [`SKILL.md`](skills/forvynx/SKILL.md) path:

```text
Use Forvynx to set up a lightweight AI coding workflow for this workspace.
Show the repository boundaries, proposal, and file changes before applying them.
```

Replies follow your Chinese or English request. Activation syntax depends on the agent; commands and JSON keys stay unchanged.

```text
Discover → Propose → Confirm → Apply → Verify
```

Installation, onboarding new repositories, and expanding scope require authorization. Required checks that have not run are reported as pending, not passed.

## Development

Run from the repository root:

```sh
python -B -m unittest discover -s tests -v
python -B scripts/validate_skill.py
python -B scripts/build_package.py
```

Build output: `dist/forvynx-0.1.0.zip`.

[Command reference](skills/forvynx/references/workflow.md) · [Design (中文)](docs/forvynx-v0.1-design.md) · [Implementation notes (中文)](docs/implementation-status.md)
