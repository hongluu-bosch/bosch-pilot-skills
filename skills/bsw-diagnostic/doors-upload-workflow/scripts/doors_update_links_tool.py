#!/usr/bin/env python
"""
Upload a DOORS links Excel file via MCP.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import sys
import uuid
from typing import Any, Dict, Optional

import requests

DEFAULT_SERVER_URL = "http://10.54.7.36:8000/mcp"
DEFAULT_MODULE_UUID = "links-batch"


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
            "clientInfo": {"name": "doors-links-update-client", "version": "1.0.0"},
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
        return {
            "code": 1,
            "message": f"HTTP {resp.status_code}: {resp.text[:300]}",
        }

    return parse_sse_response(resp.text)


def update_links_file(
    server_url: str,
    session_id: str,
    excel_file: str,
    username: str,
    password: str,
    module_uuid: str,
    timeout: int,
) -> Dict[str, Any]:
    if not os.path.exists(excel_file):
        return {"code": 1, "message": f"File not found: {excel_file}"}

    try:
        file_bytes = open(excel_file, "rb").read()
    except Exception as exc:
        return {"code": 1, "message": f"Failed to read file: {exc}"}

    file_base64 = base64.b64encode(file_bytes).decode("utf-8")
    file_name = os.path.basename(excel_file)

    print(f"[INFO] File: {file_name}")
    print(f"[INFO] Size: {len(file_bytes):,} bytes")
    print(f"[INFO] Base64 length: {len(file_base64):,}")
    print(f"[INFO] Updating DOORS links batch: {module_uuid}")

    return call_tool(
        server_url=server_url,
        session_id=session_id,
        tool_name="update_doors_links",
        arguments={
            "user_nt": username,
            "password": password,
            "file_name": file_name,
            "file_base64": file_base64,
            "module_uuid": module_uuid,
        },
        timeout=timeout,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload DOORS links Excel file via MCP.")
    parser.add_argument("excel_file", help="Path to links .xlsx file")
    parser.add_argument("username", help="NT username")
    parser.add_argument(
        "password",
        nargs="?",
        default="",
        help="DOORS password (omit if using --prompt-password or --password-env)",
    )
    parser.add_argument(
        "--module-uuid",
        default=DEFAULT_MODULE_UUID,
        help=f"DOORS links module UUID/batch name (default: {DEFAULT_MODULE_UUID})",
    )
    parser.add_argument(
        "--prompt-password",
        action="store_true",
        help="Prompt for password (avoids putting password in command history)",
    )
    parser.add_argument(
        "--password-env",
        default="",
        help="Read password from an environment variable name (e.g. DOORS_PASSWORD)",
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
        "--update-timeout",
        type=int,
        default=180,
        help="Links update timeout in seconds (default: 180)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    password = args.password
    if not password and args.password_env:
        password = os.environ.get(args.password_env, "")
    if not password and args.prompt_password:
        password = getpass.getpass("DOORS password: ")
    if not password:
        print("[FAIL] No password provided. Use --prompt-password or --password-env.")
        return 2

    print("=" * 72)
    print("DOORS MCP Links Update Tool")
    print("=" * 72)
    print(f"File:        {args.excel_file}")
    print(f"User:        {args.username}")
    print(f"Module UUID: {args.module_uuid}")
    print(f"Server:      {args.server_url}")
    print("=" * 72)

    session_id = initialize_session(args.server_url, args.init_timeout)
    if not session_id:
        print("[FAIL] Unable to initialize MCP session.")
        return 1
    print(f"[OK] Session initialized: {session_id[:8]}...")

    result = update_links_file(
        server_url=args.server_url,
        session_id=session_id,
        excel_file=args.excel_file,
        username=args.username,
        password=password,
        module_uuid=args.module_uuid,
        timeout=args.update_timeout,
    )

    print("-" * 72)
    if result.get("code") == 0:
        print("[SUCCESS] Links update completed successfully.")
        print(f"Message: {result.get('message', 'OK')}")
        if "data" in result:
            print(f"Data: {result.get('data')}")
        return 0

    print("[FAILED] Links update failed.")
    print(f"Code: {result.get('code')}")
    print(f"Message: {result.get('message')}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
