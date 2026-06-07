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


class RuleBasedUserSimulator:
    """Generates deterministic user replies from output/state matching rules."""

    def __init__(self, rules: list[dict]):
        self.rules = rules
        self.used: set[int] = set()

    @classmethod
    def from_case(cls, case: EvalCase) -> "RuleBasedUserSimulator | None":
        raw = case.scenario.get("user_simulator") or {}
        if raw.get("type") != "rule_based":
            return None
        return cls([rule for rule in raw.get("rules", []) or [] if isinstance(rule, dict)])

    def next_turn(self, assistant_output: str, state: dict) -> str | None:
        for index, rule in enumerate(self.rules):
            if index in self.used:
                continue
            when = rule.get("when") or {}
            if _rule_matches(when, assistant_output, state):
                self.used.add(index)
                return str(rule.get("reply", ""))
        return None


def _rule_matches(when: dict, assistant_output: str, state: dict) -> bool:
    output_contains = when.get("output_contains")
    if output_contains is not None and str(output_contains) not in assistant_output:
        return False
    state_matches = when.get("state_matches") or {}
    for path, expected in state_matches.items():
        from evaluators.matching import get_path, value_matches

        exists, actual = get_path(state, str(path))
        if not exists or not value_matches(expected, actual, "exact"):
            return False
    return True
