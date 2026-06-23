class FakeRunnable:
    def invoke(self, payload):
        return {
            "output": f"langchain answer: {payload['input']}",
            "intermediate_steps": [
                {"tool": "search", "input": {"query": payload["input"]}, "output": {"hits": 1}},
            ],
        }


class FakeAsyncRunnable:
    async def ainvoke(self, payload):
        return {
            "answer": "async answer",
            "spans": [
                {"span_id": "root", "name": "chain", "kind": "chain"},
                {"span_id": "retrieval", "parent_span_id": "root", "name": "retriever", "kind": "retrieval", "output": {"docs": 1}},
            ],
        }


def build_runnable(config=None):
    return FakeRunnable()


def build_async_runnable(config=None):
    return FakeAsyncRunnable()


def build_callable(config=None):
    def run(payload):
        return {"content": f"callable: {payload['question']}", "tool_calls": [{"name": "lookup", "input": {"id": 1}, "output": "ok"}]}

    return run


def build_failing(config=None):
    def run(payload):
        raise RuntimeError("langchain boom")

    return run
