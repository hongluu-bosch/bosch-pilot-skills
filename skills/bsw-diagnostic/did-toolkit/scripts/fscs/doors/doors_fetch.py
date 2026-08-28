#!/usr/bin/env python3
"""Fetch a DOORS module via MCP `get_doors_module` and persist the
response to ``outputs/doors/doors_export.json`` (the path that
``anchor.py`` reads).

Usage::

    python scripts/fscs/doors/doors_fetch.py <module_uuid> <user_nt> [--refresh]

Flags:
    --out PATH               override the export path (default
                             outputs/doors/doors_export.json)
    --refresh                first call `refresh_doors_module` so the
                             server re-pulls from live DOORS before
                             returning the rows.
    --server-url URL         override the MCP endpoint
                             (default http://10.54.7.36:8000/mcp)
    --init-timeout SEC       MCP session-init timeout (default 15)
    --call-timeout SEC       per-tool-call timeout (default 300)

Exits 0 on success, 1 on transport error, 2 on missing args.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from mcp_transport import DEFAULT_SERVER_URL, MCPTransport  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = SKILL_ROOT / "outputs" / "doors" / "doors_export.json"


def fetch_module(
    *,
    module_uuid: str,
    user_nt: str,
    server_url: str = DEFAULT_SERVER_URL,
    init_timeout: int = 15,
    call_timeout: int = 300,
    refresh: bool = False,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Initialise an MCP session, optionally call ``refresh_doors_module``,
    then call ``get_doors_module`` and return the raw `{code, message,
    data}` payload.

    Refresh failures are non-fatal -- they only mean the cached read
    will be stale -- so we surface them as a console warning unless
    ``quiet`` is set."""
    transport = MCPTransport(
        server_url=server_url,
        init_timeout=init_timeout,
        client_name="did-toolkit-doors-fetch",
    )

    if refresh:
        result = transport.call(
            "refresh_doors_module",
            {"module_uuid": module_uuid, "user_nt": user_nt},
            call_timeout,
        )
        if result.get("code") != 0 and not quiet:
            print(
                f"[doors_fetch] refresh skipped (code={result.get('code')}, "
                f"message={result.get('message')!r}); proceeding with cached read.",
                file=sys.stderr,
            )

    return transport.call(
        "get_doors_module",
        {"module_uuid": module_uuid, "user_nt": user_nt},
        call_timeout,
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="did-toolkit/doors_fetch.py",
        description="Fetch a DOORS module via MCP and persist the JSON payload.",
    )
    p.add_argument("module_uuid")
    p.add_argument("user_nt")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    p.add_argument("--init-timeout", type=int, default=15)
    p.add_argument("--call-timeout", type=int, default=300)
    args = p.parse_args(argv)

    print("=" * 72)
    print("did-toolkit -> DOORS fetch")
    print("=" * 72)
    print(f"Module : {args.module_uuid}")
    print(f"User   : {args.user_nt}")
    print(f"Server : {args.server_url}")
    print(f"Refresh: {args.refresh}")
    print(f"Out    : {args.out}")
    print("=" * 72)

    try:
        result = fetch_module(
            module_uuid=args.module_uuid,
            user_nt=args.user_nt,
            server_url=args.server_url,
            init_timeout=args.init_timeout,
            call_timeout=args.call_timeout,
            refresh=args.refresh,
        )
    except RuntimeError as exc:
        print(f"[doors_fetch] {exc}", file=sys.stderr)
        return 1

    code = result.get("code")
    print(f"[STEP] get_doors_module -> code={code} message={result.get('message', '')!r}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    size = out_path.stat().st_size
    print(f"[OK] wrote {out_path} ({size:,} bytes)")

    rows = (result.get("data") or {}).get("rows") if isinstance(result.get("data"), dict) else None
    if isinstance(rows, list):
        print(f"[INFO] rows: {len(rows)}")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
