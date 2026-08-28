#!/usr/bin/env python3
"""diagcomm-toolkit -> DOORS upload (Step 8c).

Calls the `upload_doors_module` MCP tool over plain HTTP/SSE so we can
control the upload timeout (default 180s) instead of relying on the
Cursor MCP transport. Use this on the xlsx produced by
`build_doors_payload.py` (which now writes DOORS-native xlsxwriter
format directly -- no fix step needed).

Usage (run from project root; ``<skill>`` = e.g.
``~/.cursor/skills/diagcomm-toolkit``):
    python <skill>/scripts/doors_upload.py <xlsx> <module_uuid> <user_nt> <password>

Optional:
    --server-url     http://10.54.7.36:8000/mcp   (default)
    --init-timeout   15  seconds for MCP session init
    --upload-timeout 180 seconds for the upload itself

Exit codes:
    0  upload succeeded (server returned code == 0)
    1  upload failed / network error / file not found
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

# DOORS MCP server URL. Defaults to the internal team server; override
# per-environment via the DIAGCOMM_DOORS_MCP_URL env var or the
# --server-url CLI flag (CLI > env var > default).
DEFAULT_SERVER_URL = os.environ.get(
    "DIAGCOMM_DOORS_MCP_URL", "http://10.54.7.36:8000/mcp"
)

SKILL_ROOT = Path(__file__).resolve().parent.parent


def _require_requests():
    try:
        import requests  # noqa: F401
    except ImportError:
        raise SystemExit(
            f"requests missing. Run: python -m pip install -r "
            f"{(SKILL_ROOT / 'scripts' / 'requirements.txt').as_posix()}"
        )


def initialize_session(server_url: str, timeout: int) -> Optional[str]:
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
            "clientInfo": {"name": "diagcomm-doors-upload", "version": "1.0.0"},
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
    except Exception as exc:
        return {"code": 1, "message": f"HTTP request failed: {exc}"}

    if resp.status_code != 200:
        return {
            "code": 1,
            "message": f"HTTP {resp.status_code}: {resp.text[:300]}",
        }

    return parse_sse_response(resp.text)


def upload_file(
    server_url: str,
    session_id: str,
    excel_file: str,
    module_uuid: str,
    username: str,
    password: str,
    timeout: int,
) -> Dict[str, Any]:
    if not os.path.exists(excel_file):
        return {"code": 1, "message": f"File not found: {excel_file}"}

    try:
        with open(excel_file, "rb") as f:
            file_bytes = f.read()
    except Exception as exc:
        return {"code": 1, "message": f"Failed to read file: {exc}"}

    file_base64 = base64.b64encode(file_bytes).decode("utf-8")
    file_name = os.path.basename(excel_file)

    print(f"[INFO] File: {file_name}")
    print(f"[INFO] Size: {len(file_bytes):,} bytes")
    print(f"[INFO] Base64 length: {len(file_base64):,}")
    print(f"[INFO] Uploading to module: {module_uuid}")

    return call_tool(
        server_url=server_url,
        session_id=session_id,
        tool_name="upload_doors_module",
        arguments={
            "module_uuid": module_uuid,
            "user_nt": username,
            "password": password,
            "file_name": file_name,
            "file_base64": file_base64,
        },
        timeout=timeout,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="diagcomm-toolkit/doors_upload.py",
        description="Upload a DOORS xlsx via the upload_doors_module MCP tool.",
    )
    parser.add_argument("excel_file", help="Path to .xlsx file (DOORS-native format)")
    parser.add_argument("module_uuid", help="DOORS module UUID")
    parser.add_argument("username", help="NT username")
    parser.add_argument("password", help="DOORS password")
    parser.add_argument(
        "--server-url",
        default=DEFAULT_SERVER_URL,
        help=f"MCP server URL (default: {DEFAULT_SERVER_URL})",
    )
    parser.add_argument(
        "--init-timeout",
        type=int,
        default=15,
        help="Session-init timeout in seconds (default: 15)",
    )
    parser.add_argument(
        "--upload-timeout",
        type=int,
        default=180,
        help="Upload timeout in seconds (default: 180)",
    )
    return parser.parse_args()


def main() -> int:
    _require_requests()
    args = parse_args()

    print("=" * 72)
    print("diagcomm-toolkit -> DOORS upload")
    print("=" * 72)
    print(f"File:   {args.excel_file}")
    print(f"Module: {args.module_uuid}")
    print(f"User:   {args.username}")
    print(f"Server: {args.server_url}")
    print("=" * 72)

    session_id = initialize_session(args.server_url, args.init_timeout)
    if not session_id:
        print("[FAIL] Unable to initialize MCP session.")
        return 1
    print(f"[OK] Session initialized: {session_id[:8]}...")

    result = upload_file(
        server_url=args.server_url,
        session_id=session_id,
        excel_file=args.excel_file,
        module_uuid=args.module_uuid,
        username=args.username,
        password=args.password,
        timeout=args.upload_timeout,
    )

    print("-" * 72)
    if result.get("code") == 0:
        print("[SUCCESS] Upload completed successfully.")
        print(f"Message: {result.get('message', 'OK')}")
        if "data" in result:
            print(f"Data: {result.get('data')}")
        return 0

    print("[FAILED] Upload failed.")
    print(f"Code: {result.get('code')}")
    print(f"Message: {result.get('message')}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
