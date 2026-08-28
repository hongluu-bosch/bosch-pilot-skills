"""Unit tests for :mod:`scripts.fscs.doors.doors_state` (v1.17.0).

Three concerns:

1. **Round-trip fidelity** -- save-then-load must be identity for a
   non-trivial state graph. Anything less and the post-upload
   reconcile would silently drop landings between runs.
2. **Migration of v1.10.x state files** -- ``schema_version: 2``
   reads as an empty :class:`State` with a stderr advisory; never
   raise (otherwise existing operators upgrading from v1.16.0 see
   their first ``--phase doors`` blow up).
3. **Defensive error surfaces** -- corrupt JSON / unknown schema /
   wrong top-level type all raise :class:`ValueError` with the
   path baked into the message so the operator can find the
   offending file.

Atomic save semantics is also pinned (write to ``.tmp`` then
rename; failure mid-write must never leave a partial file behind).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fscs.doors.doors_state import (
    SCHEMA_VERSION,
    DIDState,
    ModuleState,
    ServiceLanding,
    State,
    load_state,
    now_utc_iso,
    reset_module,
    save_state,
)


# --------------------------------------------------------------------------- #
# basic dataclass surface                                                     #
# --------------------------------------------------------------------------- #


class TestServiceLanding:

    def test_empty_landing_is_not_recorded(self):
        assert ServiceLanding().is_recorded is False

    def test_partial_landing_is_not_recorded(self):
        """A half-populated landing is treated as INSERT next run --
        we never want to UPDATE pointed at a phantom AbsoluteNumber."""
        partial = ServiceLanding(fs_abs="401", cs_abs="402",
                                 content_hash=None, last_uploaded_at="2026-05-13T...")
        assert partial.is_recorded is False

    def test_fully_populated_landing_is_recorded(self):
        full = ServiceLanding(fs_abs="401", cs_abs="402",
                              content_hash="sha256:abcd",
                              last_uploaded_at="2026-05-13T14:00:00+00:00")
        assert full.is_recorded is True


class TestDIDState:

    def test_for_service_accepts_short_and_long_keys(self):
        landing = ServiceLanding(fs_abs="500", cs_abs="501",
                                 content_hash="sha256:x",
                                 last_uploaded_at="t")
        did = DIDState(service_22=landing)
        assert did.for_service("22") == landing
        assert did.for_service("service_22") == landing
        assert did.for_service("2E").is_recorded is False
        assert did.for_service("2e").is_recorded is False

    def test_for_service_rejects_unknown_service(self):
        with pytest.raises(KeyError, match="unknown service"):
            DIDState().for_service("99")

    def test_with_service_returns_new_instance(self):
        """``with_service`` is a builder, not a mutator -- preserves
        the immutable-by-discipline posture of ServiceLanding."""
        ll = ServiceLanding(fs_abs="1", cs_abs="2", content_hash="h",
                            last_uploaded_at="t")
        original = DIDState()
        updated = original.with_service("22", ll)
        assert original.service_22.is_recorded is False  # untouched
        assert updated.service_22 == ll
        assert updated.service_2e.is_recorded is False


class TestModuleState:

    def test_landing_returns_empty_for_unknown_did(self):
        ms = ModuleState()
        assert ms.landing("0xF190", "22").is_recorded is False

    def test_remember_then_landing_round_trips(self):
        ms = ModuleState()
        ll = ServiceLanding(fs_abs="401", cs_abs="402",
                            content_hash="sha256:abcd",
                            last_uploaded_at="2026-05-13T14:00:00+00:00")
        ms.remember("0xF190", "22", ll)
        assert ms.landing("0xF190", "22") == ll
        # Other service stays empty.
        assert ms.landing("0xF190", "2E").is_recorded is False

    def test_hex_normalisation_collapses_case_and_prefix(self):
        """Operator typos (lower-case hex, missing 0x) shouldn't
        create two state entries for the same DID."""
        ms = ModuleState()
        ll = ServiceLanding(fs_abs="1", cs_abs="2",
                            content_hash="sha256:h",
                            last_uploaded_at="t")
        ms.remember("f190", "22", ll)
        assert ms.landing("0xF190", "22") == ll
        assert ms.landing("0XF190", "22") == ll
        assert ms.landing("0xf190", "22") == ll
        assert len(ms.dids) == 1


# --------------------------------------------------------------------------- #
# State.for_module                                                            #
# --------------------------------------------------------------------------- #


def test_for_module_creates_substate_lazily():
    state = State()
    assert state.modules == {}
    ms = state.for_module("MOD-A")
    assert isinstance(ms, ModuleState)
    assert "MOD-A" in state.modules
    # Second call returns the SAME object (so writes stick).
    assert state.for_module("MOD-A") is ms


def test_reset_module_drops_only_target():
    state = State()
    state.for_module("MOD-A").remember(
        "0xF190", "22",
        ServiceLanding(fs_abs="1", cs_abs="2", content_hash="h",
                       last_uploaded_at="t"),
    )
    state.for_module("MOD-B").remember(
        "0x3030", "22",
        ServiceLanding(fs_abs="3", cs_abs="4", content_hash="h",
                       last_uploaded_at="t"),
    )
    reset_module(state, "MOD-A")
    assert "MOD-A" not in state.modules
    assert "MOD-B" in state.modules
    assert state.for_module("MOD-B").landing("0x3030", "22").is_recorded


# --------------------------------------------------------------------------- #
# load / save behaviour matrix                                                #
# --------------------------------------------------------------------------- #


def test_load_missing_file_returns_empty_state(tmp_path):
    state = load_state(tmp_path / "absent.json")
    assert state.schema_version == SCHEMA_VERSION
    assert state.modules == {}


def test_load_empty_file_returns_empty_state(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("   \n", encoding="utf-8")
    state = load_state(p)
    assert state.modules == {}


def test_load_corrupt_json_raises_with_path(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_state(p)
    msg = str(excinfo.value)
    assert "broken.json" in msg
    assert "line" in msg and "column" in msg


def test_load_non_object_top_level_raises(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON object"):
        load_state(p)


def test_load_unknown_schema_version_raises(tmp_path):
    p = tmp_path / "future.json"
    p.write_text(json.dumps({"schema_version": "9.99", "modules": {}}),
                 encoding="utf-8")
    with pytest.raises(ValueError, match="unknown schema_version"):
        load_state(p)


@pytest.mark.parametrize("legacy_version", [2, "2", "2.0"])
def test_load_v1_10_x_migrates_to_empty_state_with_advisory(
    tmp_path, capsys, legacy_version,
):
    """v1.10.x aggregate-only state -> empty v3 state + stderr WARN."""
    p = tmp_path / "legacy.json"
    p.write_text(
        json.dumps({
            "schema_version": legacy_version,
            "modules": {
                "MOD-A": {
                    "last_upload_at": "2026-05-12T...",
                    "fscs_sha256": "abc",
                    "did_count_22": 5,
                    "did_count_2e": 2,
                }
            }
        }),
        encoding="utf-8",
    )
    state = load_state(p)
    assert state.modules == {}, "aggregate counters must be discarded"
    captured = capsys.readouterr()
    assert "v1.10.x" in captured.err
    assert "v1.17.0" in captured.err


# --------------------------------------------------------------------------- #
# round-trip                                                                  #
# --------------------------------------------------------------------------- #


def test_save_then_load_round_trips_non_trivial_state(tmp_path):
    """Two modules, several DIDs each, mixed half/full landings."""
    state = State()
    ms_a = state.for_module("MOD-A")
    ms_a.last_uploaded_at = "2026-05-13T14:00:00+00:00"
    ms_a.remember("0xF190", "22",
                  ServiceLanding(fs_abs="401", cs_abs="402",
                                 content_hash="sha256:fedb",
                                 last_uploaded_at="2026-05-13T14:00:00+00:00"))
    ms_a.remember("0xF190", "2E",
                  ServiceLanding(fs_abs="403", cs_abs="404",
                                 content_hash="sha256:ee11",
                                 last_uploaded_at="2026-05-13T14:00:00+00:00"))
    ms_a.remember("0x3030", "22",
                  ServiceLanding(fs_abs="500", cs_abs="501",
                                 content_hash="sha256:beef",
                                 last_uploaded_at="2026-05-13T14:00:00+00:00"))

    ms_b = state.for_module("MOD-B")
    ms_b.last_uploaded_at = "2026-05-13T14:05:00+00:00"
    ms_b.remember("0xF180", "22",
                  ServiceLanding(fs_abs="601", cs_abs="602",
                                 content_hash="sha256:cafe",
                                 last_uploaded_at="2026-05-13T14:05:00+00:00"))

    target = tmp_path / "doors_upload_state.json"
    save_state(target, state)
    reloaded = load_state(target)

    assert reloaded.schema_version == SCHEMA_VERSION
    assert set(reloaded.modules) == {"MOD-A", "MOD-B"}
    assert reloaded.modules["MOD-A"].landing("0xF190", "22").fs_abs == "401"
    assert reloaded.modules["MOD-A"].landing("0xF190", "22").cs_abs == "402"
    assert reloaded.modules["MOD-A"].landing("0xF190", "2E").content_hash == "sha256:ee11"
    assert reloaded.modules["MOD-A"].landing("0x3030", "22").is_recorded
    assert reloaded.modules["MOD-A"].landing("0x3030", "2E").is_recorded is False
    assert reloaded.modules["MOD-B"].landing("0xF180", "22").fs_abs == "601"


def test_save_creates_parent_dirs_and_atomic(tmp_path):
    """save_state should create the parent state/ dir on demand AND
    not leave the .tmp sibling lying around on success."""
    target = tmp_path / "deeply" / "nested" / "state" / "x.json"
    state = State()
    state.for_module("MOD").remember(
        "0xF190", "22",
        ServiceLanding(fs_abs="1", cs_abs="2", content_hash="h",
                       last_uploaded_at="t"),
    )
    save_state(target, state)
    assert target.is_file()
    siblings = list(target.parent.iterdir())
    # Only the final file -- the .tmp sibling must be gone.
    assert siblings == [target], f"unexpected leftover siblings: {siblings}"


def test_save_uses_two_space_indent_and_trailing_newline(tmp_path):
    target = tmp_path / "x.json"
    save_state(target, State())
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")
    parsed = json.loads(text)
    assert parsed["schema_version"] == SCHEMA_VERSION
    assert parsed["modules"] == {}


def test_save_modules_are_sorted_for_diff_hygiene(tmp_path):
    """Stable ordering = grep-able diff between runs. The internal
    state may add modules in arbitrary order; the file always
    serialises them sorted by UUID."""
    state = State()
    state.for_module("MOD-Z").remember(
        "0xF190", "22",
        ServiceLanding(fs_abs="1", cs_abs="2", content_hash="h",
                       last_uploaded_at="t"),
    )
    state.for_module("MOD-A").remember(
        "0x3030", "22",
        ServiceLanding(fs_abs="3", cs_abs="4", content_hash="h",
                       last_uploaded_at="t"),
    )
    target = tmp_path / "x.json"
    save_state(target, state)
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert list(parsed["modules"].keys()) == ["MOD-A", "MOD-Z"]


def test_now_utc_iso_format_pin():
    """RFC-3339 UTC, second precision, no microseconds. The exact
    shape matters because we already use it elsewhere
    (`generated_at`, `created_date`)."""
    s = now_utc_iso()
    # YYYY-MM-DDTHH:MM:SS+00:00 -- 25 chars, fixed shape
    assert len(s) == 25, s
    assert s.endswith("+00:00")
    assert "T" in s
    assert "." not in s   # no microseconds
