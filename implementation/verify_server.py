from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from init_db import create_database


ROOT = Path(__file__).resolve().parent


class MCPClient:
    def __init__(self, command: list[str], env: dict[str, str]):
        self.proc = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._next_id = 1

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def request(self, method: str, params: dict | None = None):
        request_id = self._next_id
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self._write(message)
        while True:
            response = self._read()
            if response.get("id") == request_id:
                return response

    def notify(self, method: str, params: dict | None = None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._write(message)

    def _write(self, message: dict):
        assert self.proc.stdin is not None
        payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        self.proc.stdin.write((payload + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def _read(self):
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("server closed stdout")
        return json.loads(line.decode("utf-8"))


def assert_ok(response: dict, label: str):
    assert "result" in response, f"{label} failed: {response}"
    assert "error" not in response, f"{label} unexpectedly errored: {response}"


def extract_result_payload(response: dict):
    result = response["result"]
    if "structuredContent" in result:
        return result["structuredContent"]
    content = result.get("content") or []
    if content and content[0].get("type") == "text":
        text = content[0]["text"]
        try:
            return json.loads(text)
        except Exception:
            return text
    return result


def assert_error(response: dict, contains: str, label: str):
    assert "result" in response, f"{label} expected tool error result: {response}"
    assert response["result"].get("isError") is True, f"{label} expected isError: {response}"
    content = response["result"]["content"][0]["text"]
    message = content
    assert contains in message, f"{label} error mismatch: {message}"


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = create_database(Path(tmpdir) / "sqlite_lab.db")
        env = os.environ.copy()
        env["SQLITE_LAB_DB"] = str(db_path)
        client = MCPClient([sys.executable, "mcp_server.py"], env=env)
        try:
            assert_ok(
                client.request(
                    "initialize",
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "verify-server", "version": "0.1.0"},
                    },
                ),
                "initialize",
            )
            client.notify("notifications/initialized")
            assert_ok(client.request("ping", {}), "ping")
            tools = client.request("tools/list", {})
            assert_ok(tools, "tools/list")
            tool_names = {tool["name"] for tool in tools["result"]["tools"]}
            assert {"search", "insert", "aggregate"}.issubset(tool_names), tool_names

            resources = client.request("resources/list", {})
            assert_ok(resources, "resources/list")
            resource_uris = {resource["uri"] for resource in resources["result"]["resources"]}
            assert "schema://database" in resource_uris, resource_uris

            templates = client.request("resources/templates/list", {})
            assert_ok(templates, "resources/templates/list")
            template_uris = {template["uriTemplate"] for template in templates["result"]["resourceTemplates"]}
            assert "schema://table/{table_name}" in template_uris, template_uris

            db_schema = client.request("resources/read", {"uri": "schema://database"})
            assert_ok(db_schema, "schema://database")

            table_schema = client.request("resources/read", {"uri": "schema://table/students"})
            assert_ok(table_schema, "schema://table/students")

            search = client.request(
                "tools/call",
                {
                    "name": "search",
                    "arguments": {
                        "table": "students",
                        "filters": [{"column": "cohort", "operator": "=", "value": "A1"}],
                        "columns": ["id", "name", "cohort", "score"],
                        "order_by": "score",
                        "descending": True,
                        "limit": 5,
                        "offset": 0,
                    },
                },
            )
            assert_ok(search, "search")
            search_payload = extract_result_payload(search)
            assert search_payload["count"] >= 1

            insert = client.request(
                "tools/call",
                {
                    "name": "insert",
                    "arguments": {
                        "table": "students",
                        "values": {
                            "name": "Lan",
                            "cohort": "A1",
                            "score": 97,
                            "email": "lan@example.com",
                        },
                    },
                },
            )
            assert_ok(insert, "insert")
            insert_payload = extract_result_payload(insert)
            assert insert_payload["table"] == "students"

            aggregate = client.request(
                "tools/call",
                {
                    "name": "aggregate",
                    "arguments": {
                        "table": "students",
                        "metric": "avg",
                        "column": "score",
                        "group_by": "cohort",
                    },
                },
            )
            assert_ok(aggregate, "aggregate")
            aggregate_payload = extract_result_payload(aggregate)
            assert aggregate_payload["table"] == "students"

            bad_table = client.request(
                "tools/call",
                {
                    "name": "search",
                    "arguments": {"table": "missing", "filters": []},
                },
            )
            assert_error(bad_table, "Unknown table", "bad table")

            bad_metric = client.request(
                "tools/call",
                {
                    "name": "aggregate",
                    "arguments": {"table": "students", "metric": "median", "column": "score"},
                },
            )
            assert_error(bad_metric, "Unsupported aggregate metric", "bad metric")

            print("Verification passed.")
        finally:
            client.close()


if __name__ == "__main__":
    main()
