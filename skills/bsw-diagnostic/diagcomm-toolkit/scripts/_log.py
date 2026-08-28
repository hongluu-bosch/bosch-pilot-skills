"""Tiny stderr logger so pipeline.py can stay framework-free.

Usage:
    from _log import info, warn, err
    info("doing thing")
    warn("non-fatal: %s", detail)
    err("fatal: %s", detail)
"""

from __future__ import annotations

import sys
from typing import Any

_PREFIX = {
    "INFO": "[doors] ",
    "WARN": "[doors][WARN] ",
    "ERR ": "[doors][ERR ] ",
}


def _emit(level: str, msg: str, *args: Any) -> None:
    text = msg % args if args else msg
    sys.stderr.write(_PREFIX[level] + text + "\n")
    sys.stderr.flush()


def info(msg: str, *args: Any) -> None:
    _emit("INFO", msg, *args)


def warn(msg: str, *args: Any) -> None:
    _emit("WARN", msg, *args)


def err(msg: str, *args: Any) -> None:
    _emit("ERR ", msg, *args)
