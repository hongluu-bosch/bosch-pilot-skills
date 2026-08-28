"""Integration tests for ``paths.per_product`` skip semantics.

End-to-end pin for the "直接删掉" requirement: when
``paths.per_product.<PT>.<key>`` is set to ``null``, the Bosch-tree
mirror for that (PT, key) combination is not produced. The fan-out
work-set itself is unchanged — every product the FSCS document carries
still gets the chance to participate, but per-key skips peel off
specific outputs cleanly.

The project tree is the SOLE Phase 2 / Phase 3 sink (there is no
``output_mode`` knob). The ``per_product[<PT>].<key>=null``
sentinel means "do not write into the Bosch tree at all for this
(PT, key)"; there is no ``outputs/<artefact>/<PT>/...`` mirror under
``.DCOM_AI/DID_Toolkit_PRJ/outputs/`` either (only reports live there).

Canonical cases:

* ``paths.per_product.ESPCL.arxml_file = null`` (Phase 2): no
  ``cfg/ESP/Dcm_..._ESPCL.arxml`` is produced (ESPCL writes into ESP's
  folder via the Phase-2 path alias). The skip suppresses that one
  file without disturbing other products in the work-set.
* ``paths.per_product.Common.config_settings_h = null`` (Phase 3): no
  ``Common/dcompr/cfg/RBDCOM_ConfigSettings.h`` mirror is produced.
  Common's other Phase 3 artefacts (c_code, pdm, the other two header
  files) still flow.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import pipeline as pipeline_mod


def _make_did(*, hex_id: str, name: str, product_type: str) -> dict:
    """Build a single FSCSDocument-shaped DID dict."""
    return {
        "did_hex": hex_id,
        "did_name": name,
        "data_type": "Unsigned",
        "storage_position": "EEPROM",
        "size_bytes": 1,
        "rw_state": "R",
        "nvm_item": f"NVM_ID_DCOM_{name.upper()}",
        "service_22": {
            "supported": True,
            "used": True,
            "sessions": ["defaultSession"],
            "security_levels": [{"level": "L0"}],
            "behavior": "",
        },
        "service_2e": {
            "supported": False,
            "used": False,
            "sessions": [],
            "security_levels": [],
            "behavior": "",
        },
        "product_type": product_type,
    }


_FSCS_FAN_OUT_BOTH = {
    "schema_version": "1.5",
    "generated_at": "2026-05-14T00:00:00+00:00",
    "generator": {"tool": "did-toolkit/test", "source_inputs": None},
    "project": {"customer_name": "rbcn"},
    "dids": [
        _make_did(hex_id="F180", name="EspclOnly", product_type="ESPCL"),
        _make_did(hex_id="F181", name="CommonOnly", product_type="Common"),
    ],
}


def _project_json_with(per_product: dict) -> dict:
    """Build a schema-2.2 (v1.27.0) project.json carrying the
    per_product overrides being tested. Other paths.* mirror the
    canonical ``tiny_project.json`` template so the rest of the
    fan-out stays template-driven."""
    return {
        "schema_version": "2.2",
        "paths": {
            "base_dir": ".",
            "pdm_file": "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/cfg/RBDCOM_Customer.pdm",
            "config_h": "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/api/RBAPLCUST_Config.h",
            "config_elements_h": "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/api/RBAPLCUST_ConfigElements.h",
            "config_settings_h": "Fe_Super/rb/as/rbcn/{product_type_lower}/dcompr/cfg/RBDCOM_ConfigSettings.h",
            "c_output_subdir": "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/src/{product_type_upper}",
            "arxml_file": "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/cfg/{product_type_arxml_folder}/Dcm_CusDiag_Services_EcucValues_{product_type_suffix}.arxml",
            "per_product": per_product,
        },
        "options": {},
    }


@pytest.fixture
def sandbox_with_per_product(tmp_path):
    """Materialise a workspace carrying the synthetic FSCS doc and
    a project.json shaped by the caller-supplied per_product
    overrides. Returns the tmp_path so the test can drive Phase 2
    / Phase 3 against it directly via :class:`PipelineController`."""

    def _make(per_product: dict) -> Path:
        (tmp_path / "inputs").mkdir(exist_ok=True)
        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "outputs" / "fscs").mkdir(parents=True, exist_ok=True)
        (tmp_path / "outputs" / "fscs" / "fscs.json").write_text(
            json.dumps(_FSCS_FAN_OUT_BOTH, indent=2),
            encoding="utf-8",
        )
        (tmp_path / "config" / "project.json").write_text(
            json.dumps(_project_json_with(per_product), indent=2),
            encoding="utf-8",
        )
        return tmp_path

    return _make


def _controller_at(sandbox: Path) -> pipeline_mod.PipelineController:
    controller = pipeline_mod.PipelineController()
    controller.base_dir = sandbox
    return controller


# ---------------------------------------------------------------------------
# Phase 2: paths.per_product.ESPCL.arxml_file = null
# ---------------------------------------------------------------------------


class TestPhase2PerProductSkip:
    """ESPCL.arxml_file=null peels ESPCL out of Phase 2 entirely."""

    def test_espcl_skipped_no_bosch_mirror(self, sandbox_with_per_product):
        sandbox = sandbox_with_per_product({"ESPCL": {"arxml_file": None}})
        controller = _controller_at(sandbox)
        assert controller.run_phase2() is True

        # v1.24.0: ESPCL's Bosch mirror would have landed under
        # ``cfg/ESP/Dcm_..._ESPCL.arxml`` (not ``cfg/ESPCL/...``); the
        # skip suppresses that specific file. Since this fixture has
        # no ESP DID either, the entire ``cfg/ESP/`` dir must also be
        # absent.
        bosch_esp_dir = (
            sandbox / "Fe_Super" / "rb" / "as" / "rbcn"
            / "core" / "app" / "dcom" / "RBAPLCust" / "cfg" / "ESP"
        )
        assert not bosch_esp_dir.exists()

    def test_other_products_unaffected_by_espcl_skip(
        self, sandbox_with_per_product
    ):
        sandbox = sandbox_with_per_product({"ESPCL": {"arxml_file": None}})
        controller = _controller_at(sandbox)
        assert controller.run_phase2() is True

        common_bosch = (
            sandbox / "Fe_Super" / "rb" / "as" / "rbcn"
            / "core" / "app" / "dcom" / "RBAPLCust" / "cfg" / "Common"
            / "Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml"
        )
        assert common_bosch.is_file()


# ---------------------------------------------------------------------------
# Phase 3: paths.per_product.Common.config_settings_h = null
# ---------------------------------------------------------------------------


class TestPhase3PerProductSkip:
    """Common.config_settings_h=null peels just that artefact off
    Common's Phase 3 iteration — the rest of Phase 3 flows normally."""

    def test_common_config_settings_skipped_no_bosch_mirror(
        self, sandbox_with_per_product,
    ):
        sandbox = sandbox_with_per_product(
            {"Common": {"config_settings_h": None}}
        )
        controller = _controller_at(sandbox)
        assert controller.run_phase3() is True

        common_dcompr = (
            sandbox / "Fe_Super" / "rb" / "as" / "rbcn"
            / "Common" / "dcompr" / "cfg" / "RBDCOM_ConfigSettings.h"
        )
        assert not common_dcompr.exists()

    def test_other_products_config_settings_still_mirrored(
        self, sandbox_with_per_product,
    ):
        sandbox = sandbox_with_per_product(
            {"Common": {"config_settings_h": None}}
        )
        controller = _controller_at(sandbox)
        assert controller.run_phase3() is True

        espcl_dcompr = (
            sandbox / "Fe_Super" / "rb" / "as" / "rbcn"
            / "esp10cl" / "dcompr" / "cfg" / "RBDCOM_ConfigSettings.h"
        )
        assert espcl_dcompr.is_file()

    def test_string_override_redirects_mirror_destination(
        self, sandbox_with_per_product,
    ):
        override_rel = (
            "Fe_Super/rb/as/rbcn/esp10cl/dcompr/cfg/"
            "RBDCOM_ConfigSettings_CUSTOMVARIANT.h"
        )
        sandbox = sandbox_with_per_product(
            {"ESPCL": {"config_settings_h": override_rel}}
        )
        controller = _controller_at(sandbox)
        assert controller.run_phase3() is True

        custom_target = sandbox / override_rel
        assert custom_target.is_file()
        default_target = (
            sandbox / "Fe_Super" / "rb" / "as" / "rbcn"
            / "esp10cl" / "dcompr" / "cfg" / "RBDCOM_ConfigSettings.h"
        )
        assert not default_target.exists()


# ---------------------------------------------------------------------------
# Smoke: per_product overrides survive a full Phase 2 + Phase 3 run.
# ---------------------------------------------------------------------------


def test_per_product_does_not_break_pipeline_baseline(
    sandbox_with_per_product,
):
    """Sanity: a project.json with per_product overrides loads cleanly
    through the controller's normal config code path. Phase 2 + Phase
    3 both run successfully on the synthetic FSCS doc even with
    multiple skips in play."""
    sandbox = sandbox_with_per_product({
        "ESPCL": {"arxml_file": None},
        "Common": {"config_settings_h": None},
    })
    controller = _controller_at(sandbox)
    assert controller.run_phase2() is True
    assert controller.run_phase3() is True
