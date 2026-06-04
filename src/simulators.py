from __future__ import annotations

from schemas import ChatMessage, EvalCase


class ScriptedUserSimulator:
    """Builds a deterministic multi-turn message list from scripted user turns."""

    def __init__(self, turns: list[str]):
        self.turns = turns

    @classmethod
    def from_case(cls, case: EvalCase) -> "ScriptedUserSimulator | None":
        raw = case.scenario.get("user_simulator") or case.expected.get("user_simulator")
        if not raw or raw.get("type") != "scripted":
            return None
        return cls([str(turn) for turn in raw.get("turns", [])])

    def messages(self, initial: str | list[ChatMessage]) -> list[ChatMessage]:
        if isinstance(initial, str):
            messages = [ChatMessage(role="user", content=initial)]
        else:
            messages = list(initial)
        messages.extend(ChatMessage(role="user", content=turn) for turn in self.turns)
        return messages
