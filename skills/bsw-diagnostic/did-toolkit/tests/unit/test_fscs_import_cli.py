"""Unit tests for the ``scripts/fscs_import.py`` CLI.

The CLI is a thin shim around :func:`scripts.fscs.import_fscs_txt`; the
tests focus on argument-parsing edge cases rather than the import
semantics (which are already covered in ``test_fscs_importer.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import fscs_import


class TestRequireAtLeastOneSource:

    def test_rejects_both_sources_missing(self, tmp_path, capsys):
        with pytest.raises(SystemExit):
            fscs_import.main(["--output", str(tmp_path / "out.json")])

    def test_rejects_nonexistent_file(self, tmp_path):
        with pytest.raises(SystemExit):
            fscs_import.main([
                "--fscs-22", str(tmp_path / "missing.txt"),
                "--output", str(tmp_path / "out.json"),
            ])


class TestHappyPath:

    def test_writes_fscs_json_for_both_sides(self, fixtures_dir, tmp_path):
        out = tmp_path / "fscs.json"
        code = fscs_import.main([
            "--fscs-22", str(fixtures_dir / "expected_fscs_22.txt"),
            "--fscs-2e", str(fixtures_dir / "expected_fscs_2e.txt"),
            "--output", str(out),
        ])
        assert code == 0
        assert out.is_file()
        data = json.loads(out.read_text(encoding="utf-8"))
        # v1.16.0: schema bumped 1.4 -> 1.5 (product_scope rename).
        assert data["schema_version"] == "1.5"
        assert len(data["dids"]) == 5

    def test_single_file_import_leaves_missing_service_unsupported(
        self, fixtures_dir, tmp_path,
    ):
        out = tmp_path / "fscs.json"
        fscs_import.main([
            "--fscs-22", str(fixtures_dir / "expected_fscs_22.txt"),
            "--output", str(out),
        ])
        data = json.loads(out.read_text(encoding="utf-8"))
        for did in data["dids"]:
            assert did["service_2e"]["supported"] is False

    def test_project_metadata_threaded_through_cli(self, fixtures_dir, tmp_path):
        """v1.16.0: ``--customer-name`` still lands on project metadata,
        but ``--product-type`` now stamps each DID's per-DID
        ``product_type`` field (the global ``project.product_type``
        was removed in schema 1.5)."""
        out = tmp_path / "fscs.json"
        fscs_import.main([
            "--fscs-22", str(fixtures_dir / "expected_fscs_22.txt"),
            "--output", str(out),
            "--customer-name", "Acme",
            "--product-type", "DPB",
        ])
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["project"]["customer_name"] == "Acme"
        # FSCSProject no longer carries product_type.
        assert "product_type" not in data["project"]
        # Per-DID stamp picked up the CLI flag.
        assert data["dids"], "no DIDs imported -- fixture regression?"
        for did in data["dids"]:
            assert did["product_type"] == "DPB"

    def test_output_directory_created(self, fixtures_dir, tmp_path):
        out = tmp_path / "nested" / "dir" / "fscs.json"
        code = fscs_import.main([
            "--fscs-22", str(fixtures_dir / "expected_fscs_22.txt"),
            "--output", str(out),
        ])
        assert code == 0
        assert out.is_file()
