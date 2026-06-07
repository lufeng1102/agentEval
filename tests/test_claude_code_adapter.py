from pathlib import Path

from agents.claude_code_adapter import ClaudeCodeAgentAdapter
from config import AgentConfig
from schemas import ChatMessage, EvalCase, RunContext


class FakeCompletedProcess:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeRunner:
    def __init__(self, result: FakeCompletedProcess):
        self.result = result
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append((command, kwargs))
        return self.result


def test_claude_code_adapter_invokes_configured_agent(tmp_path: Path) -> None:
    runner = FakeRunner(FakeCompletedProcess("agent output"))
    adapter = ClaudeCodeAgentAdapter(AgentConfig(provider="claude_code", settings={"agent_name": "reviewer", "cwd": str(tmp_path)}), runner=runner)

    run = adapter.run_sync(EvalCase(id="c1", input="检查代码"), context=None)

    command, kwargs = runner.commands[0]
    assert command[:2] == ["claude", "--print"]
    assert "Use the reviewer agent" in command[-1]
    assert kwargs["cwd"] == str(tmp_path)
    assert run.case_id == "c1"
    assert run.final_output == "agent output"


def test_claude_code_adapter_records_command_failure(tmp_path: Path) -> None:
    runner = FakeRunner(FakeCompletedProcess("", stderr="boom", returncode=1))
    adapter = ClaudeCodeAgentAdapter(AgentConfig(provider="claude_code", settings={"cwd": str(tmp_path)}), runner=runner)

    run = adapter.run_sync(EvalCase(id="c1", input="检查代码"), context=None)

    assert run.final_output == ""
    assert "boom" in run.errors[0]


def test_claude_code_adapter_passes_extra_args_and_timeout(tmp_path: Path) -> None:
    runner = FakeRunner(FakeCompletedProcess("ok"))
    adapter = ClaudeCodeAgentAdapter(
        AgentConfig(
            provider="claude_code",
            settings={"cwd": str(tmp_path), "executable": "claude-dev", "args": ["--model", "opus"], "timeout_seconds": 12},
        ),
        runner=runner,
    )

    adapter.run_sync(EvalCase(id="c1", input="检查代码"), context=None)

    command, kwargs = runner.commands[0]
    assert command == ["claude-dev", "--print", "--model", "opus", "检查代码"]
    assert kwargs["timeout"] == 12


def test_claude_code_adapter_uses_context_parent_as_default_cwd(tmp_path: Path) -> None:
    runner = FakeRunner(FakeCompletedProcess("ok"))
    adapter = ClaudeCodeAgentAdapter(AgentConfig(provider="claude_code"), runner=runner)
    context = RunContext(output_dir=tmp_path / "run")

    adapter.run_sync(EvalCase(id="c1", input="检查代码"), context=context)

    _, kwargs = runner.commands[0]
    assert kwargs["cwd"] == str(tmp_path)


def test_claude_code_adapter_joins_message_input_for_prompt(tmp_path: Path) -> None:
    runner = FakeRunner(FakeCompletedProcess("ok"))
    adapter = ClaudeCodeAgentAdapter(AgentConfig(provider="claude_code", settings={"cwd": str(tmp_path)}), runner=runner)
    case = EvalCase(id="c1", input=[ChatMessage(role="user", content="第一轮"), ChatMessage(role="assistant", content="第二轮")])

    run = adapter.run_sync(case, context=None)

    command, _ = runner.commands[0]
    assert command[-1] == "第一轮\n第二轮"
    assert run.messages[0].content == "[ChatMessage(role='user', content='第一轮'), ChatMessage(role='assistant', content='第二轮')]"


def test_claude_code_adapter_wraps_prompt_with_agent_name(tmp_path: Path) -> None:
    runner = FakeRunner(FakeCompletedProcess("ok"))
    adapter = ClaudeCodeAgentAdapter(AgentConfig(provider="claude_code", settings={"cwd": str(tmp_path), "agent_name": "tester"}), runner=runner)

    adapter.run_sync(EvalCase(id="c1", input="检查代码"), context=None)

    command, _ = runner.commands[0]
    assert command[-1] == "Use the tester agent to answer this evaluation case.\n\n检查代码"


def test_claude_code_adapter_uses_returncode_fallback_when_stderr_empty(tmp_path: Path) -> None:
    runner = FakeRunner(FakeCompletedProcess("", stderr="", returncode=7))
    adapter = ClaudeCodeAgentAdapter(AgentConfig(provider="claude_code", settings={"cwd": str(tmp_path)}), runner=runner)

    run = adapter.run_sync(EvalCase(id="c1", input="检查代码"), context=None)

    assert run.errors == ["Claude Code exited with 7"]
