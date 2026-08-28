"""Unit tests for :mod:`scripts.fscs.drift`.

Covers the three distinct outcomes the drift checker has to handle:

* No ``fscs.json`` on disk  -> graceful no-op, no warning.
* JSON present and both .txt files match -> silent success.
* JSON present but one or more .txt files are stale / missing ->
  return a populated :class:`DriftReport` *and* write a single
  multi-line ``WARN`` block to the configured stream.

The tests build a minimal :class:`FSCSDocument` in-memory (no real
inputs.json fixture needed) and roundtrip it through the real
renderer, so any future format change is picked up here immediately.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from fscs import (  # noqa: E402
    DIDFscsEntry,
    FSCSDocument,
    FSCSGeneratorMeta,
    FSCSProject,
    FSCSServiceAccess,
    FSCSValueRangeNone,
    check_fscs_drift,
    render_fscs_22_txt,
    render_fscs_2e_txt,
    save_fscs_json,
)


@pytest.fixture
def document() -> FSCSDocument:
    """A tiny document with one read-only DID — enough for drift checks."""
    return FSCSDocument(
        generated_at="2026-04-20T12:00:00+00:00",
        generator=FSCSGeneratorMeta(
            tool="did-toolkit/test",
            source_inputs="tests/fixtures/tiny_did.json",
        ),
        project=FSCSProject(),
        dids=[
            DIDFscsEntry(
                did_hex="F190",
                did_name="BaselineCounter",
                data_type="Unsigned",
                storage_position="RAM",
                size_bytes=1,
                rw_state="R",
                nvm_item="",
                service_22=FSCSServiceAccess(
                    supported=True,
                    sessions=["defaultSession"],
                ),
                service_2e=FSCSServiceAccess(supported=False),
                sub_fields=[],
                value_range=FSCSValueRangeNone(),
            )
        ],
    )


def _write_aligned(outputs_dir: Path, doc: FSCSDocument) -> None:
    fscs_dir = outputs_dir / "fscs"
    fscs_dir.mkdir(parents=True, exist_ok=True)
    save_fscs_json(doc, fscs_dir / "fscs.json")
    (fscs_dir / "FSCS_22.txt").write_text(
        render_fscs_22_txt(doc), encoding="utf-8"
    )
    (fscs_dir / "FSCS_2E.txt").write_text(
        render_fscs_2e_txt(doc), encoding="utf-8"
    )


def test_no_json_returns_empty_report_without_warning(tmp_path):
    stream = io.StringIO()

    report = check_fscs_drift(tmp_path, stream=stream)

    assert report.has_drift is False
    assert report.checked == []
    assert report.drifted == []
    assert report.missing == []
    assert stream.getvalue() == ""


def test_aligned_triplet_reports_no_drift(tmp_path, document):
    _write_aligned(tmp_path, document)
    stream = io.StringIO()

    report = check_fscs_drift(tmp_path, stream=stream)

    assert report.has_drift is False
    assert len(report.checked) == 2
    assert report.drifted == []
    assert report.missing == []
    assert stream.getvalue() == ""


def test_stale_txt_is_flagged_with_warn(tmp_path, document):
    _write_aligned(tmp_path, document)
    stale = tmp_path / "fscs" / "FSCS_22.txt"
    stale.write_text(
        stale.read_text(encoding="utf-8") + "\n# hand-edit sneaked in\n",
        encoding="utf-8",
    )
    stream = io.StringIO()

    report = check_fscs_drift(tmp_path, stream=stream)

    assert report.has_drift is True
    assert stale in report.drifted
    warning = stream.getvalue()
    assert warning.startswith("WARN [fscs.drift]")
    assert "FSCS_22.txt" in warning
    assert "python scripts/generate_fscs.py" in warning


def test_missing_txt_is_surfaced_separately(tmp_path, document):
    _write_aligned(tmp_path, document)
    (tmp_path / "fscs" / "FSCS_2E.txt").unlink()
    stream = io.StringIO()

    report = check_fscs_drift(tmp_path, stream=stream)

    assert report.has_drift is True
    assert tmp_path / "fscs" / "FSCS_2E.txt" in report.missing
    warning = stream.getvalue()
    assert "missing" in warning
    assert "FSCS_2E.txt" in warning


def test_emit_warning_false_suppresses_stream_output(tmp_path, document):
    _write_aligned(tmp_path, document)
    (tmp_path / "fscs" / "FSCS_22.txt").write_text("tampered", encoding="utf-8")
    stream = io.StringIO()

    report = check_fscs_drift(tmp_path, stream=stream, emit_warning=False)

    assert report.has_drift is True
    assert stream.getvalue() == ""
