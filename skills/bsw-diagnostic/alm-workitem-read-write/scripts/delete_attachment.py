#!/usr/bin/env python
"""Delete a WorkItem attachment by attachment ID."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _wi_http import DEFAULT_API_KEY, DEFAULT_BASE_URL, ensure_output_path, request_http, write_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete ALM WorkItem attachment.")
    parser.add_argument("workitem_id", help="WorkItem/Task ID, e.g. 6741996")
    parser.add_argument("attachment_id", help="Attachment ID to delete.")
    parser.add_argument("--out", help="Output JSON path.")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="API key.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL.")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout in seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.workitem_id.isdigit() or not args.attachment_id.isdigit():
        print("[FAILED] workitem_id and attachment_id must be numeric.")
        return 2

    url = (
        f"{args.base_url}/post/UpdateWorkItemAttachment/"
        f"{args.workitem_id},delete,{args.attachment_id}"
    )
    out_path = ensure_output_path(
        args.out,
        Path("output") / f"alm_workitem_delete_attachment_{args.workitem_id}_{args.attachment_id}.json",
    )

    try:
        status, data = request_http("POST", url, args.api_key, args.timeout)
    except Exception as exc:
        write_result(
            out_path,
            {
                "ok": False,
                "status": None,
                "url": url,
                "workitem_id": args.workitem_id,
                "attachment_id": args.attachment_id,
                "error": str(exc),
            },
        )
        print("[FAILED] Delete attachment failed.")
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
            "attachment_id": args.attachment_id,
            "data": data,
        },
    )
    print("[SUCCESS] Delete attachment completed." if ok else "[FAILED] Delete attachment failed.")
    print(f"[INFO] WorkItem ID: {args.workitem_id}")
    print(f"[INFO] Attachment ID: {args.attachment_id}")
    print(f"[INFO] HTTP status: {status}")
    print(f"[INFO] Output: {out_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
