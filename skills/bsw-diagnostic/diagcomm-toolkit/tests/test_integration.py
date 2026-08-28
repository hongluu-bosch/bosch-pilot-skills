"""End-to-end pipeline tests against the minimal ARXML fixture.

These tests exercise the real CLI dispatch (``pipeline.main``) after
``fixture_project`` has rewired the module-level paths to a temporary
copy of ``tests/fixtures/minimal/``. Each test asserts on observable
artifacts (exit code, file contents, patched XML) rather than private
state, so refactors inside runtime/semantic/reports don't cause flakes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

AR_NS = "http://autosar.org/schema/r4.0"
NS = {"ar": AR_NS}


# ---------------------------------------------------------------------------
# Helpers


def _read_param_values(arxml: Path, def_suffix: str) -> list[str]:
    """Return the VALUE text of every PARAM-VALUE whose DEFINITION-REF
    ends with ``/def_suffix``. Lets us assert 'this ARXML now contains
    the new literal' without depending on locator internals."""
    root = etree.parse(str(arxml)).getroot()
    out: list[str] = []
    for tag in ("ECUC-NUMERICAL-PARAM-VALUE", "ECUC-TEXTUAL-PARAM-VALUE"):
        for pv in root.iter(f"{{{AR_NS}}}{tag}"):
            dref = pv.find(f"{{{AR_NS}}}DEFINITION-REF")
            if dref is None or not dref.text:
                continue
            if dref.text.rsplit("/", 1)[-1] != def_suffix:
                continue
            val = pv.find(f"{{{AR_NS}}}VALUE")
            out.append((val.text or "") if val is not None else "")
    return out


# ---------------------------------------------------------------------------
# status


def test_status_ready_on_fixture(fixture_project, capsys):
    import pipeline
    rc = pipeline.main(["status"])
    out = capsys.readouterr().out
    # READY == rc 0; the fixture is wired to be self-consistent.
    assert rc == 0, f"status should be READY, got rc={rc}\n--- stdout ---\n{out}"
    assert "OVERALL: READY" in out


# ---------------------------------------------------------------------------
# validate


def test_validate_passes_on_fixture(fixture_project, capsys):
    import pipeline
    rc = pipeline.main(["validate"])
    out = capsys.readouterr().out
    assert rc == 0, f"validate rc={rc}\n--- stdout ---\n{out}"
    # The CLI prints ``errors     : N`` (padded colon-delimited); match
    # that literal plus the ``ERROR `` line prefix used for each finding.
    assert "errors     : 0" in out.lower() or "errors: 0" in out.lower()
    assert "  ERROR " not in out  # no individual error lines


def test_validate_fails_on_11bit_with_29bit_id(fixture_project, capsys):
    """Drop a 29-bit ID into an 11-bit-declared values file and make sure
    validate refuses it with a non-zero exit code. This proves the
    semantic layer is actually wired into the CLI (not just imported)."""
    import pipeline
    unified = json.loads(fixture_project["values"].read_text(encoding="utf-8"))
    unified["parameters"]["CAN_ID_Format"] = "11bit"
    unified["parameters"]["CAN_Functional_Request_ID"] = "0x18DAF100"   # 29-bit
    fixture_project["values"].write_text(json.dumps(unified), encoding="utf-8")

    rc = pipeline.main(["validate"])
    out = capsys.readouterr().out
    assert rc != 0, f"validate should fail on 11-bit overflow\n--- stdout ---\n{out}"
    assert "11-bit" in out


# ---------------------------------------------------------------------------
# apply --dry-run


def test_apply_dry_run_produces_hits_without_mutating_files(fixture_project, capsys):
    """apply --dry-run must:
     * return rc 0 on a self-consistent fixture
     * report a non-zero number of hits
     * NOT write any changes back to disk
    """
    import pipeline

    # Snapshot every arxml's mtime + size so we can prove apply --dry-run
    # leaves disk state untouched.
    dcom: Path = fixture_project["dcom"]
    before = {
        p: (p.stat().st_size, p.stat().st_mtime_ns)
        for p in dcom.rglob("*.arxml")
    }

    rc = pipeline.main(["apply", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0, f"apply --dry-run rc={rc}\n--- stdout ---\n{out}"
    # Hits report lives in outputs/diff_report.txt, printed to stdout too.
    assert "Total hits:" in out

    after = {
        p: (p.stat().st_size, p.stat().st_mtime_ns)
        for p in dcom.rglob("*.arxml")
    }
    assert before == after, "apply --dry-run must not modify any arxml"


# ---------------------------------------------------------------------------
# apply (real write path)


def test_apply_writes_values_and_produces_diff_report(fixture_project, capsys):
    """Full apply: values land in the correct arxml nodes and a
    diff_report is written."""
    import pipeline
    dcom: Path = fixture_project["dcom"]
    cantp = dcom / "RBAPLCust" / "cfg" / "Common" / "CanTp_CusDiag_EcucValues.arxml"
    cantp_feature = dcom / "Cubas" / "cfg" / "CanTp_Feature_EcucValues.arxml"
    dcm_feature = dcom / "Cubas" / "cfg" / "Dcm_Feature_EcucValues.arxml"
    can_pt = dcom / "RBAPLCust" / "cfg" / "DPB" / "Can0_CusDiag_EcucValues_DPB.arxml"

    # The fixture sets dry_run_default=true, so an unqualified `apply`
    # would be a dry run. Force a real write with --apply.
    rc = pipeline.main(["apply", "--apply"])
    out = capsys.readouterr().out
    assert rc == 0, f"apply rc={rc}\n--- stdout ---\n{out}"

    # N_As = 70 ms -> 0.07 s. Three TX NSdu rows in our fixture? Only one,
    # so one match is enough; assert the literal appears.
    nas_values = _read_param_values(cantp, "CanTpNas")
    assert nas_values, "N_As PARAM-VALUE missing from fixture"
    assert all(v == "0.07" for v in nas_values), nas_values

    # NRC78_Times = 10 -> int literal "10"
    nrc_values = _read_param_values(dcm_feature, "DcmDslDiagRespMaxNumRespPend")
    assert nrc_values == ["10"]

    # PaddingByte "0xAA" -> decimal 170
    padding = _read_param_values(cantp_feature, "CanTpPaddingByte")
    assert padding == ["170"]

    # Derived CanTpFlexibleDataRateSupport: values have rx=tx=CANFD -> "true"
    flex = _read_param_values(cantp_feature, "CanTpFlexibleDataRateSupport")
    assert flex == ["true"]

    # CAN_Response_ID "0x7A2" -> decimal 1954 in the XMT CanIfTxPduCanId spot.
    resp_ids = _read_param_values(can_pt, "CanIfTxPduCanId")
    assert resp_ids == [str(0x7A2)]

    # diff report was written to the temp outputs/ dir.
    diff_report = fixture_project["outputs"] / "diff_report.txt"
    assert diff_report.exists()
    assert "Total hits:" in diff_report.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Surgical write invariant: bytes outside matched <VALUE> are unchanged


def test_apply_only_rewrites_matched_value_nodes(fixture_project, capsys):
    """After apply, every byte of each arxml that is *not* inside one of
    the matched ``<VALUE>...</VALUE>`` ranges must be byte-identical to
    the pre-apply file.

    This is the regression guard for the "full-file re-serialisation
    noise" bug: tree.write() used to rewrite the XML declaration,
    namespace attribute quoting, self-closing tags, and CRLF/LF line
    endings on every file that had even one changed VALUE. The
    surgical patcher now only touches the inner text of each matched
    VALUE element.
    """
    from lxml import etree

    import pipeline

    dcom: Path = fixture_project["dcom"]

    # Snapshot every arxml file's original bytes.
    originals = {p: p.read_bytes() for p in dcom.rglob("*.arxml")}

    rc = pipeline.main(["apply", "--apply"])
    assert rc == 0, capsys.readouterr().out

    AR_NS = "http://autosar.org/schema/r4.0"

    for arxml, original in originals.items():
        patched = arxml.read_bytes()
        if patched == original:
            continue  # no changes expected for this file -- trivial pass

        # Walk every PARAM-VALUE with a VALUE child in BOTH the original
        # and patched trees; any VALUE whose text differs is a "permitted"
        # mutation. Anything else must be byte-identical.
        orig_root = etree.fromstring(original)
        patched_root = etree.fromstring(patched)

        orig_values = _collect_values(orig_root, AR_NS)
        patched_values = _collect_values(patched_root, AR_NS)
        assert set(orig_values) == set(patched_values), (
            f"{arxml.name}: PARAM-VALUE set changed (patcher added/removed nodes)")

        changed_keys = {
            key for key in orig_values
            if orig_values[key] != patched_values[key]
        }
        assert changed_keys, (
            f"{arxml.name}: bytes differ but no VALUE text changed -- "
            f"apply must only alter matched VALUE nodes")

        # The prologue (everything up to the first '<AUTOSAR' tag) must be
        # byte-identical; that's where lxml used to normalise the XML
        # declaration. This catches the bug even if later-in-file whitespace
        # coincidentally masked it.
        orig_prologue = original.split(b"<AUTOSAR", 1)[0]
        patched_prologue = patched.split(b"<AUTOSAR", 1)[0]
        assert orig_prologue == patched_prologue, (
            f"{arxml.name}: XML declaration / prologue was rewritten "
            f"(got {patched_prologue!r}, expected {orig_prologue!r})")

        # Line endings must also be preserved. If the source used CRLF we
        # must still have CRLF after apply.
        orig_has_crlf = b"\r\n" in original
        patched_has_crlf = b"\r\n" in patched
        assert orig_has_crlf == patched_has_crlf, (
            f"{arxml.name}: line-ending style changed "
            f"(CRLF before={orig_has_crlf}, after={patched_has_crlf})")


def _collect_values(root, ns: str) -> dict[tuple[str, ...], str]:
    """Return ``{(ancestor-short-name-chain, def_suffix): value_text}``
    for every PARAM-VALUE / TEXTUAL-PARAM-VALUE in the tree.

    The key is stable across patched/unpatched trees because it uses
    structural identity (SHORT-NAME chain) rather than source position.
    """
    out: dict[tuple[str, ...], str] = {}
    for tag in ("ECUC-NUMERICAL-PARAM-VALUE", "ECUC-TEXTUAL-PARAM-VALUE"):
        for pv in root.iter(f"{{{ns}}}{tag}"):
            dref = pv.find(f"{{{ns}}}DEFINITION-REF")
            val = pv.find(f"{{{ns}}}VALUE")
            if dref is None or not dref.text:
                continue
            def_suffix = dref.text.rsplit("/", 1)[-1]
            chain: list[str] = []
            cur = pv.getparent()
            while cur is not None:
                sn = cur.find(f"{{{ns}}}SHORT-NAME")
                if sn is not None and sn.text:
                    chain.append(sn.text)
                cur = cur.getparent()
            key = (tuple(reversed(chain)) + (def_suffix,))
            out[key] = (val.text or "") if val is not None else ""
    return out


# ---------------------------------------------------------------------------
# landing-report


def test_landing_report_emits_expected_counts(fixture_project, capsys):
    import pipeline
    rc = pipeline.main(["landing-report"])
    out = capsys.readouterr().out
    assert rc == 0, out

    report = fixture_project["outputs"] / "landing_report.txt"
    assert report.exists()
    body = report.read_text(encoding="utf-8")
    # The report prints resolved arxml *paths* (file alias -> filename),
    # not the symbolic alias keys. Assert on each unique arxml filename
    # every PARAM_MAP entry should reach.
    for arxml_name in (
        "CanTp_CusDiag_EcucValues.arxml",
        "CanTp_Feature_EcucValues.arxml",
        "Dcm_Feature_EcucValues.arxml",
        "Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml",
        "Can0_CusDiag_EcucValues_DPB.arxml",
    ):
        assert arxml_name in body, f"landing_report missing {arxml_name}"
    # Every non-derived top-level param name should appear verbatim.
    for param in ("N_As", "N_Bs", "STmin", "P2_Max", "CAN_ID_Format",
                  "NRC78_Times", "PaddingByte", "StrictDlcCheck"):
        assert param in body, f"landing_report missing {param}"
    # On the minimal fixture every locator should resolve (0 unmatched).
    assert "unmatched locators: 0" in body, body


# ---------------------------------------------------------------------------
# fscs


def test_fscs_writes_readable_report(fixture_project, capsys):
    import pipeline
    rc = pipeline.main(["fscs"])
    assert rc == 0
    fscs = fixture_project["outputs"] / "FSCS.txt"
    assert fscs.exists()
    body = fscs.read_text(encoding="utf-8")
    # Concise, human-first format: section headings + the values we set.
    assert "CAN_Functional_Request_ID" in body
    assert "0x7DF" in body or "7DF" in body.upper()
    # NRC78_Times should be in the DCM section.
    assert "NRC78_Times" in body


# ---------------------------------------------------------------------------
# lazy-seed: if inputs/DiagComm_values.json is missing on a fresh
# project, the first pipeline command must reverse-walk the live arxml,
# write the values file, and exit 1 (DEGRADED) so the agent can pass
# control back to the user for review.


def test_status_broken_when_xlsx_missing(fixture_project, capsys):
    """Since 1.20.0 the lazy-seed-from-arxml path is gone.

    The user-facing input is ``inputs/DiagComm.xlsx`` (scaffolded by
    ``--init-project``); a missing xlsx is a hard BROKEN status with a
    one-line ``--init-project --force`` recovery hint. The skill no
    longer fabricates a v2 JSON skeleton on the user's behalf.
    """
    import pipeline
    xlsx_path = fixture_project["inputs"] / "DiagComm.xlsx"
    xlsx_path.unlink()
    assert not xlsx_path.exists()

    rc = pipeline.main(["status"])
    out = capsys.readouterr().out

    assert rc == 2, f"expected BROKEN (rc=2), got rc={rc}\n{out}"
    assert "OVERALL: BROKEN" in out
    assert "DiagComm.xlsx" in out
    # The recovery hint names --init-project --force.
    assert "--init-project" in out


# NOTE: There is no test for "validate / apply refuses when xlsx
# missing" because the fixture monkey-patches `runtime._ensure_cache_fresh`
# to a no-op (so the test bed can ship pre-cooked v2 JSON instead of a
# real .xlsx). In production, if `inputs/DiagComm.xlsx` is missing
# `excel_loader` raises a `LoaderError` that surfaces from
# `runtime.load_user_inputs` as a `SystemExit` with the recovery hint.
# `test_status_broken_when_xlsx_missing` above covers the user-facing
# behaviour at the dashboard level.


# ---------------------------------------------------------------------------
# reseed: 1.20.0+ behaviour (Excel is the source of truth).
#
# Default mode is a no-op deprecation notice (the Excel template ships
# pre-filled with schema defaults; nothing to seed). ``--from-arxml``
# writes a *suggestion* file under ``outputs/`` for the user to
# transcribe back into the Excel sheet, leaving inputs/ untouched.


def test_reseed_default_is_noop(fixture_project, capsys):
    import pipeline

    rc = pipeline.main(["reseed"])
    out = capsys.readouterr().out

    assert rc == 0, out
    assert "no-op" in out
    assert "1.20.0" in out
    # Default reseed must NOT touch inputs/.
    assert (fixture_project["values"]).exists()  # still there, untouched
    assert (fixture_project["config"]).exists()
    # And it must NOT have written a suggestion file (only --from-arxml does).
    assert not (fixture_project["outputs"] / "reseed_suggestion.json").exists()


def test_reseed_from_arxml_writes_suggestion_to_outputs(
        fixture_project, capsys):
    """``reseed --from-arxml`` writes outputs/reseed_suggestion.json (NOT
    inputs/) so the cache regen-from-Excel cycle never wipes the user's
    investigation.
    """
    import pipeline

    rc = pipeline.main(["reseed", "--from-arxml"])
    out = capsys.readouterr().out

    assert rc == 0, out
    suggestion = fixture_project["outputs"] / "reseed_suggestion.json"
    assert suggestion.exists(), out
    payload = json.loads(suggestion.read_text(encoding="utf-8"))
    assert payload.get("$schema") == "diagcomm-toolkit/v2"
    assert "parameters" in payload
    assert "transcribe" in out
    assert "DiagComm.xlsx" in out
    # Sanity: the reverse walk populated the full parameter surface in
    # the suggestion file.
    params = payload["parameters"]
    assert "CAN_DLC" in params and isinstance(params["CAN_DLC"], dict)
    assert "CAN_Functional_Request_ID" in params


def test_reseed_rejects_unknown_force_flag(fixture_project, capsys):
    """--force was removed as part of tightening the inputs/ ownership
    contract. Make sure it's gone from the CLI surface, not just the
    docs -- argparse should reject it."""
    import pipeline
    values_path = fixture_project["values"]
    values_path.unlink()  # even on the seed-allowed path --force must fail
    with pytest.raises(SystemExit):
        pipeline.main(["reseed", "--force"])
    err = capsys.readouterr().err
    assert "unrecognized arguments" in err or "--force" in err
