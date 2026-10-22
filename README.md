# Forvynx

**先理解工程，再建立适合它的 AI 编码工作流。**

Forvynx 是一个面向 Codex 的 bootstrap Skill：识别开发需求，检查工作区与 Git 边界，在用户确认后生成适量的协作规则，并用确定性脚本验证生成结果。

当前版本：**v0.1.0 · 本地原型**。核心使用 Python 标准库和 Git，无需安装第三方 Python 运行依赖。

## 为什么使用 Forvynx

AI 编码流程应随任务和工程变化。修一个小问题不需要先搭一套体系；持续开发又需要可复用的工程入口、清楚的边界和真实的检查结果。

Forvynx 将语义判断留给 Skill，将可以确定检查的约束交给程序：

| Skill 负责 | 控制器负责 |
| --- | --- |
| 判断是否为开发任务，以及需要多重的流程 | 识别工作区、checkout 和路径边界 |
| 提出与工程证据匹配的设计和工作流 | 生成带完整内容、摘要和差异的计划 |
| 在大规模实现前形成设计共识 | 核对确认范围、文件漂移和覆盖冲突 |
| 解释结果与未解决事项 | 应用、验证、记录结果及有条件恢复 |

## 核心能力

- **开发意图分流**：翻译、写作等非开发任务直接处理；只读代码解释不默认接入；小改动保持轻量。
- **多仓库工作区**：父目录可以没有 Git，目录下各仓库分别识别和接入，兼容 linked worktree 与嵌套仓库边界。
- **先预览后接入**：首次安装、接入新仓库或扩大范围前，展示具体目标、文件差异和命令。
- **按已有工程适配**：首版提供通用回退与 Python 清单适配，保留原有规则，不默认强加 DDD、TDD 或多代理流程。
- **确定性应用与验证**：检查摘要、归属、范围和漂移；重复执行不追加；冲突时保留用户后续编辑。
- **可选门禁**：生成独立 GitHub Actions 配置或本地 hook 集成预览，复用固定的便携检查器。

```text
任务分流 → 只读发现 → 设计与变更预览 → 确认 → 受限应用 → 验证
```

用户暂不接入时，仍可按原任务授权和工程已有约定继续编码。

## 环境要求

- Python **3.11 或以上**。
- 可通过命令行调用的 Git。
- 使用 Skill 时，需要支持本地 Skill 和文件/命令操作的 Codex 环境。

以下命令均从本仓库根目录执行，`python` 指实际可用的解释器。Windows 未将 Python 加入 PATH 时，可换成 `py -3`，或使用解释器的绝对路径。

## 使用 Skill

Skill 源目录是 [`skills/forvynx`](skills/forvynx)，入口为 [`SKILL.md`](skills/forvynx/SKILL.md)。

可以在具备本地文件访问能力的 Codex 会话中直接提出：

> 使用当前仓库 skills/forvynx 下的 Forvynx Skill，检查我指定的工作区。先给出仓库边界、工作流建议和具体变更预览，确认接入后再应用。

如需持久安装，可让 Codex 将**整个 `skills/forvynx` 目录**安装到当前宿主支持的 Skill 发现位置。安装前明确目的地及同名冲突处理；本项目不自动修改用户级配置，也不提供未经确认的覆盖安装。

安装并确认被宿主发现后，可显式调用：

```text
$forvynx 为这个工作区建立适量的 AI 编码工作流，先展示方案和接入差异。
```

Skill 保持默认自动匹配能力，但能否自动触发由宿主判断，不保证拦截每一条对话。

## 直接运行控制器

不安装 Skill 也可以使用脚本。先确认入口可运行：

```text
python -B skills/forvynx/scripts/forvynx.py --version
```

### 1. 只读发现

下面是 PowerShell 示例，将 `D:\work` 换成你选择的工作区。中间文件保存在已忽略的 `.forvynx-preview` 目录中：

```powershell
New-Item -ItemType Directory -Force .forvynx-preview | Out-Null
python -B skills/forvynx/scripts/forvynx.py probe --workspace 'D:\work' |
    Set-Content -Encoding utf8 .forvynx-preview/inventory.json
```

探测不初始化 Git、不安装依赖、不运行工程脚本。默认发现深度为 3，目录/条目预算为 5,000；结果中的 `complete: false` 表示未完成全部发现，不能理解为没有其他仓库。

### 2. 选择仓库并生成计划

根据发现结果创建 `.forvynx-preview/selection.json`。例如，只接入工作区下的 `service-a`：

```json
{
  "repositories": [
    { "path": "service-a" }
  ]
}
```

如果仓库根与工作区根相同，使用 `"path": "."`。多个仓库分别列出，发现到的仓库不会自动全部接入。

```powershell
python -B skills/forvynx/scripts/forvynx.py plan `
    --inventory .forvynx-preview/inventory.json `
    --selection .forvynx-preview/selection.json |
    Set-Content -Encoding utf8 .forvynx-preview/plan.json
```

计划包含具体文件差异、完整写入载荷、前后摘要、checkout 身份、检查命令、范围及 `digest`。生成计划不会应用这些变更。

### 3. 确认后应用，再验证

完整审阅计划并取得对应范围的授权后，将下面的摘要字符串替换为计划中真实的 `digest`：

```text
python -B skills/forvynx/scripts/forvynx.py apply --plan .forvynx-preview/plan.json --confirm "已审阅计划的 digest"
python -B skills/forvynx/scripts/forvynx.py verify --plan .forvynx-preview/plan.json
```

摘要确认是一种本地审计约定，不能独立证明人类已批准。助手或自动化流程仍须遵守实际用户授权，不能把拥有计划文件当成允许应用。

### 4. 运行已授权的工程检查

在 selection 的仓库项中声明经过审阅的 `checks`。控制器不会自动执行从清单中发现的 `test` 或 `lint` 命令。完整字段和例子见 [控制器使用说明](skills/forvynx/references/workflow.md)。

```text
python -B skills/forvynx/scripts/forvynx.py verify --plan .forvynx-preview/plan.json --execute "repo-id:check-id" --confirm-execution "同一计划的 digest"
```

检查 ID 使用计划中 `checks` 的真实 `key`。状态区分 `passed`、`failed`、`not_run` 和 `unsupported`；必需检查未运行不能算通过。没有配置工程检查时，就绪仅表示生成工作流可用，不代表业务代码已经测试。

## 会生成哪些文件

| 位置 | 用途 |
| --- | --- |
| `<workspace>/.forvynx/workspace.json` | 已接入仓库索引 |
| `<repo>/.forvynx/repo.json` | 工程 profile、组件与检查清单 |
| `<repo>/.forvynx/workflow.md` | 适合当前工程的精简工作流 |
| `<repo>/.forvynx/check.py` | 固定模板的便携检查器 |
| `<repo>/AGENTS.md` 中的专属块 | 工作流入口，保留原有非托管文字 |
| `<repo>/.github/workflows/forvynx.yml` | 选择 `"ci": true` 时生成的独立 CI 配置 |

本机审计记录和备份放在 OS 临时目录 `forvynx-state/<workspace-hash>`，不进入目标仓库。临时目录可能被系统清理，不能当作永久备份。

## 冲突、恢复与可选门禁

应用前后都会核对边界与内容。计划后出现的新嵌套仓库、相关输入变化、托管文件漂移或覆盖冲突都会阻止继续。跨仓库应用不提供整体原子事务；部分失败会记录状态并尝试条件补偿。

需要恢复时，先检查日志，再使用原计划：

```text
python -B skills/forvynx/scripts/forvynx.py rollback --plan .forvynx-preview/plan.json --confirm "原计划的 digest"
```

恢复只处理本事务尝试过、且当前内容仍符合相应摘要的文件，不覆盖用户后续编辑；不会使用 `reset`、`clean` 或 `stash`。回滚后可能保留空目录。

`hook-preview` 仅输出集成方案，不安装 hook 或修改 `core.hooksPath`。暂存检查读取同一份 Git index 快照。已有 hook 管理器需要单独审阅和整合。

GitHub Actions 配置的生成不表示 CI 已运行，也不表示合并保护已启用。本地 hook 可以被跳过，脚本也只约束经过其入口的操作。

## 开发与打包

```text
python -B -m unittest discover -s tests -v
python -B scripts/validate_skill.py
python -B scripts/build_package.py
```

打包产物为 `dist/forvynx-0.1.0.zip`，采用可重现构建，包含独立的 `forvynx/` Skill 目录。`dist/` 不纳入源码提交；生成 ZIP 不代表已安装或发布。

当前本地验证记录：49 项测试中 48 项通过，1 项因 Windows 文件符号链接权限跳过；junction 场景和独立解压运行已验证。仓库包含 Windows/Linux、Python 3.11/3.12 的 CI 配置，远端实际执行结果以 GitHub 为准。

`validate_skill.py` 检查本项目约定的受限元数据格式、引用和 Python 语法，不是通用 YAML 校验器。

## 项目结构

```text
skills/forvynx/       可安装的 Skill、控制器、模板及参考资料
tests/               临时工作区中的行为、边界与打包测试
scripts/             开发期校验和可重现打包脚本
docs/                设计、实现状态与交接说明
.github/workflows/   本项目的 CI 配置
```

进一步阅读：[设计规格](docs/forvynx-v0.1-design.md) · [实现与验证记录](docs/implementation-status.md) · [控制器命令参考](skills/forvynx/references/workflow.md)。
