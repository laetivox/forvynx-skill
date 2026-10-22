# Forvynx：需求清单与上下文交接

更新日期：2026-10-22（Asia/Shanghai）。本次核对的代码基线：`2c1a48b08733361cb4e0ed6c7d6000690afde427`，版本 `0.1.0`。本文的文档提交可晚于该代码基线。

仓库：[laetivox/forvynx-skill](https://github.com/laetivox/forvynx-skill)，主分支 `main`。当前机器项目目录：`C:\Users\sskj-work\Documents\ChatGPT\forvynx.skill`；换机器时使用实际 checkout 路径。

本文用于新上下文接续，区分需求、实现和验证。它不是全量完成声明，也不授权安装到用户机器或接入其他真实项目。

## 1. 需求解释与变更规则

1. 用户后续明确指令优先于本文；本文记录的最新取舍优先于旧设计中的过时措辞。详细技术背景见 [设计规格](forvynx-v0.1-design.md)，实际 CLI 见 [使用说明](../skills/forvynx/references/workflow.md)。
2. 原 ChatGPT 会话“推荐AI项目”的助手正文未能完整恢复。不能补写为“用户此前已经确认”的需求；可确认的依据是本次接续上下文和已落盘资料。
3. 修改需求时保留本清单 ID，写明原要求、修改理由、用户依据、影响范围和验收变化。Agent 建议不是用户决定。
4. 修复既定行为可继续；新增大功能、技术栈适配或改变产品定位，先给与规模匹配的设计。已有明确设计授权不重复询问。
5. 状态推进必须附代码位置或验证证据。新增代码不自动等于验收通过；跳过、缺环境和未核验都不能记为通过。

状态含义：**已实现**＝代码中存在该能力；**指令已实现**＝Skill 有明确要求，但语义行为依赖 Agent；**部分实现**＝只覆盖部分设计；**待验证**＝缺执行证据；**未实现**＝设计内仍有缺口；**非首版范围**＝不自动排入待办。

## 2. 已确定的产品方向

| ID | 冻结要求 | 当前状态与边界 |
| --- | --- | --- |
| P01 | 名称 Forvynx；中文简介固定为“为你的agent自动搭建适量、可验证的编码工作流。” | 已落实两版 README；不要改回“为项目”或加“一个通用 Agent Skill” |
| P02 | 面向能加载该格式的 Agent，不限定 Codex | 已实现通用 Skill 和独立控制器；跨宿主安装/触发仍待实测 |
| P03 | 核心过程：识别任务 → 只读发现 → 适量方案 → 具体差异 → 确认 → 应用 → 验证 | 原型闭环已实现；语义分流和方案适配不是脚本自动证明 |
| P04 | 大规模代码前先达成设计共识；小修改流程保持轻量 | 指令已实现；不为每次修改重开设计审批 |
| P05 | 非开发小任务直接处理；不扫描、不建状态、不提安装 | 指令已实现；历史有一次翻译负例，系统评估待补 |
| P06 | 支持中文、英文；Agent 解释跟随用户语言，字段和命令保持稳定 | 指令已实现；不是要求所有固定模板双语；README 不再声明该语言规则 |
| P07 | README 简洁，英文 README.md 与中文 README.zh-CN.md 相互链接，详细流程放参考资料 | 已实现；不恢复“开发”章节、语言说明或打包介绍 |
| P08 | 克隆/下载后安装完整 skills/forvynx 目录；不要求用户或维护者自定义打包 | 已实现；打包脚本和 dist 产物已删除；没有正式 Release 发布记录 |
| P09 | 一个 Skill 配合必要的确定性脚本、可选 hooks/CI；不能只靠提示词约束 | 已实现原型；不据“只是 Skill”删除必要验证逻辑，也不扩成常驻服务 |
| P10 | 当前首版技术取舍为 Python 3.11+ 标准库和 Git，通用回退 + Python 证据适配 | 已采用；无厂商 API、SDK 或 pip 必需依赖；不要再称该取舍“待确认” |
| P11 | 不默认强加 DDD、TDD、多代理、大量子 Skill 或长文档体系 | 指令已实现；目标项目已有要求时沿用 |

## 3. 功能与约束清单

### 3.1 触发、任务规模与授权

主要证据：[SKILL.md](../skills/forvynx/SKILL.md)。

| ID | 必须满足的内容 | 状态 / 尚缺内容 |
| --- | --- | --- |
| R01 | 支持显式加载和宿主可用的 Skill 匹配，不把某产品的调用语法当通用语法 | 指令已实现；隐式匹配的跨宿主可靠性待验证 |
| R02 | 翻译、写作等非开发任务绕过 Forvynx；只读解释/评审不自动接入 | 指令已实现；只读评审等真实行为评估待补 |
| R03 | 普通小改动遵循已有规则，只做相关检查；用户拒绝接入仍能完成原任务 | 指令已实现；拒绝接入后的完整行为评估待补 |
| R04 | 新功能/结构变更先明确目标、边界、接口、取舍和验收，再实施 | 指令已实现；依赖 Agent 交互，非确定性语义判定器 |
| R05 | 首次安装、首次接入、新仓库、扩大范围前提供具体位置、文件差异、命令和影响 | 仓库计划已实现；宿主安装目的地/冲突预览只有指令，尚无已交付实例 |
| R06 | 已有范围明确的授权持续有效；不反复确认，不将设计批准推断为全局安装授权 | 指令已实现；控制器只核对摘要约定 |
| R07 | 安装、接入、执行检查、安装 hook、CI 变更分别辨明授权范围 | 指令及计划 scope 已实现；没有统一宿主授权事件适配 |
| R08 | 可编辑 JSON、摘要或 --confirm 不是不可伪造的人类授权证明 | 已实现告知与摘要核对；不得声称能抵抗 Agent 伪造确认 |

### 3.2 工作区、仓库与只读发现

主要代码：[probe.py](../skills/forvynx/scripts/forvynx_lib/probe.py)、[boundary.py](../skills/forvynx/scripts/forvynx_lib/boundary.py)、[adapters.py](../skills/forvynx/scripts/forvynx_lib/adapters.py)。

| ID | 必须满足的内容 | 状态 / 尚缺内容 |
| --- | --- | --- |
| W01 | 工作区父目录可不是 Git 仓库；支持多个独立 checkout，按选择分别接入 | 已实现，有临时多仓测试；单仓根等于工作区根也覆盖 |
| W02 | 区分工作区、checkout 和模块；不能因有工程清单就当成独立仓库 | checkout 身份已实现；模块清单/模块专属工作流未实现 |
| W03 | 支持 .git 目录/文件、linked worktree、嵌套仓库与子模块独立边界 | 识别基础已实现；worktree/嵌套有测试，真实 submodule 专项待补 |
| W04 | common Git 目录可在外部，只读取身份，不接管公共配置或其他 worktree | 已实现，有 worktree 不改公共配置测试 |
| W05 | 工作区外的真实仓库根只报告关系；不得自动扩大范围或读取其工程证据 | 已实现，有测试 |
| W06 | 默认深度 3、目录/枚举预算 5000；排除依赖/缓存/.git，不跟随重解析点 | 已实现有界扫描；找到仓库后仍在预算内递归发现嵌套，和旧设计“发现即停止普通递归”表述有差异，见 G04 |
| W07 | 达上限、权限错误、缺 Git、损坏元数据分别如实报告；不自动 git init | 已实现主要错误路径；权限拒绝专项待补 |
| W08 | 规范化路径并核对真实包含关系，拒绝 ..、相似前缀误判、设备名、ADS、链接越界 | 已实现并有多项测试；UNC/大小写敏感目录组合仍待实测 |
| W09 | 证据文件读取也受边界限制，不跟随 AGENTS/清单链接读取外部内容 | 已实现；本机文件 symlink 测试历史跳过，junction 已有执行证据 |
| W10 | 每个写入目标重新核对最近所属 checkout；新出现的嵌套边界阻止旧计划写入 | 已实现，有计划后新增嵌套仓库拒写测试 |
| W11 | probe/plan/静态 verify 不执行工程脚本、不导入目标 checker、不安装依赖、不联网 | 已实现，有副作用哨兵与目标 checker 不执行测试 |
| W12 | 保留 dirty 和未跟踪文件；不 stash/reset/clean，不改全局 Git 配置 | 已实现相关路径与回归；Git 查询关闭可选锁、fsmonitor 等辅助行为 |

### 3.3 自适应方案与生成物

主要代码：[adapters.py](../skills/forvynx/scripts/forvynx_lib/adapters.py)、[plan.py](../skills/forvynx/scripts/forvynx_lib/plan.py)。

| ID | 必须满足的内容 | 状态 / 尚缺内容 |
| --- | --- | --- |
| A01 | 从已有规则、工程清单、锁文件、测试配置、CI 中获取证据，而非凭空套流程 | 部分实现：收集固定根级证据及最多 16 个 CI 文件摘要；深入解析/继承多层规则主要靠 Agent |
| A02 | 建议说明证据、未知项及可信程度，保留现有工程约定 | 部分实现：有证据摘要、警告和候选来源；未形成逐项建议理由/置信程度契约 |
| A03 | 提供通用回退与 Python 适配，候选命令只推荐、不自动执行或安装工具 | 已实现基础适配：pyproject.toml 中的 pytest/ruff/mypy 工具节可给候选；其他配置多为证据，不能宣称完整 Python 工具链识别 |
| A04 | 工作流随项目证据、任务规模和现有约定调整，支持轻量/标准/跨仓需要 | 部分实现：Skill 有分流，选择可定制 checks/CI；workflow() 目前是固定文字加 profile，不接受项目专属方案，属核心缺口 G01 |
| A05 | 每仓生成最小入口和配置：workspace.json、repo.json、workflow.md、AGENTS 托管块、固定 check.py | 已实现；workspace.json 是工作区级共享索引，其余按 checkout 管理 |
| A06 | AGENTS 非托管内容保留，标记缺损/重复拒绝，不直接覆盖同名非托管文件 | 已实现；支持 UTF-8，保留已有换行文本；不能安全处理的编码拒绝转换 |
| A07 | 不在非 Git 父目录创建庞大 AGENTS 并假定子仓继承；宿主不自动读入口时显式读 workflow | 指令与生成结构已实现；跨宿主加载行为待实测 |
| A08 | 工程命令按完整 argv/cwd/env/timeout/required/sources 审阅并绑定来源 | 已实现结构与来源漂移核对；依赖、网络和其他副作用尚无结构化声明字段 |
| A09 | 便携配置与 checker 随目标仓库版本化，CI 不依赖用户本机 Skill | 已实现；单独复制 Skill 后完整运行也通过；本机路径只进入本地计划/状态，不进入默认便携模板 |
| A10 | 没有可靠工程检查时如实报告未配置，不能把结构完成说成业务通过 | 已实现 ready_scope=generated_workflow_only、engineering_verification=not_configured |

### 3.4 计划、应用与恢复

主要代码：[domain.py](../skills/forvynx/scripts/forvynx_lib/domain.py)、[plan.py](../skills/forvynx/scripts/forvynx_lib/plan.py)、[apply.py](../skills/forvynx/scripts/forvynx_lib/apply.py)。

| ID | 必须满足的内容 | 状态 / 尚缺内容 |
| --- | --- | --- |
| T01 | 计划包含 schema、checkout 身份、范围、完整载荷、前后摘要、真实 diff、命令及证据 | 已实现主要字段；旧设计里更完整的数据契约仍有差异，见 G03 |
| T02 | 摘要稳定，区分 absent 与空文件；payload/diff/摘要必须一致，未知格式拒绝 | 已实现；有篡改、不完整组件、误导 diff、未知 schema 回归 |
| T03 | 无确切摘要确认时目标与本地审计状态都不写 | 已实现并有测试；人类批准来源仍需外部交互保证 |
| T04 | 应用前重查范围、身份、相关证据、目标状态；相关漂移在写入前阻止 | 已实现内容/身份预检；没有对所有目标写权限进行可靠的预先保证，I/O 失败靠补偿，见 G03 |
| T05 | 工作区索引与各仓资源协调加锁，固定顺序获取，逐文件重查边界 | 已实现；共享锁互斥有测试，多进程争用/崩溃专项待补 |
| T06 | 只写计划路径，临时文件与原子替换，保持文件模式，非计划文件保留 | 已实现；不承诺跨文件或跨仓整体原子事务 |
| T07 | 重复应用 no_change，不重复插入入口，不制造无意义变化 | 已实现，有测试 |
| T08 | 多仓部分失败如实报告，记录事务和备份，条件补偿 | 已实现，故障注入有测试；真实跨盘/进程崩溃仍待验证 |
| T09 | rollback 只恢复仍匹配本次 after 的内容，保留后续用户编辑与冲突记录 | 已实现，有后续编辑、重复回滚和残留探测测试 |
| T10 | 本机审计/备份在 OS 临时目录，残留恢复优先显示；不自动删未知过期锁 | 已实现；临时目录可能被系统清理，不承诺长期恢复 |
| T11 | 托管组件升级先检查已有内容与模板，漂移不静默覆盖 | 已实现保守拒绝和新计划路径；定制内容合并/迁移工具未实现，不可擅自加需求 |

### 3.5 验证与门禁

主要代码：[verify.py](../skills/forvynx/scripts/forvynx_lib/verify.py)、[portable.py](../skills/forvynx/scripts/forvynx_lib/portable.py)、[hooks.py](../skills/forvynx/scripts/forvynx_lib/hooks.py)。

| ID | 必须满足的内容 | 状态 / 尚缺内容 |
| --- | --- | --- |
| V01 | 区分结构、计划一致性、产品行为测试、目标工程检查，不混为“全部通过” | 已实现分层机制；行为测试是产品套件，不是每次 verify 自动执行 |
| V02 | 用产品模板基线静态验证，不运行/导入目标生成 checker 来证明自身正确 | 已实现，有拒绝执行目标 checker 测试 |
| V03 | 工程检查仅运行批准计划中的 ID，绑定命令来源；不信任被改写的 repo.json | 已实现，有命令定义不一致/来源漂移回归 |
| V04 | 状态区分 passed/failed/not_run/unsupported；必需检查没运行不能 ready | 已实现，有失败、缺工具、超时和未运行回归 |
| V05 | 参数数组运行，不拼 shell，固定 cwd、有超时；不自动补装依赖 | 已实现；继承宿主环境再覆盖选定变量，非洁净环境；无进程树沙箱 |
| V06 | 检查报告保留命令、目录、退出码、耗时、原因；输出处理有明确限制 | 部分实现：已运行检查具备主要字段，stdout/stderr 丢弃；未运行项字段较少，无日志引用，见 G03 |
| V07 | 可选 Git hook 预览应展示真实路径、已有 hook、hooksPath、共享 worktree 情况 | 已实现 hook-preview，只读且包含绑定摘要的 checker 副本/片段；不自动安装 |
| V08 | hook 用同一暂存快照检查配置/引用，支持 GIT_INDEX_FILE，拒绝未合并 index | 已实现，包含真实临时 commit 拦截测试；index 模式不运行工程测试 |
| V09 | 保留现有 hook/管理器，不改全局配置；安装、实测和恢复作为具体接入动作 | 指令与手工方案已实现；真实用户项目接入、卸回演练和安装预览实例待做，非自动安装器需求 |
| V10 | 可选 GitHub Actions 模板固定 action 提交、最小权限、独立配置，不暗中装依赖 | 已实现生成；其他 CI 仅提供通用 checker 入口 |
| V11 | 区分配置已生成、hook 已安装、CI 已运行、远端必需检查已启用 | 已实现保守默认报告；没有实时探测外部启用状态，不得误读为实时仪表盘 |
| V12 | 真实远端保护才提供合并强制性，不能把本地 hook 或 YAML 存在说成不可绕过 | 指令已实现；首版不自动改远端规则 |
| V13 | 产品本身有元数据/引用/语法校验、临时仓库回归、Windows/Linux CI 配置 | 已实现；本机主要证据为 Windows，远端执行结果未核验 |

## 4. 原设计验收 A01–A18 的证据映射

下面的“设计验收 Axx”编号来自旧设计，与上一节“功能 Axx”分开使用。测试均在 [test_controller.py](../tests/test_controller.py)；此表不把存在测试函数等同于最新版本已全量跑过。

| 设计验收 | 当前可用证据 | 剩余验证 |
| --- | --- | --- |
| A01 非开发绕过 | Skill 指令；历史一次独立翻译负例 | 更多负例、误触发、用户纠正，保存可复现记录 |
| A02 只读解释 | Skill 指令 | 独立 Agent 行为评估 |
| A03 空非 Git 工作区 | test_empty_workspace_probe_is_read_only | 已有程序证据 |
| A04 多仓仅接入选定仓 | test_multi_repo_select_one_preserves_other；历史两仓试用 | 已有程序和历史试用证据 |
| A05 新仓/嵌套/子模块 | test_nested_repo_is_separate_candidate、test_nested_checkout_appearing_after_plan_blocks | 真实 submodule、新增独立仓接入生命周期专项 |
| A06 linked worktree | test_worktree_identity_and_common_metadata | 更复杂 hooksPath/共享 hook 手工接入验证 |
| A07 路径语义 | test_unicode_and_space_repository_names、test_read_guard_blocks_escape_and_similar_prefix | UNC、大小写敏感目录/别名组合 |
| A08 链接/替换越界 | test_windows_junction_is_rejected、test_linked_evidence_is_not_read | 本机文件 symlink 历史跳过；写入期间路径替换专项 |
| A09 限制/权限 | test_scan_limits_report_incomplete、缺 Git/损坏元数据测试 | 真实拒绝访问、网络盘错误专项 |
| A10 无批准/漂移 | test_no_confirmation_does_not_write_or_create_state、test_plan_tamper_is_rejected、test_file_drift_before_apply_refuses_all_writes 等 | 已有主要程序证据 |
| A11 保留用户规则/dirty/hook/CI | test_existing_agents_bytes_preserved、test_unmanaged_files_are_not_overwritten、test_untracked_files_are_dirty、只读 hook 预览 | 已有 hook 管理器及现存 CI 的完整保留样例 |
| A12 幂等 | test_idempotent_replay、test_same_workspace_as_single_repository | 已有程序证据 |
| A13 失败恢复 | test_partial_failure_compensates、test_recovery_preserves_subsequent_edit、test_conflict_journal_is_visible_in_probe | 多进程崩溃/跨盘真实失败样例 |
| A14 不执行发现的脚本 | test_discovery_does_not_execute_package_scripts、test_static_verify_never_executes_target_checker | 已有程序证据 |
| A15 生成物无效 | test_incomplete_bundle_cannot_be_applied、test_misleading_diff_cannot_be_applied、元数据/引用校验 | 独立固定预期对所有模板的覆盖需复核，不能仅依赖同一生成器自检 |
| A16 检查状态 | test_required_check_is_not_passed_when_not_run、test_failed_check_is_not_passed、test_missing_executable_and_timeout_are_not_success | 已有主要程序证据 |
| A17 门禁真实生效 | test_hook_preview_writes_nothing、test_real_fixture_hook_rejects_bad_staged_config、test_active_alternate_index_is_used、test_unmerged_index_is_rejected、CI 保守报告测试 | 真实宿主安装预览、真实项目接入需后续具体授权；远端 CI 结果待核验 |
| A18 拒绝接入仍修小问题 | Skill 指令 | 独立 Agent 行为评估 |

## 5. 核心缺口与后续顺序

以下是设计内的未完成/未闭合事项，不代表本次已授权立即编写所有相关代码。先核对缺口，再给必要的具体方案。

| ID / 顺序 | 当前缺口 | 下一步与完成条件 |
| --- | --- | --- |
| G01 / 优先 | 自适应工作流仅有固定模板加 profile，无法承载项目专属决策 | 先设计最小、可审核、可验证的方案表示，明确 Agent 决策与固定 checker 边界；用两个证据不同的工程证明工作流确实相应变化，且未知项不伪造、已有规则不覆盖。不要把自由生成代码变成可信 checker |
| G02 / 优先 | 实现状态容易被误报为“所有需求已验收” | 按本清单和设计验收映射复核当前测试，补缺失高价值样例；核验 GitHub 4 个矩阵任务结果；区分平台缺环境与程序错误 |
| G03 / 随闭环处理 | 旧设计的数据/报告契约与实现不完全一致 | 逐项决定补实现还是按已接受首版范围收敛文档，保留理由。具体包括建议依据/置信程度、命令依赖与副作用说明、批准时间、报告字段与日志引用、全目标写权限预检；不为满足抽象表格增加无用框架。契约修改不能静默进行 |
| G04 / 随发现测试处理 | 发现策略是预算内继续递归，旧设计曾写发现仓库后停止普通递归 | 保留嵌套仓发现要求，比较扫描范围/成本；明确采用的策略并更新设计、补回归。不能直接删掉嵌套发现来追求“停止扫描” |
| G05 / 优先验收 | 跨 Agent 的加载、显式调用、隐式匹配、只读/拒绝接入负例证据不足 | 用可用宿主建立正负例与用户纠正记录；宿主能力逐个报告。测试自身不得借机安装到用户级目录，除非用户已有明确目的地授权 |
| G06 / 发布检查 | 首版安装目的地与冲突处理尚无具体可审阅交付样例 | 给一个目标宿主的实际安装预览/手工步骤及冲突策略；安装仍按用户具体授权执行。自动安装器不属于首版要求 |
| G07 / 补齐验收 | submodule、UNC/大小写、权限错误、并发/崩溃、现有 hook/CI 集成覆盖不完整 | 依风险补关键场景，并记录不能运行的环境；不将原型宣称为防恶意本地进程的安全边界 |
| G08 / 收口 | 历史独立试用有状态摘要，未保存完整可复现评估资料 | 后续评估记录输入、环境、观察和结果；不能用新写的记录冒充历史原始日志 |

v0.1 的完成条件：设计内核心能力已实现或经用户明确收敛；适用验收有证据，未运行项明确；Skill 校验与相关回归通过；非 Git 父目录下多仓流程可演练；有具体安装预览和限制说明。当前应称“已推送的 v0.1 原型”，不能称“全部需求已完成”。

## 6. 不是当前必须补齐的事项

| 内容 | 范围决定 |
| --- | --- |
| Node/Java/Go/Rust 等专用适配器、任意模块级工作流 | 首版只做通用回退 + Python 基础适配，扩展须另定设计 |
| 每种 Agent 的专用安装器、厂商插件包、全局宿主 hooks | 不属于首版；通用加载/手工安装仍须能说明 |
| 常驻服务、独立模型 API、跨所有聊天的全局意图拦截 | 非首版范围 |
| 自动发布、自动修改远端保护、自动发送外部消息 | 不属于默认工作流，也未因接入而获授权 |
| 自定义 ZIP 构建、打包命令、要求用户构建后安装 | 用户已明确移除，不恢复；仓库克隆/源码下载足够，正式 Release 按后续要求处理 |
| 自动生成一套子 Skill、强制 DDD/TDD/多代理 | 用户不要求，不能默认引入 |
| 不可伪造的人类批准系统、任意代码安全沙箱、对恶意本地进程的隔离 | 不承诺；依赖宿主/OS 权限，控制器只约束经过自身入口的操作 |
| 自动卸载、自动合并用户定制组件、自动删除既有 CI | 当前无此产品能力要求；rollback 是按原计划有条件恢复，不等于通用卸载 |
| 全模板中英切换 | 当前双语要求是两版 README 和 Agent 交互语言，固定命令/字段/模板保持稳定 |

## 7. 当前实现入口与验证事实

| 位置 | 用途 |
| --- | --- |
| [SKILL.md](../skills/forvynx/SKILL.md) | Agent 的分流、授权和执行流程 |
| [workflow.md](../skills/forvynx/references/workflow.md) | CLI、selection 示例、恢复与限制 |
| [forvynx.py](../skills/forvynx/scripts/forvynx.py) | probe / plan / apply / verify / rollback / hook-preview |
| [forvynx_lib](../skills/forvynx/scripts/forvynx_lib) | 边界、发现、计划、应用、checker、验证、适配器 |
| [github-ci.yml](../skills/forvynx/assets/github-ci.yml) | 可选生成到目标仓库的 CI 模板 |
| [test_controller.py](../tests/test_controller.py) | 当前 49 个程序用例：WorkspaceTest 46、SkillPortabilityTest 3 |
| [validate_skill.py](../scripts/validate_skill.py) | 本项目受限元数据/引用/Python 语法校验 |
| [ci.yml](../.github/workflows/ci.yml) | 本产品测试矩阵：Windows/Linux × Python 3.11/3.12 |

代码基线已经推送并核对本地/远端 `main` 提交一致。本次交接核对没有改动运行代码，也没有重跑全量测试。

已知执行证据：

- 历史完整回归：当时 49 项，48 通过、1 项因 Windows 文件 symlink 权限跳过。这是历史版本结果，不冒充当前提交的全量结果。
- 移除打包流程后的 3 项定向测试全部通过：元数据/引用/语法、没有 OpenAI 展示元数据时的校验、复制到独立目录并移除该元数据后的 probe → plan → apply → verify。
- `scripts/validate_skill.py` 本地通过；校验器使用标准库，仅支持本项目约定的元数据子集。
- 历史有两仓试用和一次非开发负例摘要，细节见 [实现状态](implementation-status.md)；完整行为评估资料待补。
- skill-creator 附带 quick_validate.py 曾因缺 PyYAML 未跑通；不是 Skill 运行时要求，也未为此安装依赖。
- GitHub CI 是否运行/成功尚未核验。2026-10-22 本次通过公开 API 查询返回 HTTP 403 rate limit exceeded；不据此判断 CI 没有运行，也不判断失败。可查看 [Actions](https://github.com/laetivox/forvynx-skill/actions)。

维护者检查（不放回 README，不要求用户打包）：

```sh
python -B -m unittest discover -s tests -v
python -B scripts/validate_skill.py
```

当前机器 Python 未在 PATH，可用 `C:\Users\sskj-work\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`。这只是本机路径，不能写入可移植工程配置；新环境先找实际解释器。

## 8. 已有授权与明确未执行的动作

- 已授权：在当前 Forvynx 项目内按接受的首版设计实现、修复、验证、完善文档；没有阻塞决策时继续。用户提供上述 GitHub 地址并明确要求推送，代码基线已推送。
- 未执行：用户级 Skill 安装、相邻真实项目接入、真实项目 hook 启用、全局 Git/宿主配置修改、远端分支保护变更、正式 Release 发布。
- 新上下文不能把“继续”“读交接文档”“按设计实现”当成这些未执行动作的新授权。可先准备具体预览；已有明确授权覆盖时不重复询问。
- 本地状态/备份在 OS 临时目录 `forvynx-state/<workspace-hash>`，锁在 `forvynx-locks`，不是仓库的 `.forvynx`。不要删未知锁或恢复日志，也不要将它们推送到 GitHub。

## 9. 可直接粘贴到新上下文

```text
继续 Forvynx 项目。先检查实际 checkout、Git 状态和适用的 AGENTS.md，然后读取 docs/requirements-and-handoff.md；详细依据是 docs/forvynx-v0.1-design.md，CLI 以 skills/forvynx/references/workflow.md 为准。

仓库：https://github.com/laetivox/forvynx-skill.git，main。交接核对的运行代码基线为 2c1a48b08733361cb4e0ed6c7d6000690afde427，文档提交可能更新。原机器路径 C:\Users\sskj-work\Documents\ChatGPT\forvynx.skill 只是定位信息，新环境用实际 checkout。

产品简介固定为“为你的agent自动搭建适量、可验证的编码工作流。”它面向各种可加载该 Skill 的 Agent，不限定 Codex。工作区可不是 Git 仓库且可含多个独立仓库。非开发小任务绕过，普通小改动保持轻量；大规模代码前先达成设计共识。安装、新仓接入及范围扩大先做具体预览再依据用户明确授权应用，不反复索要已有批准。保留用户规则、dirty 文件、hooks 和 CI，确定性脚本负责边界、漂移和结果核验，不只靠提示词。

当前是 Python 3.11+ 标准库 + Git 的 v0.1 原型，含 probe/plan/apply/verify/rollback/hook-preview。边界、计划、应用与恢复已有实现；自适应工作流目前仍是固定模板加 profile，不能说所有需求完成。先核对交接清单 G01–G08 与设计验收 A01–A18，给最小下一步方案和验收，再实施必要改动。已有设计授权有效，不重做项目、不擅自新增语言适配、常驻服务或多代理架构。

保留精简双语 README。不要恢复语言说明、README 开发章节、自定义打包脚本或 dist 构建产物。用户直接克隆/下载仓库并安装 skills/forvynx 目录。

区分已实现、部分实现、待验证和非首版范围；保持清单 ID。历史回归不是当前提交全量通过证明，GitHub CI 结果仍待核验。未经具体授权不要安装到用户级目录、接入相邻真实项目、启用真实 hooks 或更改远端保护。拿不到文件时先拉取/读取仓库，不要假装记得旧会话或已经改过本地文件。
```
