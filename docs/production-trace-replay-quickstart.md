# Production Trace Replay Quickstart

Production trace replay lets you evaluate real observed agent behavior without calling the original agent again. Import traces, replay them through deterministic evaluators, and promote failures into regression datasets.

## 1. Import production or vendor traces

```bash
PYTHONPATH=src python -m cli trace-import \
  --input examples/production/traces-otel.jsonl \
  --source otel \
  --out runs/trace-smoke/import.json \
  --format json \
  --format jsonl \
  --format markdown
```

Supported sources include AgentEval, production event JSON, OpenTelemetry/OpenInference, Langfuse, and Phoenix-style traces.

Generated artifacts:

- `runs/trace-smoke/import.json`: normalized trace import report.
- `runs/trace-smoke/import.jsonl`: replayable AgentEval trace stream, one normalized trace per line.
- `runs/trace-smoke/import.md`: human-readable import summary.

## 2. Replay traces through evaluators

```bash
PYTHONPATH=src python -m cli trace-replay \
  --traces runs/trace-smoke/import.jsonl \
  --source agenteval \
  --config examples/configs/trace_replay.yaml \
  --out runs/trace-smoke/replay \
  --dataset-out runs/trace-smoke/replay-dataset.yaml
```

Trace replay converts each trace into an `AgentRun` and evaluates it with the configured evaluators. It does not rerun the original agent.

Generated artifacts:

- `runs/trace-smoke/replay/traces.jsonl`: replayed `AgentRun` records.
- `runs/trace-smoke/replay/results.jsonl`: evaluator results for replayed traces.
- `runs/trace-smoke/replay/report.json`, `.md`, or `.html`: aggregate replay report according to the config.
- `runs/trace-smoke/replay-dataset.yaml`: optional dataset synthesized from the trace replay input.

## 3. Convert failed traces to regressions

```bash
PYTHONPATH=src python -m cli trace-to-regressions \
  --traces runs/trace-smoke/import.jsonl \
  --source agenteval \
  --out runs/trace-smoke/regressions.yaml \
  --only-errors
```

Review generated cases before appending them to a durable regression library. `trace-to-regressions` writes a standalone regression YAML from imported traces, while `regressions --run` mines the replay results and can append/dedupe into a long-lived dataset:

```bash
PYTHONPATH=src python -m cli regressions \
  --run runs/trace-smoke/replay \
  --append-to datasets/regressions/production.yaml \
  --dedupe
```

## 4. Use replay in a governance loop

A typical CI/release loop is:

1. Run baseline/candidate evals.
2. Compare baseline vs candidate.
3. Replay recent production traces against the candidate evaluator config.
4. Generate regression candidates from replay failures.
5. Gate promotion with `compare` and `promote`.

```bash
PYTHONPATH=src python -m cli compare \
  --baseline runs/main \
  --candidate runs/pr \
  --out runs/pr/compare \
  --format markdown \
  --format json \
  --fail-on-new-failures

PYTHONPATH=src python -m cli promote \
  --baseline runs/main \
  --candidate runs/pr \
  --policy examples/policies/promotion.yaml \
  --out runs/pr/promotion \
  --format markdown \
  --format json
```

Upload the imported traces, replay report, generated regressions, compare report, and promotion report as CI artifacts for review.
