# Forvynx

[English](README.md) | 简体中文

一个通用 Agent Skill，为当前工程建立适量、可验证的 AI 编码工作流。

**v0.1.0 · 原型** — 适用于支持 [Agent Skills](https://agentskills.io/specification) 且具备本地文件和命令访问能力的 Agent。

## 特性

- **流程适量**：小任务保持轻量，非开发请求直接处理。
- **多仓库工作区**：支持独立 checkout，父目录可以不是 Git 仓库。
- **接入前预览**：确认具体范围和文件差异后再应用，保留原有约定与用户修改。
- **结果可验证**：确定性检查、条件恢复，以及可选的 CI/hook 集成。

## 安装

需要 **Python 3.11+** 和 **Git**，无需第三方 Python 运行依赖。

通过目标 Agent 的 Skill 安装器安装整个 [`skills/forvynx`](skills/forvynx) 目录，或将其放入该 Agent 支持的 Skill 发现位置。安装前确认目的地和同名冲突；宿主专用元数据为可选项。

## 使用

让 Agent 按名称或 [`SKILL.md`](skills/forvynx/SKILL.md) 路径加载 Forvynx：

```text
使用 Forvynx 为这个工作区建立适量的 AI 编码工作流。
先展示仓库边界、方案和文件差异，确认后再应用。
```

回复跟随你的中文或英文请求。调用语法遵循对应 Agent，命令和 JSON 字段保持不变。

```text
发现 → 提议 → 确认 → 应用 → 验证
```

安装、接入新仓库或扩大范围需要授权；必需检查未运行时会明确标记，不会视为通过。

## 开发

从仓库根目录运行：

```sh
python -B -m unittest discover -s tests -v
python -B scripts/validate_skill.py
python -B scripts/build_package.py
```

打包产物：`dist/forvynx-0.1.0.zip`。

[命令参考](skills/forvynx/references/workflow.md) · [设计规格](docs/forvynx-v0.1-design.md) · [实现记录](docs/implementation-status.md)
