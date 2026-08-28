#!/usr/bin/env python
"""Manage ALM WorkItem Tags (add / remove) with read-before-write safety."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _wi_http import DEFAULT_API_KEY, DEFAULT_BASE_URL, ensure_output_path, request_http, write_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage ALM WorkItem Tags.")
    parser.add_argument("workitem_id", help="WorkItem/Task ID, e.g. 6741996")
    parser.add_argument("--add-tags", nargs="+", help="Tags to add.")
    parser.add_argument("--remove-tags", nargs="+", help="Tags to remove.")
    parser.add_argument("--dry-run", action="store_true", help="Print payload only, do not write.")
    parser.add_argument("--out", help="Output JSON path.")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="API key.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL.")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout in seconds.")
    return parser.parse_args()


def fetch_workitem(workitem_id: str, base_url: str, api_key: str, timeout: int) -> dict:
    url = f"{base_url}/get/workitem/{workitem_id}"
    status, data = request_http("GET", url, api_key, timeout)
    if not (200 <= status < 300):
        raise RuntimeError(f"Failed to read WorkItem {workitem_id}: HTTP {status}, data={data}")
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected response type for WorkItem {workitem_id}: {type(data)}")
    return data


def extract_current_tags(data: dict) -> list[str]:
    tags = data.get("subject")
    if tags is None:
        raise RuntimeError("Response missing 'subject' field.")
    if isinstance(tags, str):
        return [tag.strip() for tag in tags.split(",") if tag.strip()]
    if isinstance(tags, list):
        return [str(tag).strip() for tag in tags if str(tag).strip()]
    raise RuntimeError(f"Unexpected 'subject' type: {type(tags)}")


def compute_new_tags(current: list[str], add: list[str] | None, remove: list[str] | None) -> list[str]:
    tag_set = set(current)
    if add:
        for tag in add:
            tag_set.add(tag.strip())
    if remove:
        for tag in remove:
            tag_set.discard(tag.strip())
    return sorted(tag_set)


def update_workitem_tags(workitem_id: str, tags: list[str], base_url: str, api_key: str, timeout: int) -> tuple[int, object, dict[str, str]]:
    url = f"{base_url}/post/UpdateWorkItem/{workitem_id}"
    payload = {"Tags": ", ".join(tags)}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    status, data = request_http("POST", url, api_key, timeout, body=body, content_type="application/json")
    return status, data, payload


def main() -> int:
    args = parse_args()
    if not args.workitem_id.isdigit():
        print(f"[FAILED] Invalid WorkItem ID: {args.workitem_id}")
        return 2

    if not args.add_tags and not args.remove_tags:
        print("[FAILED] Must specify at least one of --add-tags or --remove-tags.")
        return 2

    print(f"[INFO] Reading WorkItem {args.workitem_id} ...")
    try:
        wi_data = fetch_workitem(args.workitem_id, args.base_url, args.api_key, args.timeout)
    except Exception as exc:
        print(f"[FAILED] {exc}")
        return 1

    try:
        current_tags = extract_current_tags(wi_data)
    except Exception as exc:
        print(f"[FAILED] {exc}")
        return 1

    print(f"[INFO] Current tags ({len(current_tags)}): {current_tags}")

    new_tags = compute_new_tags(current_tags, args.add_tags, args.remove_tags)
    print(f"[INFO] New tags     ({len(new_tags)}): {new_tags}")

    if new_tags == current_tags:
        print("[INFO] No change needed. Exiting.")
        return 0

    if args.dry_run:
        print(f"[DRY-RUN] Would update with payload: {{\"Tags\": \"{', '.join(new_tags)}\"}}")
        return 0

    print(f"[INFO] Updating WorkItem {args.workitem_id} ...")
    payload: dict[str, str] | None = None
    try:
        status, data, payload = update_workitem_tags(args.workitem_id, new_tags, args.base_url, args.api_key, args.timeout)
    except Exception as exc:
        out_path = ensure_output_path(args.out, Path("output") / f"alm_workitem_update_{args.workitem_id}.json")
        write_result(out_path, {
            "ok": False,
            "status": None,
            "workitem_id": args.workitem_id,
            "payload": payload,
            "error": str(exc),
        })
        print(f"[FAILED] Update failed: {exc}")
        return 1

    ok = 200 <= status < 300
    out_path = ensure_output_path(args.out, Path("output") / f"alm_workitem_update_{args.workitem_id}.json")
    write_result(out_path, {
        "ok": ok,
        "status": status,
        "workitem_id": args.workitem_id,
        "payload": payload,
        "data": data,
    })

    print("[SUCCESS] Tags updated." if ok else "[FAILED] Update failed.")
    print(f"[INFO] HTTP status: {status}")
    print(f"[INFO] Output: {out_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
