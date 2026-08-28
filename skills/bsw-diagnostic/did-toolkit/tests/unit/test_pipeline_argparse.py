"""Unit tests for pipeline CLI argument wiring.

The CLI does not expose ``--output-mode`` / ``--no-backup`` /
``--list-briefs``. There is no ``outputs/<artefact>/`` mirror, no
rolling backup mechanism, and no per-DID Markdown briefs. The
project tree is the sole sink for Phase 2 / Phase 3 and the
``ImplementationGenerator.generate`` kwargs are ``output_dir``
(report sink), ``fscs_json_path``, ``product_type``, and
``dry_run``.

Tests pin:

* ``--help`` still parses (sanity: no left-over references to retired
  flags blow up argparse construction);
* ``run_phase3(dry_run=...)`` forwards ``dry_run`` to the
  (mocked) generator and infers ``product_type`` from the FSCS
  work-set fan-out (no ``--product-type`` CLI knob);
* the deprecated ``output_mode`` / ``no_backup`` parameters are
  rejected by ``run_phase3`` so an agent / CI that still passes
  them fails loudly.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import pipeline as pipeline_mod


# Minimal valid FSCSDocument with one ``used`` DID tagged ``DPB``.
# Phase 3's work-set computation yields ``("DPB",)`` for this fixture
# so the mocked ImplementationGenerator gets called once.
_MINIMAL_FSCS_JSON = {
    "schema_version": "1.5",
    "generated_at": "2024-01-01T00:00:00+00:00",
    "generator": {"tool": "did-toolkit/test", "source_inputs": None},
    "project": {"customer_name": None},
    "dids": [
        {
            "did_hex": "F190",
            "did_name": "TestDid",
            "data_type": "Unsigned",
            "storage_position": "EEPROM",
            "size_bytes": 4,
            "rw_state": "R",
            "nvm_item": "NVM_ID_DCOM_TEST",
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
            "product_type": "DPB",
        }
    ],
}


class TestMainArgparseAcceptsFlags:
    def test_parser_accepts_help(self, monkeypatch):
        # Argparse construction itself is the test: a stale
        # ``parser.add_argument('--output-mode', ...)`` would break
        # consistency; ``--help`` exiting cleanly is the canary.
        monkeypatch.setattr(
            pipeline_mod.sys,
            "argv",
            ["pipeline.py", "--help"],
        )
        with pytest.raises(SystemExit):
            pipeline_mod.main()


class TestRunPhase3KwargsContract:
    @pytest.fixture
    def controller(self, tmp_path):
        """A PipelineController anchored at a throwaway workspace.

        Seeds the expected FSCS inputs and a project.json so
        ``run_phase3`` gets past its hard-gate, then stubs the
        generator.
        """
        (tmp_path / "outputs" / "fscs").mkdir(parents=True)
        (tmp_path / "outputs" / "fscs" / "FSCS_22.txt").write_text("", encoding="utf-8")
        (tmp_path / "outputs" / "fscs" / "FSCS_2E.txt").write_text("", encoding="utf-8")
        (tmp_path / "outputs" / "fscs" / "fscs.json").write_text(
            json.dumps(_MINIMAL_FSCS_JSON),
            encoding="utf-8",
        )
        (tmp_path / "config").mkdir()
        # ``options`` is empty by design. ``paths.base_dir`` is
        # mandatory because Phase 3 writes directly into the Bosch
        # tree; we point it at the sandbox root so the hard-gate
        # passes.
        (tmp_path / "config" / "project.json").write_text(
            json.dumps(
                {
                    "schema_version": "2.2",
                    "options": {},
                    "paths": {"base_dir": str(tmp_path)},
                }
            ),
            encoding="utf-8",
        )
        ctrl = pipeline_mod.PipelineController()
        ctrl.base_dir = tmp_path
        return ctrl

    def test_dry_run_and_product_type_forwarded_to_generator(self, controller):
        captured = {}

        def fake_generate(**kwargs):
            captured.update(kwargs)
            return {
                "total": 0,
                "eeprom": 0,
                "read_functions": 0,
                "write_functions": 0,
                "skipped_c_files": [],
                "agent_fill_targets": [],
                "agent_stub_targets": [],
            }

        with patch("generate_implementation.ImplementationGenerator") as MockGen:
            MockGen.return_value.generate = fake_generate
            ok = controller.run_phase3(dry_run=True)

        assert ok is True
        assert captured["dry_run"] is True
        # Work-set fan-out injects the per-iteration product into
        # the generator kwargs (no ``--product-type`` flag — the
        # CLI knob is not exposed).
        assert captured["product_type"] == "DPB"
        # Retired kwargs must not be present in the call.
        assert "output_mode" not in captured
        assert "no_backup" not in captured

    def test_phase3_rejects_retired_output_mode_kwarg(self, controller):
        """A caller still passing ``output_mode=`` must trip a
        ``TypeError``. Safety net for any external script / CI step
        that has not been migrated yet."""
        with pytest.raises(TypeError):
            controller.run_phase3(output_mode="outputs")

    def test_phase3_rejects_retired_no_backup_kwarg(self, controller):
        """Same rule for ``no_backup`` — the rolling backup mechanism
        is gone, so passing the kwarg must fail loud."""
        with pytest.raises(TypeError):
            controller.run_phase3(no_backup=True)
