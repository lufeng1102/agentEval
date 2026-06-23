# AgentEval P3 PRD：生态集成与 UI/SaaS 化

## 1. 背景

AgentEval 当前已经具备本地/CI 评测主链路：数据集、配置、runner、adapter 协议、evaluators、报告、trace import/replay、promotion gate、RSI governance 等能力。

P3 的目标是把 AgentEval 从“本地/CI eval 工具”推进为“可接入主流 agent 生态、可观测、可协作、可托管、可与外部平台互通的 eval platform”。

当前状态基线：

| 能力 | 状态 |
|---|---|
| Claude Code adapter | 已有 |
| Trace model / trace import / replay | 部分已有 |
| 静态 HTML dashboard/report | 部分已有 |
| SDK instrumentation | 未完整实现 |
| LangChain / AutoGen / CrewAI / OpenAI Agents SDK adapters | 未实现 |
| Alerts | 未实现 |
| Team workspace | 未实现 |
| Hosted mode | 未实现 |
| Langfuse / Phoenix / Braintrust export | 未实现，当前偏 import/replay |

## 2. 目标

### 2.1 产品目标

1. 提供低侵入 SDK instrumentation，采集真实 agent runtime traces。
2. 支持主流 agent 框架 adapter：LangChain、AutoGen、CrewAI、OpenAI Agents SDK，并增强 Claude Code adapter。
3. 提供交互式 web dashboard，覆盖 run、case、result、trace、compare、governance 视图。
4. 提供 alerts，对 regression、threshold、safety、RSI governance 风险触发通知。
5. 支持 team workspace：project、members、roles、shared runs、tokens、audit。
6. 支持 hosted mode：run ingestion、artifact persistence、hosted dashboard、API。
7. 支持外部平台导出：Langfuse / Phoenix / Braintrust compatible output。

### 2.2 非目标

- P3 MVP 不托管用户 agent runtime，只托管 eval artifacts、reports、dashboard、API。
- 不重写现有 runner/evaluator/report 核心链路。
- 不替代 Langfuse/Phoenix/Braintrust，只提供兼容导出或后续 direct push。
- MVP 不做完整企业 SSO、计费、多区域部署、多语言 SDK。
- 不保证覆盖每个框架的全部高级语义，优先统一 AgentRun、AgentTrace、TraceSpan、ToolCall、EvalResult。

## 3. 用户画像

| 用户 | 诉求 | P3 价值 |
|---|---|---|
| Agent 应用开发者 | 快速接入 eval，定位失败 trace | SDK、adapter、dashboard |
| AI 平台/Infra 工程师 | 统一多框架 eval/trace 数据 | adapters、hosted mode、exports |
| Eval Engineer | 管理 datasets、configs、failures、regressions | dashboard、trend、replay、export |
| 安全/Governance 负责人 | 发现 eval gaming、holdout leak、memory pollution、unsafe actions | RSI governance view、alerts |
| 工程经理 | 查看团队项目质量趋势和发布风险 | workspace、dashboard、alerts |

## 4. 范围与优先级

| 模块 | MVP | P1 | P2 |
|---|---|---|---|
| SDK instrumentation | Python decorator/context manager、本地 JSONL trace 输出、sync/async、error/tool/span capture | 采样、脱敏、hosted upload、常见框架 auto hooks | 多语言 SDK、生产级采集策略 |
| Adapters | Claude Code contract 对齐；LangChain MVP；AutoGen 或 CrewAI MVP；adapter conformance tests | 补齐 AutoGen/CrewAI/OpenAI Agents SDK；更完整 retriever/handoff/task metadata | 插件市场、复杂 graph/workflow 可视化 |
| Web dashboard | 本地交互式 run/case/result/trace/compare view | trend、failure mining、governance、filters、share links | custom widgets、多项目高级视图 |
| Alerts | threshold/regression webhook alerts | Slack/email、safety/governance/cost/latency alerts、notification center | routing、dedupe、escalation、PagerDuty/Opsgenie |
| Team workspace | 暂不进 MVP，可为 hosted 数据模型预留 project_id | workspace/project/member/RBAC/API token/audit | SSO/OIDC/SAML、合规审计导出 |
| Hosted mode | server、run ingestion、artifact persistence、CLI upload、hosted dashboard | workspace/project association、API token、background jobs | multi-tenant isolation、retention、billing readiness |
| External export | Langfuse/Phoenix/Braintrust compatible file export + validation | direct API push、mapping customization、hosted export jobs | 双向 sync、connector marketplace |

## 5. 功能需求

### 5.1 SDK Instrumentation

#### 功能说明

提供 Python SDK，使用户能用 decorator/context manager 包裹 agent run，自动采集 AgentEval-compatible trace。

#### 需求

| ID | 需求 | 优先级 |
|---|---|---|
| SDK-001 | 提供 `trace_agent_run` decorator/context manager | MVP |
| SDK-002 | 支持 sync/async 函数 | MVP |
| SDK-003 | 支持 span start/end/error | MVP |
| SDK-004 | 支持 tool call name/input/output/error | MVP |
| SDK-005 | 支持 latency、usage、metadata | MVP |
| SDK-006 | 支持本地 JSONL writer | MVP |
| SDK-007 | 输出可被现有 trace import/replay 消费 | MVP |
| SDK-008 | instrumentation 异常不得中断用户业务流程 | MVP |
| SDK-009 | 支持采样率配置 | P1 |
| SDK-010 | 支持 PII/secret 脱敏 hook | P1 |
| SDK-011 | 支持 hosted upload | P1 |

#### 验收标准

- 包裹同步/异步 agent run 后，能生成包含 final_output、spans、tool_calls、latency、errors 的 trace。
- agent run 抛错时，trace 记录 error，原异常语义不被吞掉。
- 生成 trace 可通过现有 AgentEval schema，并能进入 replay/import 链路。
- instrumentation 内部失败时，默认只记录 warning，不导致业务 run 失败。

### 5.2 Adapter 生态

#### 通用 contract

所有 adapter 必须输出或尽力输出：

- `AgentRun.case_id`
- `messages`
- `final_output`
- `tool_calls`
- `spans`
- `latency_ms`
- `usage`
- `errors`
- `raw_response`
- `artifacts` / `metadata.framework` / `metadata.adapter_version`

#### Claude Code adapter

| ID | 需求 | 优先级 |
|---|---|---|
| CC-001 | 梳理现有 Claude Code adapter 与统一 contract 差异 | MVP |
| CC-002 | 保持现有测试和行为不回归 | MVP |
| CC-003 | 增强 tool/file/bash operation trace fidelity | P1 |
| CC-004 | 增加 adapter conformance tests | P1 |

#### LangChain adapter

| ID | 需求 | 优先级 |
|---|---|---|
| LC-001 | 支持 LangChain agent final output 映射 | MVP |
| LC-002 | 支持 tool calls 映射 | MVP |
| LC-003 | 支持 LLM call latency/error/usage 映射 | MVP |
| LC-004 | 支持 retriever spans | P1 |
| LC-005 | 支持 memory/callback metadata | P1 |
| LC-006 | 支持 LangGraph 基础映射 | P2 |

#### AutoGen adapter

| ID | 需求 | 优先级 |
|---|---|---|
| AG-001 | 支持 conversation 映射为 AgentRun | MVP |
| AG-002 | 支持多 agent message sequence | MVP |
| AG-003 | 支持 speaker/agent role metadata | MVP |
| AG-004 | 支持 tool/code execution spans | MVP |
| AG-005 | 支持 group chat termination reason | P1 |

#### CrewAI adapter

| ID | 需求 | 优先级 |
|---|---|---|
| CR-001 | 支持 crew run 映射为 AgentRun | MVP |
| CR-002 | 支持 crew/task/agent span | MVP |
| CR-003 | 支持 tool calls 映射 | MVP |
| CR-004 | 支持 role/goal/task dependency metadata | P1 |
| CR-005 | 支持 crew workflow 可视化 | P2 |

#### OpenAI Agents SDK adapter

| ID | 需求 | 优先级 |
|---|---|---|
| OA-001 | 支持 run final output 映射 | MVP |
| OA-002 | 支持 tool calls 映射 | MVP |
| OA-003 | 支持 errors/latency/usage 映射 | MVP |
| OA-004 | 支持 handoff metadata | P1 |
| OA-005 | 支持 guardrail result 映射 | P1 |

#### Adapter conformance tests

- success run
- failed run
- tool call run
- multi-message run
- usage/latency metadata
- schema validation
- error handling：adapter 异常转为 `AgentRun.errors`，不崩整个 suite

### 5.3 Web Dashboard

#### MVP 页面

1. Runs list
2. Run summary
3. Cases table
4. Case detail
5. Evaluator results
6. Trace viewer
7. Compare view
8. Artifact links/download

#### P1 页面

1. Trend view
2. Failure mining view
3. RSI governance view
4. Alert center
5. Export jobs view
6. Filter/search：tag、evaluator、framework、status、risk

#### 验收标准

- 给定一个 run directory 或 hosted run，dashboard 能展示 summary、cases、results。
- trace viewer 能展示 nested spans、tool calls、latency、errors。
- compare view 能展示 pass rate delta、avg score delta、new failures。
- governance view 能展示 risk level、gates、required actions、evidence。

### 5.4 Alerts

#### 告警类型

| 类型 | 优先级 |
|---|---|
| pass rate / avg score threshold | MVP |
| baseline vs candidate regression | MVP |
| new failures | MVP |
| safety evaluator failure | P1 |
| RSI governance high/critical risk | P1 |
| cost/latency threshold | P1 |
| hosted ingestion/export failure | P2 |

#### 告警渠道

| 渠道 | 优先级 |
|---|---|
| CLI exit code/stdout | 已有/延续 |
| Webhook | MVP |
| Slack | P1 |
| Email | P1 |
| Dashboard notification center | P1 |
| PagerDuty/Opsgenie | P2 |

#### 验收标准

- 当 pass rate 低于阈值时，生成 alert event。
- 当 candidate 出现 new failures 时，生成 regression alert。
- webhook payload 包含 run_id、severity、rule_id、summary、artifact/dashboard link。
- webhook 失败时有 retry 和 delivery log。

### 5.5 Team Workspace

#### 数据模型

- Workspace
- Project
- User
- Membership
- Role
- API Token
- AuditLog

#### 角色

| 角色 | 权限 |
|---|---|
| Owner | workspace 管理、成员、项目、token、billing readiness |
| Admin | 项目、成员、alerts、exports 管理 |
| Developer | 上传 runs、查看 reports、调试 failures |
| Eval Engineer | 管理 datasets/configs/policies/alerts |
| Viewer | 只读查看 |

#### 验收标准

- Viewer 只能查看，不能修改 alert/export/token。
- Developer 可上传 run 到指定 project。
- Admin 可邀请成员、配置 alerts。
- Audit log 记录上传、导出、token 创建、权限变更。

### 5.6 Hosted Mode

#### MVP 能力

| ID | 需求 | 优先级 |
|---|---|---|
| HM-001 | 本地可启动 AgentEval server | MVP |
| HM-002 | Run ingestion API | MVP |
| HM-003 | artifact persistence：manifest/traces/results/report | MVP |
| HM-004 | CLI upload/sync run directory | MVP |
| HM-005 | Hosted dashboard 读取 persisted runs | MVP |
| HM-006 | run ingestion 幂等 | MVP |

#### P1/P2 能力

- Project/workspace association
- API token auth
- Background worker：alerts/export/indexing
- Multi-tenant isolation
- Retention policy
- Usage metering/billing readiness

#### 验收标准

- 本地 eval 完成后，可通过 CLI 上传 run artifacts。
- 同一 run_id 重复上传不创建重复数据。
- 无权限 token 上传返回 403。
- hosted dashboard 可查看 uploaded runs。

### 5.7 External Platform Export

#### 目标平台

- Langfuse compatible output
- Phoenix compatible output
- Braintrust compatible output

#### 映射关系

| AgentEval | 外部平台概念 |
|---|---|
| Run | experiment/run/trace collection |
| AgentTrace | trace |
| TraceSpan | span |
| ToolCall | tool span/event |
| EvalResult | score/feedback/evaluation |
| EvalCase | dataset example/input |
| Report summary | metrics/summary |
| Manifest metadata | tags/metadata |

#### 需求

| ID | 需求 | 优先级 |
|---|---|---|
| EXP-001 | `export langfuse` compatible JSON/JSONL | MVP |
| EXP-002 | `export phoenix` compatible JSON/JSONL | MVP |
| EXP-003 | `export braintrust` compatible JSON/JSONL | MVP |
| EXP-004 | Export schema validation | MVP |
| EXP-005 | 保留 parent-child span 关系 | MVP |
| EXP-006 | evaluator score 独立导出 | MVP |
| EXP-007 | hosted export job | P1 |
| EXP-008 | direct API push connector | P1 |
| EXP-009 | mapping customization | P1 |

#### 验收标准

- 给定 AgentEval run directory，能导出三类 compatible files。
- 导出文件通过基础 schema validation。
- nested spans 的 parent-child 关系不丢失。
- 多 evaluator scores 可独立查看/解析。

## 6. 非功能需求

### 6.1 性能

| 项目 | 要求 |
|---|---|
| Dashboard 首屏 | 中型 run ≤ 3s |
| Trace viewer | 支持 10k spans 分页/虚拟化 |
| Run upload | 支持至少 100MB artifact 压缩包 |
| Export | 中型 run ≤ 60s |
| Alert processing | run 完成后 60s 内评估 |

### 6.2 安全

- API token 可撤销、可限定 project scope。
- Hosted artifact 访问必须鉴权。
- Trace prompt/output/tool args 支持脱敏和 retention policy。
- Webhook secrets 不明文展示。
- Export 下载受权限控制。
- P2 多租户必须做 tenant isolation。

### 6.3 兼容性

- 不破坏现有 CLI 命令。
- `report.json`、`traces.jsonl`、`results.jsonl` 新字段尽量 additive。
- Adapter 支持版本必须写入文档。
- Exporter 输出记录 exporter version 和目标平台格式版本。

### 6.4 可观测性

- Hosted mode 记录 ingestion/export/alert/API metrics。
- Background jobs 有 pending/running/succeeded/failed 状态。
- Alerts 有 delivery log。
- Adapter 输出包含 framework_version 和 adapter_version。

## 7. 里程碑

### Phase 0：契约和设计冻结（1-2 周）

交付：

- Adapter contract spec
- Trace/export mapping spec
- SDK instrumentation API design
- Dashboard 信息架构和 wireframe
- Hosted data model draft
- MVP acceptance test plan

### Phase 1：MVP 本地闭环（3-5 周）

交付：

- SDK instrumentation MVP
- Claude Code adapter contract 对齐
- LangChain adapter MVP
- AutoGen 或 CrewAI adapter MVP
- Adapter conformance tests MVP
- 本地 interactive dashboard MVP
- Langfuse/Phoenix/Braintrust file export MVP
- Threshold/regression webhook alerts MVP

验收：

- 至少 3 类 runtime 能进入 AgentEval eval/trace/report 链路。
- Dashboard 能从 run 下钻到 case/result/trace。
- Export 能生成三类 compatible output。
- CI threshold/regression 可触发 webhook alert。

### Phase 2：Hosted 与团队协作（4-6 周）

交付：

- Hosted server/API
- Run ingestion + artifact persistence
- CLI upload/sync
- Hosted dashboard
- Project/workspace/member/RBAC/API token
- Alert rule management
- Slack/email
- Trend/failure mining/governance view
- OpenAI Agents SDK adapter MVP
- AutoGen/CrewAI 补齐 P1

验收：

- 团队可在 hosted project 中共享 runs。
- Developer 可上传，Viewer 可只读查看。
- Admin 可配置 alerts 和 exports。
- Trend/governance view 可用于发布风险判断。

### Phase 3：SaaS 成熟化（6-10 周）

交付：

- Multi-tenant isolation
- Retention policy
- SSO/OIDC/SAML
- Export direct push connectors
- Custom dashboard widgets
- Adapter plugin marketplace
- Usage metering/billing readiness

## 8. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 不同框架 trace 模型差异大 | adapter 输出不一致 | 最小通用 contract + framework metadata |
| 外部平台格式变化 | export 失效 | exporter version、schema validation、兼容矩阵 |
| Trace 数据量大 | dashboard 卡顿/upload 慢 | 压缩、分页、虚拟化、分块上传 |
| Hosted 范围膨胀 | MVP 延期 | 首期只托管 eval artifacts，不托管 agent runtime |
| Trace 含敏感数据 | 合规风险 | 脱敏、采样、字段开关、retention |
| Alert 噪声过多 | 用户忽略告警 | severity、dedupe、cooldown、routing |
| Adapter 依赖框架版本 | 维护成本高 | 支持矩阵、conformance tests、experimental/stable 标识 |

## 9. 总体验收标准

P3 MVP 完成时需满足：

1. 至少 3 个 runtime 可通过 adapter/instrumentation 完成 eval。
2. SDK instrumentation 可生成可 replay 的 AgentEval trace。
3. Dashboard 可查看 run summary、case detail、trace viewer、compare。
4. Threshold/regression alert 可通过 webhook 触发。
5. Export CLI 可生成 Langfuse、Phoenix、Braintrust compatible output，并通过基础 validation。
6. Hosted mode 可接收本地 run 上传并展示。
7. 现有 CLI runner、report、trace import、promotion workflow 不发生破坏性回归。
8. Adapter conformance tests 进入 CI。
9. 文档包含每个 adapter 的 quickstart、支持版本、字段映射和限制。
