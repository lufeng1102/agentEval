# P3 Phase 0：MVP Acceptance Test Plan

## 1. 总体验收

P3 Phase 0 / MVP 通过条件：

1. 现有 static eval smoke test 不回归。
2. 新 adapter contract conformance tests 可运行。
3. SDK instrumentation 生成的 trace 可被 trace import/replay 消费。
4. Langfuse/Phoenix/Braintrust export 至少能生成可验证 JSONL。
5. Dashboard data layer 可加载本地 run directory。
6. Hosted mode 可上传并读取 run artifacts。
7. 所有新测试不依赖真实 Anthropic/OpenAI credentials。

## 2. Non-regression tests

必须通过：

```bash
python -m pytest
```

本地 smoke：

```bash
PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs/static_eval.yaml \
  --out runs/latest \
  --min-pass-rate 0.5 \
  --min-score 0.5 \
  --fail-on-error
```

建议新增：

```text
tests/test_p3_non_regression.py
```

测试点：

| 测试 | 验收 |
|---|---|
| static run artifacts | `manifest.json/traces.jsonl/results.jsonl/report.json` 存在 |
| report top-level keys | `summary/cases/runs/results` 存在 |
| traces.jsonl shape | 每行可 parse 为 `AgentRun` |
| results.jsonl shape | 每行可 parse 为 `EvalResult` |
| CLI thresholds | 行为与当前一致 |

## 3. Adapter conformance tests

建议新增：

```text
tests/adapters/test_contract_conformance.py
```

测试矩阵：

| 用例 | 验收点 |
|---|---|
| success run | `final_output` 正确，无 errors |
| failed run | errors 记录，runner 不崩 |
| tool call | `ToolCall` 与 tool span 存在 |
| multi message | messages 顺序正确 |
| usage | usage 可汇总 |
| latency | latency 非负 |
| span hierarchy | parent-child 可还原 |
| raw response | JSON serializable |
| adapter metadata | `artifacts.adapter.contract_version` 存在 |

示例：

```python
issues = validate_agent_run_contract(run)
assert not [item for item in issues if item.severity == "error"]
```

## 4. SDK instrumentation tests

建议新增：

```text
tests/instrumentation/test_sdk_tracer.py
```

| 测试 | 验收 |
|---|---|
| sync decorator | 函数返回值不变，写入 1 条 AgentTrace |
| async decorator | await 正常，latency >= 0 |
| exception preserving | 用户异常重新抛出，trace 记录 error |
| fail-open | writer 抛异常时用户函数仍返回 |
| span nesting | parent_span_id 正确 |
| tool call | 同时出现在 tool_calls 和 spans |
| usage accumulation | 多次 record_usage 正确累加 |
| redaction | token/password 被替换 |
| schema validation | 输出可 `AgentTrace.model_validate` |
| replay compatibility | 可转为 AgentRun 用于 replay |

## 5. Export tests

建议新增：

```text
tests/exports/test_exporters.py
```

Fixture：

```text
tests/fixtures/runs/p3_export_fixture/
  manifest.json
  traces.jsonl
  results.jsonl
  report.json
```

测试：

| target | 验收 |
|---|---|
| langfuse | 输出 JSONL 可解析；每条有 observations/scores |
| phoenix | 每行 span 有 trace_id/span_id/name/attributes |
| braintrust | 每行有 input/output/expected/scores |
| validation | 缺 span_id 报 error |
| missing parent | 报 warning，不丢弃 |
| multi evaluator | scores 独立导出，不覆盖 |
| synthetic tool span | tool_calls 无 spans 时自动合成 |

## 6. Dashboard tests

建议新增：

```text
tests/dashboard/test_dashboard_data.py
```

| 场景 | 验收 |
|---|---|
| load local run | summary/cases/results 可读 |
| case detail | input/output/evaluator/trace 数据完整 |
| trace view | parent-child tree 构建正确 |
| 10k spans fixture | data layer 支持分页/虚拟化输入 |
| compare view | pass_rate delta/new failures 正确 |
| raw json | AgentRun.raw_response/artifacts 可展示 |

## 7. Hosted mode tests

建议新增：

```text
tests/hosted/test_ingestion.py
```

| 测试 | 验收 |
|---|---|
| health | `GET /healthz` 返回 ok |
| upload run | multipart 上传成功并返回 run_id |
| idempotency | 重复上传同一 artifact 不创建重复 run |
| conflict | 同 run_key 不同 hash 返回 409 |
| artifact download | 下载 sha256 与上传一致 |
| auth required | 无 token 上传返回 401/403 |
| role enforcement | viewer token 上传返回 403 |
| audit log | upload/export/token 操作写 audit |

## 8. Alert MVP tests

建议新增：

```text
tests/alerts/test_alert_rules.py
```

| 规则 | 验收 |
|---|---|
| pass rate threshold | 低于阈值生成 alert_event |
| avg score threshold | 低于阈值生成 alert_event |
| new failures | candidate 新失败生成 alert |
| webhook payload | 包含 run_id/severity/rule_id/summary/dashboard_url |
| webhook retry | 500 后记录 delivery failed 并按策略重试 |
| dedupe | 相同 run/rule 不重复生成 open alert |

Webhook payload 示例：

```json
{
  "run_id": "run_123",
  "severity": "high",
  "rule_id": "pass_rate_threshold",
  "summary": "Pass rate dropped below 80%",
  "dashboard_url": "https://agenteval.example.com/runs/run_123",
  "artifact_url": "https://agenteval.example.com/runs/run_123/artifacts/report_json"
}
```

## 9. CI 建议

Phase 0 新增测试不应依赖真实外部服务。CI 可分层：

```bash
python -m pytest tests/test_p3_non_regression.py
python -m pytest tests/adapters tests/instrumentation tests/exports tests/dashboard tests/alerts
```

Hosted mode 若引入 web framework，可使用 test client 和临时目录/SQLite，不依赖外部数据库。

## 10. Exit criteria

Phase 0 设计冻结完成条件：

- 文档完成并评审通过。
- Adapter contract tests 列表明确。
- SDK API public surface 明确。
- Export 三目标映射明确。
- Dashboard data model 明确。
- Hosted entity/API/idempotency 规则明确。
- MVP acceptance tests 可拆成开发任务。
