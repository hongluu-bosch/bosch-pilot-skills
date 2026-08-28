#!/usr/bin/env python3
"""Thin wrapper around the DOORS MCP `upload_doors_module` and
`update_doors_links` tools.

The skill's higher-level orchestrator (`doors_sync.py`) drives this
file twice for content (one xlsx per service) and once for links.

Usage::

    python scripts/fscs/doors/doors_upload_mcp.py upload  <xlsx> <module_uuid> <user_nt> <password>
    python scripts/fscs/doors/doors_upload_mcp.py links   <xlsx> <module_uuid> <user_nt> <password>

The `links` subcommand calls `update_doors_links`; `module_uuid` for
links is the Link-Module UUID (NOT the content module). Pass the
literal string ``links-batch`` to fall through to the server's
default link module.

Both subcommands print the parsed `{code, message, data}` payload as
JSON on stdout and exit 0 on `code == 0`, 1 otherwise.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from mcp_transport import DEFAULT_SERVER_URL, MCPTransport  # noqa: E402


def _read_b64(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"upload file missing: {path}")
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def upload_module(
    *,
    excel_path: Path,
    module_uuid: str,
    user_nt: str,
    password: str,
    server_url: str = DEFAULT_SERVER_URL,
    init_timeout: int = 15,
    upload_timeout: int = 180,
) -> Dict[str, Any]:
    """POST `upload_doors_module`. Returns the parsed
    ``{code, message, data}`` dict from the server."""
    transport = MCPTransport(
        server_url=server_url,
        init_timeout=init_timeout,
        client_name="did-toolkit-doors-upload",
    )
    file_b64 = _read_b64(excel_path)
    return transport.call(
        "upload_doors_module",
        {
            "module_uuid": module_uuid,
            "user_nt": user_nt,
            "password": password,
            "file_name": excel_path.name,
            "file_base64": file_b64,
        },
        upload_timeout,
    )


def update_links(
    *,
    excel_path: Path,
    user_nt: str,
    password: str,
    module_uuid: str = "links-batch",
    server_url: str = DEFAULT_SERVER_URL,
    init_timeout: int = 15,
    upload_timeout: int = 180,
) -> Dict[str, Any]:
    """POST `update_doors_links`. The default `module_uuid` matches the
    server's default for the links endpoint."""
    transport = MCPTransport(
        server_url=server_url,
        init_timeout=init_timeout,
        client_name="did-toolkit-doors-links",
    )
    file_b64 = _read_b64(excel_path)
    return transport.call(
        "update_doors_links",
        {
            "module_uuid": module_uuid,
            "user_nt": user_nt,
            "password": password,
            "file_name": excel_path.name,
            "file_base64": file_b64,
        },
        upload_timeout,
    )


def _print_result(result: Dict[str, Any]) -> int:
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("code") == 0 else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="did-toolkit/doors_upload_mcp.py",
        description="Upload DOORS content / link xlsx via MCP.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("xlsx", help="Path to the xlsx to upload")
    common.add_argument("module_uuid", help="Target DOORS module UUID")
    common.add_argument("user_nt", help="NT username")
    common.add_argument("password", nargs="?", help="DOORS password (or set $DOORS_PWD)")
    common.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    common.add_argument("--init-timeout", type=int, default=15)
    common.add_argument("--upload-timeout", type=int, default=180)

    sub.add_parser("upload", parents=[common], help="POST upload_doors_module")
    sub.add_parser("links", parents=[common], help="POST update_doors_links")

    args = p.parse_args(argv)

    password = args.password or os.environ.get("DOORS_PWD")
    if not password:
        print("[doors_upload_mcp] ERROR: password missing (CLI arg or $DOORS_PWD)", file=sys.stderr)
        return 2

    excel_path = Path(args.xlsx)

    print("=" * 72)
    print(f"did-toolkit -> DOORS {args.cmd}")
    print("=" * 72)
    print(f"File   : {excel_path}")
    print(f"Module : {args.module_uuid}")
    print(f"User   : {args.user_nt}")
    print(f"Server : {args.server_url}")
    print("=" * 72)

    try:
        if args.cmd == "upload":
            result = upload_module(
                excel_path=excel_path,
                module_uuid=args.module_uuid,
                user_nt=args.user_nt,
                password=password,
                server_url=args.server_url,
                init_timeout=args.init_timeout,
                upload_timeout=args.upload_timeout,
            )
        else:  # links
            result = update_links(
                excel_path=excel_path,
                user_nt=args.user_nt,
                password=password,
                module_uuid=args.module_uuid,
                server_url=args.server_url,
                init_timeout=args.init_timeout,
                upload_timeout=args.upload_timeout,
            )
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[doors_upload_mcp] ERROR: {exc}", file=sys.stderr)
        return 1

    return _print_result(result)


if __name__ == "__main__":
    raise SystemExit(main())
