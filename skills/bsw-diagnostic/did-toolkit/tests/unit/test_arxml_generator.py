"""Unit tests for ARXMLGenerator.

End-to-end smoke against the tiny fixture, plus spot checks on the
hex-to-decimal and name-cleaning helpers. Full-fidelity output is
diffed against the committed `tests/golden/phase_all/` tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from generate_arxml import ARXMLGenerator


@pytest.fixture
def gen() -> ARXMLGenerator:
    return ARXMLGenerator()


class TestHelpers:
    def test_hex_to_decimal_handles_0x(self, gen):
        assert gen.hex_to_decimal("0xF190") == 0xF190
        assert gen.hex_to_decimal("$F190") == 0xF190
        assert gen.hex_to_decimal("F190") == 0xF190

    def test_clean_name_passes_through_valid(self, gen):
        assert gen.clean_name("BaselineCounter") == "BaselineCounter"

    def test_clean_name_strips_specials(self, gen):
        assert gen.clean_name("A-B!C") == "ABC"


class TestGenerate:
    def test_end_to_end_against_tiny_fscs(self, gen, project_root, tmp_path):
        """Generate ARXML from the golden ``fscs.json``.

        Part 6 removed the TXT ingestion path from the generator, so
        the test now drives the generator with the committed Phase 1
        JSON just like the pipeline does at runtime.
        """
        fscs_json = project_root / "tests" / "golden" / "phase_all" / "fscs" / "fscs.json"
        out = tmp_path / "DID_Config.arxml"
        result = gen.generate(
            fscs_json_path=fscs_json,
            output_path=out,
        )
        assert out.is_file()
        assert result.get("total", 0) == 5
        content = out.read_text(encoding="utf-8")
        # ARXML should be valid XML-ish and include DCM container plus every DID name.
        assert "<AR-PACKAGE>" in content or "<AR-PACKAGES>" in content
        for name in ("BaselineCounter", "ModeSelector", "LiveTemperature",
                     "CalibrationConstant", "RegionCode"):
            assert name in content
