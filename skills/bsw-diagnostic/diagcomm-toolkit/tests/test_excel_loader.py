"""Tests for ``scripts/excel_loader.py``.

Strategy: build a fresh Excel workbook in ``tmp_path`` from the
schema (via the same ``build_inputs_template`` script the production
template uses), fill in a few cells programmatically with openpyxl,
then exercise:

  - ``load_xlsx`` -> coercion (bool / int / float / hex / enum)
  - ``validate`` -> required-field detection + enum membership
  - ``dump_cache`` -> JSON / YAML round-trip + cache freshness
  - ``merge_doors_skeleton`` -> override merge with the bundled skeleton
  - ``load_or_refresh`` -> mtime-based skip / regenerate

The test file lives under ``tests/`` and consumes the production
schema and skeleton so a schema change automatically flows into the
test bed.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
ASSETS_DIR = REPO_ROOT / "assets"
SCHEMA_PATH = ASSETS_DIR / "DiagComm_schema.json"
SKELETON_PATH = ASSETS_DIR / "doors_mapping_skeleton.yaml"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# These imports come from scripts/. They depend on openpyxl + pyyaml.
openpyxl = pytest.importorskip("openpyxl")
yaml = pytest.importorskip("yaml")

import build_inputs_template  # noqa: E402
import excel_loader  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers

def _fresh_xlsx(tmp_path: Path) -> Path:
    """Render a blank template into ``tmp_path`` using the production
    builder. Returns the xlsx path."""
    out = tmp_path / "DiagComm.xlsx"
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    wb = build_inputs_template.build_workbook(schema)
    wb.save(out)
    return out


def _set_cell(xlsx_path: Path, sheet: str, field: str, value):
    """Find the row whose Field column equals ``field`` on ``sheet`` and
    overwrite the Value column with ``value``. Mirrors what a user does
    by hand in Excel."""
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb[sheet]
    for row in range(2, ws.max_row + 1):
        f = ws.cell(row=row, column=1).value
        if f == field:
            ws.cell(row=row, column=2).value = value
            wb.save(xlsx_path)
            wb.close()
            return
    wb.close()
    raise KeyError(f"field {field!r} not found on sheet {sheet!r}")


# ---------------------------------------------------------------------------
# load_xlsx

def test_load_xlsx_blank_template_yields_empty_required_fields(tmp_path):
    xlsx = _fresh_xlsx(tmp_path)
    merged = excel_loader.load_xlsx(xlsx)

    assert merged["$schema"] == "diagcomm-toolkit/v2"
    # blank template: project identity is empty
    assert merged["project"]["name"] is None
    assert merged["project"]["product_type"] is None
    # required CAN_DLC sub-fields are empty
    can_dlc = merged["parameters"]["CAN_DLC"]
    assert can_dlc["rx_frame_type"] is None
    assert can_dlc["tx_frame_type"] is None
    assert can_dlc["rx_dl"] is None
    assert can_dlc["tx_dl"] is None
    # required CAN IDs are empty
    assert merged["parameters"]["CAN_Functional_Request_ID"] is None
    # paths defaults pre-filled
    assert merged["paths"]["base_dir"] == "../.."
    # options coerced bool
    assert merged["options"]["dry_run_default"] is True
    assert merged["options"]["validate_before_apply"] is True
    # DOORS overrides default values. The placeholder string is
    # intentionally preserved verbatim so the downstream
    # build_doors_payload "PUT-" in module_uuid check still trips.
    overrides = merged["_doors_overrides"]
    assert overrides["doors"]["document_uuid"] == "PUT-DOORS-DOCUMENT-UUID-HERE"
    assert overrides["mode"] == "insert"
    assert overrides["upload"]["dry_run"] is False


def test_load_xlsx_coerces_filled_cells(tmp_path):
    xlsx = _fresh_xlsx(tmp_path)
    _set_cell(xlsx, "Project & Parameters", "project.name", "MyProject")
    _set_cell(xlsx, "Project & Parameters", "project.product_type", "ESP")
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_DLC.rx_frame_type", "CANFD")
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_DLC.tx_frame_type", "CANFD")
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_DLC.rx_dl", 64)
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_DLC.tx_dl", 64)
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_Functional_Request_ID", "0x7DF")
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_Physical_Request_ID", "0x7E0")
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_Response_ID", "0x7E8")
    _set_cell(xlsx, "Project & Parameters", "parameters.STmin", 5.0)
    _set_cell(xlsx, "DOORS Upload", "doors.document_uuid", "abcd-1234-FEED")

    merged = excel_loader.load_xlsx(xlsx)

    assert merged["project"]["name"] == "MyProject"
    assert merged["project"]["product_type"] == "ESP"
    can_dlc = merged["parameters"]["CAN_DLC"]
    assert can_dlc["rx_frame_type"] == "CANFD"
    assert can_dlc["rx_dl"] == 64
    assert can_dlc["tx_dl"] == 64
    # hex preserved with 0x prefix and uppercased
    assert merged["parameters"]["CAN_Functional_Request_ID"] == "0x7DF"
    assert merged["parameters"]["CAN_Physical_Request_ID"] == "0x7E0"
    assert merged["parameters"]["CAN_Response_ID"] == "0x7E8"
    # float coerced
    assert merged["parameters"]["STmin"] == 5.0
    assert merged["_doors_overrides"]["doors"]["document_uuid"] == "abcd-1234-FEED"


def test_load_xlsx_missing_file_raises_loader_error(tmp_path):
    missing = tmp_path / "does_not_exist.xlsx"
    with pytest.raises(excel_loader.LoaderError) as exc_info:
        excel_loader.load_xlsx(missing)
    msg = str(exc_info.value)
    assert "DiagComm.xlsx" in msg or "does_not_exist.xlsx" in msg


# ---------------------------------------------------------------------------
# validate

def test_validate_blank_template_flags_required(tmp_path):
    xlsx = _fresh_xlsx(tmp_path)
    merged = excel_loader.load_xlsx(xlsx)
    errors = excel_loader.validate(merged)
    # Expect 9 required fields: 2 project + 4 CAN_DLC + 3 CAN IDs.
    assert len(errors) == 9
    required_fields = (
        "project.name",
        "project.product_type",
        "parameters.CAN_DLC.rx_frame_type",
        "parameters.CAN_DLC.tx_frame_type",
        "parameters.CAN_DLC.rx_dl",
        "parameters.CAN_DLC.tx_dl",
        "parameters.CAN_Functional_Request_ID",
        "parameters.CAN_Physical_Request_ID",
        "parameters.CAN_Response_ID",
    )
    for f in required_fields:
        assert any(f in line for line in errors), f"missing report for {f}: {errors}"


def test_validate_filled_template_clean(tmp_path):
    xlsx = _fresh_xlsx(tmp_path)
    _set_cell(xlsx, "Project & Parameters", "project.name", "MyProject")
    _set_cell(xlsx, "Project & Parameters", "project.product_type", "ESP")
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_DLC.rx_frame_type", "CANFD")
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_DLC.tx_frame_type", "CANFD")
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_DLC.rx_dl", 64)
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_DLC.tx_dl", 64)
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_Functional_Request_ID", "0x7DF")
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_Physical_Request_ID", "0x7E0")
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_Response_ID", "0x7E8")

    merged = excel_loader.load_xlsx(xlsx)
    assert excel_loader.validate(merged) == []


def test_validate_rejects_invalid_enum(tmp_path):
    xlsx = _fresh_xlsx(tmp_path)
    _set_cell(xlsx, "Project & Parameters", "project.name", "MyProject")
    _set_cell(xlsx, "Project & Parameters", "project.product_type", "NotARealVariant")

    merged = excel_loader.load_xlsx(xlsx)
    errors = excel_loader.validate(merged)
    assert any("product_type" in e and "NotARealVariant" in e for e in errors)


def test_validate_rejects_out_of_range(tmp_path):
    xlsx = _fresh_xlsx(tmp_path)
    _set_cell(xlsx, "Project & Parameters", "project.name", "MyProject")
    _set_cell(xlsx, "Project & Parameters", "project.product_type", "ESP")
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_DLC.rx_frame_type", "CANFD")
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_DLC.tx_frame_type", "CANFD")
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_DLC.rx_dl", 64)
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_DLC.tx_dl", 64)
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_Functional_Request_ID", "0x7DF")
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_Physical_Request_ID", "0x7E0")
    _set_cell(xlsx, "Project & Parameters", "parameters.CAN_Response_ID", "0x7E8")
    _set_cell(xlsx, "Project & Parameters", "parameters.STmin", 999)  # > max 127

    merged = excel_loader.load_xlsx(xlsx)
    errors = excel_loader.validate(merged)
    assert any("STmin" in e and "999" in e for e in errors)


# ---------------------------------------------------------------------------
# dump_cache + round-trip

def test_dump_cache_round_trip(tmp_path):
    xlsx = _fresh_xlsx(tmp_path)
    _set_cell(xlsx, "Project & Parameters", "project.name", "MyProject")
    _set_cell(xlsx, "Project & Parameters", "project.product_type", "ESP")
    _set_cell(xlsx, "DOORS Upload", "doors.document_uuid", "abcd-1234")

    merged = excel_loader.load_xlsx(xlsx)
    cache_dir = tmp_path / "cache"
    paths = excel_loader.dump_cache(
        merged, cache_dir=cache_dir, skeleton_path=SKELETON_PATH,
    )

    # Three files written under cache/.
    assert paths["values"].exists()
    assert paths["config"].exists()
    assert paths["doors_mapping"].exists()

    # JSON shape mirrors the legacy v2 split.
    values_back = json.loads(paths["values"].read_text(encoding="utf-8"))
    assert values_back["project"]["name"] == "MyProject"
    assert values_back["project"]["product_type"] == "ESP"
    assert "parameters" in values_back

    config_back = json.loads(paths["config"].read_text(encoding="utf-8"))
    assert "paths" in config_back and "options" in config_back

    # YAML carries the merged DOORS mapping with the user's UUID.
    doors_back = yaml.safe_load(paths["doors_mapping"].read_text(encoding="utf-8"))
    assert doors_back["doors"]["document_uuid"] == "abcd-1234"
    assert doors_back["mode"] == "insert"
    assert doors_back["upload"]["dry_run"] is False
    # Skeleton fields preserved verbatim.
    assert doors_back["template"]["sheet"] == "CS Data"
    assert "value_maps" in doors_back


def test_merge_doors_skeleton_uses_overrides(tmp_path):
    xlsx = _fresh_xlsx(tmp_path)
    _set_cell(xlsx, "DOORS Upload", "doors.document_uuid", "real-uuid-here")
    _set_cell(xlsx, "DOORS Upload", "mode", "update")
    _set_cell(xlsx, "DOORS Upload", "upload.dry_run", "TRUE")

    merged = excel_loader.load_xlsx(xlsx)
    full = excel_loader.merge_doors_skeleton(merged, skeleton_path=SKELETON_PATH)

    assert full["doors"]["document_uuid"] == "real-uuid-here"
    assert full["mode"] == "update"
    assert full["upload"]["dry_run"] is True
    # Static skeleton fields still merged in.
    assert full["template"]["path"] == "assets/doors_template.xlsx"
    assert full["columns"]["RB_Product"] == "extras.rb_product_value"


# ---------------------------------------------------------------------------
# Cache freshness

def test_load_or_refresh_skips_when_cache_fresh(tmp_path):
    xlsx = _fresh_xlsx(tmp_path)
    cache_dir = tmp_path / "cache"

    # First call writes the cache.
    excel_loader.load_or_refresh(
        xlsx_path=xlsx,
        skeleton_path=SKELETON_PATH,
        cache_dir=cache_dir,
    )
    cache_file = cache_dir / "DiagComm_values.json"
    first_mtime = cache_file.stat().st_mtime

    # Second call (without touching xlsx) should reuse the cache.
    time.sleep(0.05)
    excel_loader.load_or_refresh(
        xlsx_path=xlsx,
        skeleton_path=SKELETON_PATH,
        cache_dir=cache_dir,
    )
    assert cache_file.stat().st_mtime == first_mtime


def test_load_or_refresh_regenerates_after_xlsx_touch(tmp_path):
    xlsx = _fresh_xlsx(tmp_path)
    cache_dir = tmp_path / "cache"

    excel_loader.load_or_refresh(
        xlsx_path=xlsx, skeleton_path=SKELETON_PATH, cache_dir=cache_dir,
    )
    cache_file = cache_dir / "DiagComm_values.json"
    first_mtime = cache_file.stat().st_mtime

    # Bump xlsx mtime forward by 2s to force a regen.
    new_ts = first_mtime + 2.0
    import os
    os.utime(xlsx, (new_ts, new_ts))

    excel_loader.load_or_refresh(
        xlsx_path=xlsx, skeleton_path=SKELETON_PATH, cache_dir=cache_dir,
    )
    assert cache_file.stat().st_mtime > first_mtime


def test_load_or_refresh_force(tmp_path):
    xlsx = _fresh_xlsx(tmp_path)
    cache_dir = tmp_path / "cache"

    excel_loader.load_or_refresh(
        xlsx_path=xlsx, skeleton_path=SKELETON_PATH, cache_dir=cache_dir,
    )
    cache_file = cache_dir / "DiagComm_values.json"
    first_mtime = cache_file.stat().st_mtime

    time.sleep(0.05)
    excel_loader.load_or_refresh(
        xlsx_path=xlsx, skeleton_path=SKELETON_PATH, cache_dir=cache_dir,
        force=True,
    )
    assert cache_file.stat().st_mtime > first_mtime
