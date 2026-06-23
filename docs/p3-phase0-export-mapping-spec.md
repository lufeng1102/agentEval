# P3 Phase 0：External Export Mapping Spec

## 1. 目标

将 AgentEval run artifacts 转换为 Langfuse、Phoenix、Braintrust compatible output。

MVP 特性：

- 只读本地 run directory。
- 不 rerun agent。
- 不重新评估。
- 生成 JSON/JSONL 文件。
- 支持基础 validation。
- 保留 span parent-child 关系。

建议新增：

```text
src/exports/base.py
src/exports/langfuse.py
src/exports/phoenix.py
src/exports/braintrust.py
src/exports/validators.py
```

## 2. CLI 入口建议

```bash
PYTHONPATH=src python -m cli export langfuse \
  --run runs/latest \
  --out runs/latest/export/langfuse.jsonl \
  --validate

PYTHONPATH=src python -m cli export phoenix \
  --run runs/latest \
  --out runs/latest/export/phoenix.jsonl \
  --validate

PYTHONPATH=src python -m cli export braintrust \
  --run runs/latest \
  --out runs/latest/export/braintrust.jsonl \
  --validate
```

## 3. 输入 artifacts

| 文件 | 用途 |
|---|---|
| `manifest.json` | run metadata、config/dataset/prompt hash |
| `traces.jsonl` | AgentRun records |
| `results.jsonl` | EvalResult records |
| `report.json` | summary、cases、runs、results |

## 4. Export IR

不要从 AgentEval 直接分别映射到三种目标格式，先归一为 Export IR。

```python
class ExportBundle(BaseModel):
    run_id: str
    manifest: dict[str, Any]
    summary: dict[str, Any]
    runs: list[AgentRun]
    results: list[EvalResult]
    cases: list[dict[str, Any]] = Field(default_factory=list)
```

```python
class ExportTraceRecord(BaseModel):
    trace_id: str
    run_id: str
    case_id: str
    repeat_index: int
    input: Any
    output: str
    spans: list[TraceSpan]
    tool_calls: list[ToolCall]
    scores: list[EvalResult]
    metadata: dict[str, Any]
```

## 5. 通用映射

| AgentEval | Export IR / 外部平台 |
|---|---|
| Run directory | experiment/run collection |
| `AgentRun` | trace/root record |
| `TraceSpan` | span/observation |
| `ToolCall` | tool span/event |
| `EvalResult` | score/feedback/evaluation |
| `EvalCase` | dataset example/input |
| `report.summary` | metrics/summary |
| `manifest` | metadata/tags |

## 6. Langfuse compatible output

MVP：每行一个 trace-like record。

```json
{
  "id": "trace_case_001_0",
  "name": "AgentEval case case_001",
  "input": "user input",
  "output": "final answer",
  "metadata": {
    "agenteval_run_id": "run_abc",
    "case_id": "case_001",
    "repeat_index": 0,
    "provider": "anthropic",
    "model": "claude-opus-4-8"
  },
  "tags": ["support", "rag"],
  "observations": [
    {
      "id": "span_1",
      "parentObservationId": null,
      "type": "GENERATION",
      "name": "llm.generate",
      "input": {"model": "claude-opus-4-8"},
      "output": {"text": "final answer"},
      "metadata": {"agenteval.kind": "llm"}
    }
  ],
  "scores": [
    {
      "name": "contains",
      "value": 1.0,
      "comment": null,
      "metadata": {"passed": true, "metrics": {}}
    }
  ]
}
```

Kind 映射：

| TraceSpan.kind | Langfuse type |
|---|---|
| `llm` | `GENERATION` |
| `tool` | `TOOL` |
| `retrieval` | `RETRIEVER` 或 `SPAN` |
| 其他 | `SPAN` |

## 7. Phoenix compatible output

MVP：每行一个 OpenInference-like span。

```json
{
  "context": {
    "trace_id": "trace_case_001_0",
    "span_id": "span_1"
  },
  "parent_id": null,
  "name": "llm.generate",
  "start_time": "2026-06-22T12:00:00Z",
  "end_time": "2026-06-22T12:00:01Z",
  "status_code": "OK",
  "attributes": {
    "openinference.span.kind": "LLM",
    "input.value": "user input",
    "output.value": "final answer",
    "llm.model_name": "claude-opus-4-8",
    "agenteval.case_id": "case_001",
    "agenteval.repeat_index": 0,
    "agenteval.run_id": "run_abc"
  },
  "events": []
}
```

Kind 映射：

| TraceSpan.kind | openinference.span.kind |
|---|---|
| `llm` | `LLM` |
| `tool` | `TOOL` |
| `retrieval` | `RETRIEVER` |
| `embedding` | `EMBEDDING` |
| `chain` | `CHAIN` |
| `agent` | `AGENT` |
| `api` | `TOOL` 或 `CHAIN` |
| `custom` | `CHAIN` |

Scores 可单独输出为 eval records。

## 8. Braintrust compatible output

MVP：每行一个 case/run result。

```json
{
  "id": "case_001:0",
  "experiment_id": "agenteval:run_abc",
  "input": "user input",
  "expected": {"answer": "expected answer"},
  "output": "final answer",
  "scores": {
    "contains": 1.0,
    "safety": 0.0
  },
  "metadata": {
    "case_id": "case_001",
    "repeat_index": 0,
    "latency_ms": 1234.5,
    "usage": {"input_tokens": 100, "output_tokens": 50},
    "errors": []
  },
  "span_attributes": [
    {
      "span_id": "span_1",
      "parent_span_id": null,
      "name": "llm.generate",
      "kind": "llm"
    }
  ]
}
```

## 9. Parent-child span 保真

规则：

1. span id 缺失时生成 deterministic id。
2. parent 缺失时不丢 span，记录 warning。
3. `ToolCall` 没有对应 tool span 时合成 tool span：

```text
span_id = synthetic_tool_<case_id>_<repeat_index>_<index>
kind = tool
parent_span_id = root_span_id
```

## 10. Exporter 接口

```python
class Exporter(Protocol):
    name: str
    format_version: str

    def export(self, bundle: ExportBundle) -> Iterable[dict[str, Any]]:
        ...

    def validate(self, records: Iterable[dict[str, Any]]) -> list[ValidationIssue]:
        ...
```

```python
class ValidationIssue(BaseModel):
    severity: Literal["error", "warning"]
    path: str
    message: str
```

## 11. Validation MVP

| 校验 | 严重级别 |
|---|---|
| 输出不可 JSON parse | error |
| 缺 trace/case/run identity | error |
| score 非 number | error |
| span id 为空 | error |
| parent span 缺失 | warning |
| target required field 缺失 | error |

## 12. 验收标准

- Langfuse export 输出 JSONL 可解析，每条包含 observations/scores。
- Phoenix export 每行包含 trace_id/span_id/name/attributes。
- Braintrust export 每行包含 input/output/expected/scores。
- 多 evaluator scores 不互相覆盖。
- parent-child span 关系保留。
- missing parent 只报 warning，不丢弃 span。
- tool_calls 无 spans 时可合成 tool span。
