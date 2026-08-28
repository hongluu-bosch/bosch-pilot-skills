#!/usr/bin/env python
"""Read ALM WorkItem info by WorkItem ID."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _wi_http import DEFAULT_API_KEY, DEFAULT_BASE_URL, ensure_output_path, request_http, write_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read ALM WorkItem info.")
    parser.add_argument("workitem_id", help="WorkItem/Task ID, e.g. 6741996")
    parser.add_argument("--out", help="Output JSON path.")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="API key.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL.")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout in seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.workitem_id.isdigit():
        print(f"[FAILED] Invalid WorkItem ID: {args.workitem_id}")
        return 2

    url = f"{args.base_url}/get/workitem/{args.workitem_id}"
    out_path = ensure_output_path(args.out, Path("output") / f"alm_workitem_get_{args.workitem_id}.json")

    try:
        status, data = request_http("GET", url, args.api_key, args.timeout)
    except Exception as exc:
        write_result(
            out_path,
            {
                "ok": False,
                "status": None,
                "url": url,
                "error": str(exc),
            },
        )
        print("[FAILED] Read WorkItem failed.")
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
            "data": data,
        },
    )
    print("[SUCCESS] Read WorkItem completed." if ok else "[FAILED] Read WorkItem failed.")
    print(f"[INFO] WorkItem ID: {args.workitem_id}")
    print(f"[INFO] HTTP status: {status}")
    print(f"[INFO] Output: {out_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
