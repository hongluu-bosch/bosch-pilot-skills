#!/usr/bin/env python
"""
Fetch a DOORS module via MCP and save the response as JSON.

This mirrors the MCP JSON-RPC + SSE pattern used by doors_upload_tool.py,
but calls `get_doors_module`.
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
            "clientInfo": {"name": "doors-get-client", "version": "1.0.0"},
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
        return None
    return session_id


def parse_sse_response(text: str) -> Dict[str, Any]:
    payload_parts = []

    def parse_payload(payload: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(payload, strict=False)
            content = data.get("result", {}).get("content", [])
            if not content:
                return None
            content_text = content[0].get("text", "{}")
            return json.loads(content_text, strict=False)
        except Exception as exc:
            return {"code": 1, "message": f"Failed to parse SSE data: {exc}"}

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            if payload_parts:
                parsed = parse_payload("\n".join(payload_parts))
                if parsed is not None:
                    return parsed
                payload_parts = []
            continue

        if line.startswith("data:"):
            payload_parts.append(line[5:].lstrip())
        elif payload_parts and not line.startswith("event:"):
            # Some DOORS MCP responses contain raw wrapped JSON lines inside
            # the data payload instead of prefixing each continuation with data:.
            payload_parts.append(line)

    if payload_parts:
        parsed = parse_payload("\n".join(payload_parts))
        if parsed is not None:
            return parsed

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
    parser = argparse.ArgumentParser(description="Fetch DOORS module via MCP.")
    parser.add_argument("module_uuid", help="DOORS module UUID")
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
        "--get-timeout",
        type=int,
        default=180,
        help="Fetch timeout in seconds (default: 180)",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Path to write JSON response (default: output/doors_module_<uuid>.json)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    out_path = (
        Path(args.out)
        if args.out
        else (Path("output") / f"doors_module_{args.module_uuid}.json")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("DOORS MCP Get Tool")
    print("=" * 72)
    print(f"Module: {args.module_uuid}")
    print(f"Server: {args.server_url}")
    print(f"Out:    {out_path}")
    print("=" * 72)

    session_id = initialize_session(args.server_url, args.init_timeout)
    if not session_id:
        print("[FAIL] Unable to initialize MCP session.")
        return 1
    print(f"[OK] Session initialized: {session_id[:8]}...")

    result = call_tool(
        server_url=args.server_url,
        session_id=session_id,
        tool_name="get_doors_module",
        arguments={"module_uuid": args.module_uuid},
        timeout=args.get_timeout,
    )

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("-" * 72)
    if result.get("code") == 0:
        print("[SUCCESS] Fetch completed successfully.")
        print(f"Message: {result.get('message', 'OK')}")
        return 0

    print("[FAILED] Fetch failed.")
    print(f"Code: {result.get('code')}")
    print(f"Message: {result.get('message')}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

