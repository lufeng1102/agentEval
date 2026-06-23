# P3 Phase 0 Implementation Status

## Status

Phase 0 skeleton is implemented for the main P3 foundation blocks.

## Implemented blocks

| Block | Status | Files |
|---|---|---|
| Adapter contract | Implemented | `src/adapters/contract.py`, `src/adapters/conformance.py` |
| Claude Code contract metadata | Implemented | `src/agents/claude_code_adapter.py` |
| SDK instrumentation | Implemented skeleton | `src/instrumentation/` |
| External export | Implemented skeleton | `src/exports/` |
| Dashboard local data layer | Implemented skeleton | `src/dashboard/data.py` |
| Alerts MVP | Implemented skeleton | `src/alerts/` |
| Hosted ingestion | Implemented skeleton | `src/hosted/` |
| CLI export | Implemented | `python -m cli export <target>` |
| CLI upload | Implemented local hosted storage | `python -m cli upload --run <dir> --storage <dir>` |

## CLI commands

### Export

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

### Upload to local hosted storage

```bash
PYTHONPATH=src python -m cli upload \
  --run runs/latest \
  --storage runs/hosted \
  --project-id default
```

## Test coverage

| Area | Tests |
|---|---|
| Adapter contract | `tests/adapters/test_contract_conformance.py` |
| Claude Code adapter | `tests/test_claude_code_adapter.py` |
| SDK instrumentation | `tests/instrumentation/test_sdk_tracer.py` |
| Export | `tests/exports/test_exporters.py` |
| Dashboard data layer | `tests/dashboard/test_dashboard_data.py` |
| Alerts | `tests/alerts/test_alert_rules.py` |
| Hosted ingestion | `tests/hosted/test_ingestion.py` |
| Integration | `tests/test_p3_phase0_integration.py` |

## Current limitations

- Framework-specific adapters for LangChain, AutoGen, CrewAI, and OpenAI Agents SDK are not implemented yet.
- SDK instrumentation is local JSONL only; hosted upload is not wired into tracer yet.
- Export formats are compatible skeletons, not official direct API push connectors.
- Dashboard is a data layer skeleton, not a served interactive web UI.
- Hosted mode is local artifact storage/indexing, not a network API server.
- Alerts support rule evaluation and webhook delivery skeleton, but no persisted alert rule store or worker yet.

## Recommended next steps

1. Add LangChain adapter MVP using adapter contract and conformance tests.
2. Add served local dashboard command on top of `LocalRunDataSource`.
3. Add hosted API server wrapper around `HostedIngestionService`.
4. Add webhook alert CLI/worker integration.
5. Add official export schema fixtures for Langfuse/Phoenix/Braintrust compatibility checks.
