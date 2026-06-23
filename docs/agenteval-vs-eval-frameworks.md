# AgentEval vs DeepEval, promptfoo, Inspect, and Ragas

AgentEval is an artifact-first evaluation and governance harness for agent versions. It is not a replacement for every LLM evaluation framework; it is strongest when you need local/CI runs, normalized traces, regression mining, promotion gates, production replay, and RSI governance in one loop.

## Positioning summary

| Framework | Strong fit | AgentEval difference |
| --- | --- | --- |
| DeepEval | LLM application quality metrics, RAG-style judge metrics, unit-test-like evals. | AgentEval includes similar foundational judge metrics but centers run artifacts, adapter traces, CLI thresholds, promotion policy gates, production replay, and RSI governance. |
| promptfoo | Provider/model comparison, prompt assertions, red-team style prompt testing, broad YAML-driven testing. | AgentEval focuses more on agent adapters, `AgentRun` traces, tool/state/minefield evaluators, baseline/candidate governance, regression mining, and release decisions. |
| Inspect | Agentic evaluations, tool/sandbox tasks, security-oriented eval design, rich task definitions. | AgentEval is a lightweight Python CI/governance harness with durable JSONL/report artifacts, production trace replay, and recursive self-improvement safety checks. Inspect is stronger for sophisticated sandboxed eval task authoring. |
| Ragas | RAG evaluation metrics such as faithfulness, relevancy, context precision/recall. | AgentEval can run RAG metrics through built-in judge evaluators, then connect those results to traces, regressions, promotion policy, production feedback, and RSI governance. |

## When to choose AgentEval

Choose AgentEval when you need to:

- Evaluate an agent through a stable adapter contract (`static`, `anthropic`, `claude_code`, `langchain`, or plugin).
- Persist `manifest.json`, `traces.jsonl`, `results.jsonl`, `report.json`, Markdown, and HTML artifacts.
- Compare baseline/candidate runs and gate promotion by quality, safety, cost, latency, tag, capability, evaluator, or risk level.
- Mine failures into regression datasets and dedupe them into durable suites.
- Replay production or vendor traces without rerunning the original agent.
- Convert negative production feedback into regression candidates.
- Govern self-evolving / RSI agents with integrity, holdout, anti-gaming, memory, action-risk, red-team, and final decision reports.

## When to combine tools

These tools are complementary:

- Use DeepEval or Ragas metrics as additional evaluators when you need specialized LLM/RAG quality signals.
- Use promptfoo when you need broad provider/prompt matrix testing, then import selected failures as AgentEval regression cases.
- Use Inspect for rich sandboxed tasks or security eval suites, then mirror release-critical findings into AgentEval CI gates.
- Use AgentEval as the artifact and governance layer that turns eval results into release decisions, regressions, and audit trails.
