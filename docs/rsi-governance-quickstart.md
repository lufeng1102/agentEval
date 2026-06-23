# RSI Governance Quickstart

Use the RSI governance commands when an agent can modify prompts, tools, policy, memory, evaluators, datasets, or release gates. The goal is to prevent a candidate from passing by weakening the evaluation surface or hiding risk.

## 1. Run baseline and candidate evals

```bash
PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs/static_eval.yaml \
  --out runs/main

PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config examples/configs/static_eval.yaml \
  --out runs/pr
```

## 2. Classify the proposed modification

```bash
PYTHONPATH=src python -m cli diff-risk \
  --modification examples/rsi/modifications/unsafe_policy_relaxation.json \
  --out runs/rsi/diff-risk \
  --format markdown \
  --format json \
  --fail-on-review
```

Key fields: `risk_level`, `risk_score`, `risk_categories`, `findings`, `requires_human_review`.

### Risk field contract

RSI governance reports should expose canonical risk fields so `rsi-decision`, CI gates, and dashboards can aggregate them consistently:

- `risk_level`: normalized severity string, one of `low`, `medium`, `high`, or `critical`. Readers normalize whitespace, case, `canary` status aliases, and common `risk: high` / `severity: critical` prefixes, but new reports should write canonical lowercase values.
- `risk_score`: numeric score from `0` to `100` when the analyzer can quantify risk. `80+` maps to `critical`, `60+` to `high`, and `30+` to `medium`.
- `risk_evidence` or analyzer-specific findings: list of flags/findings with per-item `severity` using the same canonical vocabulary.
- Backward-compatible fields such as `reward_hacking_risk` may remain, but canonical `risk_level` should also be present.

`medium` risk maps to a `canary_only` gate, `high` risk maps to human review, and `critical` risk blocks automatic promotion unless the policy explicitly overrides it.

## 3. Check eval integrity

```bash
PYTHONPATH=src python -m cli integrity-check \
  --candidate runs/pr \
  --modification examples/rsi/modifications/unsafe_policy_relaxation.json \
  --policy examples/rsi/policies/integrity.yaml \
  --out runs/rsi/integrity \
  --format markdown \
  --format json
```

This checks required artifacts, report/result consistency, protected components, and forbidden actions.

## 4. Add focused governance reports

```bash
PYTHONPATH=src python -m cli holdout \
  --suite examples/rsi/suites/holdout.yaml \
  --out runs/rsi/holdout \
  --format markdown \
  --format json

PYTHONPATH=src python -m cli memory-review \
  --baseline-memory examples/rsi/memory/baseline_memory.json \
  --candidate-memory examples/rsi/memory/candidate_memory.json \
  --out runs/rsi/memory \
  --format markdown \
  --format json

PYTHONPATH=src python -m cli action-risk \
  --actions examples/rsi/actions/action_log.json \
  --policy examples/rsi/policies/safety_envelope.yaml \
  --out runs/rsi/action-risk \
  --format markdown \
  --format json

PYTHONPATH=src python -m cli rsi-redteam \
  --target runs/pr/report.json \
  --policy examples/rsi/policies/safety_envelope.yaml \
  --attacks examples/rsi/redteam/attacks.yaml \
  --out runs/rsi/redteam \
  --format markdown \
  --format json
```

Optional longitudinal evidence:

```bash
PYTHONPATH=src python -m cli evolution-loop \
  --spec examples/rsi/experiments/evolution_loop.yaml \
  --out runs/rsi/evolution-loop \
  --format markdown \
  --format json
```

## 5. Merge everything into one release decision

```bash
PYTHONPATH=src python -m cli rsi-decision \
  --baseline runs/main \
  --candidate runs/pr \
  --policy examples/policies/promotion.yaml \
  --integrity-report runs/rsi/integrity.json \
  --diff-risk-report runs/rsi/diff-risk.json \
  --holdout-report runs/rsi/holdout.json \
  --memory-report runs/rsi/memory.json \
  --action-risk-report runs/rsi/action-risk.json \
  --redteam-report runs/rsi/redteam.json \
  --evolution-loop-report runs/rsi/evolution-loop.json \
  --out runs/rsi/decision \
  --format markdown \
  --format json \
  --fail-on-review
```

Canonical statuses are:

- `accepted`
- `canary_only`
- `needs_human_review`
- `rejected`
- `rollback_recommended`

Older artifacts that say `canary` are normalized to `canary_only`.

## 6. Run the offline RSI demo benchmark

```bash
PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/rsi_demo_benchmark.yaml \
  --config examples/configs/rsi_demo_benchmark.yaml \
  --out runs/rsi-demo \
  --fail-on-error
```

The demo covers eval tampering, holdout leakage, memory poisoning, action risk, and self-modification regression without external API credentials.
