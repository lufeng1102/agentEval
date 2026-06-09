import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from config import EnvironmentConfig
from environments.http_api import prepare_http_api_environment
from evaluators.environment import EnvironmentEvaluator
from schemas import AgentRun, EvalCase


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


def _server():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_http_api_environment_records_checks(tmp_path):
    server = _server()
    try:
        prepared = prepare_http_api_environment(
            EvalCase(id="api1", input="check"),
            0,
            tmp_path / "run",
            EnvironmentConfig(type="http_api", settings={}, test_checks=[{"path": "/health", "expected_status": 200}]),
        )
        prepared.base_url = f"http://127.0.0.1:{server.server_port}"

        asyncio.run(prepared.run_commands("test", prepared.test_commands))

        assert prepared.record.http[0].status_code == 200
        assert prepared.record.http[0].json_body["status"] == "ok"
    finally:
        server.shutdown()


def test_environment_evaluator_checks_http_status_and_json() -> None:
    case = EvalCase(
        id="api1",
        input="check",
        expected={"environment": {"http": {"required_status": [{"path": "/health", "status": 200}], "required_json_paths": [{"path": "/health", "json_path": "status", "value": "ok"}], "max_http_failures": 0}}},
    )
    run = AgentRun(case_id="api1", artifacts={"environment": {"type": "http_api", "http": [{"phase": "test", "method": "GET", "url": "http://local/health", "status_code": 200, "json": {"status": "ok"}, "error": None}]}})

    result = asyncio.run(EnvironmentEvaluator().evaluate(case, run))

    assert result.passed is True
    assert result.metrics["http_checks"] == 1


def test_environment_evaluator_fails_http_json_mismatch() -> None:
    case = EvalCase(id="api1", input="check", expected={"environment": {"http": {"required_json_paths": [{"path": "/health", "json_path": "status", "value": "ok"}]}}})
    run = AgentRun(case_id="api1", artifacts={"environment": {"type": "http_api", "http": [{"phase": "test", "method": "GET", "url": "http://local/health", "status_code": 200, "json": {"status": "bad"}, "error": None}]}})

    result = asyncio.run(EnvironmentEvaluator().evaluate(case, run))

    assert result.passed is False
    assert "json path" in result.failure_reason
