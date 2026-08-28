"""Unit tests for ``scripts.fscs.product_workset.compute_workset``.

Phase 2 / Phase 3 fan out over the set of products that actually
appear on a ``used`` DID in ``fscs.json`` — there is no
``--product-type`` CLI flag. ``compute_workset`` is the single
decision point — these tests pin its filtering rules so a
regression here would silently change which products get built and
which DIDs land in which output directory.

Pinned rules:

1. ``used_flag``-driven: only DIDs where
   ``service_22.used or service_2e.used`` contribute.
2. Empty / missing ``product_type`` collapses to ``Common`` (legacy
   "applies everywhere" semantics).
3. Case-insensitive matching against the recognised whitelist
   (``DPB`` / ``ESP`` / ``ESPCL`` / ``IPB`` / ``RBU`` / ``Common``)
   with canonical output spelling (upper-case for production
   products, title-case for ``Common``).
4. Unrecognised non-empty values raise
   :class:`UnknownProductTypeError` — Phase 2 / 3 surface this as a
   fail-loud (Q6).
"""

from __future__ import annotations

import pytest

from fscs.product_workset import (
    RECOGNISED_PRODUCTS,
    UnknownProductTypeError,
    compute_workset,
    phase2_alias_source_for,
    phase2_alias_target_for,
)
from fscs.schema import (
    DIDFscsEntry,
    FSCSDocument,
    FSCSSecurityLevel,
    FSCSServiceAccess,
)
from implementation.paths import COMMON_TOKEN


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_product_scope.py to keep tests self-contained)
# ---------------------------------------------------------------------------


def _make_service(*, supported=True, used=True):
    return FSCSServiceAccess(
        supported=supported,
        used=used,
        sessions=["defaultSession"],
        security_levels=[FSCSSecurityLevel(level="L0")],
    )


def _make_did(*, did_hex, did_name, product_type=None,
              service_22=None, service_2e=None):
    return DIDFscsEntry(
        did_hex=did_hex,
        did_name=did_name,
        data_type="Unsigned",
        storage_position="EEPROM",
        size_bytes=4,
        rw_state="R",
        nvm_item="NVM_ID_DCOM_TEST",
        service_22=service_22 or _make_service(),
        service_2e=service_2e or _make_service(supported=False, used=False),
        product_type=product_type,
    )


# ---------------------------------------------------------------------------
# Whitelist sanity
# ---------------------------------------------------------------------------


class TestRecognisedProducts:
    def test_canonical_six_entries(self):
        # Pin so a future cull / addition is a deliberate test edit.
        assert RECOGNISED_PRODUCTS == frozenset({
            "DPB", "ESP", "ESPCL", "IPB", "RBU", COMMON_TOKEN,
        })

    def test_common_token_uses_titlecase_literal(self):
        # The work-set tuple feeds straight into resolve_path; the
        # title-case literal ``Common`` is the spelling that
        # round-trips through Bosch-tree directory naming.
        assert COMMON_TOKEN in RECOGNISED_PRODUCTS
        assert "COMMON" not in RECOGNISED_PRODUCTS
        assert "common" not in RECOGNISED_PRODUCTS


# ---------------------------------------------------------------------------
# used_flag filter (Q1)
# ---------------------------------------------------------------------------


class TestUsedFlagFilter:
    def test_skips_did_with_both_services_unused(self):
        document = FSCSDocument(dids=[
            _make_did(
                did_hex="F190", did_name="Off",
                service_22=_make_service(used=False),
                service_2e=_make_service(supported=False, used=False),
                product_type="DPB",
            ),
        ])
        ws = compute_workset(document)
        assert ws.products == ()
        assert ws.used_did_count == 0
        assert ws.is_empty()

    def test_picks_did_when_service_22_used(self):
        document = FSCSDocument(dids=[
            _make_did(did_hex="F190", did_name="A", product_type="DPB"),
        ])
        ws = compute_workset(document)
        assert ws.products == ("DPB",)
        assert ws.used_did_count == 1

    def test_picks_did_when_only_service_2e_used(self):
        document = FSCSDocument(dids=[
            _make_did(
                did_hex="F190", did_name="WriteOnly",
                service_22=_make_service(used=False),
                service_2e=_make_service(supported=True, used=True),
                product_type="ESP",
            ),
        ])
        ws = compute_workset(document)
        assert ws.products == ("ESP",)
        assert ws.used_did_count == 1


# ---------------------------------------------------------------------------
# Empty product_type → Common collapse (Q5 lenient default)
# ---------------------------------------------------------------------------


class TestEmptyProductTypeCollapse:
    def test_none_becomes_common(self):
        document = FSCSDocument(dids=[
            _make_did(did_hex="F190", did_name="A", product_type=None),
        ])
        ws = compute_workset(document)
        assert ws.products == (COMMON_TOKEN,)

    def test_empty_string_becomes_common(self):
        # Pydantic accepts ``""`` for an Optional[str] field; the
        # work-set must treat empty same as None (CSV operators may
        # leave the cell blank rather than removing the column).
        document = FSCSDocument(dids=[
            _make_did(did_hex="F190", did_name="A", product_type=""),
        ])
        ws = compute_workset(document)
        assert ws.products == (COMMON_TOKEN,)

    def test_whitespace_only_becomes_common(self):
        document = FSCSDocument(dids=[
            _make_did(did_hex="F190", did_name="A", product_type="   "),
        ])
        ws = compute_workset(document)
        assert ws.products == (COMMON_TOKEN,)


# ---------------------------------------------------------------------------
# Case-insensitive matching → canonical spelling
# ---------------------------------------------------------------------------


class TestCanonicalSpelling:
    def test_lower_case_input_normalises_to_upper(self):
        document = FSCSDocument(dids=[
            _make_did(did_hex="F190", did_name="A", product_type="dpb"),
        ])
        ws = compute_workset(document)
        assert ws.products == ("DPB",)

    def test_mixed_case_common_normalises_to_titlecase(self):
        for spelling in ("Common", "common", "COMMON", "CoMmOn"):
            document = FSCSDocument(dids=[
                _make_did(did_hex="F190", did_name="A",
                          product_type=spelling),
            ])
            ws = compute_workset(document)
            assert ws.products == (COMMON_TOKEN,), \
                f"spelling {spelling!r} failed"

    def test_dedup_across_did_rows(self):
        document = FSCSDocument(dids=[
            _make_did(did_hex="F190", did_name="A", product_type="DPB"),
            _make_did(did_hex="F191", did_name="B", product_type="dpb"),
            _make_did(did_hex="F192", did_name="C", product_type="DPB"),
        ])
        ws = compute_workset(document)
        assert ws.products == ("DPB",)


# ---------------------------------------------------------------------------
# Display order (production products first, Common last)
# ---------------------------------------------------------------------------


class TestDisplayOrder:
    def test_production_products_alphabetical(self):
        document = FSCSDocument(dids=[
            _make_did(did_hex="F190", did_name="A", product_type="RBU"),
            _make_did(did_hex="F191", did_name="B", product_type="DPB"),
            _make_did(did_hex="F192", did_name="C", product_type="IPB"),
            _make_did(did_hex="F193", did_name="D", product_type="ESP"),
        ])
        ws = compute_workset(document)
        # DPB < ESP < IPB < RBU per _PRODUCT_DISPLAY_ORDER.
        assert ws.products == ("DPB", "ESP", "IPB", "RBU")

    def test_common_sorts_last(self):
        document = FSCSDocument(dids=[
            _make_did(did_hex="F190", did_name="A", product_type="Common"),
            _make_did(did_hex="F191", did_name="B", product_type="DPB"),
        ])
        ws = compute_workset(document)
        assert ws.products == ("DPB", COMMON_TOKEN)

    def test_full_workset_ordering(self):
        document = FSCSDocument(dids=[
            _make_did(did_hex=f"F19{i}", did_name=f"D{i}", product_type=p)
            for i, p in enumerate(
                ["Common", "ESPCL", "IPB", "RBU", "DPB", "ESP"]
            )
        ])
        ws = compute_workset(document)
        assert ws.products == (
            "DPB", "ESP", "ESPCL", "IPB", "RBU", COMMON_TOKEN,
        )


# ---------------------------------------------------------------------------
# Unrecognised value → UnknownProductTypeError (Q6 hard fail)
# ---------------------------------------------------------------------------


class TestUnknownProductTypeError:
    def test_typo_raises_with_did_context(self):
        document = FSCSDocument(dids=[
            _make_did(did_hex="F190", did_name="A", product_type="DPC"),
        ])
        with pytest.raises(UnknownProductTypeError) as exc_info:
            compute_workset(document)
        err = exc_info.value
        assert err.did_hex == "F190"
        assert err.raw_value == "DPC"
        assert "DPB" in err.recognised
        assert "DPC" not in err.recognised
        assert "0xF190" in str(err)
        assert "DPC" in str(err)

    def test_unrecognised_token_raises(self):
        document = FSCSDocument(dids=[
            _make_did(did_hex="F190", did_name="A",
                      product_type="MyCustomProduct"),
        ])
        with pytest.raises(UnknownProductTypeError):
            compute_workset(document)

    def test_unused_did_with_unknown_type_does_not_raise(self):
        # used_flag filter wins: an unused DID isn't part of the
        # build, so its (possibly stale / experimental)
        # product_type doesn't trigger the whitelist check.
        document = FSCSDocument(dids=[
            _make_did(
                did_hex="F190", did_name="Off",
                service_22=_make_service(used=False),
                service_2e=_make_service(supported=False, used=False),
                product_type="MyCustomProduct",
            ),
        ])
        ws = compute_workset(document)
        assert ws.products == ()


# ---------------------------------------------------------------------------
# used_did_count surfacing (for the Q5 empty-workset warning message)
# ---------------------------------------------------------------------------


class TestUsedDidCount:
    def test_counts_all_used_dids_even_when_collapsing_to_common(self):
        document = FSCSDocument(dids=[
            _make_did(did_hex="F190", did_name="A"),
            _make_did(did_hex="F191", did_name="B"),
            _make_did(did_hex="F192", did_name="C"),
        ])
        ws = compute_workset(document)
        # All three collapse to Common (no product_type set), but the
        # count still reflects all three so the user-visible warning
        # ("3 used DIDs but no product_type set") can be precise.
        assert ws.products == (COMMON_TOKEN,)
        assert ws.used_did_count == 3

    def test_count_excludes_unused(self):
        document = FSCSDocument(dids=[
            _make_did(did_hex="F190", did_name="A", product_type="DPB"),
            _make_did(
                did_hex="F191", did_name="Off",
                service_22=_make_service(used=False),
                service_2e=_make_service(supported=False, used=False),
                product_type="DPB",
            ),
        ])
        ws = compute_workset(document)
        assert ws.used_did_count == 1


# ---------------------------------------------------------------------------
# v1.24.0: Phase-2 product **path** aliases (ESPCL → ESP folder)
# ---------------------------------------------------------------------------


class TestPhase2AliasLookups:
    """Pin the lookup helpers for Phase 2's path-alias mechanism.

    The alias map (currently ``{"ESPCL": "ESP"}``) lives in
    ``scripts.fscs.product_workset._PHASE2_PRODUCT_ALIASES`` and is
    consumed via two public helpers (``phase2_alias_target_for`` and
    ``phase2_alias_source_for``); the higher-level
    ``product_type_arxml_folder`` placeholder helper lives in
    :mod:`scripts.implementation.paths` and has its own test
    coverage in ``test_path_resolution.py``.
    """

    def test_alias_target_for_known_source(self):
        assert phase2_alias_target_for("ESPCL") == "ESP"

    def test_alias_target_for_unknown_returns_none(self):
        assert phase2_alias_target_for("DPB") is None
        assert phase2_alias_target_for("ESP") is None
        assert phase2_alias_target_for("Common") is None
        assert phase2_alias_target_for("") is None
        assert phase2_alias_target_for("   ") is None
        assert phase2_alias_target_for(None) is None  # type: ignore[arg-type]

    def test_alias_target_case_insensitive(self):
        for spelling in ("ESPCL", "espcl", "EspCl"):
            assert phase2_alias_target_for(spelling) == "ESP"

    def test_alias_source_for_target(self):
        # ESP is the destination of one alias (ESPCL).
        assert phase2_alias_source_for("ESP") == ("ESPCL",)

    def test_alias_source_for_non_target(self):
        # DPB / IPB / RBU / Common have no alias source folding into them.
        for pt in ("DPB", "IPB", "RBU", "Common"):
            assert phase2_alias_source_for(pt) == ()

    def test_alias_source_case_insensitive(self):
        for spelling in ("ESP", "esp", "Esp"):
            assert phase2_alias_source_for(spelling) == ("ESPCL",)

    def test_alias_source_handles_empty(self):
        assert phase2_alias_source_for("") == ()
        assert phase2_alias_source_for("   ") == ()
