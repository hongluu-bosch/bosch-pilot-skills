"""Unit tests for ``scripts/version.py``.

Covers both the happy path (three version sources agree, valid SemVer)
and every drift / corruption mode the runtime check is meant to catch.
Tests always operate on a temp-copy of the skill root so the real
``VERSION`` / ``SKILL.md`` / ``CHANGELOG.md`` files stay untouched.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from version import (  # type: ignore[import-not-found]
    check_version_consistency,
    read_version,
    _SEMVER_RE,
)


@pytest.fixture()
def skill_root(tmp_path: Path, project_root: Path) -> Path:
    """A writable copy of the skill's version-bearing files.

    We don't need the whole skill -- just the three files the version
    module reads. Copy them into a tmp dir so individual tests can
    mutate freely without cross-contamination or leaking into the real
    checkout.
    """
    for name in ("VERSION", "SKILL.md", "CHANGELOG.md"):
        shutil.copy2(project_root / name, tmp_path / name)
    return tmp_path


class TestReadVersion:
    def test_returns_canonical_string(self, skill_root: Path, project_root: Path):
        expected = (project_root / "VERSION").read_text(encoding="utf-8").strip()
        assert read_version(skill_root) == expected

    def test_strips_trailing_newline(self, skill_root: Path):
        (skill_root / "VERSION").write_text("2.3.4\n\n", encoding="utf-8")
        assert read_version(skill_root) == "2.3.4"

    def test_missing_file_raises(self, skill_root: Path):
        (skill_root / "VERSION").unlink()
        with pytest.raises(FileNotFoundError):
            read_version(skill_root)


class TestSemverRegex:
    @pytest.mark.parametrize(
        "value",
        [
            "1.0.0",
            "0.0.1",
            "10.20.30",
            "1.0.0-rc1",
            "1.0.0-alpha.2",
            "1.0.0+build.42",
            "1.0.0-rc1+exp.sha.5114f85",
        ],
    )
    def test_accepts_valid_semver(self, value: str):
        assert _SEMVER_RE.match(value) is not None

    @pytest.mark.parametrize(
        "value",
        [
            "1.0",                    # missing patch
            "1",                      # missing minor + patch
            "v1.0.0",                 # leading v
            "1.0.0 ",                 # trailing space
            "1.0.0-",                 # empty pre-release
            "1.0.a",                  # non-numeric patch
            "",                       # empty string
            "release-candidate",
        ],
    )
    def test_rejects_marketing_strings(self, value: str):
        assert _SEMVER_RE.match(value) is None


class TestConsistencyHappyPath:
    def test_all_three_sources_agree(self, skill_root: Path, project_root: Path):
        expected = (project_root / "VERSION").read_text(encoding="utf-8").strip()
        ok, diagnostics = check_version_consistency(skill_root)
        assert ok is True, diagnostics
        assert diagnostics == [f"did-toolkit {expected}"]

    def test_first_diagnostic_is_always_the_version_line(
        self, skill_root: Path
    ):
        _, diagnostics = check_version_consistency(skill_root)
        assert diagnostics[0].startswith("did-toolkit ")


class TestConsistencyDriftDetection:
    def test_skill_md_out_of_sync(self, skill_root: Path):
        (skill_root / "SKILL.md").write_text(
            "---\nname: did-toolkit\nversion: 0.9.9\ndescription: x\n---\n# x\n",
            encoding="utf-8",
        )
        ok, diagnostics = check_version_consistency(skill_root)
        assert ok is False
        assert any("SKILL.md" in d and "0.9.9" in d for d in diagnostics)

    def test_changelog_out_of_sync(self, skill_root: Path):
        (skill_root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [0.1.0] - 2020-01-01\nFirst release.\n",
            encoding="utf-8",
        )
        ok, diagnostics = check_version_consistency(skill_root)
        assert ok is False
        assert any("CHANGELOG" in d and "0.1.0" in d for d in diagnostics)

    def test_version_file_missing(self, skill_root: Path):
        (skill_root / "VERSION").unlink()
        ok, diagnostics = check_version_consistency(skill_root)
        assert ok is False
        assert diagnostics == ["VERSION file missing from skill root"]

    def test_version_file_not_semver(self, skill_root: Path):
        (skill_root / "VERSION").write_text("v1.0-beta", encoding="utf-8")
        ok, diagnostics = check_version_consistency(skill_root)
        assert ok is False
        assert any("not valid SemVer" in d for d in diagnostics)

    def test_skill_md_missing_frontmatter(self, skill_root: Path):
        (skill_root / "SKILL.md").write_text(
            "# DID Toolkit\n\nNo frontmatter here.\n", encoding="utf-8"
        )
        ok, diagnostics = check_version_consistency(skill_root)
        assert ok is False
        assert any(
            "SKILL.md" in d and "no version found" in d for d in diagnostics
        )

    def test_changelog_unreleased_section_is_skipped(
        self, skill_root: Path, project_root: Path
    ):
        """A draft ``## [Unreleased]`` block above the real entry is OK."""
        expected = (project_root / "VERSION").read_text(encoding="utf-8").strip()
        (skill_root / "CHANGELOG.md").write_text(
            "# Changelog\n\n"
            "## [Unreleased]\n\n- Draft notes.\n\n"
            f"## [{expected}] - 2026-04-20\n\n"
            "Release notes.\n",
            encoding="utf-8",
        )
        ok, diagnostics = check_version_consistency(skill_root)
        assert ok is True, diagnostics


class TestConsistencyBumpFlow:
    """Simulates cutting a new release to make sure the check passes
    again once all three sources are bumped in lock-step."""

    def test_coordinated_bump_passes(self, skill_root: Path):
        import re as _re

        new_version = "99.88.77"
        (skill_root / "VERSION").write_text(f"{new_version}\n", encoding="utf-8")

        skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        skill_text = _re.sub(
            r"^version:\s*[^\r\n]+$",
            f"version: {new_version}",
            skill_text,
            count=1,
            flags=_re.MULTILINE,
        )
        (skill_root / "SKILL.md").write_text(skill_text, encoding="utf-8")

        changelog = (skill_root / "CHANGELOG.md").read_text(encoding="utf-8")
        if changelog.startswith("# Changelog\n\n"):
            bumped = (
                "# Changelog\n\n"
                f"## [{new_version}] - 2026-05-10\n\nAdded feature X.\n\n"
                + changelog.split("# Changelog\n\n", 1)[1]
            )
        else:
            bumped = (
                "# Changelog\n\n"
                f"## [{new_version}] - 2026-05-10\n\nAdded feature X.\n"
            )
        (skill_root / "CHANGELOG.md").write_text(bumped, encoding="utf-8")

        ok, diagnostics = check_version_consistency(skill_root)
        assert ok is True, diagnostics
        assert diagnostics[0] == f"did-toolkit {new_version}"
