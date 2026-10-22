# Forvynx

[English](README.md) | 简体中文

为你的agent自动搭建适量、可验证的编码工作流。

**v0.1.0 · 原型**

## 特性

- 按任务复杂度调整流程，非开发请求直接处理。
- 支持多仓库工作区，父目录无需是 Git 仓库。
- 应用前预览文件差异，保留已有规则和用户修改。
- 用脚本校验生成结果，可接入 CI 和 Git hooks。

## 安装

需要 **Python 3.11+**、**Git** 和支持 [Agent Skills](https://agentskills.io/specification) 的 Agent。

通过 Agent 的 Skill 安装器安装 [`skills/forvynx`](skills/forvynx)，或将整个目录复制到其 Skill 目录。

## 使用

安装后向 Agent 发送：

```text
使用 Forvynx 检查这个项目，搭建开发工作流。
先给出方案和文件差异，确认后再应用。
```

支持中文和英文，默认跟随你的提问语言。

## 开发

从仓库根目录运行：

```sh
python -B -m unittest discover -s tests -v
python -B scripts/validate_skill.py
python -B scripts/build_package.py
```

打包产物：`dist/forvynx-0.1.0.zip`。

[详细用法](skills/forvynx/references/workflow.md)
