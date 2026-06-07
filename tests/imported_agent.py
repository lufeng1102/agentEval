from __future__ import annotations

from schemas import AgentRun, EvalCase, RunContext


class ImportedAgent:
    def __init__(self, response: str = "imported ok"):
        self.response = response

    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        return AgentRun(case_id=case.id, final_output=self.response)


class TypeErrorAgent:
    async def run(self, case: EvalCase, context: RunContext) -> AgentRun:
        return AgentRun(case_id=case.id, final_output="typeerror fallback")


def build_agent(config):
    return ImportedAgent(config.agent.static_response or "factory ok")


def build_agent_without_config():
    return ImportedAgent("no config ok")


def build_agent_type_error(config):
    raise TypeError("factory exploded")
