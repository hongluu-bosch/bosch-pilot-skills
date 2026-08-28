"""Tests for the read-only agent orientation script."""
from __future__ import annotations

import json
from pathlib import Path


def _wire_context(monkeypatch, context, project_root: Path,
                  *, skill_root: Path | None = None
                  ) -> tuple[Path, Path, Path, Path]:
    """Re-route context.py path constants into a fake v2 layout.

    ``project_root`` simulates the user's project; the workspace lives
    under ``project_root/.DCOM_AI/DiagComm_Toolkit_PRJ/``. ``skill_root``
    defaults to the project root (since the tests don't care about
    where assets live -- ``_seed_assets`` writes to the workspace's
    own assets/ dir).
    """
    workspace = project_root / ".DCOM_AI" / "DiagComm_Toolkit_PRJ"
    inputs = workspace / "inputs"
    assets = workspace / "assets"
    outputs = workspace / "outputs"
    cache = workspace / ".cache"
    for d in (workspace, inputs, assets, outputs, cache):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(context, "SKILL_ROOT", skill_root or project_root)
    monkeypatch.setattr(context, "WORKSPACE_ROOT", workspace, raising=False)
    monkeypatch.setattr(context, "INPUTS_DIR", inputs)
    monkeypatch.setattr(context, "ASSETS_DIR", assets)
    monkeypatch.setattr(context, "OUTPUTS_DIR", outputs)
    monkeypatch.setattr(context, "CACHE_DIR", cache)
    monkeypatch.setattr(context, "XLSX_PATH", inputs / "DiagComm.xlsx")
    monkeypatch.setattr(context, "TEMPLATE_PATH",
                        assets / "inputs_template.xlsx", raising=False)
    monkeypatch.setattr(context, "DOORS_SKELETON_PATH",
                        assets / "doors_mapping_skeleton.yaml", raising=False)
    monkeypatch.setattr(context, "VALUES_PATH", cache / "DiagComm_values.json")
    monkeypatch.setattr(context, "CONFIG_PATH", cache / "DiagComm_config.json")
    monkeypatch.setattr(context, "DOORS_MAPPING_PATH",
                        cache / "doors_mapping.yaml", raising=False)
    # Hermetic: tests provide the cache JSON directly; don't run the
    # excel_loader inside context.build_context().
    monkeypatch.setattr(context, "_refresh_cache_quietly",
                        lambda: None, raising=False)
    return inputs, assets, outputs, cache


def _seed_assets(assets: Path) -> None:
    """Drop placeholder bundled files so context.py reports them OK."""
    (assets / "DiagComm.txt").write_text("stub", encoding="utf-8")
    (assets / "DiagComm_schema.json").write_text("{}", encoding="utf-8")
    (assets / "doors_template.xlsx").write_bytes(b"PK\x03\x04stub")
    (assets / "inputs_template.xlsx").write_bytes(b"PK\x03\x04stub")
    (assets / "doors_mapping_skeleton.yaml").write_text("doors: {}\n",
                                                          encoding="utf-8")


def test_context_reports_resolved_dcom_and_targets(tmp_path, monkeypatch):
    import context

    project_root = tmp_path / "project"
    project_root.mkdir()
    inputs, assets, _outputs, cache = _wire_context(
        monkeypatch, context, project_root)
    _seed_assets(assets)
    # Pretend the user has filled and saved the Excel.
    (inputs / "DiagComm.xlsx").write_bytes(b"PK\x03\x04stub")

    dcom = project_root / "platform" / "rb" / "as" / "bsw" / "core" / "app" / "dcom"
    target = dcom / "RBAPLCust" / "cfg" / "DPB" / "Can0_CusDiag_EcucValues_DPB.arxml"
    target.parent.mkdir(parents=True)
    target.write_text("<AUTOSAR/>", encoding="utf-8")

    (cache / "DiagComm_values.json").write_text(json.dumps({
        "$schema": "diagcomm-toolkit/v2",
        "project": {"name": "Demo", "product_type": "DPB"},
        "parameters": {"CAN_Channel": 0},
    }), encoding="utf-8")
    # v2: base_dir is relative to WORKSPACE_ROOT which lives at
    # <project>/.DCOM_AI/DiagComm_Toolkit_PRJ/, so two ".." segments
    # land back at project_root.
    (cache / "DiagComm_config.json").write_text(json.dumps({
        "$schema": "diagcomm-toolkit/v2",
        "paths": {"base_dir": "../..", "dcom_root": "*/rb/as/*/core/app/dcom"},
        "options": {},
    }), encoding="utf-8")
    (cache / "doors_mapping.yaml").write_text("doors: {}\n", encoding="utf-8")

    ctx = context.build_context()

    assert ctx["skill_root"] == project_root.as_posix()
    assert ctx["base_dir"] == project_root.as_posix()
    assert ctx["dcom_roots"] == [dcom.as_posix()]
    assert ctx["project"] == {"name": "Demo", "product_type": "DPB", "CAN_Channel": 0}
    assert set(ctx["inputs"]) == {"DiagComm.xlsx (user)"}
    assert set(ctx["cache"]) == {
        "DiagComm_values.json", "DiagComm_config.json", "doors_mapping.yaml",
    }
    assert set(ctx["assets"]) == {
        "DiagComm.txt", "DiagComm_schema.json", "doors_template.xlsx",
        "inputs_template.xlsx", "doors_mapping_skeleton.yaml",
    }
    assert all(status == "OK" for status in ctx["assets"].values())
    can_pt = [item for item in ctx["target_files"] if item["alias"] == "can_pt_file"][0]
    assert can_pt["status"] == "OK"
    assert can_pt["absolute_path"] == target.as_posix()


def test_context_points_missing_inputs_to_template(tmp_path, monkeypatch):
    import context

    project_root = tmp_path / "project"
    project_root.mkdir()
    _inputs, assets, _outputs, _cache = _wire_context(
        monkeypatch, context, project_root)
    _seed_assets(assets)
    # No inputs/DiagComm.xlsx and no .cache/* present.

    ctx = context.build_context()

    assert ctx["inputs"]["DiagComm.xlsx (user)"] == "MISSING"
    assert "Recover the user template" in ctx["next_step"]


def test_context_flags_missing_assets_as_broken_install(tmp_path, monkeypatch):
    import context

    project_root = tmp_path / "project"
    project_root.mkdir()
    _wire_context(monkeypatch, context, project_root)

    ctx = context.build_context()

    assert ctx["assets"]["doors_template.xlsx"] == "MISSING"
    assert ctx["assets"]["DiagComm_schema.json"] == "MISSING"
    assert "Skill install incomplete" in ctx["next_step"]
    assert "doors_template.xlsx" in ctx["next_step"]


def test_context_lists_unfilled_required_fields(tmp_path, monkeypatch):
    import context

    project_root = tmp_path / "project"
    project_root.mkdir()
    inputs, assets, _outputs, cache = _wire_context(
        monkeypatch, context, project_root)
    _seed_assets(assets)
    (inputs / "DiagComm.xlsx").write_bytes(b"PK\x03\x04stub")

    schema_payload = {
        "fields": {
            "product_type": {
                "type": "enum", "allowed": ["DPB", "ESP"],
                "prompt_required": True, "default": "DPB",
            },
            "CAN_DLC": {
                "type": "object",
                "fields": {
                    "rx_frame_type": {
                        "type": "enum", "allowed": ["ClassicCAN", "CANFD"],
                        "prompt_required": True, "default": "ClassicCAN",
                    },
                },
            },
            "CAN_Functional_Request_ID": {
                "type": "hex", "default": "0x7DF",
                "prompt_required": True,
            },
            "N_As": {"type": "float", "unit": "ms", "default": 25},
        }
    }
    (assets / "DiagComm_schema.json").write_text(
        json.dumps(schema_payload), encoding="utf-8")

    (cache / "DiagComm_values.json").write_text(json.dumps({
        "$schema": "diagcomm-toolkit/v2",
        "_README": ["this comment must be ignored"],
        "project": {"name": "<fill-me>", "product_type": "<fill-me>"},
        "parameters": {
            "CAN_DLC": {"rx_frame_type": None},
            "CAN_Functional_Request_ID": None,
        },
    }), encoding="utf-8")
    (cache / "DiagComm_config.json").write_text(json.dumps({
        "$schema": "diagcomm-toolkit/v2",
        "paths": {"base_dir": ".", "dcom_root": "dcom"},
        "options": {},
    }), encoding="utf-8")
    (cache / "doors_mapping.yaml").write_text("doors: {}\n", encoding="utf-8")

    ctx = context.build_context()

    unfilled = ctx["unfilled"]
    assert any("project.name" in u for u in unfilled)
    assert any("project.product_type" in u for u in unfilled)
    assert any("CAN_DLC.rx_frame_type" in u for u in unfilled)
    assert any("CAN_Functional_Request_ID" in u for u in unfilled)
    # Non-prompt-required fields stay quiet
    assert not any("N_As" in u for u in unfilled)
    assert "Fill" in ctx["next_step"]
