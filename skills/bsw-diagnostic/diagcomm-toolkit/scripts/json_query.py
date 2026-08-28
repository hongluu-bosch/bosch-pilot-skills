"""Lightweight JSON query for diagcomm-toolkit (Step 7.5 / 8 helpers).

We deliberately avoid jsonpath-ng (extra dep). Supported syntax is a tiny
subset that covers the patterns DOORS exports actually need:

    a.b.c                       nested keys
    a.b[0].c                    integer index
    a.b[*].c                    wildcard over a list -> list of results
    a.b[?key=='value'].id       filter list-of-dicts by exact equality
                                (single quotes only; value may be empty)

Public API:
    query(data, path) -> list[Any]   (always a list; empty if nothing matched)
    query_one(data, path, *, default=_RAISE) -> Any
        returns the first match; raises KeyError if no match and no default.
"""

from __future__ import annotations

import re
from typing import Any, List

_TOKEN_RE = re.compile(
    r"""
    (?P<key>[A-Za-z_][\w\-]*)
    | \[ (?P<idx>-?\d+) \]
    | \[\*\]
    | \[ \? (?P<filt_key>[A-Za-z_][\w\-]*)
        \s* == \s* '(?P<filt_val>[^']*)' \]
    | \.
    """,
    re.VERBOSE,
)

_RAISE = object()


def _tokenize(path: str) -> List[tuple]:
    pos = 0
    tokens: List[tuple] = []
    while pos < len(path):
        m = _TOKEN_RE.match(path, pos)
        if not m:
            raise ValueError(f"json_query: bad token at pos {pos} in {path!r}")
        if m.group("key"):
            tokens.append(("key", m.group("key")))
        elif m.group("idx"):
            tokens.append(("idx", int(m.group("idx"))))
        elif m.group("filt_key"):
            tokens.append(("filt", m.group("filt_key"), m.group("filt_val")))
        elif m.group(0) == "[*]":
            tokens.append(("wild",))
        elif m.group(0) == ".":
            pass
        else:
            raise ValueError(f"json_query: unhandled token {m.group(0)!r}")
        pos = m.end()
    return tokens


def query(data: Any, path: str) -> List[Any]:
    """Return all values matching `path`. Always a list (possibly empty)."""
    tokens = _tokenize(path)
    current: List[Any] = [data]
    for tok in tokens:
        nxt: List[Any] = []
        kind = tok[0]
        if kind == "key":
            (_, key) = tok
            for item in current:
                if isinstance(item, dict) and key in item:
                    nxt.append(item[key])
        elif kind == "idx":
            (_, idx) = tok
            for item in current:
                if isinstance(item, list) and -len(item) <= idx < len(item):
                    nxt.append(item[idx])
        elif kind == "wild":
            for item in current:
                if isinstance(item, list):
                    nxt.extend(item)
                elif isinstance(item, dict):
                    nxt.extend(item.values())
        elif kind == "filt":
            (_, fkey, fval) = tok
            for item in current:
                if not isinstance(item, list):
                    continue
                for el in item:
                    if isinstance(el, dict) and str(el.get(fkey, "")) == fval:
                        nxt.append(el)
        else:
            raise ValueError(f"json_query: unknown token kind {kind!r}")
        current = nxt
    return current


def query_one(data: Any, path: str, *, default: Any = _RAISE) -> Any:
    """Return the first match; raise KeyError if none and no default."""
    results = query(data, path)
    if results:
        return results[0]
    if default is _RAISE:
        raise KeyError(f"json_query: no match for {path!r}")
    return default
