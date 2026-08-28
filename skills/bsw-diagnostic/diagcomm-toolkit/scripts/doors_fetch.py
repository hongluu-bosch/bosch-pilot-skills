#!/usr/bin/env python3
"""One-shot DOORS module fetch over HTTP/SSE.

Mirrors the timeout-controlled transport used by ``doors_upload.py``
so a hanging Cursor-side MCP transport doesn't block this skill from
investigating the module state. Persists the fetch result to a path
of the caller's choosing (default: ``outputs/doors_export_fresh.json``)
in the same shape ``build_doors_payload.py`` already understands
(``{code, message, data}``).

Usage (run from project root; ``<skill>`` = e.g.
``~/.cursor/skills/diagcomm-toolkit``):
    python <skill>/scripts/doors_fetch.py <module_uuid> <user_nt> [--out PATH]
                                          [--refresh] [--server-url URL]
                                          [--init-timeout SEC]
                                          [--call-timeout SEC]

Notes:
    --refresh first calls ``refresh_doors_module`` to force the
    server-side cache to re-pull from DOORS. Adds latency (the live
    DOORS query is the slow part) but is the only way to see a row
    that was just inserted by a sibling upload.
"""

from __future__ import annotations

import argparse
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
            "clientInfo": {"name": "diagcomm-doors-fetch", "version": "1.0.0"},
        },
    }
    try:
        resp = requests.post(server_url, headers=headers, json=body, timeout=timeout)
    except Exception as exc:
        print(f"[ERROR] Session initialize failed: {exc}", file=sys.stderr)
        return None
    sid = resp.headers.get("Mcp-Session-Id")
    if not sid:
        print("[ERROR] No Mcp-Session-Id returned by server.", file=sys.stderr)
        return None
    return sid


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


def call_tool(server_url: str, session_id: str, tool_name: str,
              arguments: Dict[str, Any], timeout: int) -> Dict[str, Any]:
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
        return {"code": 1,
                "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}
    return parse_sse_response(resp.text)


def fetch_module(module_uuid: str, user_nt: str, *,
                 server_url: str = DEFAULT_SERVER_URL,
                 init_timeout: int = 15,
                 fetch_timeout: int = 120,
                 refresh: bool = False,
                 refresh_timeout: int = 70,
                 quiet: bool = False) -> Dict[str, Any]:
    """One-shot wrapper that initializes a session and calls
    ``get_doors_module`` (optionally preceded by ``refresh_doors_module``).

    Returns the raw ``{code, message, data}`` payload from the MCP
    server. ``code == 0`` indicates success and ``data.rows`` will hold
    the module rows. Refresh failures are non-fatal -- we log them
    (unless ``quiet``) and continue with the cached read, since the
    upstream DOORS server frequently returns 60s read-timeouts that
    we can't fix from the client side.

    Used for two flows:

    * ``scripts/doors_fetch.py`` (CLI tool, persists the fetch to disk)
    * ``scripts/doors_sync.py::_reconcile_abs_after_insert`` (post-insert
      reconciliation, in-memory only)

    Both share this function so the transport semantics (timeouts,
    SSE parsing) live in exactly one place.
    """
    _require_requests()
    sid = initialize_session(server_url, init_timeout)
    if not sid:
        return {"code": 1, "message": "Failed to initialize MCP session"}

    if refresh:
        rresult = call_tool(
            server_url, sid, "refresh_doors_module",
            {"module_uuid": module_uuid, "user_nt": user_nt},
            refresh_timeout,
        )
        if rresult.get("code") != 0 and not quiet:
            print(
                f"[doors_fetch] refresh did not complete "
                f"(code={rresult.get('code')}, message={rresult.get('message')!r}); "
                "continuing with cached read.",
                file=sys.stderr,
            )

    return call_tool(
        server_url, sid, "get_doors_module",
        {"module_uuid": module_uuid, "user_nt": user_nt},
        fetch_timeout,
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="diagcomm-toolkit/doors_fetch.py",
        description="Fetch a DOORS module via HTTP/SSE with explicit timeouts.",
    )
    p.add_argument("module_uuid")
    p.add_argument("user_nt")
    p.add_argument(
        "--out",
        default=str(Path("outputs") / "doors_export_fresh.json"),
        help="Where to write the fetch payload (default: outputs/doors_export_fresh.json).",
    )
    p.add_argument(
        "--refresh", action="store_true",
        help="Call refresh_doors_module before get_doors_module to force re-pull from DOORS.",
    )
    p.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    p.add_argument("--init-timeout", type=int, default=15)
    p.add_argument("--call-timeout", type=int, default=300,
                   help="Per-tool-call timeout in seconds (default: 300).")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    print("=" * 72)
    print("diagcomm-toolkit -> DOORS fetch")
    print("=" * 72)
    print(f"Module : {args.module_uuid}")
    print(f"User   : {args.user_nt}")
    print(f"Server : {args.server_url}")
    print(f"Refresh: {args.refresh}")
    print(f"Out    : {args.out}")
    print("=" * 72)

    result = fetch_module(
        module_uuid=args.module_uuid,
        user_nt=args.user_nt,
        server_url=args.server_url,
        init_timeout=args.init_timeout,
        fetch_timeout=args.call_timeout,
        refresh=args.refresh,
        refresh_timeout=args.call_timeout,
        quiet=False,
    )
    code = result.get("code")
    print(f"[STEP] get_doors_module -> code={code} message={result.get('message', '')!r}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"[OK] wrote {out} ({out.stat().st_size:,} bytes)")

    if code != 0:
        return 1

    rows = result.get("data", {}).get("rows") if isinstance(result.get("data"), dict) else None
    if isinstance(rows, list):
        print(f"[INFO] rows: {len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
