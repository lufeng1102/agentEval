from __future__ import annotations

from schemas import AgentRun, EvalCase, RunContext


class ImportedAgent:
    def __init__(self, response: str = "imported ok"):
        self.response = response

    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        return AgentRun(case_id=case.id, final_output=self.response)


class EnvironmentEditingAgent:
    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        root = context.environment["root"] if context.environment else None
        if root:
            from pathlib import Path

            path = Path(root) / str(case.metadata.get("edit_path", "src/auth.py"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(case.metadata.get("edit_content", "fixed")), encoding="utf-8")
        return AgentRun(case_id=case.id, final_output="edited environment")


class EnvironmentForbiddenAgent:
    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        root = context.environment["root"] if context.environment else None
        if root:
            from pathlib import Path

            path = Path(root) / "tests/hidden.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("tampered", encoding="utf-8")
        return AgentRun(case_id=case.id, final_output="edited forbidden path")


class TypeErrorAgent:
    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        return AgentRun(case_id=case.id, final_output="typeerror fallback")


def build_agent(config):
    return ImportedAgent(config.agent.static_response or "factory ok")


def build_environment_agent(config):
    return EnvironmentEditingAgent()


def build_forbidden_environment_agent(config):
    return EnvironmentForbiddenAgent()


def build_agent_without_config():
    return ImportedAgent("no config ok")


def build_agent_type_error(config):
    raise TypeError("factory exploded")
