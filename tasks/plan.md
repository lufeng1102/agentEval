# Implementation Plan: AgentEval Maturity Roadmap

## Overview

AgentEval already has a strong v0.1/v0.2 core: YAML datasets/configs, agent adapters, runner, evaluators, reports, CI thresholds, evolution diagnostics, production feedback, human review, and RSI governance modules. The next milestone should stabilize and productize the platform rather than add another broad feature.

This plan focuses on a P0/P1 maturity increment: governance hardening, protocol stability, provider readiness, CLI maintainability, extension contracts, policy-driven RSI release decisions, and lightweight trends/dashboard visibility.

## Assumptions

- Scope is the next maturity milestone for this repository, not a full rewrite.
- Priority is reliability/productization over adding new evaluator types.
- Backwards compatibility matters for existing examples/tests unless a deliberate migration is approved.
- Work should be sliced vertically so each task leaves a usable CLI path and passing tests.
- Existing command behavior should remain stable unless explicitly called out in a task.

## Current Structure

- `src/cli.py` — monolithic Typer CLI, currently registers all commands.
- `src/schemas.py` — core run/dataset/result contracts.
- `src/config.py` — YAML config model and dataset loading.
- `src/runners/executor.py` — execution, retries, repeats, traces/results.
- `src/agents/` — static, Anthropic, Claude Code, import/plugin adapters.
- `src/evaluators/` — deterministic, environment, judge, cost, trajectory evaluators.
- `src/reporters/` — JSON/Markdown/HTML report generation.
- `src/evolution/` — comparisons, diagnosis, regressions, suite health, pairwise, PR summary.
- `src/production/` — production events, feedback, coverage, regression conversion.
- `src/review/` — human review queue/import/calibration.
- `src/rsi/` — RSI governance analyzers and release decision support.
- `.github/workflows/agenteval.yml` — pytest + static AgentEval smoke CI.
- `examples/` — representative datasets/configs/policies/production/review samples.

## Dependency Graph

```text
Protocol contracts
  ├── Dataset/config schema versioning
  │     ├── Dataset/config loaders
  │     ├── CLI validate/run behavior
  │     ├── Examples and docs
  │     └── Tests for backwards compatibility
  │
  ├── Report/trace/manifest versioning
  │     ├── Reporters
  │     ├── Compare/matrix/evolution consumers
  │     ├── RSI/integrity consumers
  │     └── CI artifacts
  │
  └── Plugin contracts
        ├── Agent adapter factory
        ├── Evaluator factory
        ├── Plugin examples/tests
        └── Docs

CLI command layer
  ├── Shared output/format helpers
  ├── Command modules by domain
  │     ├── core run/validate/html/compare/matrix
  │     ├── review/production
  │     ├── evolution/promotion
  │     └── RSI governance
  └── Existing app registration and tests

Provider readiness
  ├── Config loading
  ├── Agent adapter construction
  ├── Anthropic/Claude Code compatibility checks
  └── CLI health command and docs

Suite governance
  ├── Dataset metadata and review dates
  ├── Run artifact loading
  ├── Production coverage integration
  ├── Human review integration
  └── Suite health reports/thresholds

Policy-driven release governance
  ├── Existing promotion and RSI reports
  ├── Policy schema
  ├── Decision engine
  ├── Evidence links
  └── CLI/report outputs
```

Implementation should start with low-risk governance hardening and protocol scaffolding before larger CLI refactors. This keeps the project shippable after each phase.

## Architecture Decisions

- **Vertical slices over horizontal rewrites:** Each task should ship one complete user-facing improvement: command behavior, tests, docs, and examples where applicable.
- **Add version fields compatibly:** Existing datasets/configs without explicit schema versions should continue to load as v1 with implicit defaults, not break immediately.
- **Keep `src/cli.py` registration stable at first:** Extract command modules gradually after shared helper contracts are stable.
- **Use existing artifacts:** Suite health, provider checks, and policy decisions should consume existing `manifest.json`, `report.json`, `traces.jsonl`, `results.jsonl`, human review, and production artifacts rather than inventing new artifact formats first.
- **Test live-provider behavior without requiring live credentials in CI:** Provider health check should support deterministic/static checks and mockable Anthropic/Claude Code paths.

## Phase 1: Planning and Governance Baseline

### Task 1: Create repository planning artifacts

**Description:** Save this roadmap into repository-owned planning files so it survives session boundaries and can be reviewed/edited alongside code.

**Acceptance criteria:**
- [ ] `tasks/plan.md` exists and contains the roadmap, dependency graph, phases, risks, and checkpoints.
- [ ] `tasks/todo.md` exists and contains a concise ordered checklist of tasks with dependencies.
- [ ] The files do not claim implementation is complete; they are planning artifacts only.

**Verification:**
- [ ] `test -f tasks/plan.md && test -f tasks/todo.md`
- [ ] Manual review: tasks are vertically sliced and each has acceptance/verification.

**Dependencies:** None

**Files likely touched:**
- `tasks/plan.md`
- `tasks/todo.md`

**Estimated scope:** Small: 2 files

### Task 2: Harden `suite-health` as the first governance slice

**Description:** Complete the recently added suite health command by addressing the highest-value correctness and lifecycle gaps: respect `stale_days`, avoid reporting run-history cases not present in the audited dataset, and document the review-date format.

**Acceptance criteria:**
- [ ] High-risk cases with stale `metadata.last_reviewed_at` are flagged according to `--stale-days`.
- [ ] Run-history saturation/flakiness/regression issues are generated only for case IDs present in the audited dataset.
- [ ] Invalid or unparseable review dates produce a clear suite-health issue rather than crashing.
- [ ] README documents accepted `last_reviewed_at` format and semantics.

**Verification:**
- [ ] `python -m pytest tests/test_suite_health.py tests/test_suite_health_cli.py`
- [ ] `PYTHONPATH=src python -m cli suite-health --dataset examples/datasets/basic_agent_eval.yaml --out runs/suite-health.md --format markdown --format json`

**Dependencies:** Task 1 preferred, but not technically required

**Files likely touched:**
- `src/evolution/suite_health.py`
- `tests/test_suite_health.py`
- `tests/test_suite_health_cli.py`
- `README.md`

**Estimated scope:** Medium: 4 files

### Checkpoint: Governance Baseline

- [ ] Suite health tests pass.
- [ ] Existing static AgentEval smoke run still passes.
- [ ] Planning artifacts exist.
- [ ] Human reviews whether suite-health semantics match intended governance policy.

## Phase 2: Protocol Stability

### Task 3: Add explicit schema-version constants and compatible defaults

**Description:** Introduce stable version identifiers for dataset/config/report/trace/manifest contracts without breaking existing examples.

**Acceptance criteria:**
- [ ] Dataset loading accepts missing `schema_version` as the current default version.
- [ ] Config loading accepts missing `schema_version` as the current default version.
- [ ] New manifests/reports include explicit schema/protocol version fields.
- [ ] Unsupported future/unknown versions fail with actionable errors.

**Verification:**
- [ ] `python -m pytest tests/test_dataset_loader.py tests/test_config_schema_edges.py tests/test_manifest.py tests/test_reporters.py`
- [ ] `PYTHONPATH=src python -m cli validate --dataset examples/datasets/basic_agent_eval.yaml --config examples/configs/static_eval.yaml`
- [ ] Inspect generated `runs/latest/manifest.json` and `runs/latest/report.json` after smoke run.

**Dependencies:** Task 2

**Files likely touched:**
- `src/schemas.py`
- `src/config.py`
- `src/manifest.py`
- `src/reporters/json_reporter.py`
- relevant tests under `tests/`

**Estimated scope:** Medium: 4-5 files

### Task 4: Document protocol contracts

**Description:** Add concise protocol documents for dataset, config, report, trace, and manifest v1 so third-party users know what is stable.

**Acceptance criteria:**
- [ ] `docs/protocols/dataset-v1.md` documents required/optional fields and compatibility behavior.
- [ ] `docs/protocols/config-v1.md` documents agent/runner/evaluator/report config.
- [ ] `docs/protocols/artifacts-v1.md` documents manifest/traces/results/report artifacts.
- [ ] README links to the protocol docs from the architecture/protocol section.

**Verification:**
- [ ] Manual docs review: examples match actual YAML/report artifacts.
- [ ] `python -m pytest` remains green.

**Dependencies:** Task 3

**Files likely touched:**
- `docs/protocols/dataset-v1.md`
- `docs/protocols/config-v1.md`
- `docs/protocols/artifacts-v1.md`
- `README.md`

**Estimated scope:** Medium: 4 files

### Checkpoint: Protocol Baseline

- [ ] All existing examples load without migration.
- [ ] New reports/manifests carry version metadata.
- [ ] Protocol docs reviewed by human.
- [ ] Full test suite passes: `python -m pytest`.

## Phase 3: Provider Readiness and Operational Reliability

### Task 5: Add provider health check command

**Description:** Add a `provider-check` CLI path that validates agent provider configuration before users run expensive or long evals.

**Acceptance criteria:**
- [ ] `provider-check --config <config>` loads config and reports provider, model, credentials/config presence, and known parameter compatibility.
- [ ] Static provider check passes offline.
- [ ] Anthropic provider check can run in non-live mode without requiring API calls.
- [ ] Optional live mode is explicit and fails clearly when credentials/model/channel are unavailable.

**Verification:**
- [ ] `python -m pytest tests/test_provider_check_cli.py` or equivalent new tests.
- [ ] `PYTHONPATH=src python -m cli provider-check --config examples/configs/static_eval.yaml`
- [ ] `PYTHONPATH=src python -m cli provider-check --config examples/configs/claude_eval.yaml --no-live` or chosen flag name.

**Dependencies:** Task 3 preferred

**Files likely touched:**
- `src/cli.py` or new command module if extraction starts
- `src/agents/claude_adapter.py`
- `src/agents/claude_code_adapter.py`
- `tests/test_provider_check_cli.py`
- `README.md`

**Estimated scope:** Medium: 4-5 files

### Task 6: Standardize command output format validation

**Description:** Reduce repeated output-format and threshold validation logic by centralizing common CLI output helpers and applying them to one complete command family first.

**Acceptance criteria:**
- [ ] A shared helper validates `markdown`/`json` aliases consistently.
- [ ] At least suite-health and one existing evolution/report command use the shared helper.
- [ ] Invalid format/threshold values are rejected before report files are written for touched commands.
- [ ] Tests cover no-side-effect validation for invalid options.

**Verification:**
- [ ] `python -m pytest tests/test_suite_health_cli.py tests/test_evolution_cli.py` or relevant command tests.
- [ ] Manual CLI check with an invalid `--format` confirms no output file is created.

**Dependencies:** Task 2 recommended

**Files likely touched:**
- `src/cli.py` or `src/commands/common.py`
- `tests/test_suite_health_cli.py`
- one existing command test file

**Estimated scope:** Small/Medium: 3 files

### Checkpoint: Operational Baseline

- [ ] Provider check works for static and non-live Claude configs.
- [ ] Touched commands validate before writing outputs.
- [ ] Static CI smoke still passes.
- [ ] Human reviews provider-check semantics before adding live-mode behavior to CI.

## Phase 4: CLI Modularization Without Behavior Changes

### Task 7: Extract one command family into a module

**Description:** Begin shrinking `src/cli.py` by moving one low-risk command family, preferably suite-health or review commands, into a command module while preserving the Typer app interface.

**Acceptance criteria:**
- [ ] Existing command name, options, help text, and output behavior are preserved.
- [ ] `src/cli.py` delegates registration to the new module.
- [ ] Existing tests for the command family pass without changes except import path updates if necessary.

**Verification:**
- [ ] `python -m pytest tests/test_suite_health_cli.py` or selected command family tests.
- [ ] `PYTHONPATH=src python -m cli --help` shows the moved commands.
- [ ] `PYTHONPATH=src python -m cli suite-health --help` still works if suite-health is selected.

**Dependencies:** Task 6

**Files likely touched:**
- `src/cli.py`
- `src/commands/__init__.py`
- `src/commands/suite_health.py` or selected family module
- relevant tests

**Estimated scope:** Medium: 3-4 files

### Task 8: Extract remaining command families in small groups

**Description:** Continue modularization by moving commands by domain: core, production/review, evolution/promotion, RSI. Do this in multiple commits/sessions if needed.

**Acceptance criteria:**
- [ ] `src/cli.py` becomes mostly app creation and command registration.
- [ ] Command modules map to existing domain boundaries.
- [ ] All existing command tests pass.
- [ ] No command names or option names are changed unintentionally.

**Verification:**
- [ ] `python -m pytest tests/test_cli.py tests/test_production_cli.py tests/test_review_cli.py tests/test_evolution_cli.py tests/test_rsi_cli.py tests/test_matrix_cli.py tests/test_pairwise_cli.py`
- [ ] `PYTHONPATH=src python -m cli --help`

**Dependencies:** Task 7

**Files likely touched:**
- `src/cli.py`
- `src/commands/*.py`
- selected CLI tests if import setup changes

**Estimated scope:** Large overall; split into multiple Medium subtasks by command family before implementation.

### Checkpoint: CLI Baseline

- [ ] Full CLI test subset passes.
- [ ] `src/cli.py` no longer owns domain-specific business logic beyond registration/shared callbacks.
- [ ] Human spot-checks help output for key commands.

## Phase 5: Platform Extension Contracts

### Task 9: Formalize plugin contracts for agents and evaluators

**Description:** Turn the existing import/plugin behavior into documented, tested contracts for external agent adapters and evaluators.

**Acceptance criteria:**
- [ ] Docs describe how to implement an external agent adapter returning `AgentRun`.
- [ ] Docs describe how to implement an external evaluator returning `EvalResult`.
- [ ] Example plugin module demonstrates both contracts.
- [ ] Tests verify plugin loading errors are actionable.

**Verification:**
- [ ] `python -m pytest tests/test_import_agent.py tests/test_plugin_evaluator.py`
- [ ] Manual docs review against example plugin code.

**Dependencies:** Task 3 and Task 4 recommended

**Files likely touched:**
- `docs/plugins.md`
- `examples/plugins/` or `examples/agents/`
- `tests/test_import_agent.py`
- `tests/test_plugin_evaluator.py`
- possibly `src/evaluators/__init__.py` / adapter factory code

**Estimated scope:** Medium: 4-5 files

### Task 10: Add onboarding docs for the main user journeys

**Description:** Create concise, path-oriented docs so new users can run their first eval, add an adapter/evaluator, wire CI, and understand evolution/RSI workflows without reading the full README.

**Acceptance criteria:**
- [ ] `docs/getting-started.md` runs a static eval end-to-end.
- [ ] `docs/evaluate-your-agent.md` explains static, Anthropic, Claude Code, and import/plugin paths.
- [ ] `docs/ci-gates.md` explains thresholds and GitHub Actions.
- [ ] `docs/evolution-workflow.md` explains compare/failures/regressions/promote.
- [ ] `docs/rsi-governance.md` explains governance commands and release decision flow.
- [ ] README links these docs prominently.

**Verification:**
- [ ] Commands in getting-started are copy/paste runnable.
- [ ] `python -m pytest` remains green.

**Dependencies:** Task 4 and Task 9 preferred

**Files likely touched:**
- `docs/getting-started.md`
- `docs/evaluate-your-agent.md`
- `docs/ci-gates.md`
- `docs/evolution-workflow.md`
- `docs/rsi-governance.md`
- `README.md`

**Estimated scope:** Medium: docs-only but 5+ files; can split by journey.

### Checkpoint: Platform Usability

- [ ] A new user can complete the getting-started path.
- [ ] Plugin contracts are clear enough to implement without reading internals.
- [ ] Human reviews docs for accuracy and target audience.

## Phase 6: Policy-Driven RSI Governance

### Task 11: Add a policy engine for RSI release decisions

**Description:** Generalize release decisions so promotion and RSI analyzer outputs can be combined by a YAML policy with blocking, warning, and human-review gates.

**Acceptance criteria:**
- [ ] Policy model supports `block_if`, `require_human_review_if`, and `warn_if` rules over existing report fields.
- [ ] `rsi-decision` can consume the policy and produce evidence for each triggered rule.
- [ ] Default policy preserves current behavior as much as possible.
- [ ] Tests cover accepted, rejected, warning, and human-review outcomes.

**Verification:**
- [ ] `python -m pytest tests/test_rsi_decision_explainer.py tests/test_rsi_cli.py`
- [ ] `PYTHONPATH=src python -m cli rsi-decision ...` using existing example artifacts/policies, adjusted as needed.

**Dependencies:** Task 3, Task 4, and CLI modularization preferred

**Files likely touched:**
- `src/rsi/decision_explainer.py`
- `src/rsi/models.py`
- `src/cli.py` or `src/commands/rsi.py`
- `examples/rsi/` or `examples/policies/`
- relevant tests

**Estimated scope:** Medium/Large; split if rule parser and CLI integration grow beyond 5 files.

### Task 12: Add evidence links and artifact completeness checks to RSI decisions

**Description:** Make RSI decision outputs more auditable by linking each gate to source artifact paths/sections and checking that required artifacts exist.

**Acceptance criteria:**
- [ ] Decision output lists source artifact paths for promotion, integrity, envelope, holdout, anti-gaming, and other inputs.
- [ ] Missing required artifacts produce explicit decision evidence and can block according to policy.
- [ ] Markdown and JSON reports include the evidence chain.

**Verification:**
- [ ] `python -m pytest tests/test_rsi_decision_explainer.py tests/test_rsi_integrity.py`
- [ ] Manual inspection of generated RSI decision markdown.

**Dependencies:** Task 11

**Files likely touched:**
- `src/rsi/decision_explainer.py`
- `src/rsi/integrity.py`
- RSI report writers/tests

**Estimated scope:** Medium: 3-5 files

### Checkpoint: RSI Governance Baseline

- [ ] RSI decision is policy-driven, explainable, and evidence-linked.
- [ ] Missing artifacts are handled explicitly.
- [ ] Human reviews default governance policy before using it as a release gate.

## Phase 7: Trends and Lightweight Dashboard

### Task 13: Add run-history trend summaries

**Description:** Build a lightweight trend analyzer over existing run directories to summarize pass rate, score, latency, cost/token, flaky count, and suite-health trends.

**Acceptance criteria:**
- [ ] Analyzer reads multiple run directories without rerunning agents.
- [ ] JSON/Markdown output includes trend rows sorted by run timestamp/name.
- [ ] Missing optional metrics are handled gracefully.
- [ ] Tests cover mixed old/new reports.

**Verification:**
- [ ] `python -m pytest tests/test_trends_cli.py` or equivalent.
- [ ] `PYTHONPATH=src python -m cli trends --runs runs --out runs/trends.md --format markdown --format json`

**Dependencies:** Task 3 recommended

**Files likely touched:**
- `src/evolution/trends.py` or `src/reporters/trends.py`
- CLI command module
- tests
- README/docs

**Estimated scope:** Medium: 4 files

### Task 14: Extend static dashboard with trend and governance cards

**Description:** Improve the existing dashboard path into a more useful static HTML report that surfaces trend and governance signals.

**Acceptance criteria:**
- [ ] Dashboard shows latest pass rate, avg score, failures, latency, tokens, and errors as it does today.
- [ ] Dashboard includes trend deltas when trend data is available.
- [ ] Dashboard links to suite-health, promotion, and RSI decision artifacts when present.
- [ ] Tests verify HTML contains core cards/links.

**Verification:**
- [ ] `python -m pytest tests/test_flakes_dashboard_cli.py` plus new dashboard tests.
- [ ] `PYTHONPATH=src python -m cli dashboard --runs runs --out runs/dashboard.html`

**Dependencies:** Task 13

**Files likely touched:**
- dashboard command/module
- tests
- README/docs

**Estimated scope:** Medium: 3-5 files

### Checkpoint: Visibility Baseline

- [ ] Trends and dashboard work without external services.
- [ ] Outputs are useful enough for CI artifacts and human review.
- [ ] Human reviews dashboard information hierarchy.

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| CLI extraction breaks command behavior | High | Extract one command family first; compare help output and run existing CLI tests. |
| Schema versioning breaks existing examples | High | Treat missing versions as current v1; add compatibility tests before docs. |
| Provider health check accidentally calls live APIs in CI | Medium | Default to non-live checks; make live mode explicit and marked/skippable. |
| RSI policy engine becomes too general/complex | Medium | Start with simple field-path predicates and existing report inputs only. |
| Docs drift from code | Medium | Keep docs command examples tied to existing examples and smoke-test manually. |
| Trend/dashboard scope expands into a full web app | Medium | Keep first version static and artifact-based. |

## Open Questions

- Should this roadmap target a named release such as `v0.2 AgentEval Core`, or remain an internal task plan?
- Should CLI modularization happen before or after schema versioning if reducing `src/cli.py` size is the immediate pain point?
- Should provider health check support only Anthropic/Claude Code initially, or also plugin/import adapters?
- Should RSI policy use a small custom predicate syntax or a standard expression language?
- Should `tasks/plan.md` and `tasks/todo.md` be committed as long-lived project planning artifacts?

## Baseline Verification Commands

```bash
python -m pytest
PYTHONPATH=src python -m cli validate \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs/static_eval.yaml
PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs/static_eval.yaml \
  --out runs/latest \
  --min-pass-rate 0.5 \
  --min-score 0.5 \
  --fail-on-error
```
