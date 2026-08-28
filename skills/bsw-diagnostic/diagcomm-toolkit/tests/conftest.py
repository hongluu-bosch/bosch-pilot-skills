"""Shared pytest fixtures for diagcomm-toolkit tests.

The tests live outside the ``scripts/`` package, so every test that
imports ``pipeline`` / ``runtime`` first has to make the scripts
directory importable. We do that here once, at collection time, instead
of sprinkling ``sys.path.insert`` calls through every test file.

Two-root layout (v2.0.0)
------------------------

The skill split into two roots in v2:

* ``SKILL_ROOT`` = the immutable bundled checkout (scripts / assets /
  reference / tests). Every fixture leaves this alone -- tests only
  ever read from it.
* ``WORKSPACE_ROOT`` = the per-project directory under
  ``<project>/.DCOM_AI/DiagComm_Toolkit_PRJ/`` that owns
  inputs / outputs / state / .cache / for that project.

``fixture_project`` synthesises a fake project tree under ``tmp_path``
and rebinds the workspace constants in every consuming module to point
at that fake project. ``SKILL_ROOT`` stays pointed at the real
checkout (so the fixture-resident schema, templates, and skeletons all
load straight from disk -- no copies needed).

The session-level ``_keep_skill_tree_clean`` hook snapshots the few
gitignored bits that may end up under the *real* SKILL_ROOT or under
the cwd-derived workspace if a test runs anything against the un-mocked
constants (``--init-project`` smoke tests, for example), and restores
that state at session end.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]   # diagcomm-toolkit/
SCRIPTS_DIR = REPO_ROOT / "scripts"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "minimal"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(scope="session", autouse=True)
def _keep_skill_tree_clean():
    """Restore the few skill-relative paths that v2 *might* still mutate
    (``--init-project`` smoke tests, for example, that intentionally
    target the un-mocked workspace) so the working copy stays release-
    clean after pytest. Best-effort; no failure here ever masks a real
    test failure.
    """
    cwd_workspace = (Path.cwd() / ".DCOM_AI" / "DiagComm_Toolkit_PRJ").resolve()
    runtime_paths = [
        REPO_ROOT / "outputs" / "diff_report.txt",
        REPO_ROOT / "outputs" / "validation_report.txt",
        REPO_ROOT / "outputs" / "FSCS.txt",
        REPO_ROOT / "outputs" / "landing_report.txt",
    ]
    before: dict[Path, bytes | None] = {
        p: (p.read_bytes() if p.exists() else None) for p in runtime_paths
    }
    cwd_workspace_existed = cwd_workspace.exists()

    yield

    for p, original in before.items():
        try:
            if original is None:
                if p.exists():
                    p.unlink()
            else:
                p.write_bytes(original)
        except OSError:
            print(f"[conftest] could not restore {p}")

    if not cwd_workspace_existed and cwd_workspace.exists():
        try:
            shutil.rmtree(cwd_workspace)
        except OSError:
            print(f"[conftest] could not remove stray workspace at {cwd_workspace}")


@pytest.fixture
def fixture_project(tmp_path: Path, monkeypatch):
    """Synthesise a fake v2 project under ``tmp_path`` and rebind the
    workspace path constants in ``runtime`` / ``pipeline`` / ``reports``
    to it.

    Layout produced:

        tmp_path/
          project/                          # = "project root"
            dcom/                           # AUTOSAR sibling tree
              RBAPLCust/...
              Cubas/...
            .DCOM_AI/
              DiagComm_Toolkit_PRJ/         # = WORKSPACE_ROOT
                inputs/
                  DiagComm.xlsx             # zero-byte stub
                  DiagComm_values.json      # fixture v2 JSON
                  DiagComm_config.json      # fixture v2 JSON
                outputs/
                .cache/
                state/
                assets/                     # fixture-local schema mirror

    The fixture writes its own absolute ``base_dir`` into the synthesised
    config so v2's ``WORKSPACE_ROOT/<rel>`` resolution lands back on the
    fake AUTOSAR tree regardless of where pytest is run from.
    """
    project_root = tmp_path / "project"
    project_root.mkdir()

    # Mirror the existing minimal fixture's content into the fake
    # project root. The fixture ships a ``dcom/`` tree at top level
    # (sibling of values.json / config.json); we keep that layout but
    # ALSO build the workspace skeleton next to it.
    for entry in FIXTURE_ROOT.iterdir():
        dest = project_root / entry.name
        if entry.is_dir():
            shutil.copytree(entry, dest)
        else:
            shutil.copy2(entry, dest)

    workspace = project_root / ".DCOM_AI" / "DiagComm_Toolkit_PRJ"
    inputs_dir  = workspace / "inputs"
    outputs_dir = workspace / "outputs"
    state_dir   = workspace / "state"
    cache_dir   = workspace / ".cache"
    assets_dir  = workspace / "assets"
    for d in (inputs_dir, outputs_dir, state_dir, cache_dir, assets_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Fixture-local schema mirror: avoids running gen-schema (which is
    # hard-wired to the real SKILL_ROOT) inside fixture setup.
    shutil.copy2(REPO_ROOT / "assets" / "DiagComm_schema.json",
                 assets_dir / "DiagComm_schema.json")

    # Inputs that the fixture's pipeline calls expect to find -- they
    # live in the (workspace) inputs/ dir to mimic the real layout.
    shutil.copy2(project_root / "values.json",
                 inputs_dir / "DiagComm_values.json")
    shutil.copy2(project_root / "config.json",
                 inputs_dir / "DiagComm_config.json")
    # Stub xlsx so existence checks pass without dragging openpyxl in.
    (inputs_dir / "DiagComm.xlsx").write_bytes(b"")

    schema_path = assets_dir / "DiagComm_schema.json"
    pipeline_values_path = inputs_dir / "DiagComm_values.json"
    pipeline_config_path = inputs_dir / "DiagComm_config.json"

    # Rewrite the fixture config so paths.base_dir is absolute -- v2
    # resolves base_dir against WORKSPACE_ROOT, which is now several
    # levels deeper than the fake project root.
    import json as _json
    fixture_config = _json.loads(
        pipeline_config_path.read_text(encoding="utf-8"))
    fixture_paths = dict(fixture_config.get("paths") or {})
    fixture_options = dict(fixture_config.get("options") or {})
    fixture_paths["base_dir"] = str(project_root)
    fixture_config["paths"] = fixture_paths
    pipeline_config_path.write_text(
        _json.dumps(fixture_config, indent=2), encoding="utf-8")

    import pipeline
    import reports
    import runtime

    # Bypass the Excel-driven cache refresh. Fixtures ship as
    # pre-rendered v2 JSON pairs and feed them directly into the legacy
    # loaders, so excel_loader.load_or_refresh must NOT run.
    monkeypatch.setattr(runtime, "_ensure_cache_fresh", lambda: None,
                        raising=False)
    # Workspace gate is also a no-op: every fixture-driven test has
    # the relevant inputs/ dir already written. Without this, every
    # cmd_status / cmd_validate raises SystemExit before reaching the
    # fixture data.
    monkeypatch.setattr(runtime, "_check_workspace_initialized",
                        lambda: None, raising=False)

    for mod in (runtime, pipeline, reports):
        # WORKSPACE_ROOT-derived constants -> fake workspace
        monkeypatch.setattr(mod, "WORKSPACE_ROOT", workspace, raising=False)
        monkeypatch.setattr(mod, "INPUTS_DIR", inputs_dir, raising=False)
        monkeypatch.setattr(mod, "OUTPUTS_DIR", outputs_dir, raising=False)
        monkeypatch.setattr(mod, "STATE_DIR", state_dir, raising=False)
        monkeypatch.setattr(mod, "CACHE_DIR", cache_dir, raising=False)
        # Workspace-resident files
        monkeypatch.setattr(mod, "XLSX_PATH",
                            inputs_dir / "DiagComm.xlsx", raising=False)
        monkeypatch.setattr(mod, "VALUES_PATH", pipeline_values_path,
                            raising=False)
        monkeypatch.setattr(mod, "CONFIG_PATH", pipeline_config_path,
                            raising=False)
        monkeypatch.setattr(mod, "DOORS_MAPPING_PATH",
                            cache_dir / "doors_mapping.yaml", raising=False)

        # ASSETS_DIR-derived constants -> fixture-local schema mirror so
        # tests don't read from the real skill assets in production
        # paths. SKILL_ROOT itself stays pointed at the real checkout
        # because the fixture doesn't try to mirror everything.
        monkeypatch.setattr(mod, "ASSETS_DIR", assets_dir, raising=False)
        monkeypatch.setattr(mod, "SCHEMA_PATH", schema_path, raising=False)
        monkeypatch.setattr(mod, "TEMPLATE_PATH",
                            assets_dir / "inputs_template.xlsx", raising=False)
        monkeypatch.setattr(mod, "DOORS_SKELETON_PATH",
                            assets_dir / "doors_mapping_skeleton.yaml",
                            raising=False)

        # Legacy probes: pin to never-existing paths so the fixture's
        # equivalent JSON files (which look like 1.19.x leftovers but
        # are the *production* loader contract for tests) don't trip
        # the v2 migration error.
        monkeypatch.setattr(mod, "_LEGACY_CONFIG_PATH",
                            project_root / "_no_legacy_here.json",
                            raising=False)
        monkeypatch.setattr(mod, "_LEGACY_INPUTS_VALUES",
                            project_root / "_no_legacy_values.json",
                            raising=False)
        monkeypatch.setattr(mod, "_LEGACY_INPUTS_CONFIG",
                            project_root / "_no_legacy_config.json",
                            raising=False)
        monkeypatch.setattr(mod, "_LEGACY_INPUTS_DOORS",
                            project_root / "_no_legacy_doors.yaml",
                            raising=False)
        monkeypatch.setattr(mod, "_LEGACY_SKILL_XLSX",
                            project_root / "_no_skill_xlsx.xlsx",
                            raising=False)
        monkeypatch.setattr(mod, "_LEGACY_SKILL_VALUES",
                            project_root / "_no_skill_values.json",
                            raising=False)
        monkeypatch.setattr(mod, "_LEGACY_SKILL_CONFIG",
                            project_root / "_no_skill_config.json",
                            raising=False)
        monkeypatch.setattr(mod, "_LEGACY_SKILL_DOORS",
                            project_root / "_no_skill_doors.yaml",
                            raising=False)

        # Lazy-seed's synthesized config uses DEFAULT_PATHS /
        # DEFAULT_OPTIONS at call time. Override them with the fixture's
        # values so a re-seed (e.g. after deleting values.json) targets
        # the fixture's dcom_root.
        monkeypatch.setattr(mod, "DEFAULT_PATHS", fixture_paths,
                            raising=False)
        monkeypatch.setattr(mod, "DEFAULT_OPTIONS", fixture_options,
                            raising=False)

    # Reset the dcom_root cache so we don't pick up a cached entry from
    # a previous test's WORKSPACE_ROOT-based config.
    runtime._DCOM_ROOT_CACHE.clear()

    return {
        "root": project_root,           # the fake project root
        "workspace": workspace,         # .DCOM_AI/DiagComm_Toolkit_PRJ/
        "values": pipeline_values_path,
        "config": pipeline_config_path,
        "schema": schema_path,
        "inputs": inputs_dir,
        "outputs": outputs_dir,
        "state":  state_dir,
        "cache":  cache_dir,
        "dcom":   project_root / "dcom",
    }
