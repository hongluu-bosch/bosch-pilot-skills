"""Unit tests for :mod:`scripts.fscs.doors.content_hash` (v1.17.0).

Determinism is the only correctness criterion -- the hash drives
the INSERT vs UPDATE vs NOOP decision in the diff engine, so any
non-determinism (key ordering, missing-vs-empty asymmetry,
unicode normalisation drift) immediately translates to spurious
UPDATE rows or, worse, false NOOP suppression that drops a real
edit.
"""

from __future__ import annotations

import pytest

from fscs.doors.content_hash import (
    HASH_PREFIX,
    HASHED_COLUMNS,
    compute_pair_hash,
    is_valid_hash,
)


# --------------------------------------------------------------------------- #
# constants                                                                   #
# --------------------------------------------------------------------------- #


def _baseline_fs() -> dict:
    return {
        "Number": "1",
        "isPicture": "no",
        "Object Heading": "Identifier $F190h - BaselineCounter",
        "Object Text": "",
        "RB_RS_CP_Status": "accepted",
        "RB_RS_MS_Status": "accepted",
        "RB_Product": "DPB",
        "RB_Configuration": "DCOM_ReferenceDiagnosis_CUST",
        "RB_Realizing_SWComponent": "RBAPLCUST, CUBAS",
        "RB_Realizing_SWitem": "Dcm_CusDiag_Services_EcucValues_DPB.arxml",
        "RB_VerificationType": "Test",
        "RB_VerificationCriteria": "No Additional Information Necessary",
        "RB_Analysis_Results": "Result / Size Estimate / Risk",
        "RB_Referenced_Testcase": "SwT",
        "RB_TestEnvironment": "Labcar/HIL",
    }


def _baseline_cs() -> dict:
    cs = _baseline_fs()
    cs["Object Heading"] = ""
    cs["Object Text"] = (
        "Description\nThis identifier returns the BaselineCounter\n"
        "\nBehavior:\nstep 1: read DCOM_BaselineCounter\n"
    )
    cs["RB_Realizing_SWitem"] = "RBAPLCUST_F190_BaselineCounter.c"
    cs["RB_Referenced_Testcase"] = "CT"
    cs["RB_TestEnvironment"] = "SIL Simulation"
    return cs


# --------------------------------------------------------------------------- #
# format / shape                                                              #
# --------------------------------------------------------------------------- #


def test_hash_returns_well_formed_sha256_string():
    h = compute_pair_hash(fs_cells=_baseline_fs(), cs_cells=_baseline_cs())
    assert h.startswith(HASH_PREFIX)
    assert len(h) == len(HASH_PREFIX) + 64
    assert is_valid_hash(h)


def test_is_valid_hash_rejects_garbage():
    assert is_valid_hash(None) is False
    assert is_valid_hash("") is False
    assert is_valid_hash("plain string") is False
    assert is_valid_hash("sha256:not-hex-XXX") is False
    assert is_valid_hash(HASH_PREFIX + "a" * 63) is False  # too short
    assert is_valid_hash(HASH_PREFIX + "a" * 65) is False  # too long


def test_hashed_columns_excludes_destination_object_and_absolute_number():
    """The 15 hashed columns must NOT include the two state-machine
    output columns; otherwise the very first UPDATE breaks NOOP."""
    assert "Destination Object" not in HASHED_COLUMNS
    assert "Absolute Number" not in HASHED_COLUMNS
    assert len(HASHED_COLUMNS) == 15


# --------------------------------------------------------------------------- #
# determinism                                                                 #
# --------------------------------------------------------------------------- #


def test_hash_is_stable_across_repeated_calls():
    h1 = compute_pair_hash(fs_cells=_baseline_fs(), cs_cells=_baseline_cs())
    h2 = compute_pair_hash(fs_cells=_baseline_fs(), cs_cells=_baseline_cs())
    assert h1 == h2


def test_hash_is_independent_of_dict_insertion_order():
    """Same cells in different insertion order must hash identically;
    Python 3.7+ dicts preserve insertion order so this is a real
    risk if the canonicalisation skips ``sort_keys=True``."""
    fs1 = _baseline_fs()
    fs2 = dict(reversed(list(fs1.items())))
    cs = _baseline_cs()
    h1 = compute_pair_hash(fs_cells=fs1, cs_cells=cs)
    h2 = compute_pair_hash(fs_cells=fs2, cs_cells=cs)
    assert h1 == h2


def test_missing_key_hashes_identically_to_explicit_empty_string():
    """If a future column gets added to the template, an old row
    that omitted it should still hash the same as a new row that
    explicitly sets it to ''."""
    fs_with = _baseline_fs()
    fs_with["Object Text"] = ""
    fs_without = _baseline_fs()
    del fs_without["Object Text"]
    h1 = compute_pair_hash(fs_cells=fs_with, cs_cells=_baseline_cs())
    h2 = compute_pair_hash(fs_cells=fs_without, cs_cells=_baseline_cs())
    assert h1 == h2


def test_extra_unhashed_keys_are_ignored():
    """RowCtx may carry bookkeeping fields the operator never sees
    (did_name, role, ...). Those must NOT change the hash."""
    fs_padded = _baseline_fs()
    fs_padded["did_name"] = "BaselineCounter"        # not a DOORS column
    fs_padded["service"] = "22"                       # not a DOORS column
    fs_padded["Destination Object"] = "401"           # explicitly excluded
    fs_padded["Absolute Number"] = ""                 # explicitly excluded
    h1 = compute_pair_hash(fs_cells=_baseline_fs(), cs_cells=_baseline_cs())
    h2 = compute_pair_hash(fs_cells=fs_padded, cs_cells=_baseline_cs())
    assert h1 == h2


def test_trailing_whitespace_per_cell_is_ignored():
    """xlsxwriter sometimes pads cells with a trailing newline.
    Treat it as whitespace noise -- a cell with and without
    trailing whitespace must hash identically."""
    fs_clean = _baseline_fs()
    fs_padded = _baseline_fs()
    fs_padded["RB_Product"] = "DPB   \n"
    h1 = compute_pair_hash(fs_cells=fs_clean, cs_cells=_baseline_cs())
    h2 = compute_pair_hash(fs_cells=fs_padded, cs_cells=_baseline_cs())
    assert h1 == h2


def test_leading_whitespace_per_cell_is_significant():
    """Object Text indentation is meaningful for the Behaviour
    section -- DOORS preserves leading whitespace and so must we.
    Two rows with different leading whitespace must hash differently."""
    fs_clean = _baseline_fs()
    fs_indented = _baseline_fs()
    fs_indented["Object Heading"] = "    Identifier $F190h - BaselineCounter"
    h1 = compute_pair_hash(fs_cells=fs_clean, cs_cells=_baseline_cs())
    h2 = compute_pair_hash(fs_cells=fs_indented, cs_cells=_baseline_cs())
    assert h1 != h2


def test_unicode_in_object_text_round_trips():
    """Chinese DID names and behaviour text must hash deterministically
    (operator-side fscs sometimes carries DID name in CN)."""
    cs = _baseline_cs()
    cs["Object Text"] = "描述\n此 DID 返回基线计数器\n"
    h1 = compute_pair_hash(fs_cells=_baseline_fs(), cs_cells=cs)
    h2 = compute_pair_hash(fs_cells=_baseline_fs(), cs_cells=cs)
    assert h1 == h2


# --------------------------------------------------------------------------- #
# sensitivity: cell change -> hash change                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("column", list(HASHED_COLUMNS))
def test_changing_any_hashed_column_changes_the_hash(column):
    """Sweep every hashed column; mutating its FS-row value must
    flip the hash. If a future refactor accidentally drops a
    column from the canonicalisation set, this test fires."""
    fs_baseline = _baseline_fs()
    cs = _baseline_cs()
    h_base = compute_pair_hash(fs_cells=fs_baseline, cs_cells=cs)

    fs_mutated = _baseline_fs()
    fs_mutated[column] = (str(fs_mutated.get(column, "")) + "_X").strip("_X") + "_X"
    h_mut = compute_pair_hash(fs_cells=fs_mutated, cs_cells=cs)
    assert h_base != h_mut, f"column {column!r} change did NOT alter the hash"


def test_cs_only_change_still_changes_the_hash():
    """A common operator workflow: tweak the Behaviour section
    without touching the heading. The CS row's Object Text changes;
    the FS row stays. Must still trigger UPDATE, not NOOP."""
    fs = _baseline_fs()
    cs1 = _baseline_cs()
    cs2 = _baseline_cs()
    cs2["Object Text"] = cs2["Object Text"] + "step 2: convert to UDS scale\n"
    h1 = compute_pair_hash(fs_cells=fs, cs_cells=cs1)
    h2 = compute_pair_hash(fs_cells=fs, cs_cells=cs2)
    assert h1 != h2


def test_destination_object_is_never_part_of_the_hash():
    """The whole point: INSERT row gets Destination Object = anchor;
    UPDATE row blanks it. If Destination Object were hashed, every
    INSERT->UPDATE transition would force one false UPDATE."""
    fs1 = _baseline_fs()
    fs2 = _baseline_fs()
    fs2["Destination Object"] = "401"
    h1 = compute_pair_hash(fs_cells=fs1, cs_cells=_baseline_cs())
    h2 = compute_pair_hash(fs_cells=fs2, cs_cells=_baseline_cs())
    assert h1 == h2


def test_absolute_number_is_never_part_of_the_hash():
    """Same reasoning: UPDATE row writes Absolute Number = recorded;
    INSERT row blanks it. Hashing it would break the very first NOOP."""
    fs1 = _baseline_fs()
    fs2 = _baseline_fs()
    fs2["Absolute Number"] = "401"
    h1 = compute_pair_hash(fs_cells=fs1, cs_cells=_baseline_cs())
    h2 = compute_pair_hash(fs_cells=fs2, cs_cells=_baseline_cs())
    assert h1 == h2
