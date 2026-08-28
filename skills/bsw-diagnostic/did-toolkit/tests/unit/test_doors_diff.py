"""Unit tests for :mod:`scripts.fscs.doors.diff` (v1.17.0).

The diff engine is pure: ``(state, module_uuid, current_hashes)``
in, ``ActionPlan`` out, no I/O. The tests sweep the four-bucket
classification matrix (INSERT / UPDATE / NOOP / STALE) plus the
two structural concerns:

1. **Per-module isolation** -- a recorded landing under MOD-A
   must NEVER bleed into a run targeting MOD-B (the operator's
   "module re-target" scenario; v1.17.0 design decision 2A).
2. **Selector + summary helpers** -- ``ActionPlan.for_workbook``
   and ``ActionPlan.summary`` are what the orchestrator actually
   consumes; pin their behaviour so a refactor of the dataclass
   internals can't accidentally drop NOOPs into the workbook.
"""

from __future__ import annotations

import pytest

from fscs.doors.diff import (
    ActionPlan,
    DIDAction,
    compute_action_plan,
    format_plan_summary,
    format_plan_table,
)
from fscs.doors.doors_state import (
    DIDState,
    ModuleState,
    ServiceLanding,
    State,
)


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


def _state_with_landing(
    *,
    module_uuid: str = "MOD-A",
    did_hex: str = "0xF190",
    service: str = "22",
    fs_abs: str = "401",
    cs_abs: str = "402",
    content_hash: str = "sha256:" + "a" * 64,
) -> State:
    """Build a ``State`` with one recorded landing -- the unit-test
    base case."""
    state = State()
    state.for_module(module_uuid).remember(
        did_hex, service,
        ServiceLanding(
            fs_abs=fs_abs, cs_abs=cs_abs,
            content_hash=content_hash,
            last_uploaded_at="2026-05-13T00:00:00+00:00",
        ),
    )
    return state


# --------------------------------------------------------------------------- #
# four-bucket classification                                                  #
# --------------------------------------------------------------------------- #


class TestInsert:

    def test_empty_state_classifies_every_did_as_insert(self):
        plan = compute_action_plan(
            state=State(),
            module_uuid="MOD-A",
            current_hashes={
                "22": {"0xF190": "sha256:" + "a" * 64,
                       "0x3030": "sha256:" + "b" * 64},
                "2E": {"0x3030": "sha256:" + "c" * 64},
            },
        )
        assert plan.summary() == {"INSERT": 3, "UPDATE": 0, "NOOP": 0, "STALE": 0}
        for action in plan.actions:
            assert action.action == "INSERT"
            assert action.fs_abs is None
            assert action.cs_abs is None
            assert action.current_hash is not None
            assert action.previous_hash is None

    def test_state_for_different_module_does_not_protect_against_insert(self):
        """Operator switched from MOD-A to MOD-B mid-workflow.
        The MOD-B run must see a clean slate -- never apply MOD-A's
        recorded AbsoluteNumbers against MOD-B's rows.

        v1.17.0 design decision 2A: the schema multiplexes by
        module UUID so isolation is automatic, no explicit drift
        detection needed."""
        state = _state_with_landing(module_uuid="MOD-A", did_hex="0xF190")
        plan = compute_action_plan(
            state=state,
            module_uuid="MOD-B",   # different module
            current_hashes={"22": {"0xF190": "sha256:" + "z" * 64}},
        )
        assert plan.summary()["INSERT"] == 1
        assert plan.summary()["UPDATE"] == 0


class TestUpdate:

    def test_recorded_did_with_changed_hash_classifies_as_update(self):
        state = _state_with_landing(content_hash="sha256:" + "a" * 64)
        plan = compute_action_plan(
            state=state,
            module_uuid="MOD-A",
            current_hashes={"22": {"0xF190": "sha256:" + "z" * 64}},
        )
        assert plan.summary() == {"INSERT": 0, "UPDATE": 1, "NOOP": 0, "STALE": 0}
        action = plan.actions[0]
        assert action.action == "UPDATE"
        assert action.fs_abs == "401"
        assert action.cs_abs == "402"
        assert action.current_hash == "sha256:" + "z" * 64
        assert action.previous_hash == "sha256:" + "a" * 64


class TestNoop:

    def test_recorded_did_with_matching_hash_classifies_as_noop(self):
        state = _state_with_landing(content_hash="sha256:" + "a" * 64)
        plan = compute_action_plan(
            state=state,
            module_uuid="MOD-A",
            current_hashes={"22": {"0xF190": "sha256:" + "a" * 64}},
        )
        assert plan.summary() == {"INSERT": 0, "UPDATE": 0, "NOOP": 1, "STALE": 0}
        action = plan.actions[0]
        assert action.action == "NOOP"
        assert action.fs_abs == "401"
        assert action.cs_abs == "402"
        assert action.previous_hash == action.current_hash

    def test_noop_actions_are_excluded_from_for_workbook(self):
        """v1.17.0 design decision 1A: NOOP rows are omitted from
        the workbook entirely. ``ActionPlan.for_workbook`` is the
        selector the orchestrator uses; pin that NOOPs never leak
        through it."""
        state = _state_with_landing(content_hash="sha256:" + "a" * 64)
        plan = compute_action_plan(
            state=state,
            module_uuid="MOD-A",
            current_hashes={"22": {"0xF190": "sha256:" + "a" * 64}},
        )
        assert plan.for_workbook("22") == []


class TestStale:

    def test_recorded_did_missing_from_current_fscs_is_stale(self):
        state = _state_with_landing(did_hex="0xF190")
        plan = compute_action_plan(
            state=state,
            module_uuid="MOD-A",
            current_hashes={"22": {}, "2E": {}},
        )
        assert plan.summary() == {"INSERT": 0, "UPDATE": 0, "NOOP": 0, "STALE": 1}
        action = plan.actions[0]
        assert action.action == "STALE"
        assert action.fs_abs == "401"
        assert action.cs_abs == "402"
        assert action.current_hash is None  # no current rendering

    def test_stale_actions_are_excluded_from_for_workbook(self):
        """STALE rows are warn-only -- never make it into the
        workbook (DOORS-side delete deferred to v1.18.x)."""
        state = _state_with_landing(did_hex="0xF190")
        plan = compute_action_plan(
            state=state,
            module_uuid="MOD-A",
            current_hashes={"22": {}, "2E": {}},
        )
        assert plan.for_workbook("22") == []


class TestPerService:

    def test_did_with_per_service_split_classifies_each_service_independently(self):
        """The same DID may be effective in service_22 and STALE
        in service_2e (operator deselected $2E for that DID).
        Each service's classification must be independent."""
        state = State()
        # Both services landed previously.
        for service in ("22", "2E"):
            state.for_module("MOD-A").remember(
                "0xF190", service,
                ServiceLanding(
                    fs_abs="40" + service[0], cs_abs="41" + service[0],
                    content_hash="sha256:" + ("a" if service == "22" else "b") * 64,
                    last_uploaded_at="t",
                ),
            )
        # Current FSCS only has service_22 effective; the hash matches.
        plan = compute_action_plan(
            state=state,
            module_uuid="MOD-A",
            current_hashes={"22": {"0xF190": "sha256:" + "a" * 64}},
        )
        assert plan.summary() == {"INSERT": 0, "UPDATE": 0, "NOOP": 1, "STALE": 1}
        # service_22 is NOOP, service_2e is STALE.
        s22 = [a for a in plan.actions if a.service == "22"][0]
        s2e = [a for a in plan.actions if a.service == "2E"][0]
        assert s22.action == "NOOP"
        assert s2e.action == "STALE"


# --------------------------------------------------------------------------- #
# selectors / hex normalisation                                               #
# --------------------------------------------------------------------------- #


def test_input_hex_is_normalised_to_canonical_form():
    """Operator-typed lower-case or no-prefix hex must collapse to
    the canonical 0xUPPER form so the state lookup succeeds."""
    state = _state_with_landing(did_hex="0xF190")
    plan = compute_action_plan(
        state=state,
        module_uuid="MOD-A",
        current_hashes={"22": {"f190": "sha256:" + "a" * 64}},  # lower, no prefix
    )
    # If normalisation didn't happen we'd get INSERT (state lookup miss).
    assert plan.summary()["NOOP"] == 1
    assert plan.actions[0].did_hex == "0xF190"


def test_action_list_preserves_fscs_iteration_order():
    """Workbook layout follows FSCS-file order, not alphabetical
    order. ``build_doors_payload`` populates ``current_hashes`` by
    walking DIDBlocks in the order they appear in
    ``FSCS_22.txt`` / ``FSCS_2E.txt``, so ``compute_action_plan``
    must keep that order intact -- the operator and the v1.16.0
    payload tests both rely on it.

    Within each service we expect the iteration order of the input
    dict; across services we expect 22 before 2E (the order
    ``SERVICES`` enumerates them).
    """
    state = State()
    plan = compute_action_plan(
        state=state,
        module_uuid="MOD-A",
        current_hashes={
            "22": {"0xC003": "x", "0xA001": "y"},  # NB: not alpha sorted
            "2E": {"0xB002": "z"},
        },
    )
    keys = [(a.service, a.did_hex) for a in plan.actions]
    assert keys == [("22", "0xC003"), ("22", "0xA001"), ("2E", "0xB002")]


def test_format_plan_table_renders_in_bucketed_order():
    """The on-disk plan table re-imposes ``(action, service,
    did_hex)`` order at render time so operators get a clean
    bucketed view even though the raw plan is FSCS-ordered."""
    from diff import format_plan_table  # local import: tiny module surface

    state = State()
    plan = compute_action_plan(
        state=state,
        module_uuid="MOD-A",
        current_hashes={
            "22": {"0xC003": "x", "0xA001": "y"},
            "2E": {"0xB002": "z"},
        },
    )
    rendered = format_plan_table(plan)
    # All three are INSERT, so within the rendered table they
    # should be alpha-sorted by (service, did_hex).
    body_lines = [ln for ln in rendered.splitlines() if ln.startswith("INSERT")]
    seen = [(ln.split("\t")[1], ln.split("\t")[2]) for ln in body_lines]
    assert seen == [("22", "0xA001"), ("22", "0xC003"), ("2E", "0xB002")]


def test_summary_counts_every_action():
    state = _state_with_landing(did_hex="0xF190")
    plan = compute_action_plan(
        state=state,
        module_uuid="MOD-A",
        current_hashes={
            "22": {
                "0xF190": "sha256:" + "z" * 64,    # UPDATE
                "0x3030": "sha256:" + "y" * 64,    # INSERT
            },
            "2E": {},
        },
    )
    s = plan.summary()
    assert sum(s.values()) == len(plan.actions)
    assert s == {"INSERT": 1, "UPDATE": 1, "NOOP": 0, "STALE": 0}


# --------------------------------------------------------------------------- #
# format helpers (operator-facing output)                                     #
# --------------------------------------------------------------------------- #


def test_format_plan_summary_one_liner():
    plan = ActionPlan(
        module_uuid="MOD-A",
        actions=[
            DIDAction(did_hex="0xF190", service="22", action="INSERT",
                      current_hash="sha256:" + "a" * 64),
            DIDAction(did_hex="0x3030", service="22", action="UPDATE",
                      fs_abs="500", cs_abs="501",
                      current_hash="sha256:" + "b" * 64,
                      previous_hash="sha256:" + "c" * 64),
        ],
    )
    s = format_plan_summary(plan)
    assert "MOD-A" in s
    assert "1 INSERT" in s
    assert "1 UPDATE" in s
    assert "0 NOOP" in s
    assert "0 STALE" in s


def test_format_plan_table_has_one_data_line_per_action():
    plan = ActionPlan(
        module_uuid="MOD-A",
        actions=[
            DIDAction(did_hex="0xF190", service="22", action="INSERT",
                      current_hash="sha256:x"),
            DIDAction(did_hex="0x3030", service="2E", action="STALE",
                      fs_abs="600", cs_abs="601",
                      previous_hash="sha256:y"),
        ],
    )
    table = format_plan_table(plan)
    lines = table.split("\n")
    # header + summary + blank + data lines
    data_lines = [l for l in lines if l.startswith(("INSERT", "UPDATE", "NOOP", "STALE"))]
    # filter out the summary line that also begins with "Plan ..."
    data_lines = [l for l in data_lines if "\t" in l]
    assert len(data_lines) == 2
    assert data_lines[0].startswith("INSERT\t22\t0xF190\t-\t-")
    assert data_lines[1].startswith("STALE\t2E\t0x3030\t600\t601")


def test_format_plan_table_handles_empty_plan():
    plan = ActionPlan(module_uuid="MOD-A", actions=[])
    table = format_plan_table(plan)
    assert "(empty plan" in table
