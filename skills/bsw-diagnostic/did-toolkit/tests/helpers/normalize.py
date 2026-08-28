"""Moderate whitespace / timestamp normalization for golden-file comparisons.

Policy chosen by user on 2026-04-20 (``normalize_moderate``):

* Replace any ``Generated[ on]: <timestamp>`` line with a stable sentinel.
* Strip trailing whitespace at end of every line.
* Collapse runs of >=3 consecutive newlines down to a single blank line.
* Keep every comment (``/*DE|...*/``, doxygen ``* ...`` blocks, ``//`` lines,
  ``#`` shell comments) because those lines are behavior contracts for the
  downstream BSW build and we want tests to catch accidental drift.

The resulting text ends with exactly one trailing newline so that minor
editor-added/dropped final newlines don't cause spurious diffs.
"""

from __future__ import annotations

import difflib
import re
from typing import Iterable

_TIMESTAMP_LINE = re.compile(
    r"^(?P<prefix>\s*(?:\*\s*)?)[Gg]enerated(?:\s+on)?:\s+.*$",
    re.MULTILINE,
)
_CHINESE_TIMESTAMP_LINE = re.compile(
    r"^(?P<prefix>\s*(?:\*\s*)?)生成时间:\s+.*$",
    re.MULTILINE,
)
# fscs.json / generator-meta fields that carry non-deterministic paths
# or timestamps. These are JSON key/value pairs so the match is anchored
# on the double-quoted key form rather than a bare label.
_JSON_TIMESTAMP_FIELD = re.compile(
    r'"generated_at"\s*:\s*"[^"]*"',
)
_JSON_SOURCE_INPUTS_FIELD = re.compile(
    r'"source_inputs"\s*:\s*"[^"]*"',
)
_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_RUN = re.compile(r"\n{3,}")
_CRLF = re.compile(r"\r\n?")


def normalize_text(s: str) -> str:
    """Return ``s`` after moderate normalization (see module docstring)."""
    s = _CRLF.sub("\n", s)
    s = _TIMESTAMP_LINE.sub(lambda m: f"{m.group('prefix')}Generated: <timestamp>", s)
    s = _CHINESE_TIMESTAMP_LINE.sub(
        lambda m: f"{m.group('prefix')}生成时间: <timestamp>", s
    )
    # Stabilise fscs.json provenance fields so tmp_path-leaking values
    # don't cause spurious diffs. We match only the exact JSON keys
    # (not any plaintext occurrences) so non-JSON files are unaffected.
    s = _JSON_TIMESTAMP_FIELD.sub('"generated_at": "<timestamp>"', s)
    s = _JSON_SOURCE_INPUTS_FIELD.sub('"source_inputs": "<source>"', s)
    s = _TRAILING_WS.sub("", s)
    s = _BLANK_RUN.sub("\n\n", s)
    return s.rstrip("\n") + "\n"


def unified_diff(expected: str, actual: str, expected_label: str, actual_label: str) -> str:
    """Return a unified-diff string suitable as an assertion message."""
    diff: Iterable[str] = difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        fromfile=expected_label,
        tofile=actual_label,
        n=3,
    )
    body = "".join(diff)
    if not body:
        return f"Files differ but unified_diff produced no output.\n  expected: {expected_label}\n  actual:   {actual_label}"
    return f"Golden mismatch (normalized):\n{body}"
