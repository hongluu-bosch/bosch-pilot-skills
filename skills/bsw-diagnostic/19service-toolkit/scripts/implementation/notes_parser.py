from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import List


@dataclass
class DataRule:
    target_byte: int
    kind: str
    target_end_byte: int | None = None
    source: str = ""
    condition: str = ""
    true_expr: str = ""
    false_expr: str = ""
    scale_expr: str = ""
    raw_text: str = ""


@dataclass
class NotesRules:
    rules: List[DataRule] = field(default_factory=list)
    referenced_symbols: List[str] = field(default_factory=list)
    raw_notes: str = ""


def parse_impl_notes(notes: str) -> NotesRules:
    text = (notes or "").strip()
    rules = NotesRules(raw_notes=text)
    if not text:
        return rules

    normalized = _normalize_notes(text)
    segments = [seg.strip() for seg in re.split(r"[;；]\s*", normalized) if seg.strip()]

    for seg in segments:
        rule = _parse_conditional_assignment(seg)
        if rule is None:
            rule = _parse_data_range_assignment(seg)
        if rule is None:
            rule = _parse_data_assignment(seg)
        if rule is None:
            rule = _parse_bit_assignment(seg)
        if rule is None:
            rule = _parse_byte_usage(seg)
        if rule is not None:
            rules.rules.append(rule)

    rules.referenced_symbols = _extract_symbols(text)
    return rules


def _normalize_notes(text: str) -> str:
    replacements = {
        "直接收": "=",
        "则": "then",
        "否则": "else",
        "，": ",",
        "；": ";",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def _parse_data_assignment(segment: str) -> DataRule | None:
    m = re.search(r"Data\[(\d+)\]\s*=\s*(.+)", segment, flags=re.IGNORECASE)
    if not m:
        return None
    target = int(m.group(1))
    expr = m.group(2).strip()
    scale_expr = ""
    scale_match = re.search(r"([A-Za-z0-9_\.]+)\s*(\*[0-9.]+|/[0-9.]+)", expr)
    if scale_match:
        scale_expr = scale_match.group(2)
    return DataRule(
        target_byte=target,
        kind="scaled_copy" if scale_expr else "direct_copy",
        source=expr,
        scale_expr=scale_expr,
        raw_text=segment,
    )


def _parse_data_range_assignment(segment: str) -> DataRule | None:
    m = re.search(r"Data\[(\d+)\s*-\s*(\d+)\]\s*=\s*(.+)", segment, flags=re.IGNORECASE)
    if not m:
        return None
    start = int(m.group(1))
    end = int(m.group(2))
    expr = m.group(3).strip()
    kind = "range_copy"
    if "big-endian" in expr.lower():
        kind = "range_copy_big_endian"
        expr = re.sub(r"\bbig-endian\b", "", expr, flags=re.IGNORECASE).strip()
    return DataRule(
        target_byte=start,
        target_end_byte=end,
        kind=kind,
        source=expr,
        raw_text=segment,
    )


def _parse_conditional_assignment(segment: str) -> DataRule | None:
    m = re.search(
        r"if\s+(.+?)\s+then\s+Data\[(\d+)\]\s*=\s*(.+?)\s+else\s+Data\[\2\]\s*=\s*(.+)",
        segment,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    return DataRule(
        target_byte=int(m.group(2)),
        kind="conditional_copy",
        condition=m.group(1).strip(),
        true_expr=m.group(3).strip(),
        false_expr=m.group(4).strip(),
        raw_text=segment,
    )


def _parse_bit_assignment(segment: str) -> DataRule | None:
    m = re.search(r"bit(\d+(?:-\d+)?)\s*=\s*(.+)", segment, flags=re.IGNORECASE)
    if not m:
        return None
    return DataRule(
        target_byte=0,
        kind="bit_pack",
        source=m.group(2).strip(),
        raw_text=segment,
    )


def _parse_byte_usage(segment: str) -> DataRule | None:
    m = re.search(r"byte\s*(\d+)\s+uses\s+(.+)", segment, flags=re.IGNORECASE)
    if not m:
        return None
    return DataRule(
        target_byte=int(m.group(1)),
        kind="byte_pack",
        source=m.group(2).strip(),
        raw_text=segment,
    )


def _extract_symbols(text: str) -> List[str]:
    found = re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)?(?:\(\))?", text)
    # Drop obvious keywords and duplicates while preserving order.
    ignore = {"Data", "if", "then", "else", "bit", "byte"}
    result: List[str] = []
    seen = set()
    for item in found:
        base = item.split(".", 1)[0].split("(", 1)[0]
        if base in ignore:
            continue
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
