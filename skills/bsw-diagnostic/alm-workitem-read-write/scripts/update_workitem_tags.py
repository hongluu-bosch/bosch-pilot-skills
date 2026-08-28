#!/usr/bin/env python
"""Update ALM WorkItem Tags by WorkItem ID."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _wi_http import DEFAULT_API_KEY, DEFAULT_BASE_URL, ensure_output_path, request_http, write_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update ALM WorkItem Tags.")
    parser.add_argument("workitem_id", help="WorkItem/Task ID, e.g. 6741996")
    parser.add_argument("--json", dest="json_text", help="JSON payload string.")
    parser.add_argument("--json-file", help="JSON payload file path.")
    parser.add_argument("--out", help="Output JSON path.")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="API key.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL.")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout in seconds.")
    return parser.parse_args()


def load_payload(json_text: str | None, json_file: str | None) -> dict[str, object]:
    if bool(json_text) == bool(json_file):
        raise ValueError("Use exactly one of --json or --json-file.")

    raw = json_text
    source = "--json"
    if json_file:
        raw = Path(json_file).read_text(encoding="utf-8")
        source = json_file

    try:
        payload = json.loads(raw or "")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON payload from {source}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object, e.g. {'Tags': 'BB52625'}.")
    return payload


def main() -> int:
    args = parse_args()
    if not args.workitem_id.isdigit():
        print(f"[FAILED] Invalid WorkItem ID: {args.workitem_id}")
        return 2

    try:
        payload = load_payload(args.json_text, args.json_file)
    except Exception as exc:
        print(f"[FAILED] {exc}")
        return 2

    url = f"{args.base_url}/post/UpdateWorkItem/{args.workitem_id}"
    out_path = ensure_output_path(args.out, Path("output") / f"alm_workitem_update_{args.workitem_id}.json")

    try:
        status, data = request_http(
            "POST",
            url,
            args.api_key,
            args.timeout,
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )
    except Exception as exc:
        write_result(
            out_path,
            {
                "ok": False,
                "status": None,
                "url": url,
                "workitem_id": args.workitem_id,
                "payload": payload,
                "error": str(exc),
            },
        )
        print("[FAILED] Update WorkItem Tags failed.")
        print(f"[INFO] Output: {out_path}")
        print(f"[ERROR] {exc}")
        return 1

    ok = 200 <= status < 300
    write_result(
        out_path,
        {
            "ok": ok,
            "status": status,
            "url": url,
            "workitem_id": args.workitem_id,
            "payload": payload,
            "data": data,
        },
    )
    print("[SUCCESS] Update WorkItem Tags completed." if ok else "[FAILED] Update WorkItem Tags failed.")
    print(f"[INFO] WorkItem ID: {args.workitem_id}")
    print(f"[INFO] HTTP status: {status}")
    print(f"[INFO] Output: {out_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
