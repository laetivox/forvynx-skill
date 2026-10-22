# Forvynx v0.1 本地原型

日期：2026-10-22。用户已允许按设计推荐默认值继续实现。

## 已实现

- `skills/forvynx/SKILL.md`：开发/非开发分流、轻量任务路径、设计先行与范围明确的接入流程；保持默认自动匹配策略，未安装到宿主发现目录。
- 标准库控制器：`probe`、`plan`、`apply`、`verify`、`rollback`、`hook-preview`。支持无 Git 父目录、多 checkout、worktree、嵌套边界、中文/空格路径。
- 计划内完整字节载荷、内容摘要与差异；范围和最近所属仓库核对；相关证据漂移拒绝；共享资源锁、幂等应用、日志与条件补偿。无确认时不创建目标配置或状态。
- 通用回退与 Python 清单适配；保留用户 AGENTS 原文，生成最小工作流与固定便携 checker。候选测试命令不会在发现时执行，也不会自动安装工具。
- 可选 GitHub Actions 模板、只读 hook 集成预览。checker 的暂存模式读取一份真实 Git index 快照，兼容活动的 `GIT_INDEX_FILE`，拒绝未解决冲突。
- 标准库元数据/引用/语法检查、可重现 ZIP 打包、Windows/Linux CI 配置。

入口与完整用法见 [Skill](../skills/forvynx/SKILL.md) 和 [命令说明](../skills/forvynx/references/workflow.md)。

## 验证证据

本地环境：Windows，Python 3.12.14，Git 2.47.0.windows.2。

- 最终冻结源码后的完整套件：49 项，48 项通过，1 项因系统不允许创建文件符号链接而跳过，耗时 135.485 秒。
- 已覆盖真实临时仓库 hook 拦截错误暂存配置、静态验证不执行目标 checker、未合并 index 拒绝、Python 候选命令使用当前解释器、不完整生成物拒写、审阅 diff 与实际载荷不一致拒写等场景。
- 分发 ZIP 的可重现构建通过；解压至独立临时目录后，完整执行探测、计划、应用、验证，无需原源码目录。
- Windows junction 场景已经实际通过；文件符号链接跳过不等价于该项通过。
- `scripts/validate_skill.py` 通过：仅验证本项目约定的受限 YAML 元数据、Markdown 引用和 Python 语法，不是通用 YAML 解析器。
- skill-creator 随附 `quick_validate.py` 已尝试，但当前运行时缺少 PyYAML，未宣称通过，也未安装该依赖。
- 独立 Skill 试用完成非 Git 父目录中两个临时仓库的完整流程：一仓标准库 unittest 通过；另一仓保留原 AGENTS 字节。必需检查未运行时 `ready=false`，执行成功后才变为就绪。
- 独立非开发负例：直接交付翻译，没有运行命令、读取/写入文件或探测仓库。

试用期间模板变更触发了旧计划验证拒绝；独立评估通过重新探测、审阅升级计划、应用再验证恢复，未绕过检查。试用还发现未跟踪文件没有计入 dirty，已修正并增加回归测试；损坏 `.git` 被误当空目录的问题同样已有回归修正。

## 当前限制与未执行项

- 按用户后续要求，本地 Git 仓库已初始化为 `main`；远程地址待用户提供，尚未推送或发布。没有用户级 Skill 安装、真实仓库接入、真实 hooks 启用或远端保护变更。
- Linux/Python 3.11 只有 CI 配置，当前会话没有该环境执行证据；远端 CI 尚未运行。
- 自动 Skill 匹配是宿主的最佳努力行为；当前原型未安装，不能声称已经在所有任务中自动触发。
- 本地确认摘要是审计约定；不提供不可伪造的人类批准凭证。脚本边界只约束经该控制器的操作。
- hook 集成须人工审阅并与既有 hook 管理器合并；生成 CI 不等于 CI 执行或已成为合并必需检查。
- 进程超时终止直接子进程；不提供任意仓库代码的进程树沙箱。命令输出默认丢弃，失败时可按现有授权在宿主终端重新诊断。
- 状态与备份位于 OS 临时目录，可能被清理；空目录可能在回滚后保留。部分恢复冲突会留下可追踪日志，不自动覆盖后续用户编辑。

## 在当前机器运行

本机 Python 未加入 PATH，可使用应用随附的绝对路径：

```powershell
& 'C:\Users\sskj-work\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest discover -s tests -v
& 'C:\Users\sskj-work\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B scripts\validate_skill.py
& 'C:\Users\sskj-work\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B scripts\build_package.py
```

这些命令从项目根目录运行。打包输出为 `dist/forvynx-0.1.0.zip`；ZIP 是可审阅的本地分发物，未自动发布，也不意味着已安装为插件。

本次分发包大小为 25,920 字节，SHA-256 为 `da2c8d33c502b74b9c30ff68e269cd33c6ded3be29abc1a83ad4405fd266c6cc`。安装前仍需明确目的地和同名冲突处理；真实仓库接入前先生成其具体计划。
