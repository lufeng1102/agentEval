# P3 Phase 0：SDK Instrumentation API Design

## 1. 目标

提供低侵入 Python SDK instrumentation，让开发者可以在本地、CI 或生产环境采集 AgentEval-compatible traces。

设计原则：

- 默认输出 `AgentTrace` JSONL。
- 输出可被现有 trace import/replay 链路消费。
- 支持 sync/async。
- 支持 decorator 和 context manager。
- instrumentation 自身失败默认 fail-open，不影响业务 agent。
- 支持基本 redaction。

建议新增：

```text
src/instrumentation/__init__.py
src/instrumentation/context.py
src/instrumentation/schema.py
src/instrumentation/writer.py
src/instrumentation/redaction.py
```

## 2. Public API

### 2.1 Decorator

```python
from agenteval.instrumentation import trace_agent_run, span, tool_call, record_usage

@trace_agent_run(
    trace_path="runs/prod-traces.jsonl",
    agent_id="support-agent",
    agent_version="2026-06-22",
    source="sdk",
    tags=["production", "support"],
)
async def run_agent(user_input: str) -> str:
    with span("retriever.search", kind="retrieval", input={"query": user_input}):
        docs = search_docs(user_input)

    with tool_call("crm_lookup", input={"user_id": "u_123"}) as tc:
        result = lookup_crm("u_123")
        tc.set_output({"found": True})

    record_usage(input_tokens=100, output_tokens=50)
    return await model_call(user_input, docs)
```

### 2.2 Context manager

```python
from agenteval.instrumentation import AgentEvalTracer

async with AgentEvalTracer(
    trace_path="runs/prod-traces.jsonl",
    case_id="prod_case_001",
    source="sdk",
    agent_id="support-agent",
) as trace:
    trace.add_message("user", user_input)

    async with trace.span("llm.generate", kind="llm", input={"model": "claude-opus-4-8"}) as sp:
        output = await call_model()
        sp.set_output({"text": output})

    trace.add_message("assistant", output)
    trace.set_final_output(output)
```

## 3. TraceConfig

```python
class TraceConfig(BaseModel):
    trace_path: Path
    source: str = "sdk"
    case_id: str | None = None
    session_id: str | None = None
    agent_id: str | None = None
    agent_version: str | None = None
    user_id_hash: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    sample_rate: float = 1.0
    fail_open: bool = True
    redaction_enabled: bool = True
```

## 4. 输出格式

每行一个 `AgentTrace`：

```json
{
  "trace_id": "trace_abc",
  "case_id": "prod_case_001",
  "session_id": "sess_001",
  "agent_id": "support-agent",
  "agent_version": "2026-06-22",
  "source": "sdk",
  "input": "user input",
  "final_output": "answer",
  "messages": [
    {"role": "user", "content": "user input"},
    {"role": "assistant", "content": "answer"}
  ],
  "spans": [],
  "tool_calls": [],
  "usage": {
    "input_tokens": 100,
    "output_tokens": 50,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0
  },
  "latency_ms": 1234.5,
  "errors": [],
  "tags": ["production", "support"],
  "metadata": {
    "instrumentation": {
      "sdk_language": "python",
      "sdk_version": "0.1.0",
      "schema_version": "agenteval.trace.v1"
    }
  }
}
```

## 5. Span API

```python
span = trace.start_span(
    name="llm.generate",
    kind="llm",
    input={"messages": messages},
    attributes={"model": "claude-opus-4-8"},
)

trace.end_span(span.span_id, output={"text": text}, status="ok")
trace.fail_span(span.span_id, error="RateLimitError: ...")
```

Context manager：

```python
with trace.span("vectorstore.search", kind="retrieval", input={"query": query}) as sp:
    docs = retriever.search(query)
    sp.set_output({"document_count": len(docs)})
```

## 6. Tool API

```python
with trace.tool_call("search", input={"query": "agent eval"}) as call:
    output = search("agent eval")
    call.set_output(output)
```

行为：

- 自动追加一个 `ToolCall`。
- 自动创建对应 `TraceSpan(kind="tool")`。
- 如果异常发生，记录 `ToolCall.error` 和 span error，并重新抛出业务异常。

## 7. Usage API

```python
trace.record_usage(
    input_tokens=100,
    output_tokens=50,
    cache_creation_input_tokens=0,
    cache_read_input_tokens=25,
)
```

多次调用应累加。

## 8. 异常语义

### 8.1 用户业务异常

- trace 记录 error。
- decorator/context manager 重新抛出原异常。
- 不吞异常。

### 8.2 instrumentation 自身异常

默认 `fail_open=True`：

- writer/redactor/serialization 异常不影响用户函数。
- 写 warning 到 logging。
- 测试可设置 `fail_open=False`。

## 9. Redaction

默认敏感 key：

```text
api_key
authorization
password
secret
token
cookie
set-cookie
```

自定义 hook：

```python
def redactor(path: str, value: Any) -> Any:
    if path.endswith(".input.headers.authorization"):
        return "[REDACTED]"
    return value
```

要求：

- 支持 messages、spans input/output、tool_calls input/output、final_output。
- redaction 失败默认 fail-open，但记录 warning。

## 10. Writer

```python
class AppendJsonlTraceWriter:
    def __init__(self, path: str | Path):
        ...

    def append(self, trace: AgentTrace) -> None:
        ...
```

要求：

- append 模式，不覆盖文件。
- 每行一个 `AgentTrace.model_dump_json()`。
- 写入前验证 JSON serializable。
- MVP 至少支持进程内 lock。

## 11. Hosted upload 预留

P1 可扩展：

```python
AgentEvalTracer(
    trace_path="runs/prod-traces.jsonl",
    upload_url="https://agenteval.example.com/api/traces",
    api_token="...",
    local_fallback_path="runs/prod-traces.jsonl",
)
```

MVP 不强耦合 hosted server。

## 12. 验收标准

- sync decorator 保持函数返回值不变，并写入 1 条 trace。
- async decorator 可 await，latency 大于等于 0。
- 用户异常重新抛出，trace 记录 error。
- writer 抛异常且 `fail_open=True` 时，用户函数仍正常返回。
- span nesting 的 `parent_span_id` 正确。
- tool call 同时出现在 `tool_calls` 和 spans。
- 多次 `record_usage` 正确累加。
- redaction 能替换 token/password。
- 输出可被 `AgentTrace.model_validate` 解析。
