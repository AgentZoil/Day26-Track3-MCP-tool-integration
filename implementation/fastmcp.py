from __future__ import annotations

import inspect
import json
import re
import sys
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, get_args, get_origin, get_type_hints


def _json_schema_for_type(annotation: Any) -> dict[str, Any]:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if annotation in (inspect._empty, Any):
        return {"type": "object"}
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is dict or origin is dict:
        return {"type": "object"}
    if annotation is list or origin is list:
        item_type = _json_schema_for_type(args[0]) if args else {"type": "object"}
        return {"type": "array", "items": item_type}
    if origin in (tuple, set):
        item_type = _json_schema_for_type(args[0]) if args else {"type": "object"}
        return {"type": "array", "items": item_type}
    if origin is None:
        return {"type": "object"}
    if str(origin) in {"typing.Union", "types.UnionType"} or origin is getattr(__import__("types"), "UnionType", None):
        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) == 1:
            return _json_schema_for_type(non_none[0])
        return {"anyOf": [_json_schema_for_type(arg) for arg in non_none]}
    return {"type": "object"}


def _schema_for_callable(fn: Callable[..., Any]) -> dict[str, Any]:
    signature = inspect.signature(fn)
    hints = get_type_hints(fn)
    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []

    for name, param in signature.parameters.items():
        annotation = hints.get(name, param.annotation)
        schema = _json_schema_for_type(annotation)
        if param.default is not inspect._empty:
            schema = dict(schema)
            schema["default"] = param.default
        else:
            required.append(name)
        properties[name] = schema

    payload: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        payload["required"] = required
    return payload


@dataclass
class _Tool:
    name: str
    fn: Callable[..., Any]
    description: str | None
    input_schema: dict[str, Any]


@dataclass
class _Resource:
    uri_template: str
    fn: Callable[..., Any]
    name: str
    description: str | None
    mime_type: str
    is_templated: bool

    def matches(self, uri: str) -> dict[str, str] | None:
        parts = []
        names: list[str] = []
        cursor = 0
        for match in re.finditer(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", self.uri_template):
            parts.append(re.escape(self.uri_template[cursor:match.start()]))
            name = match.group(1)
            names.append(name)
            parts.append(f"(?P<{name}>[^/]+)")
            cursor = match.end()
        parts.append(re.escape(self.uri_template[cursor:]))
        pattern = "^" + "".join(parts) + "$"
        match = re.match(pattern, uri)
        if not match:
            return None
        return match.groupdict()


class FastMCP:
    SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

    def __init__(self, name: str):
        self.name = name
        self._tools: dict[str, _Tool] = {}
        self._resources: list[_Resource] = []
        self._debug = os.environ.get("MCP_DEBUG") == "1"
        self._debug_log = Path(os.environ.get("MCP_DEBUG_LOG", "/private/tmp/mcp_server_debug.log"))

    def _log(self, message: str) -> None:
        if self._debug:
            line = f"[fastmcp] {message}\n"
            try:
                self._debug_log.parent.mkdir(parents=True, exist_ok=True)
                with self._debug_log.open("a", encoding="utf-8") as handle:
                    handle.write(line)
            except Exception:
                pass
            sys.stderr.write(line)
            sys.stderr.flush()

    def tool(self, name: str | None = None, description: str | None = None):
        def decorator(fn: Callable[..., Any]):
            tool_name = name or fn.__name__
            self._tools[tool_name] = _Tool(
                name=tool_name,
                fn=fn,
                description=description or (inspect.getdoc(fn) or None),
                input_schema=_schema_for_callable(fn),
            )
            return fn

        return decorator

    def resource(
        self,
        uri_template: str,
        *,
        name: str | None = None,
        description: str | None = None,
        mime_type: str = "application/json",
    ):
        def decorator(fn: Callable[..., Any]):
            self._resources.append(
                _Resource(
                    uri_template=uri_template,
                    fn=fn,
                    name=name or fn.__name__,
                    description=description or (inspect.getdoc(fn) or None),
                    mime_type=mime_type,
                    is_templated="{" in uri_template and "}" in uri_template,
                )
            )
            return fn

        return decorator

    def _resource_payload(self, resource: _Resource) -> dict[str, Any]:
        payload = {
            "uri": resource.uri_template,
            "name": resource.name,
            "mimeType": resource.mime_type,
        }
        if resource.description:
            payload["description"] = resource.description
        if resource.is_templated:
            payload["uriTemplate"] = resource.uri_template
        return payload

    def _read_resource(self, uri: str) -> dict[str, Any]:
        for resource in self._resources:
            if not resource.is_templated and resource.uri_template == uri:
                result = resource.fn()
                return self._normalize_resource_result(uri, resource.mime_type, result)

        for resource in self._resources:
            if not resource.is_templated:
                continue
            params = resource.matches(uri)
            if params is not None:
                result = resource.fn(**params)
                return self._normalize_resource_result(uri, resource.mime_type, result)

        raise KeyError(f"Unknown resource: {uri}")

    @staticmethod
    def _normalize_resource_result(uri: str, mime_type: str, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            text = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
        elif isinstance(value, (list, tuple)):
            text = json.dumps(value, indent=2, ensure_ascii=False)
        else:
            text = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)
        return {"uri": uri, "mimeType": mime_type, "text": text}

    @staticmethod
    def _result_content(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, indent=2, ensure_ascii=False, default=str)
        return [{"type": "text", "text": text}]

    @staticmethod
    def _jsonrpc_error(code: int, message: str, request_id: Any | None) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    @staticmethod
    def _jsonrpc_result(result: Any, request_id: Any | None) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _handle_request(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        self._log(f"recv {method!r} id={request_id!r}")

        if method == "initialize":
            requested_version = params.get("protocolVersion")
            protocol_version = (
                requested_version
                if requested_version in self.SUPPORTED_PROTOCOL_VERSIONS
                else self.SUPPORTED_PROTOCOL_VERSIONS[0]
            )
            return self._jsonrpc_result(
                {
                    "protocolVersion": protocol_version,
                    "serverInfo": {"name": self.name, "version": "0.1.0"},
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                    },
                    "instructions": "Use search, insert, aggregate, and schema resources for the SQLite lab server.",
                },
                request_id,
            )

        if method == "ping":
            return self._jsonrpc_result({}, request_id)

        if method == "tools/list":
            return self._jsonrpc_result(
                {
                    "tools": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "inputSchema": tool.input_schema,
                        }
                        for tool in self._tools.values()
                    ]
                },
                request_id,
            )

        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            tool = self._tools.get(name)
            if tool is None:
                return self._jsonrpc_error(-32602, f"Unknown tool: {name}", request_id)
            try:
                result = tool.fn(**args)
            except Exception as exc:  # pragma: no cover - propagated to client
                self._log(f"tool error {name!r}: {exc}")
                return self._jsonrpc_result(
                    {
                        "content": self._result_content(str(exc)),
                        "isError": True,
                    },
                    request_id,
                )
            return self._jsonrpc_result(
                {"content": self._result_content(result), "isError": False, "structuredContent": result},
                request_id,
            )

        if method == "resources/list":
            return self._jsonrpc_result(
                {
                    "resources": [
                        self._resource_payload(resource)
                        for resource in self._resources
                        if not resource.is_templated
                    ]
                },
                request_id,
            )

        if method == "resources/templates/list":
            return self._jsonrpc_result(
                {
                    "resourceTemplates": [
                        self._resource_payload(resource)
                        for resource in self._resources
                        if resource.is_templated
                    ]
                },
                request_id,
            )

        if method == "resources/read":
            uri = params.get("uri")
            try:
                resource = self._read_resource(uri)
            except KeyError as exc:
                return self._jsonrpc_error(-32602, str(exc), request_id)
            return self._jsonrpc_result(
                {
                    "contents": [
                        {
                            "uri": resource["uri"],
                            "mimeType": resource["mimeType"],
                            "text": resource["text"],
                        }
                    ]
                },
                request_id,
            )

        return self._jsonrpc_error(-32601, f"Unknown method: {method}", request_id)

    @staticmethod
    def _read_frame(stream) -> dict[str, Any] | None:
        line = stream.readline()
        if not line:
            return None
        text = line.decode("utf-8").strip()
        if not text:
            return None
        return json.loads(text)

    @staticmethod
    def _write_frame(stream, message: dict[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        stream.write((payload + "\n").encode("utf-8"))
        stream.flush()

    def run(self, transport: str = "stdio") -> None:
        if transport != "stdio":
            raise NotImplementedError("Only stdio transport is supported in this lab implementation.")

        while True:
            message = self._read_frame(sys.stdin.buffer)
            if message is None:
                return

            if message.get("method") is None:
                continue

            if "id" not in message:
                continue

            try:
                response = self._handle_request(message)
            except Exception as exc:  # pragma: no cover - debug path
                self._log(f"handler crash: {exc!r}")
                response = self._jsonrpc_error(-32000, str(exc), message.get("id"))
            if response is not None:
                self._log(f"send id={message.get('id')!r}")
                self._write_frame(sys.stdout.buffer, response)
