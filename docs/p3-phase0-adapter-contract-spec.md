# P3 Phase 0：Adapter Contract Spec

## 1. 目标

为 LangChain、AutoGen、CrewAI、OpenAI Agents SDK、Claude Code 等 agent runtime 定义统一接入契约，让不同框架输出都能进入 AgentEval 现有 runner、trace、evaluator、report、dashboard、export 链路。

Phase 0 原则：

- 不修改现有 `AgentAdapter.run(case, context) -> AgentRun` 签名。
- 不破坏现有 `AgentRun`、`ToolCall`、`TraceSpan`、`EvalResult` schema。
- 框架特有信息优先放入 `AgentRun.artifacts` 或 `TraceSpan.attributes`。
- Adapter 输出允许有信息损失，但必须明确记录 capabilities 和 lossiness。

## 2. Contract Version

```python
ADAPTER_CONTRACT_VERSION = "agenteval.adapter.v1"
```

建议新增：

```text
src/adapters/contract.py
src/adapters/conformance.py
```

## 3. Adapter 接口

现有接口保持不变：

```python
class AgentAdapter(Protocol):
    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        ...
```

Adapter 必须返回可 JSON 序列化、可 Pydantic validate 的 `AgentRun`。

## 4. AgentRun 字段规范

| 字段 | 要求 | 说明 |
|---|---|---|
| `case_id` | 必填 | 必须等于 `EvalCase.id` |
| `repeat_index` | 默认 0 | runner 可覆盖 |
| `messages` | 建议填充 | 尽量保留 user/assistant/system/tool 消息 |
| `final_output` | 必填语义 | 成功时为最终回答；失败时可为空字符串 |
| `tool_calls` | 可空 | 工具调用列表 |
| `spans` | 可空 | LLM/tool/retrieval/agent/chain spans |
| `latency_ms` | 非负 | adapter 或 runner 计算 |
| `usage` | 可空 | token/cache 使用量 |
| `errors` | 可空 | adapter/provider/framework 错误 |
| `raw_response` | 可空 | 原始响应快照，必须 JSON serializable |
| `artifacts` | 可空 | adapter metadata、framework metadata、文件引用 |

## 5. Adapter metadata

Phase 0 不给 `AgentRun` 新增 `metadata` 字段，统一放入：

```json
{
  "artifacts": {
    "adapter": {
      "contract_version": "agenteval.adapter.v1",
      "adapter_name": "langchain",
      "adapter_version": "0.1.0",
      "framework": "langchain",
      "framework_version": "0.3.x",
      "capabilities": {
        "messages": true,
        "tool_calls": true,
        "spans": true,
        "usage": true,
        "retrieval": true,
        "multi_agent": false
      },
      "lossiness": [
        "framework did not expose cache token usage"
      ]
    }
  }
}
```

必填：

- `contract_version`
- `adapter_name`
- `adapter_version`
- `framework`
- `capabilities`

## 6. Message 映射

不要扩展 `ChatMessage.role`。多 agent speaker、framework role 等信息放在 spans 或 artifacts。

| 上游消息 | AgentEval role | 附加信息 |
|---|---|---|
| human/user | `user` | 原始 role 放 attributes |
| ai/assistant/agent | `assistant` | speaker 放 span attributes |
| system | `system` | 直接映射 |
| tool result | `tool` | 直接映射 |
| unknown | `assistant` 或 `user` | 原始 role 放 artifacts |

## 7. ToolCall 规范

```python
class ToolCall(BaseModel):
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    error: str | None = None
```

规则：

- `name` 必须非空。
- `input` 必须是 dict；不能结构化时用 `{"raw": "..."}`。
- 成功时 `error=None`。
- 失败时 `error` 填错误字符串，`output` 可为 null。

## 8. TraceSpan 映射

保留现有 span kind：

```text
llm, tool, retrieval, embedding, api, agent, chain, custom
```

| 框架事件 | TraceSpan.kind | name 示例 |
|---|---|---|
| LLM/model call | `llm` | `anthropic.messages.create` |
| Tool execution | `tool` | `calculator` |
| Retriever | `retrieval` | `vectorstore.search` |
| Embedding | `embedding` | `embedding.create` |
| Chain/graph node | `chain` | `langchain.agent_executor` |
| Agent handoff/turn | `agent` | `autogen.critic` |
| External API | `api` | `github.create_issue` |
| Unknown | `custom` | framework-specific |

## 9. Span ID 规则

优先使用上游框架 run/span id。没有时生成稳定 id：

```text
sha1(run_id + case_id + repeat_index + span_index + name)
```

不要使用每次变化的随机 UUID，避免 compare/export 不稳定。

## 10. Framework adapter MVP 映射

### 10.1 Claude Code

现有 adapter 保持行为不回归，补充 adapter metadata。Phase 0 不强制解析所有内部 tool/file/bash 操作。

### 10.2 LangChain

| LangChain | AgentEval |
|---|---|
| input/output | messages/final_output |
| callbacks: llm | `TraceSpan(kind="llm")` |
| callbacks: tool | `ToolCall` + tool span |
| callbacks: chain | chain span |
| callbacks: retriever | retrieval span |

### 10.3 AutoGen

| AutoGen | AgentEval |
|---|---|
| conversation transcript | messages |
| speaker | span attributes |
| code/tool execution | ToolCall + tool span |
| agent turn | agent span |
| termination reason | artifacts.autogen |

### 10.4 CrewAI

| CrewAI | AgentEval |
|---|---|
| crew kickoff | root chain span |
| task | chain span |
| agent | agent span |
| tool | ToolCall + tool span |
| role/goal/backstory | span attributes/artifacts |

### 10.5 OpenAI Agents SDK

| OpenAI Agents SDK | AgentEval |
|---|---|
| run output | final_output |
| tool calls | ToolCall |
| model calls | llm span |
| handoff | agent span |
| guardrail | custom span |
| usage | Usage |

## 11. Conformance validation

建议新增：

```python
class ContractIssue(BaseModel):
    severity: Literal["error", "warning"]
    path: str
    message: str


def validate_agent_run_contract(run: AgentRun) -> list[ContractIssue]:
    ...
```

最低校验：

| 校验 | 严重级别 |
|---|---|
| `case_id` 为空 | error |
| `latency_ms < 0` | error |
| tool name 为空 | error |
| tool input 不是 dict | error |
| span id/name 为空 | error |
| parent span 指向不存在 span | warning |
| raw_response 不可 JSON 序列化 | error |
| 缺少 adapter metadata | warning |

## 12. 验收标准

- 所有 adapter 输出均可 validate 为 `AgentRun`。
- adapter 异常进入 `AgentRun.errors`，不崩整个 suite。
- tool calls、spans、usage、latency 尽力填充。
- conformance tests 可覆盖 success、error、tool call、span hierarchy、raw_response serializable。
