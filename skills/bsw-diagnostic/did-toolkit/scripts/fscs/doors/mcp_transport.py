"""Minimal HTTP/SSE transport for the DOORS MCP server.

Why this exists (instead of using Cursor's MCP transport directly):

* The MCP CLI inside Cursor has no upper bound on a single call's
  wall-clock duration -- a stuck DOORS server hangs the whole skill
  for as long as the LSP keeps the connection alive.
* The server expects a `tools/call` JSON-RPC over a `text/event-stream`
  reply, with the actual tool result smuggled inside the first
  ``data:`` line. We have to parse that ourselves.

This module is a tiny port of ``diagcomm-toolkit/scripts/doors_fetch.py``'s
transport layer, deliberately verbatim so behaviour stays in sync. It
provides three primitives:

* :func:`initialize_session` -- POST ``initialize`` and grab the
  ``Mcp-Session-Id`` header.
* :func:`call_tool` -- POST ``tools/call`` with explicit per-call
  timeout, parse the SSE response, return the inner ``{code, message,
  data}`` dict the upload server hands back.
* :class:`MCPTransport` -- a thin object wrapper that holds the
  session id so callers can make several tool calls in a row without
  re-initialising.

All callers must `pip install requests` first; the import is deferred
inside ``_require_requests`` so importing this module never fails just
because the dependency is missing.
"""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional


DEFAULT_SERVER_URL = "http://10.54.7.36:8000/mcp"


def _require_requests():
    try:
        import requests  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on env
        raise SystemExit(
            "did-toolkit DOORS: `requests` is not installed. "
            "Run: python -m pip install requests"
        ) from exc


def initialize_session(
    server_url: str,
    timeout: int,
    *,
    client_name: str = "did-toolkit-doors",
) -> Optional[str]:
    """POST `initialize` and return the ``Mcp-Session-Id`` header.

    Returns ``None`` if the server refused to issue a session id (in
    which case the caller should bail with a useful error)."""
    _require_requests()
    import requests

    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": client_name, "version": "1.0.0"},
        },
    }
    try:
        resp = requests.post(server_url, headers=headers, json=body, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        print(f"[mcp] initialize failed: {exc}", file=sys.stderr)
        return None
    sid = resp.headers.get("Mcp-Session-Id")
    if not sid:
        print(
            "[mcp] no Mcp-Session-Id returned by server "
            f"(status={resp.status_code}, body[:200]={resp.text[:200]!r}).",
            file=sys.stderr,
        )
        return None
    return sid


def parse_sse_response(text: str) -> Dict[str, Any]:
    """Pick the first ``data:`` line out of an SSE stream and JSON-decode
    its inner ``result.content[0].text`` payload.

    Returns a ``{"code": int, "message": str, "data": ...}`` dict. On
    parse error returns a synthetic ``{"code": 1, "message": "..."}``
    so the caller can short-circuit cleanly."""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:]
        if not payload:
            continue
        try:
            data = json.loads(payload)
            content = data.get("result", {}).get("content", [])
            if not content:
                continue
            content_text = content[0].get("text", "{}")
            return json.loads(content_text)
        except Exception as exc:  # noqa: BLE001
            return {"code": 1, "message": f"Failed to parse SSE data: {exc}"}
    return {"code": 1, "message": "No valid data payload found in SSE response"}


def call_tool(
    server_url: str,
    session_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
    timeout: int,
) -> Dict[str, Any]:
    """Invoke an MCP `tools/call` with `arguments` and return the
    parsed result. Synthesises ``{"code": 1, "message": "..."}`` on any
    network / HTTP / SSE-parse failure so callers never see an
    exception escape this function."""
    _require_requests()
    import requests

    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Mcp-Session-Id": session_id,
    }
    body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    try:
        resp = requests.post(server_url, headers=headers, json=body, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return {"code": 1, "message": f"HTTP request failed: {exc}"}
    if resp.status_code != 200:
        return {"code": 1, "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}
    return parse_sse_response(resp.text)


@dataclass
class MCPTransport:
    """Stateful wrapper that holds a session id between several
    `call_tool` invocations."""

    server_url: str = DEFAULT_SERVER_URL
    init_timeout: int = 15
    client_name: str = "did-toolkit-doors"
    session_id: Optional[str] = None

    def ensure_session(self) -> str:
        if self.session_id:
            return self.session_id
        sid = initialize_session(self.server_url, self.init_timeout, client_name=self.client_name)
        if not sid:
            raise RuntimeError("Failed to initialise MCP session against " + self.server_url)
        self.session_id = sid
        return sid

    def call(self, tool_name: str, arguments: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        sid = self.ensure_session()
        return call_tool(self.server_url, sid, tool_name, arguments, timeout)


__all__ = [
    "DEFAULT_SERVER_URL",
    "MCPTransport",
    "call_tool",
    "initialize_session",
    "parse_sse_response",
]
