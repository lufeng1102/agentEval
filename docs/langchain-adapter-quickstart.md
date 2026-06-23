# LangChain Adapter Quickstart

Use the `langchain` provider to evaluate a LangChain-compatible runnable, chain, agent executor, or plain Python factory through the AgentEval adapter contract. The adapter does not require LangChain as a hard dependency; it only needs an importable object with a supported invocation shape.

## 1. Expose a runnable factory

```python
# my_package/langchain_app.py

def build_runnable(config=None):
    class Runnable:
        def invoke(self, payload):
            return {
                "output": f"answer: {payload['input']}",
                "intermediate_steps": [
                    {"tool": "search", "input": {"query": payload["input"]}, "output": {"hits": 1}},
                ],
            }

    return Runnable()
```

Supported shapes:

- `ainvoke(payload)`
- `invoke(payload)`
- async callable
- plain callable

## 2. Configure AgentEval

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
  - type: trajectory

report:
  formats: [json, markdown]
```

Options:

- `input_key`: payload key for the case input. Default: `input`.
- `output_key`: preferred response key for final output. Default: `output`.
- `raw_input: true`: pass the string/message input directly instead of wrapping it in a dict.
- `invoke_kwargs`: extra payload keys merged into each call.

## 3. Run the eval

```bash
PYTHONPATH=src python -m cli run \
  --dataset examples/datasets/basic_agent_eval.yaml \
  --config path/to/langchain_eval.yaml \
  --out runs/langchain
```

## 4. Response mapping

The adapter maps common fields into AgentEval contracts:

| Runnable response field | AgentEval output |
| --- | --- |
| `output`, `result`, `answer`, `content` | `AgentRun.final_output` |
| `intermediate_steps`, `steps`, `tool_calls` | `AgentRun.tool_calls` |
| `spans` | `AgentRun.spans` |
| full response | `AgentRun.raw_response` |
| adapter metadata | `AgentRun.artifacts.adapter` |

Returned spans can use kinds such as `chain`, `tool`, `retrieval`, `llm`, or `custom`. Tool calls are normalized to `ToolCall(name, input, output, error)`.

## 5. Test fixture reference

See the repository's local fixtures for working examples:

- `tests/fake_langchain_app.py`
- `tests/test_langchain_adapter.py`

These cover sync runnables, async runnables, plain callables, tool-call mapping, span mapping, error recording, and CLI integration.
