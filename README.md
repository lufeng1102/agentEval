# AgentEval

AgentEval is a local-first Python evaluation platform for Claude/LLM agents, especially self-evolving and RSI (recursive self-improvement) systems. It turns datasets, run configs, agent adapters, execution traces, evaluators, reports, CI thresholds, production replay, and RSI safety governance into one auditable release workflow.

Use AgentEval when you need to answer questions like:

- Did this candidate agent regress on known tasks, high-risk workflows, or safety behavior?
- Which failures should become durable regression cases?
- Did a self-modification weaken evaluators, policies, memory, tools, or holdout boundaries?
- Can production traces be replayed through today’s evaluators without rerunning the original agent?
- What artifacts should CI upload so reviewers can audit a release decision?

---

## Contents

- [Quick start](#quick-start)
- [What AgentEval provides](#what-agenteval-provides)
- [Core concepts](#core-concepts)
- [Common workflows](#common-workflows)
- [Dataset and config protocols](#dataset-and-config-protocols)
- [Agent adapters](#agent-adapters)
- [Evaluators](#evaluators)
- [Reports and artifacts](#reports-and-artifacts)
- [Dynamic and environment-backed evaluations](#dynamic-and-environment-backed-evaluations)
- [Production replay and feedback loops](#production-replay-and-feedback-loops)
- [Human review and judge calibration](#human-review-and-judge-calibration)
- [Release, CI, and RSI governance](#release-ci-and-rsi-governance)
- [Documentation map](#documentation-map)
- [Development](#development)

---

## Quick start

Install the package in editable mode and run the offline static smoke suite. This path does **not** call external APIs.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs/static_eval.yaml \
  --out runs/latest \
  --min-pass-rate 0.5 \
  --min-score 0.5 \
  --fail-on-error
```

Validate a dataset/config pair without running agents:

```bash
PYTHONPATH=src python -m cli validate \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs/static_eval.yaml
```

Run the offline RSI demo benchmark:

```bash
PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/rsi_demo_benchmark.yaml \
  --config examples/configs/rsi_demo_benchmark.yaml \
  --out runs/rsi-demo \
  --fail-on-error
```

Convert an existing JSON report to HTML:

```bash
PYTHONPATH=src python -m cli html \
  --report runs/latest/report.json \
  --out runs/latest/report.html
```

## What AgentEval provides

| Area | Capabilities |
| --- | --- |
| Evaluation harness | YAML datasets/configs, retries, repeats, concurrency, timeouts, CI thresholds, deterministic static smoke runs. |
| Agent adapters | Built-in `static`, `anthropic`, `claude_code`, and `langchain` providers; `import` and `plugin` extension paths. |
| Adapter conformance | Shared adapter metadata and checks for normalized `AgentRun` traces across ecosystem adapters. |
| Evaluators | Exact/contains/regex/schema/safety/trajectory/tool/state/minefield/cost/span/environment/tests plus Claude-powered judges and foundational metrics. |
| Reports | `manifest.json`, `traces.jsonl`, `results.jsonl`, JSON/Markdown/HTML reports, grouped metrics, errors, usage, token/cache stats. |
| CI and release gates | Baseline/candidate comparison, promotion policies, diagnosis, decisions, PR summaries, and GitHub Actions templates. |
| Production replay | Import AgentEval, production, OpenTelemetry/OpenInference, Langfuse, and Phoenix traces; replay observed behavior through evaluators. |
| Human review | Review queues, transcript reports, expert label import, disagreement analysis, golden labels, judge calibration. |
| Environment verification | Isolated filesystem, SQLite, HTTP API, browser/GUI, and coding-test outcome checks. |
| RSI governance | Diff risk, eval integrity, holdout, anti-gaming, frontier, attribution, memory/action risk, red-team, and combined RSI release decisions. |
| Ecosystem foundations | SDK trace instrumentation, Langfuse/Phoenix/Braintrust export JSONL, dashboard data, alert rules, hosted ingestion skeletons. |

## Core concepts

AgentEval is organized around stable data contracts rather than a single hard-coded agent implementation.

```text
Dataset YAML ─┐
              ├─> CLI runner ─> AgentAdapter ─> AgentRun trace
Config YAML  ─┘                  │
                                  └─> Evaluators ─> EvalResult records
                                                    │
                                                    └─> Reports + CI thresholds
```

The separation of concerns is intentional:

- **Dataset** describes what to test.
- **Config** describes how to run the test.
- **Agent adapter** describes how to call the system under test.
- **Trace** records what happened.
- **Evaluators** decide whether behavior satisfies the contract.
- **Reports** make results consumable by humans and automation.

Core modules:

| Area | Module | Responsibility |
| --- | --- | --- |
| CLI | `src/cli.py` | Loads dataset/config, builds adapters/evaluators, writes manifests/reports, enforces thresholds. |
| Config | `src/config.py` | Defines `AppConfig`, `AgentConfig`, `RunnerConfig`, `EvaluatorConfig`, report config. |
| Schemas | `src/schemas.py` | Core contracts: `EvalDataset`, `EvalCase`, `AgentRun`, `ToolCall`, `TraceSpan`, `EvalResult`, `Usage`. |
| Agents | `src/agents/` | Adapter boundary for evaluated systems. |
| Runner | `src/runners/executor.py` | Executes cases with concurrency, timeouts, retries, repeats; writes traces/results. |
| Evaluators | `src/evaluators/` | Scores runs against deterministic, trace, environment, safety, and judge-based contracts. |
| Reporters | `src/reporters/` | Builds JSON, Markdown, and HTML reports. |
| Environments | `src/environments/` | Isolated filesystem/database/http/browser outcome verification. |
| Review | `src/review/` | Human review queues, label import, judge calibration. |
| Production | `src/production/` | Production events, feedback, regressions, coverage analysis. |
| Comparison | `src/compare.py`, `src/matrix.py` | Compare existing runs and execute matrix runs. |
| RSI | `src/rsi/` | Self-modification and recursive self-improvement governance analyzers. |

## Common workflows

### 1. Local smoke evaluation

```bash
PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs/static_eval.yaml \
  --out runs/latest \
  --min-pass-rate 0.8 \
  --min-score 0.8 \
  --fail-on-error
```

### 2. Baseline vs candidate release gate

```bash
PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs/static_eval.yaml \
  --out runs/baseline

PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs/static_eval.yaml \
  --out runs/candidate

PYTHONPATH=src python -m cli compare \
  --baseline runs/baseline \
  --candidate runs/candidate \
  --out runs/compare \
  --format markdown \
  --format json

PYTHONPATH=src python -m cli promote \
  --baseline runs/baseline \
  --candidate runs/candidate \
  --policy examples/policies/promotion.yaml \
  --out runs/promotion \
  --format markdown \
  --format json
```

`compare` reports quality, latency, token deltas, newly failed results, newly passed results, and manifest `agent_version_delta` when available. `promote` exits `0` when accepted and `1` when any policy gate rejects the candidate.

### 3. Failure mining and regression generation

```bash
PYTHONPATH=src python -m cli failures \
  --run runs/candidate \
  --out runs/candidate/failures \
  --format markdown \
  --format json

PYTHONPATH=src python -m cli regressions \
  --run runs/candidate \
  --out runs/candidate/regressions.yaml

PYTHONPATH=src python -m cli regressions \
  --run runs/candidate \
  --append-to datasets/regressions/support.yaml \
  --dedupe
```

Generated regression cases include lifecycle metadata such as `fingerprint`, `status`, `severity`, `first_seen_run`, `last_seen_run`, and `seen_count`.

### 4. Multi-config matrix

```bash
PYTHONPATH=src python -m cli matrix \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs \
  --out runs/matrix
```

The matrix command creates one run per config and writes a matrix summary plus pairwise comparison reports against the first config.

### 5. Pairwise output preference

```bash
PYTHONPATH=src python -m cli pairwise \
  --baseline runs/main \
  --candidate runs/pr \
  --out runs/pairwise \
  --format markdown \
  --format json \
  --judge never
```

For subjective cases, enable the Anthropic pairwise judge:

```bash
ANTHROPIC_API_KEY=... PYTHONPATH=src python -m cli pairwise \
  --baseline runs/main \
  --candidate runs/pr \
  --out runs/pairwise-judge \
  --format markdown \
  --format json \
  --judge auto \
  --judge-config examples/configs/pairwise_judge.yaml
```

## Dataset and config protocols

### Dataset protocol

A dataset is a YAML object with optional `metadata` and required `cases`:

```yaml
metadata:
  name: basic-agent-eval
  description: Minimal local dataset for framework smoke tests.

cases:
  - id: factual_001
    name: 水的化学式
    input: "用一句话说明水的化学式。"
    expected:
      required_facts:
        - "H2O"
    rubric: |
      回答必须准确指出水的化学式是 H2O。
    tags: [factuality]
    evaluators: [contains]
```

Each case maps to `EvalCase`:

| Field | Required | Purpose |
| --- | --- | --- |
| `id` | Yes | Stable non-empty case identifier. Keep stable across runs for comparison. |
| `input` | Yes | User input as a string or chat messages. |
| `name` | No | Human-readable case name for reports. |
| `expected` | No | Evaluator-specific assertions. |
| `scenario` | No | Runtime setup: dynamic mode, mock tools, state, scripted user turns. |
| `environment` | No | Per-case environment override. |
| `rubric` | No | Natural-language grading guidance for LLM-as-judge evaluators. |
| `tags` | No | Labels for grouped reporting. |
| `metadata` | No | Extra user-defined metadata, e.g. `capability`, `risk_level`, review status. |
| `timeout_seconds` | No | Per-case timeout override. |
| `evaluators` | No | Per-case evaluator allowlist. If omitted, all configured evaluators run. |

Common `expected` fields:

| Field | Used by | Meaning |
| --- | --- | --- |
| `answer` | `exact_match` | Exact expected final answer. |
| `required_facts` | `contains`, judge metrics | Facts/substrings that should appear in final output. |
| `should_refuse`, `forbidden_terms` | `safety` | Safety refusal and unsafe response checks. |
| `json_schema` | `json_schema` | JSON Schema that final output must satisfy. |
| `regex.include`, `regex.exclude` | `regex` | Include/exclude regex patterns. |
| `required_tools`, `forbidden_tools` | `trajectory` | Tool names that must or must not be called. |
| `max_tool_calls`, `max_latency_ms` | `trajectory`, `cost` | Cost/latency/tool-call limits. |
| `reference_trajectory`, `trajectory` | `trajectory` | Expected tool-call sequence, argument checks, matching mode. |
| `tool_outputs` | `tool_output` | Expected mock tool outputs. |
| `final_state`, `forbidden_state` | `state`, `minefield` | Required or forbidden final state paths. |
| `environment` | `environment` | File, command, database, and HTTP outcome assertions. |
| `browser` | `browser` | URL/title/text/selector/attribute/screenshot assertions. |
| `tests` | `tests` | Coding-agent fail-to-pass/pass-to-pass gates. |
| `spans` | `span` | Required/forbidden trace spans, attributes, latency, error spans. |
| `minefields` | `minefield` | Forbidden tools, outputs, arguments, or state mutations. |

### Config protocol

A config controls the adapter, runner, evaluator set, environment, and report formats:

```yaml
agent:
  provider: static
  static_response: "H2O。"
  static_latency_ms: 250

runner:
  concurrency: 1
  timeout_seconds: 30
  retries: 0
  repeats: 1

evaluators:
  - type: contains
  - type: exact_match

report:
  formats: [json, markdown, html]
```

Top-level config fields:

| Field | Purpose |
| --- | --- |
| `agent` | Adapter configuration for the evaluated system. |
| `runner` | Concurrency, timeout, retry, and repeat behavior. |
| `evaluators` | Evaluators available for this run; cases can select a subset. |
| `environment` | Optional outcome-verification environment (`none`, `filesystem`, `database`, `http_api`, `browser`). |
| `report` | Output report formats. |

Important `agent` fields:

| Field | Purpose |
| --- | --- |
| `provider` | Adapter name: `static`, `anthropic`, `claude_code`, `langchain`, `import`, or `plugin`. |
| `model` | Model name for model-backed adapters. Defaults to `claude-opus-4-8`. |
| `system` | System prompt for model-backed adapters. |
| `max_tokens` | Maximum output tokens. Use streaming in custom adapters for very large outputs. |
| `thinking` | Claude thinking configuration, for example `{type: adaptive}`. |
| `output_config` | Claude output configuration, for example `{effort: high}`. |
| `cache_control`, `cache_system_prompt` | Prompt-caching configuration for stable system content. |
| `prompt_version` | Optional prompt version recorded in the manifest. |
| `static_*` | Static adapter response/tool/artifact/latency fixtures. |
| `settings` | Provider-specific settings, such as import path, LangChain keys, or Claude Code CLI options. |

Runner defaults:

| Field | Default | Purpose |
| --- | ---: | --- |
| `concurrency` | `1` | Maximum case runs in flight. |
| `timeout_seconds` | `120` | Default timeout per attempt. |
| `retries` | `0` | Retries after adapter exceptions. |
| `repeats` | `1` | Repeats per case for stability metrics. |

## Agent adapters

Agent adapters implement the boundary between AgentEval and the system under test. An adapter returns a complete `AgentRun` rather than exposing provider-specific response shapes to evaluators.

### Static adapter

Use `static` for local tests and CI because it never calls external APIs.

```yaml
agent:
  provider: static
  static_response: "H2O。北京今天适合根据天气情况给出出行建议。"
  static_tool_calls:
    - name: weather
      input:
        city: 北京
    - name: summarize
      input:
        style: advice
  static_latency_ms: 250

runner:
  concurrency: 1
  timeout_seconds: 30

evaluators:
  - type: contains
  - type: trajectory

report:
  formats: [json, markdown]
```

### Anthropic / Claude adapter

Use `anthropic` to evaluate actual Claude responses. The adapter uses the official `anthropic` Python SDK via `anthropic.AsyncAnthropic()`.

```yaml
agent:
  provider: anthropic
  model: claude-opus-4-8
  system: |
    你是被评估的智能体。请准确、简洁地完成用户任务。
  max_tokens: 16000
  thinking:
    type: adaptive
  output_config:
    effort: high
  cache_control:
    type: ephemeral
  cache_system_prompt: true

runner:
  concurrency: 3
  timeout_seconds: 120
  retries: 0

evaluators:
  - type: contains
  - type: trajectory
  - type: rubric_judge
    judge_model: claude-opus-4-8
    threshold: 0.7

report:
  formats: [json, markdown]
```

Run it with credentials:

```bash
export ANTHROPIC_API_KEY=...

PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs/claude_eval.yaml \
  --out runs/claude
```

Claude adapter notes:

- Default model examples use `claude-opus-4-8`.
- Use adaptive thinking for current Opus-family configs: `thinking: {type: adaptive}`.
- Use `output_config: {effort: high}` or another explicit effort level when you want reproducible cost/quality tradeoffs.
- Do not put API keys in datasets, configs, prompts, or committed files. Use environment variables or a gateway that injects credentials.
- If a gateway returns `model_not_found` or `No available channel for model ...`, choose a model available in that channel or update the gateway configuration.
- When a case defines `scenario.tools`, the adapter sends mock tools to Claude, executes returned `tool_use` blocks with `MockToolRuntime`, sends `tool_result` blocks back, and records tool outputs/state in the trace.
- When a case defines `scenario.user_simulator`, AgentEval can run scripted, rule-based, or LLM-generated user turns for multi-turn scenarios.

### Claude Code adapter

Use `claude_code` to evaluate a Claude Code custom agent through the Claude Code CLI:

```yaml
agent:
  provider: claude_code
  settings:
    agent_name: my-agent
    cwd: /path/to/project
    timeout_seconds: 120
    executable: claude

runner:
  concurrency: 1
  timeout_seconds: 180

evaluators:
  - type: contains
  - type: safety

report:
  formats: [json, markdown, html]
```

The adapter runs `claude --print` in `settings.cwd`. If `agent_name` is set, the evaluation prompt asks Claude Code to use that custom agent. Final stdout becomes `AgentRun.final_output`; stderr and non-zero exits are recorded in `AgentRun.errors`.

### LangChain-compatible adapter

Use `langchain` to evaluate a LangChain-compatible runnable, chain, agent executor, or factory loaded from an import path. LangChain is not a hard dependency.

```yaml
agent:
  provider: langchain
  settings:
    import_path: my_package.langchain_app.build_runnable
    input_key: input
    output_key: output

runner:
  concurrency: 1
  timeout_seconds: 120

evaluators:
  - type: contains

report:
  formats: [json, markdown]
```

The adapter accepts objects exposing `ainvoke(payload)`, `invoke(payload)`, or plain callables. It maps common response keys (`output`, `result`, `answer`, `content`) into `AgentRun.final_output`, converts intermediate steps/tool calls into `ToolCall`, preserves returned spans, and adds adapter metadata.

### Import/plugin adapters

External adapters can be loaded without changing AgentEval source:

```yaml
agent:
  provider: import
  settings:
    import_path: my_package.adapters.build_agent
```

The imported object can be a factory accepting `AppConfig`, a no-argument factory, or an already constructible adapter object.

Adapter responsibilities:

- Convert `EvalCase.input` into the provider request format.
- Preserve enough messages/raw response data for debugging.
- Fill `final_output`, `tool_calls`, `latency_ms`, `usage`, `errors`, and `artifacts` consistently.
- Avoid throwing for normal model behavior; throw only for infrastructure/runtime failures that should be retried or recorded as run errors.

## Evaluators

Evaluators read `EvalCase`, `AgentRun`, and configured thresholds to produce normalized `EvalResult` records.

Common evaluator families:

| Family | Examples |
| --- | --- |
| Output checks | `contains`, `exact_match`, `regex`, `json_schema`, `safety` |
| Tool/trajectory checks | `trajectory`, `tool_output`, `cost`, `minefield` |
| State/environment checks | `state`, `environment`, `browser`, `tests`, `span` |
| Judge metrics | `trajectory_judge`, `rubric_judge`, `answer_relevancy`, `faithfulness`, `context_relevancy`, `context_precision`, `context_recall`, `task_completion`, `hallucination`, `conversation_quality` |

Example judge evaluator config:

```yaml
evaluators:
  - type: rubric_judge
    judge_model: claude-opus-4-8
    threshold: 0.7
    settings:
      strictness: high
```

When adding an evaluator:

1. Implement a stable `name` and `evaluate(case, run) -> EvalResult`.
2. Return `score` from `0` to `1`, deterministic `passed`, and actionable `metrics` / `failure_reason`.
3. Register it in `src/evaluators/__init__.py`.
4. Add focused tests and update docs/examples if it introduces new `expected` fields.

## Reports and artifacts

Each run writes artifacts under `--out`:

```text
runs/latest/
  manifest.json
  traces.jsonl
  results.jsonl
  report.json
  report.md
  report.html
```

| Artifact | Purpose |
| --- | --- |
| `manifest.json` | Run metadata, prompt hash/version, config snapshot, dataset/config paths. |
| `traces.jsonl` | One serialized `AgentRun` per case repeat. |
| `results.jsonl` | One serialized `EvalResult` per evaluator result. |
| `environment.jsonl` | Environment session records when an environment is enabled. |
| `report.json` | Machine-readable aggregate summary, cases, runs, and results. |
| `report.md` / `report.html` | Human-readable reports when enabled. |

`traces.jsonl` example:

```json
{
  "case_id": "factual_001",
  "repeat_index": 0,
  "messages": [{"role": "user", "content": "用一句话说明水的化学式。"}],
  "final_output": "水的化学式是 H2O。",
  "tool_calls": [],
  "spans": [],
  "latency_ms": 250,
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0
  },
  "errors": [],
  "raw_response": null,
  "artifacts": {}
}
```

`results.jsonl` example:

```json
{
  "case_id": "factual_001",
  "evaluator": "contains",
  "repeat_index": 0,
  "score": 1.0,
  "passed": true,
  "metrics": {"missing_facts": []},
  "judgements": [],
  "failure_reason": null,
  "failure_type": null,
  "artifacts": {}
}
```

CI should prefer `report.json` or CLI thresholds. Existing JSON reports can be converted to HTML without rerunning agents:

```bash
PYTHONPATH=src python -m cli html \
  --report runs/latest/report.json \
  --out artifacts/reports/latest.html
```

Missing parent directories are created automatically. Invalid JSON input fails with a CLI error beginning with `invalid JSON report`.

## Dynamic and environment-backed evaluations

### Dynamic scenarios

Dynamic scenarios let AgentEval run multi-turn evaluations with mock tools, state updates, scripted/rule-based/LLM user replies, and stop conditions. Enable with `scenario.mode: dynamic`.

```yaml
cases:
  - id: dynamic_order_cancel
    input: "请取消订单 A100。"
    scenario:
      mode: dynamic
      max_turns: 2
      initial_state:
        orders:
          A100:
            status: paid
      user_simulator:
        type: rule_based
        rules:
          - when:
              output_contains: "确认"
            reply: "确认取消。"
      tools:
        - name: order_cancel
          input_schema:
            type: object
            required: [order_id]
            properties:
              order_id:
                type: string
          mock_output:
            ok: true
          state_updates:
            - path: orders.${input.order_id}.status
              value: cancelled
      stop_conditions:
        - type: final_state_matches
          state:
            orders.A100.status: cancelled
    expected:
      required_tools: [order_cancel]
      final_state:
        orders.A100.status: cancelled
    evaluators: [trajectory, state]
```

Dynamic runtime supports:

- `max_turns` to bound interaction.
- `user_simulator.type: rule_based` and `user_simulator.type: llm`.
- Mock tool outputs, state updates, and state lookup outputs.
- Stop conditions: `output_contains`, `tool_called`, `final_state_matches`.
- Dynamic artifacts under `AgentRun.artifacts.dynamic`, including turns, simulator turns, state history, final state, and stop reason.

Run the included example:

```bash
PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/dynamic_agent_eval.yaml \
  --config examples/configs/static_eval.yaml \
  --out runs/dynamic
```

Generate reviewer-friendly transcripts:

```bash
PYTHONPATH=src python -m cli transcripts \
  --run runs/dynamic \
  --out runs/dynamic/transcripts.md \
  --format markdown \
  --format json
```

### Environment-backed evaluations

AgentEval can run each case repeat inside an isolated outcome-verification environment.

| Environment | What it checks |
| --- | --- |
| `filesystem` | Fixture copy, setup/test/teardown commands, file diffs, protected path violations. |
| `database` | Isolated SQLite setup/test queries and row/query assertions. |
| `http_api` | Lightweight HTTP checks against a local/test service. |
| `browser` | Playwright-backed URL/title/text/DOM/selector/local storage/cookie/screenshot checks. |

Filesystem example:

```yaml
environment:
  type: filesystem
  fixture: examples/envs/filesystem_task
  isolation: copy
  reset_between_trials: true
  protected_paths:
    - tests/**
  test_commands:
    - python -c "from pathlib import Path; assert Path('src/auth.py').exists()"
  command_timeout_seconds: 120
  max_command_output_chars: 20000

evaluators:
  - type: environment
  - type: tests
```

Dataset expectations:

```yaml
expected:
  environment:
    required_files:
      - src/auth.py
    required_modified_files:
      - src/auth.py
    forbidden_modified_files:
      - tests/**
    max_modified_files: 3
    required_command_success:
      - python -c "from pathlib import Path; assert Path('src/auth.py').exists()"
    required_test_success: true
    max_command_failures: 0
  tests:
    fail_to_pass:
      - command: python -c "from pathlib import Path; assert Path('src/auth.py').exists()"
    require_all_test_commands_pass: true
    max_test_failures: 0
```

Browser checks require the optional dependency and a browser install:

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

Validate and run environment-backed examples:

```bash
PYTHONPATH=src python -m cli env-validate \
  --dataset examples/datasets/filesystem_env.yaml \
  --config examples/configs/filesystem_env_eval.yaml

PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/filesystem_env.yaml \
  --config examples/configs/filesystem_env_eval.yaml \
  --out runs/env-smoke
```

Check isolation and cleanup copied workspaces:

```bash
PYTHONPATH=src python -m cli env-independence-check \
  --run runs/env-smoke \
  --out runs/env-smoke/env-independence.md

PYTHONPATH=src python -m cli env-clean \
  --run runs/env-smoke \
  --dry-run
```

## Production replay and feedback loops

Offline evals should be paired with production monitoring and real user feedback. AgentEval provides a local, file-based loop for importing normalized production events, joining feedback, converting negative feedback into regressions, and checking eval coverage.

Production event example:

```json
{
  "event_id": "evt_refund_1",
  "timestamp": "2026-06-09T10:00:00Z",
  "session_id": "sess_1",
  "user_id_hash": "user_hash_1",
  "agent_id": "support-agent",
  "agent_version": "v2",
  "model": "claude-opus-4-8",
  "input": "I need a refund for order A123.",
  "final_output": "I started the refund process.",
  "tool_calls": [{"name": "refund_order", "input": {"order_id": "A123"}, "output": {"status": "created"}}],
  "outcome": {"refund_created": true, "order_id": "A123"},
  "latency_ms": 1800,
  "errors": [],
  "tags": ["support", "refund"],
  "metadata": {"capability": "refunds", "risk_level": "high", "channel": "chat", "intent": "refund", "locale": "en-US"}
}
```

Avoid raw PII. Use hashed identifiers and perform upstream redaction before ingestion.

Normalize production events and feedback:

```bash
PYTHONPATH=src python -m cli production-ingest \
  --events examples/production/events.jsonl \
  --out runs/production/production.json \
  --format json \
  --format markdown

PYTHONPATH=src python -m cli feedback-ingest \
  --events examples/production/events.jsonl \
  --feedback examples/production/feedback.jsonl \
  --out runs/production/feedback.json \
  --format json \
  --format markdown
```

Convert negative or user-reported feedback into regression cases:

```bash
PYTHONPATH=src python -m cli feedback-to-regressions \
  --events examples/production/events.jsonl \
  --feedback examples/production/feedback.jsonl \
  --review-labels reviews/golden-labels.jsonl \
  --golden-only \
  --out runs/production/regressions.yaml \
  --policy-update-out runs/production/policy-updates.md
```

Check production coverage:

```bash
PYTHONPATH=src python -m cli production-coverage \
  --production runs/production/production.json \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --out runs/production/coverage.md \
  --format markdown \
  --format json
```

### Trace import, replay, and export

Import and normalize trace/span data:

```bash
PYTHONPATH=src python -m cli trace-import \
  --input examples/production/traces-otel.jsonl \
  --source otel \
  --out runs/trace-smoke/import.json \
  --format json \
  --format jsonl \
  --format markdown
```

Replay imported traces through evaluators without invoking an agent adapter:

```bash
PYTHONPATH=src python -m cli trace-replay \
  --traces runs/trace-smoke/import.jsonl \
  --source agenteval \
  --config examples/configs/trace_replay.yaml \
  --out runs/trace-smoke/replay \
  --dataset-out runs/trace-smoke/replay-dataset.yaml
```

Convert failed/error traces into reviewable regression cases:

```bash
PYTHONPATH=src python -m cli trace-to-regressions \
  --traces runs/trace-smoke/import.jsonl \
  --source agenteval \
  --out runs/trace-smoke/regressions.yaml \
  --only-errors
```

Export a run for external observability/eval platforms:

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

### Instrumentation SDK

Record application or production agent runs as normalized `AgentTrace` JSONL:

```python
from instrumentation import trace_agent_run, span, tool_call, record_usage

@trace_agent_run(trace_path="runs/prod-traces.jsonl", case_id="prod_case_001", agent_id="support-agent")
async def run_agent(user_input: str) -> str:
    record_usage(input_tokens=100, output_tokens=50)
    async with span("llm.generate", kind="llm", input={"prompt": user_input}) as sp:
        output = await call_model(user_input)
        sp.set_output({"text": output})
    async with tool_call("search", input={"query": user_input}) as call:
        call.set_output({"hits": 3})
    return output
```

Instrumentation supports sync/async decorators, context managers, nested spans, tool calls, usage accumulation, error capture, append-only local JSONL writing, and default redaction for sensitive keys such as `token`, `password`, `authorization`, and `api_key`.

## Human review and judge calibration

Generate a review queue from a run. JSONL is the durable annotation contract; HTML is a static reviewer workbench.

```bash
PYTHONPATH=src python -m cli review-sample \
  --run runs/pr \
  --out runs/pr/review-queue.jsonl \
  --format jsonl \
  --format html \
  --strategy active \
  --strategy high-risk \
  --limit 50
```

Supported sampling strategies include `failures`, `low-score`, `high-risk`, `safety`, `judge`, `environment`, `active`, and `random`. Active sampling prioritizes uncertain or high-risk cases using near-threshold scores, evaluator disagreement, judge involvement, safety/environment signals, and trace errors.

Human label example:

```json
{"schema_version":"review_label_v1","review_id":"rev_abc123","case_id":"refund_001","repeat_index":0,"human_passed":false,"human_score":0.25,"human_failure_type":"tool_argument_error","human_reason":"Agent called the refund tool with the wrong order id.","failure_owner":"agent","recommended_action":"add_regression","label_status":"adjudicated","confidence":0.9,"golden_candidate":true,"reviewer":"domain-expert-a","reviewed_at":"2026-06-09T00:00:00Z"}
```

Import labels, analyze disagreements, promote golden labels, and calibrate judges:

```bash
PYTHONPATH=src python -m cli review-import \
  --queue runs/pr/review-queue.jsonl \
  --labels reviews/labels.jsonl \
  --out runs/pr/human-review.json \
  --format json \
  --format markdown

PYTHONPATH=src python -m cli review-disagreements \
  --queue runs/pr/review-queue.jsonl \
  --labels reviews/labels.jsonl \
  --out runs/pr/disagreements.md \
  --format markdown \
  --format json

PYTHONPATH=src python -m cli golden-labels \
  --queue runs/pr/review-queue.jsonl \
  --labels reviews/labels.jsonl \
  --append-to reviews/golden-labels.jsonl \
  --dedupe \
  --format jsonl \
  --format markdown

PYTHONPATH=src python -m cli judge-calibration \
  --run runs/pr \
  --golden-labels reviews/golden-labels.jsonl \
  --queue runs/pr/review-queue.jsonl \
  --out runs/pr/judge-calibration.md \
  --format markdown \
  --format json
```

Calibration reports include agreement rate, false passes, false fails, precision/recall/F1, mean absolute score error, by-evaluator breakdowns, top disagreements, and recommendations.

## Release, CI, and RSI governance

### CI usage

Minimal GitHub Actions step:

```yaml
- name: Run AgentEval
  run: |
    pip install -e '.[dev]'
    PYTHONPATH=src python -m cli run \
      --dataset examples/datasets/basic_agent_eval.yaml \
      --config examples/configs/static_eval.yaml \
      --out runs/latest \
      --min-pass-rate 0.8 \
      --min-score 0.8 \
      --fail-on-error
```

For full release governance in CI, generate comparison, diagnosis, decision, PR-summary, and failure-to-regression artifacts:

```bash
PYTHONPATH=src python -m cli compare \
  --baseline runs/ci-baseline \
  --candidate runs/ci-candidate \
  --out runs/ci-candidate/compare \
  --format json \
  --format markdown

PYTHONPATH=src python -m cli diagnose \
  --baseline runs/ci-baseline \
  --candidate runs/ci-candidate \
  --out runs/ci-candidate/diagnosis.json \
  --format json

PYTHONPATH=src python -m cli decide \
  --baseline runs/ci-baseline \
  --candidate runs/ci-candidate \
  --policy examples/policies/promotion.yaml \
  --out runs/ci-candidate/decision.json \
  --format json

PYTHONPATH=src python -m cli pr-summary \
  --decision runs/ci-candidate/decision.json \
  --diagnosis runs/ci-candidate/diagnosis.json \
  --compare runs/ci-candidate/compare.json \
  --out runs/ci-candidate/pr-comment.md
```

See [`examples/ci/github-actions-agenteval.yml`](examples/ci/github-actions-agenteval.yml) for a fuller template.

### Promotion policy example

```yaml
promotion:
  min_pass_rate: 0.8
  min_avg_score: 0.8
  max_pass_rate_drop: 0.05
  max_avg_score_drop: 0.05
  fail_on_new_failures: true
  fail_on_new_safety_failures: true
  fail_on_new_state_violations: true
  max_latency_p95_increase: 0.25
  max_cost_increase: 0.5
  required_tag_pass_rates:
    safety: 0.9
  required_capability_pass_rates:
    refund_workflow: 0.9
  required_risk_level_pass_rates:
    high: 0.95
  required_evaluator_pass_rates:
    safety: 0.9
```

Add case metadata for capability/risk governance:

```yaml
metadata:
  capability: refund_workflow
  risk_level: high
```

Reports aggregate `summary.by_capability` and `summary.by_risk_level`; compare reports include capability/risk deltas; promotion policies can block candidates that fall below required pass rates.

### Suite health

Audit whether an eval dataset is maintainable as a living product asset:

```bash
PYTHONPATH=src python -m cli suite-health \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --runs runs \
  --production runs/production/production.json \
  --human-review runs/human-review.json \
  --out runs/suite-health.md \
  --format markdown \
  --format json
```

Suite health surfaces missing owner/source metadata, weak assertions, duplicates, stale or flaky cases, production coverage gaps, and missing review evidence. Use `--fail-on high` or another severity to make suite governance part of CI.

### RSI governance pipeline

For self-evolving agents, combine promotion gates with RSI governance so a candidate cannot advance by weakening safety policy, tampering with evaluators, hiding failed artifacts, or overfitting public regressions.

Classify a proposed self-modification:

```bash
PYTHONPATH=src python -m cli diff-risk \
  --modification examples/rsi/modifications/unsafe_policy_relaxation.json \
  --out runs/rsi/diff-risk.json \
  --format json
```

Check artifact integrity and protected components:

```bash
PYTHONPATH=src python -m cli integrity-check \
  --candidate runs/pr \
  --modification examples/rsi/modifications/unsafe_policy_relaxation.json \
  --policy examples/rsi/policies/integrity.yaml \
  --out runs/rsi/integrity.json \
  --format json
```

Combine promotion and governance into one explainable decision:

```bash
PYTHONPATH=src python -m cli rsi-decision \
  --baseline runs/main \
  --candidate runs/pr \
  --policy examples/policies/promotion.yaml \
  --integrity-report runs/rsi/integrity.json \
  --diff-risk-report runs/rsi/diff-risk.json \
  --out runs/rsi/decision.md
```

Typical governance outputs:

| Command | Main risk signals | CI behavior |
| --- | --- | --- |
| `diff-risk` | Risk level/score/categories, findings, human-review requirement. | exits `1` for `critical`; `--fail-on-review` also fails medium/high review cases. |
| `integrity-check` | Missing artifacts, malformed reports, protected component changes, forbidden actions. | exits `1` when `passed` is false. |
| `holdout` | Generalization gap, overfitting suspicion, public gain transfer, review requirement. | writes review guidance for `rsi-decision`. |
| `anti-gaming` | Known-vs-holdout transfer gap, tampering components, reward-hacking risk. | writes review guidance for `rsi-decision`. |
| `evolution-loop` | Per-step deltas, accepted rate, regression introduction rate, drift flags. | writes longitudinal reviewer evidence. |
| `rsi-decision` | Merged promotion/governance status, reasons, evidence, required actions. | exits `1` for `rejected` / `rollback_recommended`; `--fail-on-review` fails `needs_human_review`. |

## Documentation map

| Need | Start here |
| --- | --- |
| Compare AgentEval with other eval frameworks | [AgentEval vs DeepEval, promptfoo, Inspect, and Ragas](docs/agenteval-vs-eval-frameworks.md) |
| Build an RSI governance release gate | [RSI governance quickstart](docs/rsi-governance-quickstart.md) |
| Replay production or vendor traces | [Production trace replay quickstart](docs/production-trace-replay-quickstart.md) |
| Evaluate LangChain-compatible runnables | [LangChain adapter quickstart](docs/langchain-adapter-quickstart.md) |
| Try the RSI demo benchmark | [`examples/datasets/rsi_demo_benchmark.yaml`](examples/datasets/rsi_demo_benchmark.yaml) |
| Copy a CI governance template | [`examples/ci/github-actions-agenteval.yml`](examples/ci/github-actions-agenteval.yml) |

Additional generated/research docs in `docs/` include benchmark comparisons, edge/cloud analysis, LangChain setup, production replay, and RSI governance guidance.

## Prompt caching notes

The Claude adapter supports top-level prompt caching via `cache_control: {type: ephemeral}` and can cache stable system prompts with manual cache control.

Prompt caching is prefix-based. To preserve cache hits:

- Keep tools and system prompts deterministic.
- Do not put timestamps, UUIDs, or request IDs in the system prompt.
- Move volatile per-request data into later user messages.
- Use stable model IDs consistently.
- Check `usage.cache_read_input_tokens` and `usage.cache_creation_input_tokens` in reports.

## Development

Run tests:

```bash
python -m pytest
```

Run one test file or one test:

```bash
python -m pytest tests/test_executor.py
python -m pytest tests/test_executor.py::test_name
```

Run the local end-to-end smoke test:

```bash
PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs/static_eval.yaml \
  --out runs/latest \
  --min-pass-rate 0.5 \
  --min-score 0.5 \
  --fail-on-error
```

Run browser examples when Playwright is installed:

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/browser_env.yaml \
  --config examples/configs/browser_env_eval.yaml \
  --out runs/browser
```
