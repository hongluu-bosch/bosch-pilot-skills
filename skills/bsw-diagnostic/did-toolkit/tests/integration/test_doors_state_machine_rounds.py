"""Integration test: 3-round DOORS state-machine loop.

Exercises the full v1.17.0 INSERT -> NOOP -> UPDATE cycle through
:mod:`build_doors_payload.build_payload` plus the post-upload state
writeback helper from :mod:`doors_sync`. We simulate the DOORS
upload + ``reconcile_did_rows`` step with synthetic
:class:`LinkEntry` instances so the test can run in CI without an
MCP server, while the real-disk ``save_state`` / ``load_state``
round-trip pins the state file format end-to-end.

Round flow:

* **Round 1 — INSERT**: empty state, every effective DID classifies
  as INSERT, both workbooks land all FS+CS rows. Synthetic
  link entries get folded into state via
  :func:`doors_sync._writeback_state_post_upload` and persisted.
* **Round 2 — NOOP**: same FSCS, state from round 1 reloaded from
  disk, every DID matches its recorded hash, workbook is empty
  (rows_written == 0).
* **Round 3 — UPDATE**: mutate one DID's body (forcing its hash
  to drift), reload state, assert that exactly that DID classifies
  as UPDATE while the others stay NOOP, and that the UPDATE row's
  ``Absolute Number`` matches the recorded landing (DOORS
  overwrites in place).

This is the highest-value smoke for v1.17.0 because it cross-tests
every layer at once: the hash canonicaliser (``content_hash``),
the diff engine (``diff``), the typed state schema
(``doors_state``), the orchestration writeback
(``doors_sync._writeback_state_post_upload``), and the workbook
generator's two-pass refactor (``build_doors_payload``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# The skill keeps ``scripts/fscs/doors`` on its own sys.path; the
# integration suite has to mirror that so bare-name imports of the
# orchestration helpers (``doors_sync``, ``doors_state``) resolve.
HERE = Path(__file__).resolve()
SKILL_ROOT = HERE.parents[2]
DOORS_DIR = SKILL_ROOT / "scripts" / "fscs" / "doors"
if str(DOORS_DIR) not in sys.path:
    sys.path.insert(0, str(DOORS_DIR))

from fscs.doors import build_doors_payload as bdp  # noqa: E402
from fscs.doors.doors_links import LinkEntry  # noqa: E402
from fscs.doors.doors_state import (  # noqa: E402
    State,
    _normalise_hex,
    load_state,
    save_state,
)
import doors_sync  # noqa: E402  (skill-local module via sys.path above)


_MODULE_UUID = "demo-module"   # matches doors.document_uuid in the yaml


# --------------------------------------------------------------------- #
# fixture wiring                                                        #
# --------------------------------------------------------------------- #


def _write_yaml(path: Path) -> None:
    """Minimal 17-col mapping aligned with the v1.16.0 template."""
    path.write_text(
        """
doors:
  document_uuid: "demo-module"
anchors:
  service_22:
    heading_field: "DescriptionOfRequirementRB"
    text: |-
      $22 anchor text
  service_2e:
    heading_field: "DescriptionOfRequirementRB"
    text: |-
      $2E anchor text
template:
  sheet: "CS Data"
  size_row: 1
  header_row: 2
  data_start: 3
defaults:
  isPicture: "no"
role_values:
  FS:
    RB_Referenced_Testcase: "SwT"
    RB_TestEnvironment: "Labcar/HIL"
  CS:
    RB_Referenced_Testcase: "CT"
    RB_TestEnvironment: "SIL Simulation"
value_maps:
  RB_Product:
    DPB: "DPB"
    ESP: "ESP 10"
realizing_paths:
  fs_template: "Dcm_CusDiag_Services_EcucValues_{product_type}.arxml"
  cs_template: "RBAPLCUST_{did_hex_bare}_{did_name}.c"
  customer_default: "rbcn"
columns:
  "Destination Object":  "row.destination"
  "Absolute Number":     "row.absolute_no"
  "Object Heading":      "row.heading"
  "Object Text":         "row.object_text"
  "RB_Realizing_SWitem": "row.realizing"
  "RB_Product":          "row.rb_product"
  "isPicture":           "literal:no"
upload:
  init_timeout: 1
  upload_timeout: 1
""".lstrip(),
        encoding="utf-8",
    )


def _write_project(path: Path) -> None:
    path.write_text(json.dumps({"project": {"name": "Demo"}}), encoding="utf-8")


def _write_fscs_json(path: Path) -> None:
    path.write_text(
        json.dumps({
            "schema_version": "1.5",
            "dids": [
                {"did_hex": "5001", "product_type": "DPB"},
                {"did_hex": "0101", "product_type": "DPB"},
            ],
        }),
        encoding="utf-8",
    )


def _write_fscs_text(txt22: Path, txt2e: Path, *, body_5001: str = "body for 5001") -> None:
    """Write the per-service FSCS text files. ``body_5001`` is
    parameterised so round 3 can mutate it and force 0x5001 to
    classify as UPDATE while 0x0101 stays NOOP."""
    txt22.write_text(
        "Identifier $5001h - Vehicle mode\n\n"
        f"Description\n{body_5001}\n"
        "================================================================================\n\n"
        "Identifier $0101h - Variant Coding\n\n"
        "Description\nbody for 0101\n",
        encoding="utf-8",
    )
    txt2e.write_text(
        "Identifier $0101h - Variant Coding\n\n"
        "Description\nwrite body\n",
        encoding="utf-8",
    )


def _read_workbook(path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    headers = [c.value for c in ws[2]]
    rows = []
    for r in ws.iter_rows(min_row=3, values_only=True):
        rows.append(dict(zip(headers, r)))
    return headers, rows


@pytest.fixture
def workspace(tmp_path: Path) -> dict:
    """Stage a fresh workspace per round so each test starts clean."""
    txt22 = tmp_path / "FSCS_22.txt"
    txt2e = tmp_path / "FSCS_2E.txt"
    mapping = tmp_path / "doors_mapping.yaml"
    project = tmp_path / "project.json"
    fscs_json = tmp_path / "fscs.json"
    state_path = tmp_path / "doors_upload_state.json"
    out_dir = tmp_path / "out"
    report = out_dir / "report.txt"

    _write_yaml(mapping)
    _write_project(project)
    _write_fscs_json(fscs_json)
    _write_fscs_text(txt22, txt2e)

    return {
        "txt22": txt22, "txt2e": txt2e,
        "mapping": mapping, "project": project,
        "fscs_json": fscs_json,
        "state_path": state_path,
        "out_dir": out_dir, "report": report,
    }


def _build(workspace: dict, *, state: State | None):
    """Common build wrapper -- always runs in dry-run anchor mode
    so the test doesn't need a DOORS export fixture."""
    return bdp.build_payload(
        mapping_path=workspace["mapping"],
        project_path=workspace["project"],
        export_path=Path("/does/not/exist"),
        txt_22_path=workspace["txt22"],
        txt_2e_path=workspace["txt2e"],
        fscs_json_path=workspace["fscs_json"],
        out_dir=workspace["out_dir"],
        report_path=workspace["report"],
        require_anchors=False,
        state=state,
        module_uuid=_MODULE_UUID,
    )


def _synthetic_link_entries(plan_did_hexes: list[str]) -> list[LinkEntry]:
    """Mint LinkEntry instances that DOORS would have produced
    after a real upload + ``reconcile_did_rows``. We give each DID
    a unique, deterministic (fs_abs, cs_abs) pair so the round 3
    UPDATE assertion can pin the exact AbsoluteNumber the workbook
    addresses."""
    entries: list[LinkEntry] = []
    for i, did_hex in enumerate(plan_did_hexes, start=1):
        canonical = _normalise_hex(did_hex)
        entries.append(LinkEntry(
            cs_abs=f"CS{500 + i}",
            fs_abs=f"FS{500 + i}",
            did_hex=canonical,
            service="22+2E",
        ))
    return entries


def _synthetic_per_service_link_entries(
    *,
    pairs_22: list[str],
    pairs_2e: list[str],
) -> list[LinkEntry]:
    """v1.17.1: emit ONE LinkEntry per (service, did_hex) with
    physically distinct (fs_abs, cs_abs) per service.

    Models what ``reconcile_did_rows(service_ranges=...)`` produces
    when an operator's project has separate $22 and $2E anchors:
    a DID present in BOTH services lands at TWO different row
    pairs in DOORS (one under each anchor) and the synthetic
    entries reflect that. The 22 block uses 2NN AbsoluteNumbers,
    the 2E block uses 4NN — so a per-service writeback bug would
    surface immediately as a recorded landing pointing at the
    wrong block.
    """
    entries: list[LinkEntry] = []
    for i, did_hex in enumerate(pairs_22, start=1):
        canonical = _normalise_hex(did_hex)
        entries.append(LinkEntry(
            cs_abs=f"22-CS{200 + i}",
            fs_abs=f"22-FS{200 + i}",
            did_hex=canonical,
            service="22",
        ))
    for i, did_hex in enumerate(pairs_2e, start=1):
        canonical = _normalise_hex(did_hex)
        entries.append(LinkEntry(
            cs_abs=f"2E-CS{400 + i}",
            fs_abs=f"2E-FS{400 + i}",
            did_hex=canonical,
            service="2E",
        ))
    return entries


# --------------------------------------------------------------------- #
# 3-round end-to-end                                                    #
# --------------------------------------------------------------------- #


def test_round1_insert_then_round2_noop_then_round3_update(workspace):
    pytest.importorskip("xlsxwriter")
    pytest.importorskip("yaml")
    pytest.importorskip("openpyxl")

    # =========================== ROUND 1: INSERT =========================== #

    state = load_state(workspace["state_path"])
    assert state.modules == {}, "fresh workspace must start with empty state"

    r1 = _build(workspace, state=state)
    assert r1.action_plan is not None
    s1 = r1.action_plan.summary()
    assert s1["INSERT"] == 3   # 22 has 2 DIDs, 2E has 1 DID
    assert s1["UPDATE"] == 0
    assert s1["NOOP"] == 0
    assert s1["STALE"] == 0

    art_22 = r1.services["22"]
    art_2e = r1.services["2E"]
    assert art_22.rows_written == 4
    assert art_2e.rows_written == 2

    # Simulate the post-upload reconcile -> writeback step. We
    # gather a unique DID list (5001 is 22-only, 0101 is in both
    # services -> ONE link entry per the documented limitation).
    all_did_hexes = sorted({h for art in r1.services.values() for h in art.did_hexes})
    link_entries = _synthetic_link_entries(all_did_hexes)
    n = doors_sync._writeback_state_post_upload(
        state=state,
        module_uuid=_MODULE_UUID,
        plan=r1.action_plan,
        link_entries=link_entries,
    )
    assert n == 3, f"all 3 INSERT actions must record landings; got {n}"
    save_state(workspace["state_path"], state)

    # State file genuinely on disk -- not just in memory.
    assert workspace["state_path"].is_file()
    raw = json.loads(workspace["state_path"].read_text(encoding="utf-8"))
    assert raw["schema_version"] == "3.0"
    assert _MODULE_UUID in raw["modules"]
    module_dump = raw["modules"][_MODULE_UUID]
    # Two DIDs known to the module after round 1.
    assert set(module_dump["dids"].keys()) == {"0x5001", "0x0101"}

    # =========================== ROUND 2: NOOP ============================= #

    # Reload from disk so we genuinely round-trip through the
    # serialiser (catches any drop of fields during save/load).
    state2 = load_state(workspace["state_path"])
    assert _MODULE_UUID in state2.modules

    r2 = _build(workspace, state=state2)
    s2 = r2.action_plan.summary()
    assert s2["NOOP"] == 3, (
        f"round 2 with unchanged FSCS must classify every pair as NOOP; "
        f"got {s2}"
    )
    assert s2["INSERT"] == 0 and s2["UPDATE"] == 0 and s2["STALE"] == 0

    # NOOP DIDs must NOT land any workbook rows; both xlsx exist
    # (orchestrator invariant) but are empty.
    for service in ("22", "2E"):
        art = r2.services[service]
        assert art.rows_written == 0
        assert art.did_hexes == []
        assert art.xlsx_path.is_file()

    # =========================== ROUND 3: UPDATE =========================== #

    # Mutate 0x5001's body. 0x0101 (in both 22 and 2E) is left
    # alone, so we expect: 22/0x5001 = UPDATE, 22/0x0101 = NOOP,
    # 2E/0x0101 = NOOP.
    _write_fscs_text(
        workspace["txt22"], workspace["txt2e"],
        body_5001="DRIFTED body for 5001 -- forces hash change",
    )

    state3 = load_state(workspace["state_path"])
    r3 = _build(workspace, state=state3)
    s3 = r3.action_plan.summary()
    assert s3["UPDATE"] == 1, f"only 0x5001/22 should drift; got {s3}"
    assert s3["NOOP"] == 2
    assert s3["INSERT"] == 0
    assert s3["STALE"] == 0

    # Workbook side: 22 has the UPDATE row pair (FS+CS = 2 rows),
    # 2E has nothing (its sole DID was unchanged).
    art_22_r3 = r3.services["22"]
    art_2e_r3 = r3.services["2E"]
    assert art_22_r3.rows_written == 2
    assert art_22_r3.did_hexes == ["0x5001"]
    assert art_2e_r3.rows_written == 0

    _, rows = _read_workbook(art_22_r3.xlsx_path)
    # The two surviving rows must be UPDATE-shaped: Destination
    # Object blank, Absolute Number filled with the round-1
    # recorded landing for 0x5001.
    seen_abs = set()
    for row in rows:
        assert (row["Destination Object"] is None) or (row["Destination Object"] == "")
        assert row["Absolute Number"] in ("FS501", "CS501", "FS502", "CS502"), (
            f"UPDATE row's Absolute Number must come from the recorded landing "
            f"(round 1 minted FS501/CS501 for 0x5001); got {row['Absolute Number']!r}"
        )
        seen_abs.add(row["Absolute Number"])
    # Both FS and CS landings must appear (no row dropped).
    assert len(seen_abs) == 2

    # Simulate round-3 writeback so the recorded hash refreshes
    # to the new content, then verify a hypothetical round 4
    # would classify everything as NOOP again.
    link_entries_r3 = _synthetic_link_entries(art_22_r3.did_hexes)
    doors_sync._writeback_state_post_upload(
        state=state3,
        module_uuid=_MODULE_UUID,
        plan=r3.action_plan,
        link_entries=link_entries_r3,
    )
    save_state(workspace["state_path"], state3)

    state4 = load_state(workspace["state_path"])
    r4 = _build(workspace, state=state4)
    s4 = r4.action_plan.summary()
    assert s4["NOOP"] == 3, (
        f"after a successful UPDATE writeback, the next round with "
        f"unchanged FSCS must be all-NOOP again; got {s4}"
    )


def test_did_in_both_services_records_distinct_landings_per_service(workspace):
    """v1.17.1 regression pin: a DID present in BOTH services lands
    at TWO physically distinct row pairs in DOORS (one under each
    anchor). The state machine must record those landings
    independently — keying writeback on (service, did_hex) rather
    than did_hex alone — so a subsequent UPDATE points at the
    correct row in the correct service.

    Failure mode this test catches: pre-v1.17.1, the second
    LinkEntry's (fs_abs, cs_abs) overwrote the first in the
    landings dict, so both service_22 and service_2e ended up
    pointing at the SAME physical landing — an UPDATE under one
    service would clobber the wrong row.

    The fixture's 0x0101 is in both 22 and 2E. We use synthetic
    per-service link entries with deliberately disjoint
    AbsoluteNumber prefixes (``22-FS2NN`` vs ``2E-FS4NN``) so a
    cross-contamination bug surfaces as a wrong-prefix UPDATE
    cell on the next round.
    """
    pytest.importorskip("xlsxwriter")
    pytest.importorskip("yaml")
    pytest.importorskip("openpyxl")

    state = load_state(workspace["state_path"])

    # Round 1: build + writeback with PER-SERVICE link entries.
    r1 = _build(workspace, state=state)
    s1 = r1.action_plan.summary()
    assert s1["INSERT"] == 3   # 22 has 5001+0101 (2), 2E has 0101 (1)

    # 0x0101 is in BOTH; 0x5001 only in 22. Mint per-service
    # entries reflecting that shape.
    link_entries = _synthetic_per_service_link_entries(
        pairs_22=["0x5001", "0x0101"],
        pairs_2e=["0x0101"],
    )
    n = doors_sync._writeback_state_post_upload(
        state=state,
        module_uuid=_MODULE_UUID,
        plan=r1.action_plan,
        link_entries=link_entries,
    )
    assert n == 3, (
        f"every INSERT pair must record its OWN service-tagged landing; "
        f"got {n} (expected 3 = 22:0x5001 + 22:0x0101 + 2E:0x0101)"
    )
    save_state(workspace["state_path"], state)

    # Verify 0x0101's two recorded landings really are distinct
    # on disk (catches the dict-overwrite regression directly).
    raw = json.loads(workspace["state_path"].read_text(encoding="utf-8"))
    did_0101 = raw["modules"][_MODULE_UUID]["dids"]["0x0101"]
    abs_22 = did_0101["service_22"]["fs_abs"]
    abs_2e = did_0101["service_2e"]["fs_abs"]
    assert abs_22.startswith("22-"), (
        f"service_22 landing for 0x0101 must use the 22-block prefix, got {abs_22!r}"
    )
    assert abs_2e.startswith("2E-"), (
        f"service_2e landing for 0x0101 must use the 2E-block prefix, got {abs_2e!r}"
    )
    assert abs_22 != abs_2e, (
        f"a DID-in-both-services bug would land BOTH service slots on the "
        f"same AbsoluteNumber; here they must be distinct (22-FS:{abs_22!r} "
        f"vs 2E-FS:{abs_2e!r})"
    )

    # Round 2: drift 0x0101's body so it classifies UPDATE in
    # both services. The UPDATE's `Absolute Number` must come
    # from the SERVICE-CORRECT landing (22 row uses 22-* prefix,
    # 2E row uses 2E-* prefix). A regression where both services
    # share one landing would surface as one of the workbook
    # sheets pointing at the wrong block's prefix.
    workspace["txt22"].write_text(
        "Identifier $5001h - Vehicle mode\n\n"
        "Description\nbody for 5001\n"
        "================================================================================\n\n"
        "Identifier $0101h - Variant Coding\n\n"
        "Description\nDRIFTED body for 0101 in 22\n",
        encoding="utf-8",
    )
    workspace["txt2e"].write_text(
        "Identifier $0101h - Variant Coding\n\n"
        "Description\nDRIFTED write body in 2E\n",
        encoding="utf-8",
    )

    state2 = load_state(workspace["state_path"])
    r2 = _build(workspace, state=state2)
    s2 = r2.action_plan.summary()
    assert s2["UPDATE"] == 2, (
        f"both 22:0x0101 and 2E:0x0101 should drift; got {s2}"
    )
    assert s2["NOOP"] == 1   # 22:0x5001 unchanged

    # 22 sheet: UPDATE for 0x0101, recorded landings start "22-".
    _, rows_22 = _read_workbook(r2.services["22"].xlsx_path)
    for row in rows_22:
        assert row["Absolute Number"].startswith("22-"), (
            f"22 sheet UPDATE row points at {row['Absolute Number']!r}; "
            "must come from the 22-block recorded landing (cross-service "
            "contamination would surface as a 2E- prefix here)."
        )

    # 2E sheet: UPDATE for 0x0101, recorded landings start "2E-".
    _, rows_2e = _read_workbook(r2.services["2E"].xlsx_path)
    for row in rows_2e:
        assert row["Absolute Number"].startswith("2E-"), (
            f"2E sheet UPDATE row points at {row['Absolute Number']!r}; "
            "must come from the 2E-block recorded landing."
        )
