#!/usr/bin/env python
"""
Refresh a DOORS module via MCP.

This mirrors the MCP JSON-RPC + SSE pattern used by doors_get_tool.py,
but calls `refresh_doors_module`.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import requests

DEFAULT_SERVER_URL = "http://10.54.7.36:8000/mcp"


def initialize_session(server_url: str, timeout: int) -> Optional[str]:
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
            "clientInfo": {"name": "doors-refresh-client", "version": "1.0.0"},
        },
    }

    try:
        resp = requests.post(server_url, headers=headers, json=body, timeout=timeout)
    except Exception as exc:
        print(f"[ERROR] Session initialize request failed: {exc}")
        return None

    session_id = resp.headers.get("Mcp-Session-Id")
    if not session_id:
        print("[ERROR] No Mcp-Session-Id returned by server.")
        if resp.text:
            print(f"[ERROR] Response: {resp.text[:300]}")
        return None
    return session_id


def parse_sse_response(text: str) -> Dict[str, Any]:
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
                structured = data.get("result", {}).get("structuredContent")
                if isinstance(structured, dict):
                    return structured
                continue
            content_text = content[0].get("text", "{}")
            return json.loads(content_text)
        except Exception as exc:
            return {"code": 1, "message": f"Failed to parse SSE data: {exc}"}
    return {"code": 1, "message": "No valid data payload found in SSE response"}


def call_tool(
    server_url: str,
    session_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
    timeout: int,
) -> Dict[str, Any]:
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
    except Exception as exc:
        return {"code": 1, "message": f"HTTP request failed: {exc}"}

    if resp.status_code != 200:
        return {"code": 1, "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}

    return parse_sse_response(resp.text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh DOORS module via MCP.")
    parser.add_argument("module_uuid", help="DOORS module UUID")
    parser.add_argument(
        "--user-nt",
        default="unknown",
        help="NT username passed to the MCP tool (default: unknown)",
    )
    parser.add_argument(
        "--server-url",
        default=DEFAULT_SERVER_URL,
        help=f"MCP server URL (default: {DEFAULT_SERVER_URL})",
    )
    parser.add_argument(
        "--init-timeout",
        type=int,
        default=15,
        help="Session initialization timeout in seconds (default: 15)",
    )
    parser.add_argument(
        "--refresh-timeout",
        type=int,
        default=300,
        help="Refresh request timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Optional path to write JSON response",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print("=" * 72)
    print("DOORS MCP Refresh Tool")
    print("=" * 72)
    print(f"Module: {args.module_uuid}")
    print(f"User:   {args.user_nt}")
    print(f"Server: {args.server_url}")
    if args.out:
        print(f"Out:    {args.out}")
    print("=" * 72)

    session_id = initialize_session(args.server_url, args.init_timeout)
    if not session_id:
        print("[FAIL] Unable to initialize MCP session.")
        return 1
    print(f"[OK] Session initialized: {session_id[:8]}...")

    result = call_tool(
        server_url=args.server_url,
        session_id=session_id,
        tool_name="refresh_doors_module",
        arguments={"module_uuid": args.module_uuid, "user_nt": args.user_nt},
        timeout=args.refresh_timeout,
    )

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("-" * 72)
    if result.get("code") == 0:
        print("[SUCCESS] Refresh completed successfully.")
        print(f"Message: {result.get('message', 'OK')}")
        if "data" in result:
            print(f"Data: {result.get('data')}")
        return 0

    print("[FAILED] Refresh failed.")
    print(f"Code: {result.get('code')}")
    print(f"Message: {result.get('message')}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
