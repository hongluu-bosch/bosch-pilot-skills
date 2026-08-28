#!/usr/bin/env python
"""Common helpers for ALM WorkItem read/write scripts."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://cprds.apac.bosch.com/rtc-mb-wi"
DEFAULT_API_KEY = "rjpF9z4Q07BHT5i"
DEFAULT_RETRIES = 2
DEFAULT_RETRY_DELAY_SEC = 1


def parse_json_or_text(raw_text: str) -> Any:
    if not raw_text:
        return None
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return raw_text


def request_http(
    method: str,
    url: str,
    api_key: str,
    timeout: int,
    body: bytes | None = None,
    content_type: str | None = None,
    extra_headers: dict[str, str] | None = None,
    retries: int = DEFAULT_RETRIES,
    retry_delay_sec: int = DEFAULT_RETRY_DELAY_SEC,
) -> tuple[int, Any]:
    headers = {
        "apikey": api_key,
        "ApiKey": api_key,
        "Accept": "application/json",
        "User-Agent": "alm-workitem-read-write-script/1.0",
        "Connection": "close",
    }
    if content_type:
        headers["Content-Type"] = content_type
    if extra_headers:
        headers.update(extra_headers)

    request = Request(url=url, data=body, headers=headers, method=method)

    attempts = max(1, retries + 1)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return response.status, parse_json_or_text(raw)
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            return exc.code, parse_json_or_text(raw)
        except URLError as exc:
            last_error = exc
        except Exception as exc:
            last_error = exc

        if attempt < attempts - 1:
            time.sleep(retry_delay_sec)

    raise RuntimeError(f"HTTP request failed after {attempts} attempts: {last_error}") from last_error


def ensure_output_path(path_arg: str | None, default_path: Path) -> Path:
    path = Path(path_arg) if path_arg else default_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_result(path: Path, result: dict[str, Any]) -> None:
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
