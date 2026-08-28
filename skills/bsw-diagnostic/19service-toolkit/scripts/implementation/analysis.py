from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .models import SnapshotDIDInfo
from .notes_parser import NotesRules, parse_impl_notes


@dataclass
class SignalItem:
    raw: str
    kind: str
    container: str = ""
    field: str = ""
    call: str = ""


@dataclass
class Evidence:
    signal_items: List[SignalItem] = field(default_factory=list)
    notes_rules: NotesRules = field(default_factory=NotesRules)
    has_getter: bool = False
    has_struct_fields: bool = False
    has_plain_signals: bool = False
    has_global_fields: bool = False
    notes_lower: str = ""
    source_kind: str = ""
    can_generate: bool = False
    reason: str = ""
    strategy: Optional[str] = None


def parse_impl_signal_list(raw: str) -> List[SignalItem]:
    items: List[SignalItem] = []
    for part in [p.strip() for p in raw.split(";") if p.strip()]:
        if part.endswith(")"):
            items.append(SignalItem(raw=part, kind="getter", call=part))
            continue
        if "." in part:
            container, field = part.split(".", 1)
            # Heuristic: names with all-caps prefix / message-like stem behave like signal structs.
            kind = "struct_field" if container[:1].isupper() or container.startswith("NMSG_") or container.startswith("RBMESG_") else "global_field"
            items.append(SignalItem(raw=part, kind=kind, container=container, field=field))
            continue
        items.append(SignalItem(raw=part, kind="signal", container=part))
    return items


def collect_evidence(did: SnapshotDIDInfo, project_notes_override: dict | None = None) -> Evidence:
    ev = Evidence()
    ev.notes_lower = (did.impl_notes or "").lower()
    ev.notes_rules = parse_impl_notes(did.impl_notes or "")

    if project_notes_override:
        if project_notes_override.get("rules"):
            ev.notes_rules.rules = [
                _coerce_rule_dict(rule_dict) for rule_dict in project_notes_override.get("rules", [])
            ]
        if project_notes_override.get("symbols"):
            ev.notes_rules.referenced_symbols = project_notes_override.get("symbols", [])
        project_strategy_hint = project_notes_override.get("strategy_hint")
    else:
        project_strategy_hint = None

    if not (did.impl_notes or "").strip():
        ev.reason = "missing_impl_notes"
        return ev

    # Prefer symbols parsed from impl_notes.  Fall back to the legacy
    # impl_signal_list only when present so current workspaces remain usable
    # during the transition to notes-only input.
    note_symbols = ev.notes_rules.referenced_symbols
    source_text = ";".join(note_symbols) if note_symbols else did.impl_signal_list

    ev.signal_items = parse_impl_signal_list(source_text)
    if not ev.signal_items:
        if any(token in ev.notes_lower for token in ("battery", "voltage", "power supply", "supply voltage")):
            ev.source_kind = "getter"
            ev.strategy = "getter_scaled_byte"
            ev.can_generate = True
            ev.reason = "ready"
            return ev
        ev.reason = "empty_impl_notes_symbols"
        return ev

    ev.has_getter = any(item.kind == "getter" for item in ev.signal_items)
    ev.has_struct_fields = any(item.kind == "struct_field" for item in ev.signal_items)
    ev.has_plain_signals = any(item.kind == "signal" for item in ev.signal_items)
    ev.has_global_fields = any(item.kind == "global_field" for item in ev.signal_items)
    rule_kinds = {rule.kind for rule in ev.notes_rules.rules}

    # Project-local rule derivation is authoritative when present.
    if project_strategy_hint == "getter_scaled_byte":
        ev.source_kind = "getter"
        ev.strategy = "getter_scaled_byte"
        ev.can_generate = True
        ev.reason = "ready"
        return ev

    if project_strategy_hint == "scalar_copy_sequence":
        ev.source_kind = "scalar_sequence"
        ev.strategy = "scalar_copy_sequence"
        ev.can_generate = True
        ev.reason = "ready"
        return ev

    if project_strategy_hint == "struct_be_with_qualifier":
        ev.source_kind = "struct_field"
        ev.strategy = "struct_be_with_qualifier"
        ev.can_generate = True
        ev.reason = "ready"
        return ev

    if project_strategy_hint == "struct_be_with_qualifier_and_scaling":
        if ev.has_struct_fields:
            ev.source_kind = "struct_field"
            ev.strategy = "struct_be_with_qualifier_and_scaling"
            ev.can_generate = True
            ev.reason = "ready"
            return ev

    if project_strategy_hint == "single_byte_bit_pack":
        ev.source_kind = "bit_pack"
        ev.strategy = "single_byte_bit_pack"
        ev.can_generate = True
        ev.reason = "ready"
        return ev

    if project_strategy_hint == "simple_nibble_pack":
        ev.source_kind = "nibble_pack"
        ev.strategy = "simple_nibble_pack"
        ev.can_generate = True
        ev.reason = "ready"
        return ev

    if project_strategy_hint == "mixed_pack_scaffold":
        ev.source_kind = "mixed_pack"
        ev.strategy = "mixed_pack_scaffold"
        ev.can_generate = True
        ev.reason = "ready"
        return ev

    if project_strategy_hint == "state_pack_scaffold":
        ev.source_kind = "state_pack"
        ev.strategy = "state_pack_scaffold"
        ev.can_generate = True
        ev.reason = "ready"
        return ev

    if project_strategy_hint == "hybrid_three_byte":
        ev.source_kind = "hybrid_three_byte"
        ev.strategy = "hybrid_three_byte"
        ev.can_generate = True
        ev.reason = "ready"
        return ev

    # Fallback generic evidence-driven selection remains available when the
    # workspace parser did not produce a strategy hint.
    if len(ev.signal_items) == 1 and (ev.has_getter or "scaled_copy" in rule_kinds or "direct_copy" in rule_kinds):
        if any(token in ev.notes_lower for token in ("battery", "voltage", "power supply", "supply voltage")):
            ev.source_kind = "getter"
            ev.strategy = "getter_scaled_byte"
            ev.can_generate = True
            ev.reason = "ready"
            return ev

    if len(ev.signal_items) == 1 and ev.has_getter:
        ev.source_kind = "getter"
        ev.strategy = "getter_scaled_byte"
        ev.can_generate = True
        ev.reason = "ready"
        return ev

    if all(item.kind == "signal" for item in ev.signal_items) and did.size_bytes == len(ev.signal_items):
        ev.source_kind = "scalar_sequence"
        ev.strategy = "scalar_copy_sequence"
        ev.can_generate = True
        ev.reason = "ready"
        return ev

    if all(rule.kind in ("direct_copy", "scaled_copy") for rule in ev.notes_rules.rules) and len(ev.notes_rules.rules) == did.size_bytes:
        if all(item.kind == "signal" for item in ev.signal_items):
            ev.source_kind = "scalar_sequence"
            ev.strategy = "scalar_copy_sequence"
            ev.can_generate = True
            ev.reason = "ready"
            return ev

    if ev.has_struct_fields and all(item.kind == "struct_field" for item in ev.signal_items):
        has_range_copy = any(rule.kind in ("range_copy", "range_copy_big_endian") for rule in ev.notes_rules.rules)
        if project_notes_override and project_notes_override.get("strategy_hint") == "struct_be_with_qualifier_and_scaling":
            ev.source_kind = "struct_field"
            ev.strategy = "struct_be_with_qualifier_and_scaling"
            ev.can_generate = True
            ev.reason = "ready"
            return ev
        if project_notes_override and project_notes_override.get("strategy_hint") == "struct_be_with_qualifier":
            ev.source_kind = "struct_field"
            ev.strategy = "struct_be_with_qualifier"
            ev.can_generate = True
            ev.reason = "ready"
            return ev
        if "qualifier" in ev.notes_lower and ("big-endian" in ev.notes_lower or has_range_copy):
            if "scaling" in ev.notes_lower and "offset" in ev.notes_lower:
                ev.source_kind = "struct_field"
                ev.strategy = "struct_be_with_qualifier_and_scaling"
                ev.can_generate = True
                ev.reason = "ready"
                return ev
            if "0xff" in ev.notes_lower:
                ev.source_kind = "struct_field"
                ev.strategy = "struct_be_with_qualifier"
                ev.can_generate = True
                ev.reason = "ready"
                return ev

    if did.size_bytes == 1 and all(item.kind == "signal" for item in ev.signal_items):
        if any(rule.kind == "bit_pack" for rule in ev.notes_rules.rules) or all(f"bit{i}=" in ev.notes_lower for i in range(min(len(ev.signal_items), 6))):
            ev.source_kind = "bit_pack"
            ev.strategy = "single_byte_bit_pack"
            ev.can_generate = True
            ev.reason = "ready"
            return ev
        if len(ev.signal_items) == 2 and "low nibble" in ev.notes_lower and "high nibble" in ev.notes_lower:
            ev.source_kind = "nibble_pack"
            ev.strategy = "simple_nibble_pack"
            ev.can_generate = True
            ev.reason = "ready"
            return ev

    if did.size_bytes == 1 and ev.notes_lower:
        has_state_terms = any(token in ev.notes_lower for token in (
            "lower bits", "upper bits", "operation mode", "dynamic apply", "system state"
        ))
        has_condition_terms = any(token in ev.notes_lower for token in (
            "depends on", "influences", "based on"
        ))
        if has_state_terms and has_condition_terms:
            ev.source_kind = "state_pack"
            ev.strategy = "state_pack_scaffold"
            ev.can_generate = True
            ev.reason = "ready"
            return ev

    if did.size_bytes > 1 and ev.notes_lower:
        has_mixed_sources = len({item.kind for item in ev.signal_items}) > 1
        has_byte_layout = any(rule.kind == "byte_pack" for rule in ev.notes_rules.rules) or "byte0" in ev.notes_lower or "byte 0" in ev.notes_lower
        if has_mixed_sources and has_byte_layout:
            ev.source_kind = "mixed_pack"
            ev.strategy = "mixed_pack_scaffold"
            ev.can_generate = True
            ev.reason = "ready"
            return ev

    if did.size_bytes == 3 and ev.notes_lower:
        has_signal = any(item.kind == "signal" for item in ev.signal_items)
        has_struct_field = any(item.kind == "struct_field" for item in ev.signal_items)
        has_data_mapping = {rule.target_byte for rule in ev.notes_rules.rules if rule.kind in ("direct_copy", "scaled_copy", "conditional_copy")}
        if has_signal and has_struct_field and {0, 1, 2}.issubset(has_data_mapping):
            ev.source_kind = "hybrid_three_byte"
            ev.strategy = "hybrid_three_byte"
            ev.can_generate = True
            ev.reason = "ready"
            return ev

    if ev.notes_lower:
        ev.reason = "no_matching_project_style"
    else:
        ev.reason = "insufficient_impl_notes"
    return ev


def _coerce_rule_dict(rule_dict: dict):
    class _Rule:
        pass

    obj = _Rule()
    for key, value in rule_dict.items():
        setattr(obj, key, value)
    if not hasattr(obj, "target_end_byte"):
        obj.target_end_byte = None
    if not hasattr(obj, "condition"):
        obj.condition = ""
    if not hasattr(obj, "true_expr"):
        obj.true_expr = ""
    if not hasattr(obj, "false_expr"):
        obj.false_expr = ""
    if not hasattr(obj, "scale_expr"):
        obj.scale_expr = ""
    if not hasattr(obj, "raw_text"):
        obj.raw_text = ""
    return obj
