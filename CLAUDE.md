# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

AgentEval is a Python evaluation framework for Claude/LLM agents. It separates evaluation datasets, run configs, agent adapters, execution traces, evaluators, reports, and CI thresholds so agent behavior can be tested locally or in CI.

The central data flow is:

```text
Dataset YAML + Config YAML
  -> CLI runner
  -> AgentAdapter produces AgentRun traces
  -> Evaluators produce EvalResult records
  -> JSON/Markdown/HTML reports and threshold checks
```

## Common commands

Install the package and development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Run the full test suite:

```bash
python -m pytest
```

Run one test file:

```bash
python -m pytest tests/test_executor.py
```

Run one test:

```bash
python -m pytest tests/test_executor.py::test_name
```

Run the local static smoke evaluation, which does not call external APIs:

```bash
PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs/static_eval.yaml \
  --out runs/latest
```

Run the same evaluation with CI thresholds:

```bash
PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs/static_eval.yaml \
  --out runs/latest \
  --min-pass-rate 0.8 \
  --min-score 0.8 \
  --fail-on-error
```

Run the Anthropic-backed config. This requires the official Anthropic SDK dependency and credentials in the active shell:

```bash
export ANTHROPIC_API_KEY=...
PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs/claude_eval.yaml \
  --out runs/claude
```

Convert an existing JSON report to HTML without rerunning evaluation:

```bash
PYTHONPATH=src python -m cli html \
  --report runs/latest/report.json \
  --out runs/latest/report.html
```

Compare two run directories:

```bash
PYTHONPATH=src python -m cli compare \
  --baseline runs/main \
  --candidate runs/pr \
  --out runs/compare.md \
  --max-pass-rate-drop 0.05 \
  --max-avg-score-drop 0.05 \
  --fail-on-new-failures
```

Run a matrix of configs against one dataset:

```bash
PYTHONPATH=src python -m cli matrix \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs \
  --out runs/matrix
```

CI currently installs with `pip install -e '.[dev]'`, runs `python -m pytest`, then runs the static AgentEval smoke test with `--min-pass-rate 0.5 --min-score 0.5 --fail-on-error`.

## Architecture notes

- `src/schemas.py` contains the core contracts: `EvalDataset`, `EvalCase`, `AgentRun`, `ToolCall`, `Usage`, `EvalResult`, and `RunContext`. Prefer extending these contracts deliberately because traces, results, and reports depend on them.
- `src/config.py` defines the YAML config model: `agent`, `runner`, `evaluators`, and `report`. Dataset loading and config loading both use Pydantic validation around YAML files.
- `src/cli.py` is the orchestration entry point. It loads dataset/config, builds the agent adapter from `agent.provider`, builds evaluator instances, writes `manifest.json`, emits reports, and enforces CLI thresholds.
- `src/runners/executor.py` is responsible for concurrency, per-case timeout, retries, repeats, writing `traces.jsonl`, and writing `results.jsonl`. Adapter exceptions are converted into `AgentRun.errors` so the full suite can continue.
- `src/agents/base.py` defines the adapter protocol. Built-ins are `static` and `anthropic`; new providers should return a complete `AgentRun` rather than exposing provider-specific response shapes to evaluators.
- `src/evaluators/__init__.py` is the evaluator factory. Built-ins include `contains`, `exact_match`, `trajectory`, `safety`, `json_schema`, `regex`, `tool_output`, `cost`, `minefield`, `state`, `trajectory_judge`, `rubric_judge`, and imported plugin evaluators.
- `src/reporters/` summarizes cases, runs, and evaluator results into `report.json`, `report.md`, and `report.html`. `report.json` is the machine-readable artifact for automation.
- `src/compare.py` and the `matrix` command compare existing run directories by reading their reports; they do not rerun agents except when the matrix command creates its per-config runs.

## Core data contracts

A dataset is a YAML object with `metadata` and `cases`. Each case maps to `EvalCase` and must have a stable non-empty `id` and non-empty `input`. Optional fields include `expected`, `scenario`, `rubric`, `tags`, `metadata`, `timeout_seconds`, and a per-case `evaluators` allowlist.

`expected` is evaluator-specific. Common fields are:

- `answer` for `exact_match`
- `required_facts` for `contains` and judge evaluators
- `should_refuse` and `forbidden_terms` for `safety`
- `json_schema` for `json_schema`
- `regex.include` / `regex.exclude` for `regex`
- `required_tools`, `forbidden_tools`, `max_tool_calls`, `max_latency_ms`, and `reference_trajectory` for `trajectory`
- `tool_outputs` for `tool_output`
- `final_state` and `forbidden_state` for `state`
- `minefields` for forbidden tools, outputs, arguments, or state mutations

The config file controls how the dataset is run:

- `agent.provider` chooses the adapter (`static` or `anthropic` currently).
- `runner.concurrency`, `timeout_seconds`, `retries`, and `repeats` control execution behavior.
- `evaluators[*].type` defines the evaluator set available for the run; case-level `evaluators` selects from this configured set.
- `report.formats` controls which report files are emitted.

Run outputs under `--out` are:

- `manifest.json`: run metadata, prompt hash/version, config snapshot, and dataset/config paths.
- `traces.jsonl`: one serialized `AgentRun` per case repeat.
- `results.jsonl`: one serialized `EvalResult` per evaluator result.
- `report.json`: structured aggregate report with summary, runs, and results.
- `report.md` / `report.html`: human-readable reports when enabled.

## Extension guidance

When adding an agent adapter:

1. Implement `async run(case: EvalCase, context: RunContext) -> AgentRun`.
2. Populate `case_id`, `messages`, `final_output`, `tool_calls`, `latency_ms`, `usage`, `raw_response`, and `artifacts` where applicable.
3. Register the provider in `_build_agent` in `src/cli.py`.
4. Add tests covering success, error handling, and any provider-specific trace fields.

When adding an evaluator:

1. Implement the evaluator interface with a stable `name` and `evaluate(case, run) -> EvalResult`.
2. Return a normalized `score` from `0` to `1`, a deterministic `passed` value, and useful `metrics` / `failure_reason`.
3. Register it in `src/evaluators/__init__.py`.
4. Add focused tests and, if it introduces new `expected` fields, update README examples and protocol docs.

## Claude/Anthropic adapter notes

The Anthropic adapter uses the official `anthropic` Python SDK through `anthropic.AsyncAnthropic()`. `ANTHROPIC_API_KEY` must be available in the active environment unless a gateway injects credentials. The default model in config is `claude-opus-4-8`; if a gateway returns `model_not_found` or `No available channel for model ...`, use a model available in that channel or update the gateway configuration.

For Opus 4.x models, the adapter intentionally avoids passing `temperature` unless explicitly configured for a non-Opus-4 model because newer Opus models reject classic sampling parameters. Configs commonly use `thinking: {type: adaptive}`, `output_config: {effort: high}`, and prompt caching fields.
