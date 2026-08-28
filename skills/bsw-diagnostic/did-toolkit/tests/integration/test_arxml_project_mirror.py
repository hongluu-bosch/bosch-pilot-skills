"""Integration tests: Phase 2 ARXML project-tree sink.

Contract:

* The project tree (``paths.arxml_file`` composed with
  ``paths.base_dir``) is the SOLE Phase 2 sink — there is no
  ``output_mode`` knob and no ``outputs/arxml/<PT>/DID_Config_*.arxml``
  local mirror.
* No rolling pre-merge backup mechanism. The merge is non-destructive
  (existing ``SHORT-NAME`` containers under ``DcmDsp/SUB-CONTAINERS``
  win), so no safety-net snapshot is needed.
* ``dry_run=True`` skips the project-tree write.

``tiny_did.json`` ships no per-DID ``Product_Type``, so the work-set
collapses to the ``Common`` wildcard — the mirror target lands under
``cfg/Common/Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml`` (the
``{product_type_suffix}`` placeholder maps ``Common`` → ``SingleCANID``).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from freezegun import freeze_time

import pipeline as pipeline_mod


ARXML_REL = (
    "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/cfg/Common/"
    "Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml"
)
LOCAL_REPORT_REL = "outputs/arxml/Common/validation_report_SingleCANID.txt"


EXISTING_ARXML = """<?xml version="1.0" encoding="UTF-8"?>
<AUTOSAR xmlns="http://autosar.org/schema/r4.0">
  <AR-PACKAGES>
    <AR-PACKAGE>
      <SHORT-NAME>Project</SHORT-NAME>
      <ELEMENTS>
        <ECUC-CONTAINER-VALUE>
          <SHORT-NAME>DcmDsp</SHORT-NAME>
          <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp</DEFINITION-REF>
          <SUB-CONTAINERS>
            <ECUC-CONTAINER-VALUE>
              <SHORT-NAME>RBAPLCUST_PreExisting_HandTunedData</SHORT-NAME>
              <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspData</DEFINITION-REF>
            </ECUC-CONTAINER-VALUE>
          </SUB-CONTAINERS>
        </ECUC-CONTAINER-VALUE>
      </ELEMENTS>
    </AR-PACKAGE>
  </AR-PACKAGES>
</AUTOSAR>
"""


@pytest.fixture
def sandbox(tmp_path, fixtures_dir):
    (tmp_path / "inputs").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "outputs").mkdir()
    shutil.copyfile(fixtures_dir / "tiny_did.json", tmp_path / "inputs" / "tiny_did.json")
    shutil.copyfile(fixtures_dir / "tiny_project.json", tmp_path / "config" / "project.json")
    return tmp_path


def _run_phase1(sandbox: Path) -> pipeline_mod.PipelineController:
    controller = pipeline_mod.PipelineController()
    controller.base_dir = sandbox
    input_path = str(sandbox / "inputs" / "tiny_did.json")
    assert controller.run_phase1(input_path) is True
    return controller


@freeze_time("2026-04-20 12:00:00")
def test_phase2_creates_target_when_missing(sandbox):
    """First-time create: no existing file -> full ARXML lands in the project tree."""
    controller = _run_phase1(sandbox)
    assert controller.run_phase2() is True

    target = sandbox / ARXML_REL
    assert target.is_file(), "Phase 2 must create the project-tree ARXML"
    created = target.read_text(encoding="utf-8")

    assert created.startswith("<?xml version=")
    assert "RBAPLCUST_" in created
    assert "<SHORT-NAME>DcmDsp</SHORT-NAME>" in created

    # Validation report still lands under .DCOM_AI/DID_Toolkit_PRJ/outputs/ (the local
    # audit trail). The legacy ``outputs/arxml/.../DID_Config_*.arxml``
    # mirror is gone — only the report stays local.
    assert (sandbox / LOCAL_REPORT_REL).is_file()


@freeze_time("2026-04-20 12:00:00")
def test_phase2_merges_into_existing_target(sandbox):
    """Pre-existing target with a hand-tuned container is preserved and merged."""
    target = sandbox / ARXML_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(EXISTING_ARXML, encoding="utf-8")

    controller = _run_phase1(sandbox)
    assert controller.run_phase2() is True

    merged = target.read_text(encoding="utf-8")

    assert "RBAPLCUST_PreExisting_HandTunedData" in merged
    assert merged.count("<ECUC-CONTAINER-VALUE>") > EXISTING_ARXML.count(
        "<ECUC-CONTAINER-VALUE>"
    )

    # The merge is non-destructive, so no ``outputs/backups/<ts>/``
    # snapshot is produced. Confirm we didn't accidentally
    # re-introduce a backup mechanism.
    backups_root = sandbox / "outputs" / "backups"
    if backups_root.exists():
        sessions = [p for p in backups_root.iterdir() if p.is_dir() and any(p.iterdir())]
        assert not sessions, (
            "No backup directory should be populated; "
            "skip-on-conflict merge is non-destructive."
        )


@freeze_time("2026-04-20 12:00:00")
def test_phase2_is_idempotent(sandbox):
    """Second run with identical inputs -> zero inserts, file unchanged."""
    controller = _run_phase1(sandbox)
    assert controller.run_phase2() is True
    target = sandbox / ARXML_REL
    first = target.read_text(encoding="utf-8")

    assert controller.run_phase2() is True
    second = target.read_text(encoding="utf-8")
    assert first == second, "idempotent re-run must not modify the merged file"


@freeze_time("2026-04-20 12:00:00")
def test_dry_run_does_not_touch_target(sandbox):
    """dry_run=True previews but never writes."""
    target = sandbox / ARXML_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(EXISTING_ARXML, encoding="utf-8")

    controller = _run_phase1(sandbox)
    assert controller.run_phase2(dry_run=True) is True

    assert target.read_text(encoding="utf-8") == EXISTING_ARXML
