#!/usr/bin/env python
"""Upload a file as WorkItem attachment."""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

from _wi_http import DEFAULT_API_KEY, DEFAULT_BASE_URL, ensure_output_path, request_http, write_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload ALM WorkItem attachment.")
    parser.add_argument("workitem_id", help="WorkItem/Task ID, e.g. 6741996")
    parser.add_argument("file", help="File path to upload.")
    parser.add_argument("--field-name", default="file_name", help="Multipart form field name.")
    parser.add_argument("--out", help="Output JSON path.")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="API key.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL.")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds.")
    return parser.parse_args()


def build_multipart(field_name: str, file_path: Path, boundary: str) -> bytes:
    file_bytes = file_path.read_bytes()
    filename = file_path.name
    mime = "application/octet-stream"

    header = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"{field_name}\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8")
    footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return header + file_bytes + footer


def main() -> int:
    args = parse_args()
    if not args.workitem_id.isdigit():
        print(f"[FAILED] Invalid WorkItem ID: {args.workitem_id}")
        return 2

    file_path = Path(args.file)
    if not file_path.exists() or not file_path.is_file():
        print(f"[FAILED] File not found: {file_path}")
        return 2

    boundary = f"----WIFormBoundary{secrets.token_hex(16)}"
    body = build_multipart(args.field_name, file_path, boundary)
    content_type = f"multipart/form-data; boundary={boundary}"

    url = f"{args.base_url}/post/UpdateWorkItemAttachment/{args.workitem_id}"
    out_path = ensure_output_path(
        args.out,
        Path("output") / f"alm_workitem_upload_attachment_{args.workitem_id}_{file_path.name}.json",
    )

    try:
        status, data = request_http(
            "POST",
            url,
            args.api_key,
            args.timeout,
            body=body,
            content_type=content_type,
            extra_headers={"Content-Length": str(len(body))},
        )
    except Exception as exc:
        write_result(
            out_path,
            {
                "ok": False,
                "status": None,
                "url": url,
                "workitem_id": args.workitem_id,
                "file": str(file_path),
                "error": str(exc),
            },
        )
        print("[FAILED] Upload attachment failed.")
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
            "file": str(file_path),
            "file_size": os.path.getsize(file_path),
            "data": data,
        },
    )
    print("[SUCCESS] Upload attachment completed." if ok else "[FAILED] Upload attachment failed.")
    print(f"[INFO] WorkItem ID: {args.workitem_id}")
    print(f"[INFO] File: {file_path}")
    print(f"[INFO] HTTP status: {status}")
    print(f"[INFO] Output: {out_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
