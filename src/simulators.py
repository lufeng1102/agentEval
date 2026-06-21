from __future__ import annotations

import inspect
import json
from typing import Any

from agents.anthropic_utils import extract_text, extract_usage
from schemas import ChatMessage, EvalCase, Usage


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

    def next_turn(self, assistant_output: str, state: dict, messages: list[ChatMessage] | None = None) -> str | None:
        for index, rule in enumerate(self.rules):
            if index in self.used:
                continue
            when = rule.get("when") or {}
            if _rule_matches(when, assistant_output, state):
                self.used.add(index)
                return str(rule.get("reply", ""))
        return None


class LLMUserSimulator:
    """Generates realistic user replies with an LLM for dynamic scenarios."""

    def __init__(self, config: dict[str, Any], client: Any | None = None):
        self.config = config
        self.client = client
        self.turn_index = 0

    @classmethod
    def from_case(cls, case: EvalCase, client: Any | None = None) -> "LLMUserSimulator | None":
        raw = case.scenario.get("user_simulator") or {}
        if raw.get("type") != "llm":
            return None
        return cls(raw, client=client)

    async def next_turn(self, assistant_output: str, state: dict, messages: list[ChatMessage] | None = None) -> dict[str, Any] | None:
        client = self.client or _default_anthropic_client()
        request = self._build_request(assistant_output, state, messages or [])
        try:
            response = await client.messages.create(**request)
        except Exception as exc:
            artifact = {
                "type": "llm",
                "turn_index": self.turn_index,
                "model": request["model"],
                "reply": "",
                "usage": Usage().model_dump(),
                "stop": True,
                "error": f"{exc.__class__.__name__}: {exc}",
            }
            self.turn_index += 1
            return {"reply": None, "usage": Usage(), "artifact": artifact}
        reply = extract_text(response.content)
        stop_phrases = {str(item).strip().lower() for item in self.config.get("stop_phrases", []) or []}
        normalized = reply.lower()
        usage = extract_usage(response)
        artifact = {
            "type": "llm",
            "turn_index": self.turn_index,
            "model": request["model"],
            "reply": reply,
            "usage": usage.model_dump(),
            "stop": not reply or normalized in stop_phrases,
        }
        self.turn_index += 1
        if artifact["stop"]:
            return {"reply": None, "usage": usage, "artifact": artifact}
        return {"reply": reply, "usage": usage, "artifact": artifact}

    def _build_request(self, assistant_output: str, state: dict, messages: list[ChatMessage]) -> dict[str, Any]:
        model = str(self.config.get("model") or "claude-opus-4-8")
        system = self.config.get("system") or "You simulate a realistic user in an AI agent evaluation. Reply only with the next user message. Do not explain your reasoning."
        payload = {
            "persona": self.config.get("persona"),
            "goal": self.config.get("goal"),
            "hidden_facts": self.config.get("hidden_facts") or {},
            "instructions": self.config.get("instructions"),
            "assistant_output": assistant_output,
            "current_state": state,
            "conversation": [message.model_dump(mode="json") for message in messages],
            "stop_phrases": self.config.get("stop_phrases") or [],
        }
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": int(self.config.get("max_tokens") or 512),
            "system": str(system),
            "messages": [
                {
                    "role": "user",
                    "content": "Generate the next user reply for this evaluation scenario. Return only the user reply text.\n\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True),
                }
            ],
        }
        if self.config.get("thinking"):
            request["thinking"] = self.config["thinking"]
        if self.config.get("output_config"):
            request["output_config"] = self.config["output_config"]
        return request


def build_user_simulator(case: EvalCase) -> RuleBasedUserSimulator | LLMUserSimulator | None:
    rule_based = RuleBasedUserSimulator.from_case(case)
    if rule_based is not None:
        return rule_based
    return LLMUserSimulator.from_case(case)


async def next_simulated_turn(simulator: Any, assistant_output: str, state: dict, messages: list[ChatMessage]) -> dict[str, Any]:
    if simulator is None:
        return {"reply": None, "usage": Usage(), "artifact": None}
    result = simulator.next_turn(assistant_output, state, messages)
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, dict):
        return {"reply": result.get("reply"), "usage": result.get("usage") or Usage(), "artifact": result.get("artifact")}
    return {"reply": result, "usage": Usage(), "artifact": None}


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


def _default_anthropic_client() -> Any:
    import anthropic

    return anthropic.AsyncAnthropic()
