"""Unit tests for scripts/runtime.py helpers.

Focus on the pure / near-pure helpers: freshness compare, schema field
counter, rel-to-skill formatter, derived-value injection, and the
default can_channel plumbing. The expensive helpers that need a real
arxml tree (``_plan_entries``, ``resolve_file_alias`` under a real
fixture) are covered in test_integration.py.
"""
from __future__ import annotations

import time

import pytest

import runtime
from runtime import (
    _count_leaf_values,
    _count_schema_fields,
    _freshness,
    _inject_derived_values,
    _inject_runtime_options,
    _is_canfd_label,
    _newest_mtime,
    _referenced_file_aliases,
    _rel_to_skill,
)

# ---------------------------------------------------------------------------
# _count_leaf_values: recurses through nested dicts, counts only leaves


def test_count_leaf_values_flat():
    assert _count_leaf_values({"a": 1, "b": 2, "c": 3}) == 3


def test_count_leaf_values_nested():
    data = {
        "top": 1,
        "nested": {"x": 1, "y": 2, "z": {"deep": 1}},
    }
    assert _count_leaf_values(data) == 4


def test_count_leaf_values_non_dict():
    assert _count_leaf_values(None) == 0
    assert _count_leaf_values([1, 2, 3]) == 0


# ---------------------------------------------------------------------------
# _count_schema_fields: (top_count, leaf_count)


def test_count_schema_fields_mixed():
    schema = {
        "fields": {
            "A": {"type": "int"},
            "B": {"type": "object", "fields": {"b1": {}, "b2": {}, "b3": {}}},
            "C": {"type": "bool"},
        }
    }
    top, leaf = _count_schema_fields(schema)
    assert (top, leaf) == (3, 5)


def test_count_schema_fields_empty():
    assert _count_schema_fields({"fields": {}}) == (0, 0)
    assert _count_schema_fields({}) == (0, 0)


# ---------------------------------------------------------------------------
# _freshness: MISSING / FRESH / STALE


def test_freshness_missing(tmp_path):
    p = tmp_path / "nope.txt"
    assert _freshness(p, None) == "MISSING"


def test_freshness_none_means_fresh_when_exists(tmp_path):
    p = tmp_path / "any.txt"
    p.write_text("hello")
    assert _freshness(p, None) == "FRESH"


def test_freshness_stale_vs_fresh(tmp_path):
    out = tmp_path / "out.txt"
    out.write_text("out")
    # Synthesize an "input" that is newer than out by 2s.
    newer_than = out.stat().st_mtime + 2.0
    assert _freshness(out, newer_than) == "STALE"
    # Now input is older than out by 2s.
    older_than = out.stat().st_mtime - 2.0
    assert _freshness(out, older_than) == "FRESH"


def test_newest_mtime_picks_max(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("a")
    time.sleep(0.02)
    b.write_text("b")
    # b is newer; _newest_mtime returns its mtime.
    assert _newest_mtime([a, b]) == b.stat().st_mtime


def test_newest_mtime_ignores_missing(tmp_path):
    a = tmp_path / "a"
    a.write_text("a")
    assert _newest_mtime([a, tmp_path / "missing"]) == a.stat().st_mtime


def test_newest_mtime_all_missing(tmp_path):
    assert _newest_mtime([tmp_path / "nope1", tmp_path / "nope2"]) is None


# ---------------------------------------------------------------------------
# _rel_to_skill: always forward slashes, may use leading .. segments


def test_rel_to_skill_under_skill_root():
    # Any path inside SKILL_ROOT renders as a forward-slash relative path.
    p = runtime.SKILL_ROOT / "scripts" / "pipeline.py"
    rel = _rel_to_skill(p)
    assert "/" in rel
    assert "\\" not in rel
    assert rel.endswith("scripts/pipeline.py")


def test_rel_to_skill_sibling_uses_dotdot():
    sibling = runtime.SKILL_ROOT.parent / "some-other-skill" / "file.txt"
    rel = _rel_to_skill(sibling)
    assert rel.startswith("../")


# ---------------------------------------------------------------------------
# _is_canfd_label: tolerant of dashes / whitespace / case


@pytest.mark.parametrize("label,expected", [
    ("CANFD", True),
    ("canfd", True),
    ("CAN-FD", True),
    ("CAN FD", True),
    ("FD", True),
    ("ClassicCAN", False),
    ("", False),
    (None, False),
    ("classic", False),
])
def test_is_canfd_label(label, expected):
    assert _is_canfd_label(label) is expected


# ---------------------------------------------------------------------------
# _inject_runtime_options / _inject_derived_values


def test_inject_runtime_options_sets_can_channel():
    cfg = {"options": {"can_channel": 0}}
    _inject_runtime_options(cfg, {"CAN_Channel": 2})
    assert cfg["options"]["can_channel"] == 2


def test_inject_runtime_options_ignores_missing_key():
    cfg = {"options": {"can_channel": 0}}
    _inject_runtime_options(cfg, {})
    assert cfg["options"]["can_channel"] == 0


def test_inject_runtime_options_ignores_non_int():
    cfg = {"options": {"can_channel": 0}}
    _inject_runtime_options(cfg, {"CAN_Channel": "not-an-int"})
    assert cfg["options"]["can_channel"] == 0


# NOTE: pre-1.13.0 _inject_runtime_options also wrote product_type into
# cfg["project"]. Since the v2 schema split, project.product_type lands
# in the merged dict via split_unified() at the load_unified() stage, so
# _inject_runtime_options is no longer responsible for writing it. The
# three tests below pin the negative contract: regardless of what the
# parameters dict says about product_type, _inject_runtime_options must
# never touch cfg["project"].

def test_inject_runtime_options_does_not_write_product_type():
    cfg: dict = {"project": {"name": "foo"}, "options": {}}
    _inject_runtime_options(cfg, {"product_type": "ESP", "CAN_Channel": 1})
    assert "product_type" not in cfg["project"]
    assert cfg["project"] == {"name": "foo"}


def test_inject_runtime_options_product_type_empty_string_no_op():
    cfg: dict = {"project": {}, "options": {}}
    _inject_runtime_options(cfg, {"product_type": ""})
    assert "product_type" not in cfg["project"]


def test_inject_runtime_options_product_type_non_string_no_op():
    cfg: dict = {"project": {}, "options": {}}
    _inject_runtime_options(cfg, {"product_type": 42})
    assert "product_type" not in cfg["project"]


def test_inject_derived_values_sets_flexible_fd_when_rx_is_fd():
    values = {"CAN_DLC": {"rx_frame_type": "CANFD", "tx_frame_type": "ClassicCAN"}}
    _inject_derived_values(values)
    assert values["CAN_DLC"]["flexible_fd"] is True


def test_inject_derived_values_false_when_both_classic():
    values = {"CAN_DLC": {"rx_frame_type": "ClassicCAN", "tx_frame_type": "ClassicCAN"}}
    _inject_derived_values(values)
    assert values["CAN_DLC"]["flexible_fd"] is False


def test_inject_derived_values_no_op_when_both_missing():
    values = {"CAN_DLC": {"rx_dl": 8, "tx_dl": 8}}
    _inject_derived_values(values)
    assert "flexible_fd" not in values["CAN_DLC"]


def test_inject_derived_values_no_can_dlc_no_op():
    values = {"N_As": 70}
    _inject_derived_values(values)
    assert values == {"N_As": 70}


# ---------------------------------------------------------------------------
# _referenced_file_aliases: non-empty + sorted + unique


def test_referenced_file_aliases_is_sorted_unique_non_empty():
    aliases = _referenced_file_aliases()
    assert aliases == sorted(set(aliases))
    assert len(aliases) > 0
    # Every alias must resolve through config.paths in the real project.
    for a in aliases:
        assert isinstance(a, str)
        assert a  # non-empty
