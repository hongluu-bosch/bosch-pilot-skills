"""Unit tests for _guarded_project_write.

The guard has exactly two responsibilities:
  * When dry_run=True, print a ``[DRY-RUN] Would <action>`` line and do
    NOT touch the filesystem. Returns False.
  * When dry_run=False, write content and return True.

No routing logic lives here. v1.27.0 retired the ``output_mode`` knob
(the project tree is the sole Phase 2/3 sink); destination resolution
happens higher up in ``generate_from_dids`` via the per-product mirror
helpers, and is exercised by the integration matrix.
"""

from __future__ import annotations

import pytest

from generate_implementation import ImplementationGenerator


@pytest.fixture
def gen() -> ImplementationGenerator:
    return ImplementationGenerator()


class TestGuardedProjectWrite:
    def test_dry_run_skips_disk(self, gen, tmp_path, capsys):
        target = tmp_path / "fake.h"
        result = gen._guarded_project_write(target, "payload", dry_run=True, action="write header")
        assert result is False
        assert not target.exists()
        captured = capsys.readouterr().out
        assert "[DRY-RUN]" in captured
        assert "Would write header" in captured
        assert str(target) in captured

    def test_real_write_hits_disk(self, gen, tmp_path):
        target = tmp_path / "real.h"
        result = gen._guarded_project_write(target, "payload", dry_run=False, action="write header")
        assert result is True
        assert target.read_text(encoding="utf-8") == "payload"

    def test_real_write_overwrites_existing(self, gen, tmp_path):
        target = tmp_path / "existing.h"
        target.write_text("old", encoding="utf-8")
        gen._guarded_project_write(target, "new", dry_run=False, action="overwrite")
        assert target.read_text(encoding="utf-8") == "new"

    def test_dry_run_on_existing_file_leaves_it_unchanged(self, gen, tmp_path):
        target = tmp_path / "existing.h"
        target.write_text("old", encoding="utf-8")
        gen._guarded_project_write(target, "new", dry_run=True, action="merge")
        assert target.read_text(encoding="utf-8") == "old"

    def test_dry_run_reports_byte_count(self, gen, tmp_path, capsys):
        target = tmp_path / "x.h"
        gen._guarded_project_write(target, "abcde", dry_run=True, action="mirror")
        captured = capsys.readouterr().out
        assert "(5 B)" in captured
