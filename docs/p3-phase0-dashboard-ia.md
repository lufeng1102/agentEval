# P3 Phase 0：Dashboard 信息架构

## 1. 目标

在现有静态 HTML report/dashboard 基础上，设计本地与 hosted 可复用的交互式 dashboard 信息架构。

MVP 覆盖：

- Runs list
- Run summary
- Cases table
- Case detail
- Evaluator results
- Trace viewer
- Compare view
- Artifacts / raw JSON

P1 扩展：

- Trend view
- Failure mining view
- RSI governance view
- Alert center
- Export jobs view
- Search/filter

## 2. 数据源抽象

建议新增：

```text
src/dashboard/data.py
```

```python
class DashboardDataSource(Protocol):
    def get_run_summary(self, run_id: str) -> RunSummary: ...
    def list_cases(self, run_id: str, filters: CaseFilters) -> Page[CaseRow]: ...
    def get_case_detail(self, run_id: str, case_id: str, repeat_index: int = 0) -> CaseDetail: ...
    def get_trace(self, run_id: str, case_id: str, repeat_index: int = 0) -> TraceView: ...
    def get_results(self, run_id: str, case_id: str | None = None) -> list[EvalResult]: ...
```

实现：

- `LocalRunDataSource`：读取本地 run directory。
- `HostedApiDataSource`：读取 hosted API。

## 3. IA 层级

```text
Dashboard Home
  Runs
    Run Summary
      Cases
        Case Detail
          Input & Expected
          Output & Messages
          Evaluator Results
          Trace Viewer
          Tool Calls
          Artifacts
          Raw JSON
      Evaluators
      Trace Explorer
      Compare
      Exports
      Alerts
      Governance
```

## 4. Runs list

字段：

| 字段 | 来源 |
|---|---|
| run_id | manifest 或 hosted generated id |
| created_at | manifest/hosted metadata |
| provider | manifest/config |
| model | manifest/config |
| case_count | report.summary |
| pass_rate | report.summary |
| avg_score | report.summary |
| failure_count | derived from results |
| latency | runs summary |
| total tokens | usage summary |
| error count | AgentRun.errors |

交互：

- 排序：time/pass_rate/avg_score/error_count。
- 过滤：provider/model/status/tag/framework。
- 点击进入 run summary。

## 5. Run summary

卡片：

| 卡片 | 内容 |
|---|---|
| Quality | pass_rate、avg_score、failed cases |
| Reliability | errors、timeouts、retries |
| Performance | p50/p95/p99 latency |
| Cost/Usage | input/output/cache tokens |
| Tools | total tool calls、failed tool calls |
| Stability | repeat variance、flaky count |

图表：

- evaluator pass/fail breakdown
- tag/capability/risk breakdown
- latency distribution
- token usage distribution
- score distribution

## 6. Cases table

字段：

| 字段 | 来源 |
|---|---|
| case_id | EvalCase/report |
| name | EvalCase.name |
| tags | EvalCase.tags |
| status | result aggregation |
| score | avg EvalResult.score |
| failed evaluators | EvalResult |
| latency_ms | AgentRun |
| errors | AgentRun.errors |
| risk_level | EvalCase.metadata |
| capability | EvalCase.metadata |

过滤：

```text
status=passed|failed|error|flaky
evaluator=contains|safety|...
tag=...
framework=...
risk_level=...
latency_min/max
token_min/max
```

## 7. Case detail

布局：

```text
Header:
  case_id / status / score / latency / token usage / model

Tabs:
  1. Input & Expected
  2. Output & Messages
  3. Evaluator Results
  4. Trace
  5. Tool Calls
  6. Artifacts
  7. Raw JSON
```

Evaluator results 表：

| evaluator | score | passed | failure_type | failure_reason | metrics |
|---|---:|---|---|---|---|

## 8. Trace viewer

Trace viewer 必须能处理大 trace。MVP data layer 应支持分页或虚拟化输入。

TraceView：

```json
{
  "trace_id": "trace_case_001_0",
  "root_span_id": "root",
  "flat_spans": [
    {
      "span_id": "span_1",
      "parent_span_id": null,
      "depth": 0,
      "name": "agent.run",
      "kind": "agent",
      "latency_ms": 1234,
      "status": "ok",
      "has_error": false
    }
  ],
  "span_count": 10000
}
```

交互：

- Tree/timeline。
- kind/status filters。
- span detail drawer：input/output/attributes/events/error。
- tool calls side panel。
- evaluator failure 跳转相关 span。

## 9. Compare view

输入：

- baseline run directory/run_id
- candidate run directory/run_id

展示：

| 指标 | 内容 |
|---|---|
| pass_rate delta | candidate - baseline |
| avg_score delta | candidate - baseline |
| new failures | baseline pass, candidate fail |
| fixed failures | baseline fail, candidate pass |
| evaluator regressions | by evaluator |
| latency delta | p50/p95 |
| token delta | total/avg |
| case-level diff | per case status/score/output |

## 10. Exports view

字段：

| 字段 | 说明 |
|---|---|
| target | langfuse/phoenix/braintrust |
| status | pending/running/succeeded/failed |
| records exported | int |
| validation errors | count |
| output artifact | download link |
| created_at/completed_at | timestamps |

## 11. P1 Governance view

基于 `src/rsi/` outputs 展示：

| 模块 | 展示 |
|---|---|
| eval integrity | risk level、gates、violations、evidence |
| anti-gaming | generalization gap、tampering components |
| holdout | pass rate、gap、confidence |
| memory | risk flags、changed memories |
| action risk | unsafe/high-risk actions |
| frontier | capability jumps/regressions |
| redteam | vulnerabilities, attacks tested |

## 12. Alert center

Alert event：

```json
{
  "alert_id": "alert_123",
  "run_id": "run_abc",
  "severity": "high",
  "rule_id": "pass_rate_threshold",
  "status": "open",
  "summary": "Pass rate dropped below 80%",
  "created_at": "2026-06-22T12:00:00Z",
  "delivery": {
    "webhook": "succeeded"
  }
}
```

## 13. 验收标准

- 给定本地 run directory，dashboard data layer 能读取 summary/cases/results/traces。
- case detail 能同时展示 input、expected、output、messages、evaluator results。
- trace viewer 可构建 parent-child tree。
- 10k spans fixture 不导致 data layer 崩溃。
- compare view 可展示 pass_rate delta 和 new failures。
- raw JSON 可查看 AgentRun、EvalResult、manifest/report excerpts。
