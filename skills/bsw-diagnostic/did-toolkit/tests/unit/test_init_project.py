"""Unit tests for the ``--init-project`` scaffolder
(schema 2.2, v1.28.0 resumable state machine).

The scaffolder is now a four-state resumable state machine. Each
``--init-project`` invocation advances the workspace by exactly
one step:

1. **FRESH** (no ``.DCOM_AI/DID_Toolkit_PRJ/``) → scaffold the skeleton + starter
   templates, ``[AGENT STOP]`` asking for a questionnaire, exit 0.
2. **FOLDERS_ONLY** (skeleton present, no ``*_did.json``) → re-print
   the "drop a questionnaire" hint, ``[AGENT STOP]``, exit 0.
3. **QUESTIONNAIRE_READY** (questionnaire present, no
   ``config/project.json``) → confirm which questionnaire (numbered
   picker in TTY when multiple, ``[Y/n]`` in TTY when single,
   ``--input <basename>`` override in non-TTY), scan the Bosch
   tree, write ``project.json`` with the chosen file's basename
   recorded under ``paths.input_did_json``, ``[AGENT STOP]``, exit 0.
4. **COMPLETE** (everything in place) → optional Bosch-tree drift
   warning (TTY prompt to overwrite; non-TTY emits a WARN and keeps
   the existing config), then auto-invokes
   :meth:`PipelineController.run_phase1` against the recorded
   questionnaire so the same command that initialised the workspace
   also kicks off Phase 1.

Tests in this module exercise each transition individually. Tests
that need to reach the config-writing branch must seed a
``*_did.json`` under ``.DCOM_AI/DID_Toolkit_PRJ/inputs/`` before invoking the
scaffolder (see :func:`_seed_questionnaire`) so the state machine
starts in QUESTIONNAIRE_READY rather than FRESH.

Other observable contracts pinned here:

* **Bosch-tree detection** auto-populates the six ``paths.*``
  targets with ``{product_type_*}`` placeholders when a tree is
  structurally discoverable; leaves them empty otherwise.
* **Per-product live-tree scan** seeds ``paths.per_product`` for
  asymmetries (missing dirs → ``null`` SKIP; variant-suffixed
  files → string overrides; extras → ``[FYI]`` only).
* **Non-TTY fail-loud** (exit 4) still kicks in at the
  QUESTIONNAIRE_READY → write-config transition when there's no
  detectable tree AND insufficient CLI overrides.
* **Round-trips through the Pydantic model** -- the file written
  by init must load cleanly via :func:`load_project_config`.

The scaffolder consumes ``--name`` / ``--customer-name`` /
``--project-root`` as build-time inputs to materialise paths.*
literal segments and to gate the non-TTY fail-loud check, but
does NOT echo them back into the config (the v1.19.0 cull
removed every pure-bookkeeping field).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from config import load_project_config
from init_project import (
    INIT_STATE_COMPLETE,
    INIT_STATE_FOLDERS_ONLY,
    INIT_STATE_FRESH,
    INIT_STATE_READY,
    _build_paths_block,
    _build_starter_config,
    _detect_bosch_tree,
    _detect_init_state,
    _detect_per_product_overrides,
    _pick_questionnaire,
    run_init_project,
)
from project_root import DCOM_AI_WORKSPACE_DIR


# v1.26.0: ``--init-project <target>`` scaffolds the workspace under
# ``<target>/.DCOM_AI/DID_Toolkit_PRJ/`` rather than directly at ``<target>``. Tests
# that check the on-disk layout therefore look one level deeper.
# ``<target>`` itself is the *project container* (the same directory
# that hosts the Bosch ``rb/as/...`` tree); ``paths.base_dir``
# continues to point there so Phase 2/3 mirrors keep working
# unchanged.
def _ws(target: Path) -> Path:
    """Path to the ``.DCOM_AI/DID_Toolkit_PRJ/`` workspace under ``target``.

    Centralised so a future rename (or a return to the flat layout)
    only edits one place. Kept as a thin alias rather than inlined
    so the assertions read naturally:
    ``(_ws(target) / "config" / "project.json").is_file()``.
    """
    return target / DCOM_AI_WORKSPACE_DIR


def _materialise_bosch_tree(
    workspace: Path, project_root: str = "Fe_Super", customer: str = "rbcn",
) -> None:
    """Create the empty marker directory tree that detection requires."""
    marker = (
        workspace / project_root / "rb" / "as" / customer
        / "core" / "app" / "dcom" / "RBAPLCust"
    )
    marker.mkdir(parents=True)


# v1.28.0: the state machine refuses to write ``project.json`` until
# the operator has dropped a ``*_did.json`` under
# ``.DCOM_AI/DID_Toolkit_PRJ/inputs/``. The seed helper materialises the workspace
# skeleton and plants a minimum-viable questionnaire so each
# test-under-write starts in the QUESTIONNAIRE_READY state. Content
# is just ``[]`` because every transition that mutates
# ``project.json`` only consults the *presence* of the file, not its
# contents (Phase 1 itself does the schema validation later — out of
# scope for init-time unit tests).
_SEED_DID_FILENAME = "acme_did.json"


def _seed_questionnaire(
    target: Path,
    *,
    filename: str = _SEED_DID_FILENAME,
    contents: str = "[]",
) -> Path:
    """Pre-create ``.DCOM_AI/DID_Toolkit_PRJ/inputs/<filename>`` so the state
    machine bypasses FRESH / FOLDERS_ONLY and lands directly in
    QUESTIONNAIRE_READY (or COMPLETE if ``project.json`` is also
    present).

    Returns the absolute path of the seeded file so tests can pass
    it as ``--input`` overrides when needed.
    """
    inputs_dir = _ws(target) / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    seeded = inputs_dir / filename
    seeded.write_text(contents, encoding="utf-8")
    return seeded


# ---------------------------------------------------------------------------
# Non-TTY happy path (with the required CLI overrides)
# ---------------------------------------------------------------------------


def test_non_tty_with_full_overrides_creates_workspace(tmp_path):
    """v1.28.0 non-TTY happy path: with a seeded ``*_did.json`` and
    all identity flags, ``--init-project`` advances through
    QUESTIONNAIRE_READY in one shot. (Pre-v1.28 the same call wrote
    ``project.json`` on the first invocation; the state machine now
    requires the questionnaire to be in place first.)"""
    target = tmp_path / "fresh_workspace"
    target.mkdir()
    _seed_questionnaire(target)

    rc = run_init_project(
        str(target), interactive=False,
        name="MyProj", customer_name="rbcn", project_root="Fe_Super",
    )

    assert rc == 0
    # Workspace artefacts live under <target>/.DCOM_AI/DID_Toolkit_PRJ/.
    assert (_ws(target) / "config" / "project.json").is_file()
    assert (_ws(target) / "inputs").is_dir()
    assert (_ws(target) / "outputs").is_dir()
    # v1.26.0: scripts/ + state/ are also scaffolded so operator-written
    # extract_<customer>.py adapters and the DOORS upload state file
    # have a per-project home rather than polluting the skill folder.
    assert (_ws(target) / "scripts").is_dir()
    assert (_ws(target) / "state").is_dir()


def test_non_tty_writes_loadable_schema_2_config(tmp_path):
    """v1.27.0 starter file must be schema 2.2 and round-trip cleanly."""
    from config import SCHEMA_VERSION
    target = tmp_path / "ws"
    target.mkdir()
    _seed_questionnaire(target)
    run_init_project(
        str(target), interactive=False,
        name="MyProj", customer_name="rbcn", project_root="Fe_Super",
    )

    cfg = load_project_config(_ws(target) / "config" / "project.json")
    # v1.27.0: options block is empty by design (output_mode /
    # backup_* knobs were retired). The class is still present as
    # an extra='forbid' guard so stale keys fail loud.
    assert cfg.schema_version == SCHEMA_VERSION
    assert cfg.schema_version == "2.2"  # v1.27.0 canary


def test_non_tty_starter_omits_culled_fields(tmp_path):
    """v1.19.0 cull pin: emitted JSON must not carry any of the 10
    dropped fields. If a future refactor accidentally re-introduces
    one (e.g. resurrects ``project.created_date`` for "user-friendly
    bookkeeping"), this test surfaces it before the schema's
    forbid-extras kicks in elsewhere."""
    target = tmp_path / "ws"
    target.mkdir()
    _seed_questionnaire(target)
    run_init_project(
        str(target), interactive=False,
        name="MyProj", customer_name="rbcn", project_root="Fe_Super",
    )
    raw = json.loads(
        (_ws(target) / "config" / "project.json").read_text(encoding="utf-8")
    )
    assert set(raw.keys()) == {"schema_version", "paths", "options"}
    assert "project_root" not in raw["paths"]
    for dead_option in ("overwrite_existing", "generate_comments",
                        "validate_before_generate"):
        assert dead_option not in raw["options"]
    # v1.22.0: per_product block is part of schema 2.1; an
    # empty dict here is the no-overrides default (no live tree
    # was scanned in this test).
    assert raw["paths"]["per_product"] == {}
    # v1.28.0: paths.input_did_json records the chosen questionnaire
    # so re-runs in the COMPLETE state can find it without re-prompting.
    assert raw["paths"]["input_did_json"] == _SEED_DID_FILENAME


# ---------------------------------------------------------------------------
# Non-TTY fail-loud — the silent-placeholder fallback is gone
# ---------------------------------------------------------------------------


def test_non_tty_without_name_exits_4(tmp_path):
    """v1.28.0: the fail-loud guard kicks in at the
    QUESTIONNAIRE_READY → write-config transition, not at first
    invocation. Seed a questionnaire so the state machine actually
    reaches the config stage (otherwise FRESH → scaffold + exit 0
    masks the v1.18.0 guard)."""
    target = tmp_path / "ws"
    target.mkdir()
    _seed_questionnaire(target)

    rc = run_init_project(str(target), interactive=False)

    assert rc == 4
    assert not (_ws(target) / "config" / "project.json").exists()


def test_non_tty_first_run_on_empty_dir_scaffolds_and_exits_0(tmp_path):
    """v1.28.0 state machine: first ``--init-project`` on an empty
    directory just creates the ``.DCOM_AI/DID_Toolkit_PRJ/`` skeleton + starter
    templates and stops. No ``project.json`` is written until the
    operator drops a questionnaire and re-runs."""
    target = tmp_path / "ws"

    rc = run_init_project(str(target), interactive=False)
    assert rc == 0
    # Skeleton present, but project.json is not — caller has to drop
    # a questionnaire and re-run to advance.
    assert _ws(target).is_dir()
    assert (_ws(target) / "inputs").is_dir()
    assert (_ws(target) / "outputs").is_dir()
    assert (_ws(target) / "config").is_dir()
    assert not (_ws(target) / "config" / "project.json").exists()


def test_non_tty_with_detected_tree_can_omit_customer_and_project_root(tmp_path):
    """When a Bosch tree is structurally detectable under the
    target, --customer-name / --project-root may be omitted; only
    --name is still required. The detected (project_root,
    customer) gets baked into paths.* literals (not persisted as
    top-level fields, those are gone)."""
    target = tmp_path / "ws"
    target.mkdir()
    _materialise_bosch_tree(target, "Fe_Super", "rbcn")
    _seed_questionnaire(target)

    rc = run_init_project(str(target), interactive=False, name="WS")
    assert rc == 0

    cfg = load_project_config(_ws(target) / "config" / "project.json")
    # The detected pair should appear in the materialised paths.* literals.
    assert "Fe_Super/rb/as/rbcn/" in cfg.paths.pdm_file
    assert cfg.paths.pdm_file.endswith("RBDCOM_Customer.pdm")


# ---------------------------------------------------------------------------
# Refuse-to-clobber soft-refusal
# ---------------------------------------------------------------------------


def test_complete_state_chains_into_phase_1(tmp_path):
    """v1.28.0: a fully-initialised workspace (folders + questionnaire
    + project.json) auto-chains into Phase 1 on the next
    ``--init-project`` invocation. We mock
    :meth:`PipelineController.run_phase1` so the assertion is "Phase
    1 was invoked with the recorded questionnaire", not "Phase 1
    actually succeeded" (which would require a Phase-1-valid
    fixture; out of scope for init-time unit tests)."""
    target = tmp_path / "ws"
    target.mkdir()
    seeded = _seed_questionnaire(target)

    # First run advances FRESH/QUESTIONNAIRE_READY → COMPLETE.
    rc = run_init_project(
        str(target), interactive=False,
        name="WS", customer_name="rbcn", project_root="Fe_Super",
    )
    assert rc == 0
    assert (_ws(target) / "config" / "project.json").is_file()

    # Second run detects COMPLETE → invokes run_phase1.
    with patch("pipeline.PipelineController.run_phase1", return_value=True) \
            as mock_phase1:
        rc = run_init_project(
            str(target), interactive=False,
            name="WS", customer_name="rbcn", project_root="Fe_Super",
        )
    assert rc == 0
    mock_phase1.assert_called_once()
    # Positional input_path is the recorded questionnaire.
    invoked_path = Path(mock_phase1.call_args.args[0])
    assert invoked_path == seeded


def test_complete_state_phase_1_failure_propagates_exit_1(tmp_path):
    """Phase 1 returning ``False`` (e.g. malformed questionnaire,
    Pydantic validation refusal) should surface as ``--init-project``
    exit 1 — the only non-success exit code reachable from the
    COMPLETE auto-chain branch."""
    target = tmp_path / "ws"
    target.mkdir()
    _seed_questionnaire(target)
    run_init_project(
        str(target), interactive=False,
        name="WS", customer_name="rbcn", project_root="Fe_Super",
    )

    with patch("pipeline.PipelineController.run_phase1", return_value=False):
        rc = run_init_project(
            str(target), interactive=False,
            name="WS", customer_name="rbcn", project_root="Fe_Super",
        )
    assert rc == 1


def test_complete_state_drift_non_tty_keeps_existing_config(tmp_path):
    """v1.28.0 drift handling (non-TTY): if the on-disk Bosch tree
    no longer matches what ``paths.pdm_file`` records, we emit a
    WARN but do NOT overwrite the existing config. The operator has
    to re-run in a TTY (or hand-edit project.json) to opt in."""
    target = tmp_path / "ws"
    target.mkdir()
    _materialise_bosch_tree(target, "Fe_Super", "rbcn")
    _seed_questionnaire(target)
    run_init_project(str(target), interactive=False, name="WS")
    config_path = _ws(target) / "config" / "project.json"
    before = config_path.read_text(encoding="utf-8")

    # Simulate drift: rename Fe_Super → Fe_NewRelease on disk.
    (target / "Fe_Super").rename(target / "Fe_NewRelease")

    # Second non-TTY run with the COMPLETE state should keep the
    # existing file (no overwrite without an explicit TTY answer).
    with patch("pipeline.PipelineController.run_phase1", return_value=True):
        rc = run_init_project(str(target), interactive=False, name="WS")
    assert rc == 0
    after = config_path.read_text(encoding="utf-8")
    assert before == after, "non-TTY drift handling must not overwrite project.json"


# ---------------------------------------------------------------------------
# Interactive flow (patched ``input``)
# ---------------------------------------------------------------------------


def test_interactive_flow_uses_operator_answers(tmp_path, monkeypatch):
    """v1.18.0 prompts three identity inputs (name / customer_name /
    project_root); paths.base_dir auto-set from target. v1.19.0:
    those answers materialise paths.* literals but aren't persisted
    as top-level config fields.

    v1.28.0: with a seeded questionnaire the state machine lands in
    QUESTIONNAIRE_READY. The first prompt is now the questionnaire
    confirmation (``[Y/n] Use acme_did.json?``); ``""`` accepts the
    default Y. The remaining three identity prompts are unchanged."""
    target = tmp_path / "ws"
    target.mkdir()
    _seed_questionnaire(target)

    answers = iter([
        "",                 # v1.28.0: questionnaire confirm (default Y)
        "MyProject",        # name
        "vw_premium",       # customer_name
        "Fe_Super_Pro",     # project_root
    ])
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(answers))

    rc = run_init_project(str(target), interactive=True)
    assert rc == 0

    cfg = load_project_config(_ws(target) / "config" / "project.json")
    # v1.26.0: ``paths.base_dir`` is the project *container* (where
    # the Bosch tree lives), NOT the .DCOM_AI/DID_Toolkit_PRJ/ workspace itself.
    # ``--init-project <target>`` therefore stores ``str(target)`` —
    # the workspace path one level deeper is implicit.
    assert cfg.paths.base_dir == str(target.resolve())
    # The three identity answers materialise into paths.* literals
    # (not into a separate ``project`` block which v1.19.0 dropped).
    # Mirror is disabled because the synthetic Bosch tree doesn't exist.
    assert cfg.paths.pdm_file == ""
    # v1.28.0: the confirmed questionnaire is recorded.
    assert cfg.paths.input_did_json == _SEED_DID_FILENAME


def test_interactive_flow_no_product_type_or_base_dir_prompt(tmp_path, monkeypatch):
    """v1.16.0 dropped the product-type prompt; v1.18.0 dropped the
    base_dir prompt. v1.28.0 introduces the questionnaire-confirm
    prompt (replacing the v1.25.0 ``_wait_for_questionnaire``
    Press-Enter). If a future refactor re-introduces a prompt this
    test doesn't whitelist, ``iter()`` raises StopIteration on the
    extra ``input()`` call and the test fails loud."""
    target = tmp_path / "ws"
    target.mkdir()
    _seed_questionnaire(target)

    answers = iter([
        "",            # v1.28.0: questionnaire confirm (default Y)
        "Proj",
        "rbcn",
        "Fe_Super",
    ])
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(answers))

    rc = run_init_project(str(target), interactive=True)
    assert rc == 0


def test_interactive_flow_with_detected_tree_seeds_defaults(tmp_path, monkeypatch):
    """Detected (project_root, customer) becomes the default for the
    last two prompts. Pressing Enter (empty answer) accepts them
    and materialises into paths.* literals.

    v1.28.0: prefixed with the questionnaire-confirm answer."""
    target = tmp_path / "ws"
    target.mkdir()
    _materialise_bosch_tree(target, "Fe_RB_2026", "rbcn_premium")
    _seed_questionnaire(target)

    answers = iter([
        "",                 # v1.28.0: questionnaire confirm (default Y)
        "AcceptedProj",
        "",  # accept detected customer default
        "",  # accept detected project_root default
    ])
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(answers))

    rc = run_init_project(str(target), interactive=True)
    assert rc == 0

    cfg = load_project_config(_ws(target) / "config" / "project.json")
    # Detected pair landed in paths.* literals.
    assert "Fe_RB_2026/rb/as/rbcn_premium/" in cfg.paths.pdm_file


def test_interactive_eof_aborts_cleanly(tmp_path, monkeypatch):
    """Ctrl-D mid-prompt exits 2 and writes nothing.

    v1.28.0: the EOF lands during the questionnaire-confirm prompt
    (the first interactive ``input()`` call in the
    QUESTIONNAIRE_READY transition). Seeding a questionnaire forces
    the state machine to actually reach that prompt — without the
    seed it would short-circuit at FRESH state and return 0 without
    asking anything."""
    target = tmp_path / "ws"
    target.mkdir()
    _seed_questionnaire(target)

    def _raise(*_a, **_k):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)

    rc = run_init_project(str(target), interactive=True)
    assert rc == 2
    assert not (_ws(target) / "config" / "project.json").is_file()


# ---------------------------------------------------------------------------
# Bosch-tree detection
# ---------------------------------------------------------------------------


def test_detect_returns_none_when_no_tree(tmp_path):
    assert _detect_bosch_tree(tmp_path) is None


def test_detect_returns_pair_for_unique_tree(tmp_path):
    _materialise_bosch_tree(tmp_path, "Fe_Super", "rbcn")
    assert _detect_bosch_tree(tmp_path) == ("Fe_Super", "rbcn")


def test_detect_returns_none_for_ambiguous_multiple_trees(tmp_path):
    _materialise_bosch_tree(tmp_path, "Fe_Super", "rbcn")
    _materialise_bosch_tree(tmp_path, "Fe_Other", "rbcustom")
    assert _detect_bosch_tree(tmp_path) is None


def test_detect_returns_none_for_multi_customer_tree(tmp_path):
    _materialise_bosch_tree(tmp_path, "Fe_Super", "rbcn")
    _materialise_bosch_tree(tmp_path, "Fe_Super", "rbcustom")
    assert _detect_bosch_tree(tmp_path) is None


def test_detect_skips_hidden_dirs(tmp_path):
    """Detection skips dot-prefixed directories so .agents / .git /
    .jazz5 don't bloat the candidate list."""
    _materialise_bosch_tree(tmp_path / ".agents", "FakeRoot", "rbcn")
    _materialise_bosch_tree(tmp_path, "Fe_Super", "rbcn")
    assert _detect_bosch_tree(tmp_path) == ("Fe_Super", "rbcn")


# ---------------------------------------------------------------------------
# Mirror-enabled paths block carries product-type placeholders
# ---------------------------------------------------------------------------


def test_paths_block_with_mirror_enabled_has_product_type_placeholders():
    block = _build_paths_block(
        base_dir="/ws", project_root="Fe_Super", customer="rbcn",
        mirror_enabled=True,
    )
    # The arxml_file template uses {product_type_arxml_folder} (not
    # {product_type_upper}) so the ESPCL → ESP Phase-2 path alias
    # takes effect at template expansion time.
    assert "{product_type_arxml_folder}" in block["arxml_file"]
    assert "{product_type_suffix}" in block["arxml_file"]
    assert "{product_type_upper}" not in block["arxml_file"]
    # Phase 3 paths keep {product_type_upper} / {product_type_lower}
    # (the alias is Phase-2-only; ESPCL must keep its own Phase-3
    # subdirectories).
    assert "{product_type_upper}" in block["c_output_subdir"]
    assert "{product_type_lower}" in block["config_settings_h"]
    # PDM / config.h / config_elements.h are product-agnostic.
    assert "{product_type" not in block["pdm_file"]
    assert "{product_type" not in block["config_h"]
    assert "{product_type" not in block["config_elements_h"]
    # paths.project_root is not a config field.
    assert "project_root" not in block


def test_paths_block_with_mirror_disabled_has_empty_strings():
    block = _build_paths_block(
        base_dir="/ws", project_root="Fe_Super", customer="rbcn",
        mirror_enabled=False,
    )
    assert block["pdm_file"] == ""
    assert block["c_output_subdir"] == ""
    assert block["arxml_file"] == ""
    assert block["config_settings_h"] == ""
    assert block["base_dir"] == "/ws"


def test_init_with_detected_tree_writes_placeholder_paths(tmp_path):
    """End-to-end pin: --init-project on a Bosch-tree workspace
    writes {product_type_*} placeholders, NOT a baked-in product.
    The resumable state machine needs the questionnaire seed to
    reach the config stage."""
    target = tmp_path / "ws"
    target.mkdir()
    _materialise_bosch_tree(target, "Fe_Super", "rbcn")
    _seed_questionnaire(target)

    rc = run_init_project(str(target), interactive=False, name="WS")
    assert rc == 0

    raw = json.loads(
        (_ws(target) / "config" / "project.json").read_text(encoding="utf-8")
    )
    paths = raw["paths"]
    assert "{product_type_upper}" in paths["c_output_subdir"]
    # ARXML uses {product_type_arxml_folder} so the ESPCL alias kicks in.
    assert "{product_type_arxml_folder}" in paths["arxml_file"]
    assert "{product_type_lower}" in paths["config_settings_h"]


# ---------------------------------------------------------------------------
# Starter-config builder shape regression pin
# ---------------------------------------------------------------------------


def test_starter_config_has_only_v1_19_top_level_blocks():
    """Starter-config shape pin: exactly three top-level keys
    (schema_version / paths / options)."""
    from config import SCHEMA_VERSION
    payload = _build_starter_config(
        customer_name="rbcn",
        project_root="Fe_Super", base_dir=".",
        mirror_enabled=False,
    )
    assert set(payload.keys()) == {"schema_version", "paths", "options"}
    assert payload["schema_version"] == SCHEMA_VERSION


def test_starter_config_options_block_is_empty():
    """``options`` is an empty placeholder.

    ``output_mode`` (project tree is sole sink) and
    ``backup_before_write`` / ``backup_keep`` (no rolling backup
    mechanism) are not accepted. The class is kept only as an
    ``extra='forbid'`` guard against stale keys.
    """
    payload = _build_starter_config(
        customer_name="rbcn",
        project_root="Fe_Super", base_dir=".",
        mirror_enabled=False,
    )
    assert payload["options"] == {}


# ---------------------------------------------------------------------------
# v1.22.0 — _detect_per_product_overrides: scan a synthetic Bosch tree
# ---------------------------------------------------------------------------


def _materialise_full_bosch_tree(workspace: Path) -> tuple[str, str]:
    """Build a Fe_Super-shaped Bosch tree under ``workspace`` for the
    detector to walk. Returns ``(project_root, customer)`` so the test
    can pass them straight to :func:`_detect_per_product_overrides`.

    The synthetic tree mirrors the v1.22.0 reference customer
    layout: every canonical product gets ``cfg/<PT>/`` + a Phase 2
    ARXML, every product except ``Common`` gets ``<pt_lower>/dcompr/cfg/``
    + a plain ``RBDCOM_ConfigSettings.h``, and ``src/`` carries the
    six recognised PT subdirs. Tests then layer per-test
    perturbations on top (delete cfg/ESPCL/, swap IPB's settings
    file for variants, add IPB11/XPB extras, etc.) to drive
    detector branches deterministically.
    """
    project_root, customer = "Fe_Super", "rbcn"
    base = workspace / project_root / "rb" / "as" / customer
    customer_root = base / "core" / "app" / "dcom" / "RBAPLCust"
    cfg_root = customer_root / "cfg"
    src_root = customer_root / "src"

    cfg_root.mkdir(parents=True)
    src_root.mkdir(parents=True)

    # Phase 2 ARXMLs
    arxml_filename_for = {
        "Common": "Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml",
        "DPB": "Dcm_CusDiag_Services_EcucValues_DPB.arxml",
        "ESP": "Dcm_CusDiag_Services_EcucValues_ESP.arxml",
        "ESPCL": "Dcm_CusDiag_Services_EcucValues_ESPCL.arxml",
        "IPB": "Dcm_CusDiag_Services_EcucValues_IPB.arxml",
        "RBU": "Dcm_CusDiag_Services_EcucValues_RBU.arxml",
    }
    for pt, filename in arxml_filename_for.items():
        pt_dir = cfg_root / pt
        pt_dir.mkdir()
        (pt_dir / filename).write_text("", encoding="utf-8")

    # Phase 3 src/<PT>/ subdirs (empty; the detector only looks at names)
    for pt in ("Common", "DPB", "ESP", "ESPCL", "IPB", "RBU"):
        (src_root / pt).mkdir()

    # Phase 3 dcompr/cfg/RBDCOM_ConfigSettings.h per product. Real
    # Bosch trees omit ``Common/dcompr/`` (the whole reason the
    # v1.22.0 detector exists), but the "template-symmetric"
    # baseline includes it so individual perturbation tests can
    # delete it to drive the exact branch they care about.
    pt_lower_for = {
        "Common": "Common", "DPB": "dpb", "ESP": "esp10",
        "ESPCL": "esp10cl", "IPB": "ipb", "RBU": "rbu",
    }
    for pt, pt_lower in pt_lower_for.items():
        dcompr_cfg = base / pt_lower / "dcompr" / "cfg"
        dcompr_cfg.mkdir(parents=True)
        (dcompr_cfg / "RBDCOM_ConfigSettings.h").write_text("", encoding="utf-8")

    return project_root, customer


def test_detector_returns_empty_on_template_symmetric_tree(tmp_path):
    """A tree where every PT has both cfg/<PT>/ and dcompr/cfg/
    yields no per_product entries — the standard template covers
    everything, so init writes ``per_product: {}``."""
    project_root, customer = _materialise_full_bosch_tree(tmp_path)
    overrides, info, confirm, fyi = _detect_per_product_overrides(
        tmp_path, project_root, customer,
    )
    # v1.24.0: the Phase-2 path alias (ESPCL → ESP) is unconditional —
    # the detector announces it on every fully-populated tree as well,
    # because ESPCL writes into ``cfg/ESP/`` regardless of whether
    # ``cfg/ESPCL/`` happens to exist.
    assert overrides == {}
    info_text = "\n".join(info)
    assert "Phase 2 path alias active: ESPCL → ESP" in info_text
    assert confirm == []
    assert fyi == []


def test_detector_unconditional_phase2_path_alias_message(tmp_path):
    """v1.24.0 — Whether or not ``cfg/ESPCL/`` exists, the detector
    must announce the Phase-2 path alias once, never seed
    ``per_product.ESPCL.arxml_file = null``, and never duplicate
    the message. The alias routes ESPCL Phase-2 outputs into
    ``cfg/ESP/Dcm_..._ESPCL.arxml``; nuking ``per_product.ESPCL``
    in either direction would break that routing.
    """
    project_root, customer = _materialise_full_bosch_tree(tmp_path)
    espcl_dir = (
        tmp_path / project_root / "rb" / "as" / customer
        / "core" / "app" / "dcom" / "RBAPLCust" / "cfg" / "ESPCL"
    )
    # Remove the synthetic ESPCL ARXML + dir to simulate the real tree.
    for child in espcl_dir.iterdir():
        child.unlink()
    espcl_dir.rmdir()

    overrides, info, confirm, fyi = _detect_per_product_overrides(
        tmp_path, project_root, customer,
    )
    # No per_product entry — alias replaces it.
    assert "ESPCL" not in overrides
    # Unconditional path alias [INFO].
    info_text = "\n".join(info)
    assert "Phase 2 path alias active: ESPCL → ESP" in info_text
    # Pinned message shape so a future rewording can't hide the alias.
    assert "cfg/ESP/" in info_text
    assert "DID_Config_ESPCL.arxml" in info_text or "_ESPCL.arxml" in info_text
    # The v1.22.0 null line for ESPCL must NOT appear.
    for line in info:
        assert "paths.per_product.ESPCL.arxml_file = null" not in line
    # Detector announces the alias exactly once per recognised PT.
    alias_lines = [
        ln for ln in info if "Phase 2 path alias active: ESPCL → ESP" in ln
    ]
    assert len(alias_lines) == 1
    assert confirm == []


def test_detector_skips_common_config_settings_when_dcompr_missing(tmp_path):
    """Bosch tree has no ``Common/dcompr/`` → seeds
    ``per_product.Common.config_settings_h = null`` + INFO. The
    Common src/ subdir still exists so other Common artefacts
    are unaffected. Real Bosch trees we've inspected always
    exhibit this asymmetry, but the synthetic full-tree fixture
    seeds Common/dcompr too so each perturbation test can isolate
    the branch it cares about — here we delete it explicitly."""
    project_root, customer = _materialise_full_bosch_tree(tmp_path)
    common_dcompr = (
        tmp_path / project_root / "rb" / "as" / customer
        / "Common" / "dcompr"
    )
    # Recursively remove Common/dcompr/cfg/RBDCOM_ConfigSettings.h
    # then unwind the directory chain.
    (common_dcompr / "cfg" / "RBDCOM_ConfigSettings.h").unlink()
    (common_dcompr / "cfg").rmdir()
    common_dcompr.rmdir()

    overrides, info, confirm, fyi = _detect_per_product_overrides(
        tmp_path, project_root, customer,
    )
    assert overrides.get("Common", {}).get("config_settings_h") is None
    assert any(
        "paths.per_product.Common.config_settings_h = null" in line
        for line in info
    )


def test_detector_picks_ipb_variant_default_when_only_variants_exist(tmp_path):
    """Bosch tree has no ``ipb/dcompr/cfg/RBDCOM_ConfigSettings.h``
    plain file but does have ``..._IPB.h`` / ``..._IPB4HAD.h`` /
    ``..._RoPPSub.h`` variants → seeds the ``_IPB.h`` variant as
    the override and emits ``[CONFIRM]`` listing the alternatives."""
    project_root, customer = _materialise_full_bosch_tree(tmp_path)
    ipb_dcompr_cfg = (
        tmp_path / project_root / "rb" / "as" / customer
        / "ipb" / "dcompr" / "cfg"
    )
    # Replace the plain RBDCOM_ConfigSettings.h with three variants.
    (ipb_dcompr_cfg / "RBDCOM_ConfigSettings.h").unlink()
    for variant in ("RBDCOM_ConfigSettings_IPB.h",
                    "RBDCOM_ConfigSettings_IPB4HAD.h",
                    "RBDCOM_ConfigSettings_RoPPSub.h"):
        (ipb_dcompr_cfg / variant).write_text("", encoding="utf-8")

    overrides, info, confirm, fyi = _detect_per_product_overrides(
        tmp_path, project_root, customer,
    )
    chosen = overrides["IPB"]["config_settings_h"]
    assert chosen is not None
    assert chosen.endswith("RBDCOM_ConfigSettings_IPB.h")
    # CONFIRM lines list the alternatives so the operator can switch.
    confirm_text = "\n".join(confirm)
    assert "auto-defaulted" in confirm_text
    assert "RBDCOM_ConfigSettings_IPB4HAD.h" in confirm_text
    assert "RBDCOM_ConfigSettings_RoPPSub.h" in confirm_text


def test_detector_emits_fyi_for_extra_arxml_files(tmp_path):
    """Bosch tree carries ``Common/Dcm_..._EcucValues.arxml`` (no
    suffix) and ``IPB/Dcm_..._EcucValues_IPB11.arxml`` → standard
    template doesn't cover either → emits ``[FYI]`` with both
    paths so the operator can opt in via per_product override."""
    project_root, customer = _materialise_full_bosch_tree(tmp_path)
    cfg_root = (
        tmp_path / project_root / "rb" / "as" / customer
        / "core" / "app" / "dcom" / "RBAPLCust" / "cfg"
    )
    (cfg_root / "Common" / "Dcm_CusDiag_Services_EcucValues.arxml").write_text(
        "", encoding="utf-8",
    )
    (cfg_root / "IPB" / "Dcm_CusDiag_Services_EcucValues_IPB11.arxml").write_text(
        "", encoding="utf-8",
    )

    _, _, _, fyi = _detect_per_product_overrides(
        tmp_path, project_root, customer,
    )
    fyi_text = "\n".join(fyi)
    assert "Common/Dcm_CusDiag_Services_EcucValues.arxml" in fyi_text
    assert "IPB/Dcm_CusDiag_Services_EcucValues_IPB11.arxml" in fyi_text
    assert "hand-edit" in fyi_text  # actionable guidance present


def test_detector_emits_fyi_for_extra_src_subdirs(tmp_path):
    """``src/IPB11/`` and ``src/XPB/`` are NOT in the recognised
    workset → emits a single ``[FYI]`` line listing them with
    a hand-edit pointer."""
    project_root, customer = _materialise_full_bosch_tree(tmp_path)
    src_root = (
        tmp_path / project_root / "rb" / "as" / customer
        / "core" / "app" / "dcom" / "RBAPLCust" / "src"
    )
    (src_root / "IPB11").mkdir()
    (src_root / "XPB").mkdir()

    _, _, _, fyi = _detect_per_product_overrides(
        tmp_path, project_root, customer,
    )
    fyi_text = "\n".join(fyi)
    assert "IPB11" in fyi_text
    assert "XPB" in fyi_text
    assert "src/" in fyi_text
    assert "c_output_subdir" in fyi_text  # actionable guidance present


def test_detector_returns_empty_when_customer_root_missing(tmp_path):
    """Defensive: if ``--init-project`` was invoked from a directory
    that doesn't contain the Bosch tree at all (e.g. operator typed
    a wrong --base-dir), the detector returns empty rather than
    crashing."""
    overrides, info, confirm, fyi = _detect_per_product_overrides(
        tmp_path, "DoesNotExist", "rbcn",
    )
    assert overrides == {}
    assert info == [] and confirm == [] and fyi == []


def test_init_project_writes_detected_per_product_to_config(tmp_path):
    """End-to-end: ``--init-project`` against a tree with both
    ``cfg/ESPCL/`` AND ``Common/dcompr/`` removed (the canonical
    real-Bosch shape) writes the Common Phase-3 null into
    ``config/project.json::paths.per_product``. v1.23.0: ESPCL no
    longer appears as a per_product entry — the Phase-2 alias
    (ESPCL → ESP) supersedes the v1.22.0 auto-null."""
    project_root, customer = _materialise_full_bosch_tree(tmp_path)
    base_customer = tmp_path / project_root / "rb" / "as" / customer
    # Remove cfg/ESPCL to drive the Phase 2 alias path.
    espcl_dir = (
        base_customer / "core" / "app" / "dcom" / "RBAPLCust" / "cfg" / "ESPCL"
    )
    for child in espcl_dir.iterdir():
        child.unlink()
    espcl_dir.rmdir()
    # Remove Common/dcompr/ to drive the Phase 3 Common auto-disable.
    common_dcompr = base_customer / "Common" / "dcompr"
    (common_dcompr / "cfg" / "RBDCOM_ConfigSettings.h").unlink()
    (common_dcompr / "cfg").rmdir()
    common_dcompr.rmdir()
    _seed_questionnaire(tmp_path)

    rc = run_init_project(str(tmp_path), interactive=False, name="WS")
    assert rc == 0
    cfg = load_project_config(_ws(tmp_path) / "config" / "project.json")
    # v1.23.0: ESPCL is handled by the Phase-2 alias, not per_product.
    assert "ESPCL" not in cfg.paths.per_product
    # Common's config_settings_h still gets the auto-null.
    assert cfg.paths.per_product["Common"]["config_settings_h"] is None


# ---------------------------------------------------------------------------
# v1.28.0: state-machine primitives
# ---------------------------------------------------------------------------


def test_detect_init_state_fresh_on_empty_dir(tmp_path):
    """No ``.DCOM_AI/DID_Toolkit_PRJ/`` at all → FRESH. The classifier inspects the
    workspace directory (one level under the project container), so
    ``_ws(target)`` is what we hand it."""
    target = tmp_path / "ws"
    assert _detect_init_state(_ws(target)) == INIT_STATE_FRESH


def test_detect_init_state_folders_only_when_skeleton_exists_but_no_inputs(tmp_path):
    """Skeleton present, ``inputs/`` empty → FOLDERS_ONLY."""
    target = tmp_path / "ws"
    target.mkdir()
    (_ws(target) / "inputs").mkdir(parents=True)
    (_ws(target) / "outputs").mkdir(parents=True)
    (_ws(target) / "config").mkdir(parents=True)
    assert _detect_init_state(_ws(target)) == INIT_STATE_FOLDERS_ONLY


def test_detect_init_state_ready_when_questionnaire_but_no_config(tmp_path):
    """Questionnaire present, no ``project.json`` → QUESTIONNAIRE_READY."""
    target = tmp_path / "ws"
    target.mkdir()
    _seed_questionnaire(target)
    assert _detect_init_state(_ws(target)) == INIT_STATE_READY


def test_detect_init_state_complete_when_everything_present(tmp_path):
    """Both questionnaire and ``project.json`` present → COMPLETE."""
    target = tmp_path / "ws"
    target.mkdir()
    _seed_questionnaire(target)
    run_init_project(
        str(target), interactive=False,
        name="WS", customer_name="rbcn", project_root="Fe_Super",
    )
    assert _detect_init_state(_ws(target)) == INIT_STATE_COMPLETE


def test_pick_questionnaire_single_non_tty_auto_picks(tmp_path):
    """Single questionnaire + non-TTY → no prompt, return the file."""
    only = tmp_path / "acme_did.json"
    only.write_text("[]", encoding="utf-8")
    assert _pick_questionnaire([only], interactive=False) == only


def test_pick_questionnaire_single_tty_default_yes(tmp_path, monkeypatch):
    """Single questionnaire + TTY + empty answer → default Y."""
    only = tmp_path / "acme_did.json"
    only.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "")
    assert _pick_questionnaire([only], interactive=True) == only


def test_pick_questionnaire_cli_override_matches_basename(tmp_path):
    """``cli_override`` may be a bare basename or a relative path
    pointing into ``inputs/``. The picker should match on basename
    either way (see _pick_questionnaire docstring)."""
    a = tmp_path / "alpha_did.json"
    b = tmp_path / "beta_did.json"
    a.write_text("[]", encoding="utf-8")
    b.write_text("[]", encoding="utf-8")

    assert _pick_questionnaire(
        [a, b], interactive=False, cli_override="beta_did.json"
    ) == b
    assert _pick_questionnaire(
        [a, b], interactive=False,
        cli_override="inputs/beta_did.json",
    ) == b


def test_pick_questionnaire_cli_override_unknown_file_raises(tmp_path):
    """``--input does_not_exist.json`` must fail loud."""
    a = tmp_path / "alpha_did.json"
    a.write_text("[]", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="--input"):
        _pick_questionnaire(
            [a], interactive=False, cli_override="ghost_did.json",
        )


def test_pick_questionnaire_multi_non_tty_uses_recorded_choice(tmp_path):
    """Multiple questionnaires + non-TTY: if ``recorded_choice``
    matches one of them (this is how COMPLETE-state re-runs avoid
    re-prompting), pick that one."""
    a = tmp_path / "alpha_did.json"
    b = tmp_path / "beta_did.json"
    a.write_text("[]", encoding="utf-8")
    b.write_text("[]", encoding="utf-8")
    assert _pick_questionnaire(
        [a, b], interactive=False, recorded_choice="beta_did.json",
    ) == b


def test_pick_questionnaire_multi_tty_numbered_picker(tmp_path, monkeypatch):
    """Multiple questionnaires + TTY → numbered picker. Operator
    types ``2`` to select the second entry (alphabetical order)."""
    a = tmp_path / "alpha_did.json"
    b = tmp_path / "beta_did.json"
    a.write_text("[]", encoding="utf-8")
    b.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "2")
    chosen = _pick_questionnaire(
        sorted([a, b], key=lambda p: p.name), interactive=True,
    )
    assert chosen == b
