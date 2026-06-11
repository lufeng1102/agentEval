# AgentEval Maturity TODO

## Phase 1: Planning and Governance Baseline

- [x] Task 1: Create repository planning artifacts
  - Acceptance: `tasks/plan.md` and `tasks/todo.md` exist and contain the reviewed roadmap.
  - Verify: `test -f tasks/plan.md && test -f tasks/todo.md`
  - Dependencies: None

- [ ] Task 2: Harden suite-health governance slice
  - Acceptance: stale high-risk reviews are flagged; run-history issues ignore cases outside the audited dataset; invalid review dates produce clear issues; README documents review-date semantics.
  - Verify: `python -m pytest tests/test_suite_health.py tests/test_suite_health_cli.py`
  - Dependencies: Task 1

- [ ] Checkpoint: Governance Baseline
  - Verify: suite health tests pass; static AgentEval smoke run passes; planning artifacts exist; human reviews suite-health semantics.

## Phase 2: Protocol Stability

- [ ] Task 3: Add explicit schema-version constants and compatible defaults
  - Acceptance: missing dataset/config versions default to current v1; new manifests/reports include protocol versions; unknown versions fail clearly.
  - Verify: `python -m pytest tests/test_dataset_loader.py tests/test_config_schema_edges.py tests/test_manifest.py tests/test_reporters.py`
  - Dependencies: Task 2

- [ ] Task 4: Document protocol contracts
  - Acceptance: dataset/config/artifact v1 docs exist and README links them.
  - Verify: manual docs review plus `python -m pytest`
  - Dependencies: Task 3

- [ ] Checkpoint: Protocol Baseline
  - Verify: existing examples load; reports/manifests carry version metadata; protocol docs reviewed; full test suite passes.

## Phase 3: Provider Readiness and Operational Reliability

- [ ] Task 5: Add provider health check command
  - Acceptance: `provider-check --config` reports provider/model/config readiness; static passes offline; Anthropic non-live mode does not require API calls; live mode is explicit.
  - Verify: `python -m pytest tests/test_provider_check_cli.py` and manual static/non-live CLI checks.
  - Dependencies: Task 3 preferred

- [ ] Task 6: Standardize command output format validation
  - Acceptance: shared format helper is used by suite-health and one existing command; invalid values are rejected before output files are written.
  - Verify: relevant CLI tests and manual invalid-format no-side-effect check.
  - Dependencies: Task 2 recommended

- [ ] Checkpoint: Operational Baseline
  - Verify: provider check works; touched commands validate before writing; static CI smoke passes; human reviews provider-check semantics.

## Phase 4: CLI Modularization

- [ ] Task 7: Extract one command family into a module
  - Acceptance: selected command names/options/help/output stay stable; `src/cli.py` delegates registration to a new module.
  - Verify: selected CLI tests plus `PYTHONPATH=src python -m cli --help` and selected command `--help`.
  - Dependencies: Task 6

- [ ] Task 8: Extract remaining command families in small groups
  - Acceptance: `src/cli.py` is mostly app creation/registration; command modules map to domains; no accidental command API changes.
  - Verify: CLI test subset for core, production, review, evolution, RSI, matrix, pairwise.
  - Dependencies: Task 7

- [ ] Checkpoint: CLI Baseline
  - Verify: full CLI test subset passes; human spot-checks key help output.

## Phase 5: Platform Extension Contracts

- [ ] Task 9: Formalize plugin contracts for agents and evaluators
  - Acceptance: plugin docs and examples cover external agent adapters and evaluators; plugin loading errors are actionable.
  - Verify: `python -m pytest tests/test_import_agent.py tests/test_plugin_evaluator.py`
  - Dependencies: Tasks 3 and 4 recommended

- [ ] Task 10: Add onboarding docs for main user journeys
  - Acceptance: docs cover getting started, evaluating an agent, CI gates, evolution workflow, and RSI governance; README links them.
  - Verify: copy/paste runnable getting-started commands and `python -m pytest`.
  - Dependencies: Tasks 4 and 9 preferred

- [ ] Checkpoint: Platform Usability
  - Verify: new-user path works; plugin contracts are understandable; human reviews docs.

## Phase 6: Policy-Driven RSI Governance

- [ ] Task 11: Add RSI release policy engine
  - Acceptance: YAML policy supports blocking, warning, and human-review gates over existing report fields; `rsi-decision` emits evidence for triggered rules.
  - Verify: `python -m pytest tests/test_rsi_decision_explainer.py tests/test_rsi_cli.py`
  - Dependencies: Tasks 3, 4, and CLI modularization preferred

- [ ] Task 12: Add evidence links and artifact completeness checks
  - Acceptance: RSI decision outputs source artifact paths/sections; missing required artifacts produce explicit evidence and can block by policy.
  - Verify: RSI decision/integrity tests and manual markdown inspection.
  - Dependencies: Task 11

- [ ] Checkpoint: RSI Governance Baseline
  - Verify: RSI decision is policy-driven, explainable, and evidence-linked; human reviews default governance policy.

## Phase 7: Trends and Dashboard

- [ ] Task 13: Add run-history trend summaries
  - Acceptance: trend analyzer reads run directories without rerunning agents; JSON/Markdown include pass rate, score, latency, token/cost, flaky, and suite-health trends where available.
  - Verify: trend CLI tests and manual `trends --runs runs` command.
  - Dependencies: Task 3 recommended

- [ ] Task 14: Extend static dashboard with trend and governance cards
  - Acceptance: dashboard preserves current metrics, adds trend deltas when available, and links suite-health/promotion/RSI artifacts when present.
  - Verify: dashboard tests and manual `dashboard --runs runs` command.
  - Dependencies: Task 13

- [ ] Checkpoint: Visibility Baseline
  - Verify: trends/dashboard work without external services and are useful as CI artifacts.
