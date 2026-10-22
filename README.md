# Forvynx

English | [简体中文](README.zh-CN.md)

Automatically set up a right-sized, verifiable coding workflow for your agent.

**v0.1.0 · Prototype**

## Features

- Adapt to task complexity; handle non-development requests directly.
- Support multi-repo workspaces, including non-Git parent directories.
- Preview file changes and preserve existing rules and user edits.
- Verify generated files with scripts; optionally integrate CI and Git hooks.

## Install

Requires **Python 3.11+**, **Git**, and an agent supporting [Agent Skills](https://agentskills.io/specification).

Install [`skills/forvynx`](skills/forvynx) using your agent's Skill installer, or copy the entire folder into its skills directory.

## Use

After installation, ask your agent:

```text
Use Forvynx to inspect this project and set up its coding workflow.
Show the proposal and file changes for confirmation before applying them.
```

Supports Chinese and English; replies follow the language of your request.

## Development

Run from the repository root:

```sh
python -B -m unittest discover -s tests -v
python -B scripts/validate_skill.py
python -B scripts/build_package.py
```

Build output: `dist/forvynx-0.1.0.zip`.

[Usage guide](skills/forvynx/references/workflow.md)
