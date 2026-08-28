"""``--init-project`` scaffolder — sole workspace-init entry point.

A single ``pipeline.py --init-project`` invocation:

* Creates ``config/project.json`` (the marker file whose existence is
  what makes a directory a "project root" per
  :mod:`scripts.project_root`).
* Auto-detects an adjacent / nested Bosch BSW tree
  (``<...>/<project_root>/rb/as/<customer>/core/app/dcom/RBAPLCust``)
  and pre-populates ``paths.{pdm_file,config_h,config_elements_h,
  config_settings_h,c_output_subdir,arxml_file}`` with
  product-type-templated values. When no Bosch tree is reachable,
  ``paths.*`` is left empty and the workspace stays in the safe
  outputs-only posture (Phase 1 / 2 / 3 still run; mirroring is
  just disabled until the operator hand-edits or re-runs init from
  a directory closer to the tree).
* Walks the live Bosch tree to auto-populate
  ``paths.per_product`` with per-PT skips (``null``) and
  overrides for cases the standard template doesn't fit. A
  Phase-2 product-alias mechanism (currently ``ESPCL → ESP``)
  may pre-empt some auto-nulls; the detector reports each
  class separately:

  - Phase 2 ARXML path aliases: ``cfg/ESPCL/`` is structurally
    absent and ESPCL is registered as a Phase-2 *path* alias of
    ESP, so the detector emits an ``[INFO]`` line confirming
    the alias is active and **does not** seed
    ``per_product.ESPCL.arxml_file = null``. ESPCL still
    iterates Phase 2 with its own ESPCL+Common DID set, but its
    ARXML lands at
    ``cfg/ESP/Dcm_CusDiag_Services_EcucValues_ESPCL.arxml``
    (next to ESP's own ``..._ESP.arxml``); the local mirror is
    ``outputs/arxml/ESP/DID_Config_ESPCL.arxml`` plus
    ``..._ESPCL.txt`` reports. Operators who ship a custom tree
    that carries ``cfg/ESPCL/`` and want a separate ESPCL
    folder must remove ESPCL from ``_PHASE2_PRODUCT_ALIASES``
    in ``scripts/fscs/product_workset.py`` (deliberate code
    change, not a config edit).
  - Phase 2 ARXML missing (no alias): for any PT whose
    ``cfg/<PT>/`` is absent **and** that is not aliased, seeds
    ``per_product.<PT>.arxml_file = null`` so Phase 2 doesn't
    waste a build cycle. Operators can hand-edit the null back
    out if they create the directory later.
  - Phase 3 ConfigSettings: ``Common/dcompr/`` is structurally
    absent → seeds ``per_product.Common.config_settings_h =
    null``. ``IPB`` typically only has variant-suffixed files
    (``RBDCOM_ConfigSettings_IPB.h`` /
    ``RBDCOM_ConfigSettings_IPB4HAD.h`` /
    ``RBDCOM_ConfigSettings_RoPPSub.h``) — when no plain
    ``RBDCOM_ConfigSettings.h`` exists, the detector defaults
    to the ``_IPB.h`` variant and prints a ``[CONFIRM]`` line
    listing the alternatives.
  - The detector also emits ``[FYI]`` lines for ARXML / src
    artefacts present in the Bosch tree but not covered by the
    standard template (e.g. ``Common/Dcm_..._EcucValues.arxml``
    with no suffix, ``IPB/...IPB11.arxml``, ``src/IPB11/`` and
    ``src/XPB/`` subdirectories) so the operator can decide
    whether to add bespoke overrides via hand-edit.
* Creates empty ``inputs/`` and ``outputs/`` subdirectories.
* Refuses to overwrite an existing ``config/project.json`` so a
  double-invocation can't clobber prior edits.

Run modes
---------

**Interactive (TTY).** With no CLI overrides the operator is
prompted for ``name`` / ``customer_name`` / ``project_root``. We
auto-fill defaults from heuristics and from the structural Bosch-
tree scan; pressing Enter on every prompt is the happy path.

**Non-interactive (CI / agent).** Operators pass each value
explicitly via ``--name`` / ``--customer-name`` /
``--project-root`` / ``--base-dir``. Hard-fails (exit 4) when
stdin isn't a TTY and any required field is missing. There is no
silent-placeholder fallback — CI pipelines must supply the
values explicitly so they never ship literal ``Fe_Super`` /
``rbcn`` placeholders into real workspaces.

Re-running ``--init-project`` against an existing workspace is a
soft no-op: the function refuses to overwrite an existing
``config/project.json`` (exit 1) so an accidental second
invocation can't clobber the operator's prior edits.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


_DEFAULT_PROJECT_ROOT_NAME = "Fe_Super"
"""Default Bosch BSW workspace folder name. Used as the suggested
default in interactive mode when no real Bosch tree is detected
under the target. Operators can always override interactively."""


_DEFAULT_CUSTOMER = "rbcn"
"""Default Bosch BSW customer directory name. Used as the suggested
default in interactive mode when no real customer directory is
discovered structurally."""


# ---------------------------------------------------------------------------
# Bosch-tree discovery (quiet: this module logs, the operator-facing
# CLI does the printing).
# ---------------------------------------------------------------------------

_CUSTOMER_MARKER = Path("core") / "app" / "dcom" / "RBAPLCust"


def _iter_customer_dirs(project_root: Path) -> list[str]:
    """Return ``rb/as/<sub>`` directory names under ``project_root``
    whose subtree contains the BSW customer marker."""
    rb_as = project_root / "rb" / "as"
    if not rb_as.is_dir():
        return []
    return [
        sub.name
        for sub in rb_as.iterdir()
        if sub.is_dir() and (sub / _CUSTOMER_MARKER).exists()
    ]


def _detect_bosch_tree(workspace: Path) -> Optional[tuple[str, str]]:
    """Locate ``(project_root_dir_name, customer_name)`` under workspace.

    Pure structural matching (we never guess from names). Returns
    ``None`` when:

    * No subdirectory of ``workspace`` looks like a BSW tree.
    * Multiple subdirectories qualify (operator must disambiguate
      via ``--project-root``).
    * The unique tree has multiple customers (operator must
      disambiguate via ``--customer-name``).

    The caller treats ``None`` as "leave paths.* empty; mirror
    disabled until configured".

    v1.25.0 perf note: the per-product overrides detector
    (:func:`_detect_per_product_overrides`) used to walk the tree a
    *second* time; both helpers now share one scan via
    :func:`_scan_bosch_workspace_once` which is what
    :func:`run_init_project` actually calls. This function is kept
    for backward-compat callers (tests, external scripts) that only
    need the ``(project_root, customer)`` tuple.
    """
    if not workspace.is_dir():
        return None

    candidates: list[tuple[str, list[str]]] = []
    for entry in workspace.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        customers = _iter_customer_dirs(entry)
        if customers:
            candidates.append((entry.name, customers))

    if len(candidates) != 1:
        return None
    project_root, customers = candidates[0]
    if len(customers) != 1:
        return None
    return project_root, customers[0]


def _scan_bosch_workspace_once(
    workspace: Path,
) -> tuple[Optional[tuple[str, str]], list[tuple[str, list[str]]]]:
    """One-shot scan that yields both `(project_root, customer)` and
    every other candidate root the workspace contains.

    v1.25.0 perf optimisation: previously
    :func:`_detect_bosch_tree` walked ``workspace.iterdir()`` and
    :func:`_detect_per_product_overrides` separately walked deep
    inside the customer subtree. On large Bosch trees (5-10k files
    under ``RBAPLCust/``) the two passes plus their nested
    ``iterdir`` calls dominated init time. This helper does the
    top-level scan once and returns:

    * ``primary`` — the ``(project_root, customer)`` pair iff the
      workspace contains exactly one Bosch tree with exactly one
      customer (same contract as :func:`_detect_bosch_tree`); else
      ``None``.
    * ``all_candidates`` — every ``(project_root, customer_list)``
      pair encountered, sorted alphabetically by ``project_root``.
      Kept around so the operator-facing init log can later say
      "found 2 candidate trees, please pick one with
      ``--project-root``" instead of just "no tree detected" when
      the ambiguity is the real cause.

    The deep per-product walk under
    ``<workspace>/<project_root>/rb/as/<customer>/.../RBAPLCust/``
    still happens in :func:`_detect_per_product_overrides` once we
    know which (project_root, customer) to inspect; the win here is
    avoiding the second top-level ``iterdir()`` of ``workspace``
    (which on networked filesystems can cost hundreds of ms per
    call) and avoiding the duplicate per-candidate
    ``_iter_customer_dirs`` walk.
    """
    if not workspace.is_dir():
        return None, []

    candidates: list[tuple[str, list[str]]] = []
    for entry in workspace.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        customers = _iter_customer_dirs(entry)
        if customers:
            candidates.append((entry.name, sorted(customers)))

    candidates.sort(key=lambda pair: pair[0])

    primary: Optional[tuple[str, str]] = None
    if len(candidates) == 1 and len(candidates[0][1]) == 1:
        primary = (candidates[0][0], candidates[0][1][0])

    return primary, candidates


def _validate_bosch_tree(
    workspace: Path, project_root: str, customer: str
) -> bool:
    """True iff ``<workspace>/<project_root>/rb/as/<customer>/<marker>``
    actually exists. Used to validate operator-supplied hints before
    we bake them into ``paths.*``."""
    return (workspace / project_root / "rb" / "as" / customer / _CUSTOMER_MARKER).exists()


def _detect_default_name(target: Path) -> str:
    """Best-effort default for ``project.name``: the target dir's basename."""
    return target.name or "did-toolkit-workspace"


# ---------------------------------------------------------------------------
# v1.25.0: questionnaire pre-flight
# ---------------------------------------------------------------------------

_RAW_WORKBOOK_EXTS = (".xlsx", ".xlsm")
"""Workbook extensions that v1.27.0 explicitly does **not** accept
as Phase-1 input.

The init-time pre-flight still detects them so it can surface a
helpful "you need to run an extractor first" message — that's what
:func:`_discover_raw_workbooks` is for. The Phase-1-ready inputs
are listed separately by :func:`_discover_questionnaires`.
"""


def _discover_questionnaires(inputs_dir: Path) -> list[Path]:
    """Return every Phase-1-ready input file under ``inputs_dir``.

    Only schema-compliant ``*_did.json`` (hand-curated input — or
    output of an agent-written ``.DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py``)
    counts. There is no built-in workbook parser, so raw ``.xlsx`` /
    ``.xlsm`` files are **not** valid Phase-1 inputs.
    Workbooks are still flagged separately
    by :func:`_discover_raw_workbooks` so the pre-flight can print a
    "you've got a workbook but no JSON — write an extractor" hint.

    Mirrors :meth:`PipelineController.discover_input_candidates`
    so init-time and run-time agree on what counts.
    """
    if not inputs_dir.is_dir():
        return []
    return sorted(
        p for p in inputs_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() == ".json"
        and "did" in p.name.lower()
    )


def _discover_raw_workbooks(inputs_dir: Path) -> list[Path]:
    """Return every ``.xlsx`` / ``.xlsm`` workbook under
    ``inputs_dir``.

    v1.27.0 raw workbooks are **not** Phase-1 inputs (the built-in
    GAC / Olympus parsers were removed); this helper exists so the
    init-time pre-flight can spot them and steer the operator
    toward writing a one-shot
    ``.DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py`` adapter. Excel
    temp-files (``~$*``) are filtered out so an open workbook
    doesn't false-positive.
    """
    if not inputs_dir.is_dir():
        return []
    return sorted(
        p for p in inputs_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in _RAW_WORKBOOK_EXTS
        and not p.name.startswith("~$")
    )


# ---------------------------------------------------------------------------
# v1.28.0 resumable init state machine
# ---------------------------------------------------------------------------

INIT_STATE_FRESH = "fresh"
"""``.DCOM_AI/DID_Toolkit_PRJ/`` workspace does not yet exist at
the target (the ``.DCOM_AI/`` umbrella may or may not exist —
both situations fold into the FRESH state).

Transition: scaffold the workspace skeleton (config / inputs /
outputs / scripts / state subdirs + starter templates), print the
"drop your questionnaire" hint, ``[AGENT STOP]``, exit 0.
"""

INIT_STATE_FOLDERS_ONLY = "folders_only"
"""``.DCOM_AI/DID_Toolkit_PRJ/`` workspace exists but
``.DCOM_AI/DID_Toolkit_PRJ/inputs/`` carries no ``*_did.json``
yet.

Transition: re-print the "drop your questionnaire" hint, scaffold
any missing templates idempotently, ``[AGENT STOP]``, exit 0.
"""

INIT_STATE_READY = "questionnaire_ready"
"""``.DCOM_AI/DID_Toolkit_PRJ/inputs/`` carries at least one ``*_did.json`` but
``.DCOM_AI/DID_Toolkit_PRJ/config/project.json`` is missing.

Transition:

1. confirm which questionnaire to use (numbered picker in TTY when
   multiple; ``[Y/n]`` prompt for the single case; ``--input`` flag
   in non-TTY runs);
2. scan the Bosch tree (single pass) and write
   ``.DCOM_AI/DID_Toolkit_PRJ/config/project.json`` with the chosen questionnaire
   recorded under ``paths.input_did_json``;
3. ``[AGENT STOP]``, exit 0. The operator re-runs
   ``--init-project`` to advance into Phase 1.
"""

INIT_STATE_COMPLETE = "complete"
"""``.DCOM_AI/DID_Toolkit_PRJ/`` workspace + ``inputs/*_did.json``
+ ``config/project.json`` are all present.

Transition: optionally surface Bosch-tree drift vs the recorded
``paths.*`` (TTY ``[Y/n] overwrite project.json?`` prompt;
non-TTY emits a single WARN and keeps the existing config), then
auto-invoke ``PipelineController.run_phase1`` so the same command
that initialised the workspace also kicks off the first
generation. Phase 1's own ``[AGENT STOP]`` at the xlsx-review gate
closes the loop.
"""


def _detect_init_state(workspace: Path) -> str:
    """Classify the current ``.DCOM_AI/DID_Toolkit_PRJ/`` state
    into one of the four :data:`INIT_STATE_*` values.

    The classifier is deliberately read-only — it MUST NOT scaffold
    or write anything. The state machine in
    :func:`run_init_project` is the one place that mutates the
    workspace; this helper just observes.

    Resolution rules (first match wins, top-down):

    * workspace dir absent → ``"fresh"``;
    * workspace dir present but no ``inputs/*_did.json`` →
      ``"folders_only"`` (we don't care whether config/project.json
      is also missing here — the state machine will block on the
      questionnaire first);
    * questionnaire present but ``config/project.json`` missing →
      ``"questionnaire_ready"``;
    * everything in place → ``"complete"``.
    """
    if not workspace.is_dir():
        return INIT_STATE_FRESH
    inputs_dir = workspace / "inputs"
    config_path = workspace / "config" / "project.json"
    questionnaires = _discover_questionnaires(inputs_dir)
    if not questionnaires:
        return INIT_STATE_FOLDERS_ONLY
    if not config_path.is_file():
        return INIT_STATE_READY
    return INIT_STATE_COMPLETE


class _QuestionnaireAmbiguous(RuntimeError):
    """Raised in non-TTY mode when multiple ``*_did.json`` are
    present and no ``--input`` override was supplied.

    Caller maps this to exit code 3, matching the v1.12.0
    ``--list-inputs`` ambiguity contract.
    """


def _pick_questionnaire(
    questionnaires: list[Path],
    *,
    interactive: bool,
    recorded_choice: str = "",
    cli_override: str = "",
) -> Path:
    """Resolve which ``*_did.json`` the operator wants for Phase 1.

    Resolution order (first non-empty wins):

    1. ``cli_override`` — operator passed ``--input <basename>``
       explicitly. If the basename doesn't match any candidate,
       raises :class:`FileNotFoundError`.
    2. ``recorded_choice`` — basename previously written into
       ``paths.input_did_json``. Same not-found behaviour as #1.
    3. Single candidate present + TTY → ``[Y/n] Use <name>?``
       prompt (default ``Y``).
    4. Single candidate present + non-TTY → auto-pick (single
       choice, no ambiguity).
    5. Multiple candidates + TTY → numbered picker (sorted by
       basename; user types the index).
    6. Multiple candidates + non-TTY → :class:`_QuestionnaireAmbiguous`
       (caller maps to exit 3 + ``--list-inputs`` style hint).

    Assumes ``questionnaires`` is non-empty (caller checks this and
    blocks on the FOLDERS_ONLY state earlier).
    """
    by_name = {p.name: p for p in questionnaires}

    if cli_override:
        # ``--input`` may carry either a bare basename
        # (``foo_did.json``) or a relative/absolute path
        # (``inputs/foo_did.json`` / ``.DCOM_AI/DID_Toolkit_PRJ/inputs/foo_did.json``);
        # match on the basename in either case so we don't have to
        # care which form the operator used.
        override_basename = Path(cli_override).name
        if override_basename in by_name:
            return by_name[override_basename]
        raise FileNotFoundError(
            f"--input {cli_override!r} does not match any "
            f"*_did.json under .DCOM_AI/DID_Toolkit_PRJ/inputs/. "
            f"Candidates: {sorted(by_name)}"
        )

    if recorded_choice and recorded_choice in by_name:
        return by_name[recorded_choice]

    if len(questionnaires) == 1:
        only = questionnaires[0]
        if not interactive:
            return only
        try:
            ans = input(
                f"  [?] Use {only.name} for Phase 1? [Y/n]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            raise
        if ans in ("", "y", "yes"):
            return only
        raise KeyboardInterrupt(
            "Questionnaire declined; re-run --init-project after "
            "swapping the file in .DCOM_AI/DID_Toolkit_PRJ/inputs/."
        )

    # Multiple candidates from here on.
    if not interactive:
        raise _QuestionnaireAmbiguous(
            f"{len(questionnaires)} *_did.json files in "
            ".DCOM_AI/DID_Toolkit_PRJ/inputs/; non-TTY mode can't prompt. "
            "Pass --input <basename> to disambiguate."
        )

    print()
    print(f"  [?] Found {len(questionnaires)} *_did.json — pick one:")
    for idx, path in enumerate(questionnaires, start=1):
        print(f"      [{idx}] {path.name}")
    while True:
        try:
            raw = input(f"      Pick [1-{len(questionnaires)}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise
        try:
            idx = int(raw)
        except ValueError:
            print(f"      Not a number: {raw!r}; try again.")
            continue
        if 1 <= idx <= len(questionnaires):
            return questionnaires[idx - 1]
        print(
            f"      Out of range; expected 1-{len(questionnaires)}; "
            f"try again."
        )


def _detect_bosch_tree_drift(
    current: Optional[tuple[Optional[str], Optional[str]]],
    recorded_paths: dict,
) -> Optional[str]:
    """Spot a Bosch-tree drift between the live disk scan and what
    ``project.json`` recorded last time.

    Returns ``None`` when no meaningful drift was detected, or a
    short human-readable line describing the drift otherwise. The
    state-machine caller uses the return value to decide whether to
    prompt the operator about overwriting ``project.json``.

    The drift signal is intentionally narrow: we compare the
    auto-detected ``(project_root, customer)`` pair against the
    segments baked into ``paths.pdm_file`` (the most stable of the
    six mirror paths — the others use templated product-type
    folders, which are noisier to diff). If pdm_file is empty
    (mirror-disabled posture) **or** the live scan didn't find any
    tree at all (``current is None``), drift is undefined and we
    return ``None`` to leave the existing config alone. That keeps
    transient ambiguities (e.g. operator renamed a single folder
    mid-init) from clobbering a hand-edited config.
    """
    if current is None:
        return None
    detected_root, detected_customer = current
    if detected_root is None or detected_customer is None:
        return None
    pdm = (recorded_paths or {}).get("pdm_file", "")
    if not pdm:
        return None
    segment = f"{detected_root}/rb/as/{detected_customer}/"
    if segment in pdm:
        return None
    return (
        f"detected Bosch tree at "
        f"{detected_root}/rb/as/{detected_customer}/ but "
        f"project.json's paths.pdm_file is anchored elsewhere: "
        f"{pdm!r}"
    )


_EXTRACTOR_TEMPLATE_FILENAME = "extract_customer.py.template"
"""Name of the v1.27.0 extractor starter template under
``.DCOM_AI/DID_Toolkit_PRJ/scripts/``.

The companion file in the skill itself is
``scripts/templates/extract_customer.py.template`` — see
:func:`_scaffold_extractor_template` for the copy. Operators rename
the scaffolded copy to ``extract_<customer>.py`` (dropping the
``.template`` suffix) and edit the ``_extract_records`` body to
match their actual workbook.
"""

_DOORS_MAPPING_TEMPLATE_FILENAME = "doors_mapping.yaml.template"
"""Name of the v1.27.0 DOORS mapping starter template under
``.DCOM_AI/DID_Toolkit_PRJ/scripts/templates/``.

Source: ``scripts/templates/doors_mapping.yaml.template`` in the
skill itself. ``--init-project`` copies it into
``.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml`` (dropping the ``.template``
suffix) only when no such file already exists, so per-project edits
survive re-runs.
"""


def _scaffold_template_into(
    src_filename: str,
    dst_dir: Path,
    dst_filename: str,
    *,
    purpose: str,
) -> None:
    """Copy ``scripts/templates/<src_filename>`` into ``dst_dir`` as
    ``dst_filename`` (idempotent — won't overwrite an existing
    file).

    Shared scaffolding helper for both the v1.27.0 extractor
    template (lives next to operator-written ``extract_<customer>.py``
    adapters) and the v1.27.0 DOORS mapping template (replaces the
    pre-v1.26 skill-root ``inputs/doors_mapping.yaml``). Missing
    source (partial skill checkout) degrades to a single warning;
    init still completes.
    """
    src = Path(__file__).parent / "templates" / src_filename
    dst = dst_dir / dst_filename
    if dst.exists():
        return
    if not src.is_file():
        logger.warning(
            "%s template source missing: %s. Skipping scaffold — "
            "the workspace will still work, you just won't have a "
            "starter file in place.",
            purpose, src,
        )
        return
    try:
        dst.write_bytes(src.read_bytes())
    except OSError as exc:
        logger.warning(
            "Could not scaffold %s (%s): %s. Copy the file manually "
            "from %s if you want the starter template.",
            dst, purpose, exc, src,
        )


def _scaffold_extractor_template(scripts_dir: Path) -> None:
    """Copy ``extract_customer.py.template`` into
    ``.DCOM_AI/DID_Toolkit_PRJ/scripts/`` so the v1.27.0 extractor contract has a
    concrete starting point. See :func:`_scaffold_template_into`.
    """
    _scaffold_template_into(
        _EXTRACTOR_TEMPLATE_FILENAME,
        scripts_dir,
        _EXTRACTOR_TEMPLATE_FILENAME,
        purpose="Extractor",
    )


def _scaffold_doors_mapping_template(inputs_dir: Path) -> None:
    """Copy ``doors_mapping.yaml.template`` into ``.DCOM_AI/DID_Toolkit_PRJ/inputs/``
    as ``doors_mapping.yaml.template`` so Phase 4 (DOORS) has a
    starter mapping config.

    The operator renames it to ``doors_mapping.yaml`` (dropping the
    ``.template`` suffix) and fills in ``doors.document_uuid`` /
    ``links.link_module_uuid`` for their project. Pipeline.py reads
    ``.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml`` when ``--phase doors`` is
    invoked.

    Pre-v1.26 the file lived at the skill root under
    ``inputs/doors_mapping.yaml``; that location was retired in
    v1.27.0 cleanup.
    """
    _scaffold_template_into(
        _DOORS_MAPPING_TEMPLATE_FILENAME,
        inputs_dir,
        _DOORS_MAPPING_TEMPLATE_FILENAME,
        purpose="DOORS mapping",
    )


def _wait_for_questionnaire(
    inputs_dir: Path, *, interactive: bool,
) -> list[Path]:
    """Pre-flight check for ``inputs/`` — detect JSON, workbooks, or both,
    and emit the appropriate agent signal.

    Four branches (in order of precedence):

    1. **JSON present + workbook(s) also present.**
       Print the JSON list, then an ``[AGENT NOTICE]`` reminding the
       operator that a newer workbook may warrant re-extraction.
       Return the JSON list so the caller can advance.

    2. **JSON present, no workbooks.**
       Normal path — print the JSON list and return it.

    3. **Workbook(s) only, no JSON.**
       Print an ``[AGENT ACTION] auto-extract`` signal listing every
       workbook found.  The agent sees this stdout marker, writes a
       one-shot ``extract_<customer>.py``, runs it, and re-invokes
       ``--init-project`` afterwards.  Return ``[]`` so the state
       machine stays in ``FOLDERS_ONLY`` until the JSON appears.

    4. **Nothing at all.**
       Print a "drop your input" hint.  In TTY mode block on
       ``input()``; in non-TTY mode return ``[]`` immediately.

    The function is read-only with respect to the workspace.
    """
    found = _discover_questionnaires(inputs_dir)
    workbooks = _discover_raw_workbooks(inputs_dir)

    def _report_workbooks(label: str = "FYI") -> None:
        if not workbooks:
            return
        print(
            f"  [{label}] {len(workbooks)} workbook(s) in "
            f"{inputs_dir.name}/"
        )
        for path in workbooks[:5]:
            print(f"        - {path.name}")
        if len(workbooks) > 5:
            print(f"        ... and {len(workbooks) - 5} more")

    # ------------------------------------------------------------------
    # Branches 1 & 2: at least one *_did.json exists
    # ------------------------------------------------------------------
    if found:
        print(
            f"  [OK] {len(found)} *_did.json input(s) in "
            f"{inputs_dir.name}/."
        )
        for path in found[:5]:
            print(f"       - {path.name}")
        if len(found) > 5:
            print(f"       ... and {len(found) - 5} more")

        # Branch 1: JSON + workbook coexistence notice
        if workbooks:
            _report_workbooks(label="AGENT NOTICE")
            print(
                "         A workbook and its extracted JSON coexist. "
                "Re-extract if the workbook is newer or corrected."
            )
        return found

    # ------------------------------------------------------------------
    # Branch 3: workbook(s) only → auto-extraction signal
    # ------------------------------------------------------------------
    if workbooks:
        _report_workbooks(label="AGENT ACTION")
        print()
        print("[AGENT ACTION] auto-extract")
        print("  Detected workbook(s) but no *_did.json.")
        print("  The agent must write a one-shot")
        print("  .DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py adapter,")
        print("  run it to emit the canonical JSON, then re-invoke")
        print("  `--init-project` to advance the workspace.")
        print()
        print("  If extraction fails, the agent reports the error and")
        print("  STOPS — do not retry automatically; let the operator")
        print("  inspect the workbook and intervene.")
        print()
        return []

    # ------------------------------------------------------------------
    # Branch 4: nothing at all
    # ------------------------------------------------------------------
    if not interactive:
        print(
            f"  [warn] No diagnostic input in {inputs_dir}/."
        )
        print(
            "         Place a *_did.json or a workbook there before "
            "running --phase fscs."
        )
        return []

    print()
    print("  [!] No *_did.json or workbook detected yet.")
    print(f"      Drop one into: {inputs_dir}")
    print()
    print("  Re-run --init-project after placing the file.")
    print("  Press Enter to continue (or Ctrl-C to abort)...")
    try:
        input("  > ")
    except (EOFError, KeyboardInterrupt):
        print()
        raise

    found = _discover_questionnaires(inputs_dir)
    if found:
        print(f"  [OK] {len(found)} *_did.json now detected.")
    return found


def _maybe_report_coexistence(inputs_dir: Path) -> None:
    """If ``*_did.json`` and workbook(s) coexist, print an ``[AGENT NOTICE]``.

    Called by the state machine after it has already confirmed that at
    least one JSON exists (so the caller is either QUESTIONNAIRE_READY
    or COMPLETE).  Read-only.
    """
    workbooks = _discover_raw_workbooks(inputs_dir)
    if not workbooks:
        return
    print(
        f"  [AGENT NOTICE] {len(workbooks)} workbook(s) in "
        f"{inputs_dir.name}/ alongside the existing JSON."
    )
    for path in workbooks[:5]:
        print(f"        - {path.name}")
    if len(workbooks) > 5:
        print(f"        ... and {len(workbooks) - 5} more")
    print(
        "         Re-extract if the workbook is newer or corrected; "
        "the existing JSON remains authoritative until then."
    )


_RECOGNISED_SRC_PRODUCTS: tuple[str, ...] = (
    "Common", "DPB", "ESP", "ESPCL", "IPB", "RBU",
)
"""Canonical product subdir names under ``RBAPLCust/src/``.

Anything else a Bosch tree carries (``IPB11``, ``XPB``, future
variants) is reported as a ``[FYI]`` extra during init so the
operator can decide whether to add a per-product override.
"""

_RECOGNISED_CFG_ARXML_PRODUCTS: tuple[str, ...] = (
    "Common", "DPB", "ESP", "ESPCL", "IPB", "RBU",
)
"""Canonical product subdir names under ``RBAPLCust/cfg/``.

Same role as :data:`_RECOGNISED_SRC_PRODUCTS` but for the Phase 2
ARXML side. Bosch trees we've inspected only ever carry the six
canonical subdirs here, but the detector still walks the actual
filesystem so a future divergence shows up as ``[FYI]`` rather
than a silent miss.
"""

_DETECTOR_MSG_LIMIT = 8
"""Cap on lines printed per detector category.

The auto-detect FYI list could in principle balloon if a
customer tree carries dozens of bespoke ARXMLs / src subdirs;
we trim each category at this cap and emit a ``... and N more``
suffix so init output stays readable.
"""


def _detect_per_product_overrides(
    base_dir: Path,
    project_root: str,
    customer: str,
) -> tuple[dict, list[str], list[str], list[str]]:
    """Walk the Bosch tree and synthesise ``paths.per_product`` entries.

    Returns ``(overrides, info_msgs, confirm_msgs, fyi_msgs)``:

    * ``overrides`` — the dict to drop into ``paths.per_product``.
      Keys are canonical product names; values are ``{key: <override
      str | None>}`` sub-dicts. Empty when the tree is fully
      template-symmetric or when ``base_dir`` doesn't contain a
      reachable Bosch tree.
    * ``info_msgs`` — ``[INFO]`` lines describing AUTO-DISABLED
      mirrors (e.g. ``ESPCL.arxml_file = null`` because
      ``cfg/ESPCL/`` is missing from the tree). Operator action:
      none required, just review and confirm.
    * ``confirm_msgs`` — ``[CONFIRM]`` lines describing
      AUTO-DEFAULTED variants (e.g. picking
      ``RBDCOM_ConfigSettings_IPB.h`` when only variant-suffixed
      files exist). Operator action: verify the chosen variant or
      hand-edit ``project.json`` to a different one.
    * ``fyi_msgs`` — ``[FYI]`` lines describing artefacts present
      in the tree but NOT covered by the standard six templates
      (e.g. ``Common/Dcm_..._EcucValues.arxml`` no suffix,
      ``IPB/...IPB11.arxml``, ``src/IPB11/``, ``src/XPB/``).
      Operator action: optional — add bespoke
      ``paths.per_product.<PT>.<key>`` overrides only if you want
      these artefacts mirrored.

    The function is read-only; it never writes to the Bosch tree
    or modifies the workspace. All filesystem operations are
    guarded against missing directories so a partially-populated
    tree (e.g. customer dir exists but ``cfg/`` isn't there yet)
    silently degrades to "no overrides synthesised".
    """
    overrides: dict[str, dict[str, Optional[str]]] = {}
    info_msgs: list[str] = []
    confirm_msgs: list[str] = []
    fyi_msgs: list[str] = []

    customer_root = (
        base_dir / project_root / "rb" / "as" / customer
        / "core" / "app" / "dcom" / "RBAPLCust"
    )
    if not customer_root.is_dir():
        # Mirror not configured / tree not reachable; return empty.
        # Caller still proceeds with an empty per_product block so
        # the schema validates and the v1.22.0 wire format is honoured.
        return overrides, info_msgs, confirm_msgs, fyi_msgs

    # ---- Phase 2: ``cfg/<PT>/Dcm_CusDiag_Services_EcucValues_<suffix>.arxml`` ----
    # v1.24.0: Phase-2 product **path** aliases (currently
    # ``ESPCL → ESP``, see
    # :data:`scripts.fscs.product_workset._PHASE2_PRODUCT_ALIASES`).
    # The alias source PT iterates Phase 2 normally with its own
    # DID set, but its outputs are routed into the alias target's
    # folder via the ``{product_type_arxml_folder}`` placeholder
    # in ``paths.arxml_file`` (so ESPCL writes to
    # ``cfg/ESP/Dcm_..._ESPCL.arxml``, **not** ``cfg/ESPCL/...``).
    # Therefore an alias source PT does NOT need its own
    # ``cfg/<PT>/`` directory present, and we MUST NOT auto-null
    # its ``per_product.<PT>.arxml_file`` (doing so would cancel
    # the alias). The detector emits an unconditional ``[INFO]``
    # line confirming the alias is active, regardless of whether
    # the alias source's own directory happens to exist.
    from fscs import phase2_alias_target_for as _alias_tgt
    cfg_root = customer_root / "cfg"
    if cfg_root.is_dir():
        # Unconditional alias [INFO]: even if the operator's tree
        # does carry ``cfg/ESPCL/`` (uncommon), v1.24.0 still
        # routes ESPCL into ``cfg/ESP/``. Mention both so the
        # operator can decide whether to override.
        for pt in _RECOGNISED_CFG_ARXML_PRODUCTS:
            alias_target = _alias_tgt(pt)
            if not alias_target:
                continue
            target_dir = cfg_root / alias_target
            info_msgs.append(
                f"[INFO] Phase 2 path alias active: {pt} → {alias_target} "
                f"({pt}'s ARXML lands in cfg/{alias_target}/ as "
                f"Dcm_CusDiag_Services_EcucValues_{pt}.arxml, next to "
                f"{alias_target}'s own Dcm_..._{alias_target}.arxml; "
                f"local mirror: outputs/arxml/{alias_target}/DID_Config_{pt}.arxml). "
                f"No paths.per_product.{pt} override needed. To opt out, "
                f"remove {pt} from _PHASE2_PRODUCT_ALIASES in "
                f"scripts/fscs/product_workset.py (deliberate code change)."
            )
            if not target_dir.is_dir():
                # Edge case: ESPCL aliases to ESP, but the operator's
                # tree has no cfg/ESP/ either — flag it so they don't
                # get a silent mkdir surprise on first Phase 2 run.
                fyi_msgs.append(
                    f"[FYI] Phase 2 alias target missing: cfg/{alias_target}/ "
                    f"does not exist yet but {pt} → {alias_target} alias is "
                    f"active. Phase 2 will create the folder on first run; "
                    f"verify the resulting ARXML lands where Bosch expects."
                )

        for pt in _RECOGNISED_CFG_ARXML_PRODUCTS:
            pt_dir = cfg_root / pt
            if pt_dir.is_dir():
                continue
            if _alias_tgt(pt):
                # Alias source PT: handled by the unconditional
                # [INFO] block above; never seed an auto-null here.
                continue
            # Plain "no Bosch ARXML target" — pin SKIP so Phase 2
            # doesn't waste a build cycle producing an
            # ``outputs/arxml/<PT>/`` only to drop it on the floor.
            overrides.setdefault(pt, {})["arxml_file"] = None
            info_msgs.append(
                f"[INFO] paths.per_product.{pt}.arxml_file = null "
                f"(auto-disabled: {pt_dir} does not exist in the "
                f"Bosch tree). Phase 2 will not produce "
                f"outputs/arxml/{pt}/ for this product. To re-enable, "
                f"create the directory and remove the null entry from "
                f"config/project.json::paths.per_product.{pt}."
            )

        # FYI: ARXML files present in cfg/ that the standard template
        # doesn't cover. The template generates one file per recognised
        # product, named ``Dcm_CusDiag_Services_EcucValues_<suffix>.arxml``;
        # anything else (no suffix, alt-suffix like ``_IPB11``) is a
        # bespoke artefact the operator must opt into via per_product.
        extras = _scan_cfg_arxml_extras(cfg_root)
        if extras:
            shown = extras[:_DETECTOR_MSG_LIMIT]
            fyi_msgs.append(
                "[FYI] Bosch tree carries ARXML file(s) NOT covered by the "
                "standard paths.arxml_file template:"
            )
            for path in shown:
                fyi_msgs.append(f"          - {path}")
            if len(extras) > _DETECTOR_MSG_LIMIT:
                fyi_msgs.append(f"          ... and {len(extras) - _DETECTOR_MSG_LIMIT} more")
            fyi_msgs.append(
                "       To mirror to one of these, hand-edit "
                "config/project.json::paths.per_product.<PT>.arxml_file = "
                "\"<the literal path above>\". Otherwise the file is "
                "ignored by Phase 2."
            )

    # ---- Phase 3: ``<pt_lower>/dcompr/cfg/RBDCOM_ConfigSettings*.h`` ----
    # Each canonical product has its own ``<pt_lower>/`` dir; we
    # check whichever lower-case spelling matches the customer's
    # actual layout (``esp10`` for ESP, ``ipb`` for IPB, ``Common``
    # for the wildcard, etc.) by deferring to ``product_type_lower``.
    from implementation.paths import product_type_lower as _ptl

    for pt in _RECOGNISED_SRC_PRODUCTS:
        pt_lower_form = _ptl(None, pt)
        dcompr_dir = (
            base_dir / project_root / "rb" / "as" / customer
            / pt_lower_form / "dcompr" / "cfg"
        )
        plain_path = dcompr_dir / "RBDCOM_ConfigSettings.h"

        if not dcompr_dir.is_dir():
            # No <pt_lower>/dcompr/cfg/ directory at all — the
            # canonical case for ``Common`` (Bosch's tree has no
            # ``Common/dcompr/``). Pin the (PT, key) as SKIP so
            # Phase 3 doesn't produce header_config_settings.txt
            # locally either.
            overrides.setdefault(pt, {})["config_settings_h"] = None
            info_msgs.append(
                f"[INFO] paths.per_product.{pt}.config_settings_h = null "
                f"(auto-disabled: {dcompr_dir} does not exist in the Bosch "
                f"tree). Phase 3 will not produce a "
                f"header_config_settings.txt for this product."
            )
            continue

        if plain_path.exists():
            # Standard template path is correct; no override needed.
            continue

        # Variant-suffixed-only case (the canonical IPB story): walk
        # for ``RBDCOM_ConfigSettings_*.h`` and pick the ``_<PT>.h``
        # variant if present, else the first one alphabetically.
        # Either way, print a CONFIRM with the alternatives so the
        # operator can hand-edit if our pick is wrong.
        variants = sorted(dcompr_dir.glob("RBDCOM_ConfigSettings_*.h"))
        if not variants:
            # Directory exists but no settings header at all — drop
            # to SKIP rather than ship a path that can't merge.
            overrides.setdefault(pt, {})["config_settings_h"] = None
            info_msgs.append(
                f"[INFO] paths.per_product.{pt}.config_settings_h = null "
                f"(auto-disabled: {dcompr_dir} exists but contains no "
                f"RBDCOM_ConfigSettings*.h files). Phase 3 will not "
                f"produce a header_config_settings.txt for this product."
            )
            continue

        preferred = dcompr_dir / f"RBDCOM_ConfigSettings_{pt}.h"
        chosen = preferred if preferred.exists() else variants[0]
        rel_chosen = chosen.relative_to(base_dir).as_posix()
        overrides.setdefault(pt, {})["config_settings_h"] = rel_chosen
        confirm_msgs.append(
            f"[CONFIRM] paths.per_product.{pt}.config_settings_h = "
            f"{rel_chosen!r}"
        )
        confirm_msgs.append(
            f"          (auto-defaulted: {dcompr_dir} has no plain "
            f"RBDCOM_ConfigSettings.h; chose the _{pt} variant)."
        )
        if len(variants) > 1:
            other_names = ", ".join(p.name for p in variants if p != chosen)
            confirm_msgs.append(
                f"          Other variants present: {other_names}. "
                f"To switch, hand-edit "
                f"config/project.json::paths.per_product.{pt}.config_settings_h."
            )

    # ---- Phase 3: ``RBAPLCust/src/<extras>/`` (IPB11, XPB, ...) ----
    src_root = customer_root / "src"
    if src_root.is_dir():
        actual = sorted(
            entry.name for entry in src_root.iterdir() if entry.is_dir()
        )
        extras = [name for name in actual if name not in _RECOGNISED_SRC_PRODUCTS]
        if extras:
            shown = extras[:_DETECTOR_MSG_LIMIT]
            extras_label = ", ".join(shown)
            if len(extras) > _DETECTOR_MSG_LIMIT:
                extras_label += f" (+{len(extras) - _DETECTOR_MSG_LIMIT} more)"
            fyi_msgs.append(
                f"[FYI] Bosch tree carries src/ subdirectories NOT in the "
                f"v1.22.0 product whitelist: {extras_label}."
            )
            fyi_msgs.append(
                "       The standard paths.c_output_subdir template only "
                "writes into the six recognised PT subdirs (DPB / ESP / "
                "ESPCL / IPB / RBU / Common). To also mirror generated "
                "C files into one of the extras, hand-edit "
                "config/project.json::paths.per_product.<PT>.c_output_subdir "
                "= \"Fe_Super/.../RBAPLCust/src/<EXTRA>\" — and consider "
                "whether the DIDs targeting that variant should be tagged "
                "with that PT in fscs_edit.xlsx."
            )

    return overrides, info_msgs, confirm_msgs, fyi_msgs


def _scan_cfg_arxml_extras(cfg_root: Path) -> list[str]:
    """Return paths (relative to cfg_root.parent.parent) for ARXML files
    in ``<cfg_root>/<PT>/`` that the standard template does NOT cover.

    The standard template generates one file per product:
    ``Dcm_CusDiag_Services_EcucValues_<PT|SingleCANID>.arxml``.
    Anything else under ``<cfg_root>/<PT>/`` matching
    ``Dcm_CusDiag_Services_EcucValues*.arxml`` is "extra" — the
    detector reports it as ``[FYI]`` so the operator can decide
    whether to override.
    """
    expected_filenames: dict[str, set[str]] = {}
    for pt in _RECOGNISED_CFG_ARXML_PRODUCTS:
        suffix = "SingleCANID" if pt == "Common" else pt
        expected_filenames[pt] = {f"Dcm_CusDiag_Services_EcucValues_{suffix}.arxml"}

    extras: list[str] = []
    for pt_dir in sorted(cfg_root.iterdir()):
        if not pt_dir.is_dir():
            continue
        expected_for_pt = expected_filenames.get(pt_dir.name, set())
        for arxml in sorted(pt_dir.glob("Dcm_CusDiag_Services_EcucValues*.arxml")):
            if arxml.name not in expected_for_pt:
                # Use forward slashes for cross-platform readability
                # in init's stdout (Windows operators copy these into
                # JSON, which the loader normalises anyway).
                extras.append(arxml.as_posix())
    return extras


def _build_paths_block(
    *,
    base_dir: str,
    project_root: str,
    customer: str,
    mirror_enabled: bool,
    per_product: Optional[dict] = None,
    input_did_json: str = "",
) -> dict:
    """Build the ``paths.*`` block.

    ``project_root`` and ``customer`` are consumed at *build time*
    to materialise the path strings (literal segments, not
    placeholders) but are NOT echoed back into the config — v1.19.0
    dropped both fields after auditing that no runtime consumer
    reads them. The Bosch-tree address is fully recoverable from
    any single ``paths.*`` value if needed.

    When ``mirror_enabled`` is True (i.e. a Bosch tree was detected
    or the operator pinned both project_root + customer), the six
    target paths are pre-populated. Product-type variants are kept
    as ``{product_type_upper}`` / ``{product_type_lower}`` /
    ``{product_type_suffix}`` placeholders that Phase 2 / Phase 3
    expand per-product at run time via
    :func:`scripts.implementation.paths.resolve_path`.

    v1.21.0 introduced ``{product_type_suffix}`` so a single
    ``arxml_file`` template covers both
    ``Dcm_CusDiag_Services_EcucValues_<PT>.arxml`` (per-product) and
    ``Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml`` (Common).

    When ``mirror_enabled`` is False the six paths are left empty;
    Phase 2 / Phase 3 detect this and skip the project-tree mirror
    automatically (outputs-only posture).
    """
    block: dict = {
        "base_dir": base_dir,
        "pdm_file": "",
        "config_h": "",
        "config_elements_h": "",
        "config_settings_h": "",
        "c_output_subdir": "",
        "arxml_file": "",
        # v1.28.0: chosen questionnaire (basename), recorded by
        # the questionnaire-confirmation step of the resumable
        # ``--init-project`` state machine. Empty when no
        # questionnaire has been picked yet — Phase 1 then falls
        # back to the pre-v1.28.0 auto-discovery contract.
        "input_did_json": input_did_json,
        # v1.22.0 (schema 2.1): per-product overrides + skip
        # sentinels. ``--init-project`` populates this from a
        # live Bosch tree scan; an empty dict here is the
        # observationally-identical default for trees that don't
        # need any overrides.
        "per_product": per_product or {},
    }
    if mirror_enabled:
        path_prefix = f"{project_root}/rb/as/{customer}"
        block["pdm_file"] = f"{path_prefix}/core/app/dcom/RBAPLCust/cfg/RBDCOM_Customer.pdm"
        block["config_h"] = f"{path_prefix}/core/app/dcom/RBAPLCust/api/RBAPLCUST_Config.h"
        block["config_elements_h"] = (
            f"{path_prefix}/core/app/dcom/RBAPLCust/api/RBAPLCUST_ConfigElements.h"
        )
        block["config_settings_h"] = (
            f"{path_prefix}/{{product_type_lower}}/dcompr/cfg/RBDCOM_ConfigSettings.h"
        )
        block["c_output_subdir"] = (
            f"{path_prefix}/core/app/dcom/RBAPLCust/src/{{product_type_upper}}"
        )
        # Filename suffix uses ``{product_type_suffix}`` so a
        # ``Common`` fan-out resolves to
        # ``Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml``
        # (matching Bosch's actual ``cfg/Common/`` artefact naming),
        # while every per-product build keeps the canonical
        # ``Dcm_CusDiag_Services_EcucValues_<PT>.arxml`` shape.
        #
        # Folder slot uses ``{product_type_arxml_folder}`` (NOT
        # ``{product_type_upper}``) so the ESPCL → ESP Phase-2 path
        # alias takes effect — ESPCL's iteration writes its ARXML
        # into ``cfg/ESP/`` next to ESP's own ARXML, with the
        # filename suffix (``..._ESPCL.arxml``) doing the per-PT
        # disambiguation. Hand-edited configs that still carry
        # ``{product_type_upper}`` in this slot lose the alias and
        # write to ``cfg/ESPCL/`` instead — re-run ``--init-project``
        # (or hand-swap the placeholder) to pick up the alias.
        block["arxml_file"] = (
            f"{path_prefix}/core/app/dcom/RBAPLCust/cfg/{{product_type_arxml_folder}}"
            f"/Dcm_CusDiag_Services_EcucValues_{{product_type_suffix}}.arxml"
        )
    return block


def _build_starter_config(
    *,
    customer_name: str,
    project_root: str,
    base_dir: str,
    mirror_enabled: bool,
    name: Optional[str] = None,  # accepted but unused; v1.19.0 dropped project.name
    per_product: Optional[dict] = None,
    input_did_json: str = "",
) -> dict:
    """Assemble the starter ``config/project.json`` payload.

    The shape matches schema 2.2: only ``schema_version`` / ``paths``
    / ``options``, with ``options`` an empty placeholder (kept with
    ``extra='forbid'`` so stale knobs from older schemas fail loud at
    load).

    ``mirror_enabled`` is now structurally redundant — Phase 2 / 3
    always target the project tree — but the parameter is retained so
    upstream init flow doesn't churn; downstream :func:`_build_paths_block`
    still uses it to decide between fully-templated paths and
    placeholder-only paths.

    ``per_product`` is the v1.22.0 auto-detected overrides block
    (see :func:`_detect_per_product_overrides`); ``None`` /
    ``{}`` is the empty-overrides posture.

    The ``name`` parameter is accepted for caller compatibility
    (``run_init_project`` keeps a ``--name`` CLI flag for parity
    with the v1.18.0 surface) but is silently dropped here — the
    starter config doesn't echo it back.
    """
    from config.schema import SCHEMA_VERSION
    return {
        "schema_version": SCHEMA_VERSION,
        "paths": _build_paths_block(
            base_dir=base_dir,
            project_root=project_root,
            customer=customer_name,
            mirror_enabled=mirror_enabled,
            per_product=per_product,
            input_did_json=input_did_json,
        ),
        "options": {},
    }


def _prompt(label: str, default: str) -> str:
    """One-shot ``input()`` with a ``[bracketed]`` default fallback."""
    suffix = f" [{default}]" if default else ""
    raw = input(f"  {label}{suffix}: ").strip()
    return raw or default


def _interactive_collect(
    target: Path,
    detected: Optional[tuple[str, str]],
    *,
    name_override: Optional[str] = None,
    customer_override: Optional[str] = None,
    project_root_override: Optional[str] = None,
) -> tuple[dict, bool]:
    """TTY interactive flow: prompt for the editable identity fields.

    v1.18.0 dropped the ``paths.base_dir`` prompt — it's always set
    to the target directory automatically (the operator picks the
    workspace by passing it on the command line). It also dropped
    the product-type prompt (per-DID lives in ``fscs_edit.xlsx``,
    build target is per-run via ``--product-type``).

    The Bosch-tree detection result, if any, drives the defaults so
    the happy path is "press Enter four times".

    Returns ``(payload_dict, mirror_enabled)``. ``mirror_enabled``
    is True when the final (project_root, customer_name) pair
    structurally validates against the Bosch tree under ``target``.
    """
    print()
    from project_root import DCOM_AI_WORKSPACE_DIR
    print(f"Initialising did-toolkit workspace at {target / DCOM_AI_WORKSPACE_DIR}")
    print(f"  (project container: {target})")
    if detected:
        det_root, det_cust = detected
        print(
            f"  detected Bosch BSW tree: "
            f"{target / det_root / 'rb' / 'as' / det_cust}"
        )
    else:
        print("  no Bosch BSW tree detected under this container -- "
              "paths.* will stay empty (outputs-only posture).")
    print("Press Enter to accept the default in [brackets]; edit later in")
    print("config/project.json if needed.")
    print()

    detected_root, detected_customer = (detected or (_DEFAULT_PROJECT_ROOT_NAME, _DEFAULT_CUSTOMER))

    name = name_override or _prompt(
        "Project name", _detect_default_name(target),
    )
    customer_name = customer_override or _prompt(
        "Customer name", detected_customer,
    )
    project_root = project_root_override or _prompt(
        "Bosch project root tree name", detected_root,
    )

    mirror_enabled = _validate_bosch_tree(target, project_root, customer_name)

    # v1.22.0: scan the live Bosch tree for per-product anomalies
    # (missing dirs → SKIP sentinels, variant-suffixed
    # ConfigSettings → CONFIRM defaults, extra ARXMLs / src dirs →
    # FYI lines). Only meaningful when mirror is actually enabled;
    # otherwise return empty + caller skips the print loop.
    if mirror_enabled:
        per_product, info_msgs, confirm_msgs, fyi_msgs = (
            _detect_per_product_overrides(target, project_root, customer_name)
        )
    else:
        per_product, info_msgs, confirm_msgs, fyi_msgs = {}, [], [], []

    payload = _build_starter_config(
        customer_name=customer_name,
        project_root=project_root,
        base_dir=str(target),
        mirror_enabled=mirror_enabled,
        name=name,
        per_product=per_product,
    )
    payload["__detection_messages__"] = {
        "info": info_msgs,
        "confirm": confirm_msgs,
        "fyi": fyi_msgs,
    }
    return (payload, mirror_enabled)


def _build_from_cli_args(
    target: Path,
    *,
    name: Optional[str],
    customer_name: Optional[str],
    project_root: Optional[str],
    base_dir: Optional[str],
    detected: Optional[tuple[str, str]],
) -> tuple[dict, bool]:
    """Non-interactive path: assemble the payload from operator-supplied
    CLI overrides, falling back to detection / sane defaults for any
    field the operator omitted.

    ``mirror_enabled`` is True iff the resolved
    ``(project_root, customer_name)`` validates against the Bosch
    tree under ``base_dir`` — i.e. mirror is enabled only when we
    can prove the path will exist.

    Returns ``(payload_dict, mirror_enabled)``.
    """
    detected_root, detected_customer = (
        detected or (_DEFAULT_PROJECT_ROOT_NAME, _DEFAULT_CUSTOMER)
    )

    resolved_name = name or _detect_default_name(target)
    resolved_customer = customer_name or detected_customer
    resolved_project_root = project_root or detected_root
    resolved_base_dir = base_dir or str(target)

    mirror_enabled = _validate_bosch_tree(
        Path(resolved_base_dir), resolved_project_root, resolved_customer,
    )

    if mirror_enabled:
        per_product, info_msgs, confirm_msgs, fyi_msgs = (
            _detect_per_product_overrides(
                Path(resolved_base_dir),
                resolved_project_root,
                resolved_customer,
            )
        )
    else:
        per_product, info_msgs, confirm_msgs, fyi_msgs = {}, [], [], []

    payload = _build_starter_config(
        customer_name=resolved_customer,
        project_root=resolved_project_root,
        base_dir=resolved_base_dir,
        mirror_enabled=mirror_enabled,
        name=resolved_name,
        per_product=per_product,
    )
    payload["__detection_messages__"] = {
        "info": info_msgs,
        "confirm": confirm_msgs,
        "fyi": fyi_msgs,
    }
    return (payload, mirror_enabled)


def _scaffold_workspace_skeleton(
    workspace: Path,
    target: Path,
    *,
    quiet: bool = False,
) -> tuple[Path, Path, Path, Path, Path]:
    """Create the ``.DCOM_AI/DID_Toolkit_PRJ/`` skeleton
    (config / inputs / outputs / scripts / state) plus the starter
    templates.

    Idempotent — safe to call on every ``--init-project`` invocation.
    ``quiet=True`` skips the operator-facing ``[OK] Ready ...`` lines
    when the caller is going to print its own summary later
    (e.g. the QUESTIONNAIRE_READY transition reprints the full
    summary after writing project.json).

    Returns the five sub-directories as a tuple so the caller can
    reference them without re-deriving the paths.
    """
    config_dir = workspace / "config"
    inputs_dir = workspace / "inputs"
    outputs_dir = workspace / "outputs"
    scripts_dir = workspace / "scripts"
    state_dir = workspace / "state"
    workspace.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(exist_ok=True)
    inputs_dir.mkdir(exist_ok=True)
    outputs_dir.mkdir(exist_ok=True)
    scripts_dir.mkdir(exist_ok=True)
    state_dir.mkdir(exist_ok=True)
    # v1.27.0 starter templates (both idempotent — never overwrite
    # a hand-edited copy).
    _scaffold_extractor_template(scripts_dir)
    _scaffold_doors_mapping_template(inputs_dir)
    if not quiet:
        print(f"  [OK] Scaffolded {workspace.relative_to(target)}/")
        print(f"        ├── {config_dir.name}/   (project.json lands here on next run)")
        print(f"        ├── {inputs_dir.name}/   (drop your *_did.json here)")
        print(f"        ├── {outputs_dir.name}/  (Phase 1/2/3 reports)")
        print(f"        ├── {scripts_dir.name}/  (operator-written extract_<customer>.py)")
        print(f"        └── {state_dir.name}/    (DOORS upload bookkeeping)")
    return config_dir, inputs_dir, outputs_dir, scripts_dir, state_dir


def _print_init_completed_summary(
    config_path: Path,
    inputs_dir: Path,
    outputs_dir: Path,
    scripts_dir: Path,
    state_dir: Path,
    target: Path,
    *,
    mirror_enabled: bool,
    payload: dict,
    detection_messages: dict,
    chosen_questionnaire: Optional[Path],
) -> None:
    """Print the operator-facing summary after the QUESTIONNAIRE_READY
    state successfully writes ``project.json``.

    Pulled out of the inline summary block so the
    INIT_STATE_COMPLETE branch (auto-Phase 1) does not duplicate
    the same 30 lines for the "drift detected, project.json
    rewritten" sub-case.
    """
    print()
    print(f"  [OK] Wrote {config_path.relative_to(target)}")
    if chosen_questionnaire is not None:
        print(
            f"  [OK] Phase 1 questionnaire: {chosen_questionnaire.name} "
            "(recorded under paths.input_did_json)"
        )
    doors_template_dst = inputs_dir / _DOORS_MAPPING_TEMPLATE_FILENAME
    if doors_template_dst.is_file():
        print(
            f"  [OK] Ready {inputs_dir.relative_to(target)}/ "
            "(drop *_did.json here; v1.27.0 no longer ingests .xlsx directly;"
        )
        print(
            f"        DOORS mapping starter at "
            f"{doors_template_dst.relative_to(target)} — "
            "rename to doors_mapping.yaml + fill UUIDs before --phase doors)"
        )
    else:
        print(
            f"  [OK] Ready {inputs_dir.relative_to(target)}/ "
            "(drop *_did.json here; v1.27.0 no longer ingests .xlsx directly)"
        )
    print(f"  [OK] Ready {outputs_dir.relative_to(target)}/")
    template_dst = scripts_dir / _EXTRACTOR_TEMPLATE_FILENAME
    if template_dst.is_file():
        print(
            f"  [OK] Ready {scripts_dir.relative_to(target)}/ "
            "(operator-written extract_<customer>.py adapters;"
        )
        print(
            f"        starter template: "
            f"{template_dst.relative_to(target)})"
        )
    else:
        print(
            f"  [OK] Ready {scripts_dir.relative_to(target)}/ "
            "(operator-written extract_<customer>.py adapters)"
        )
    print(f"  [OK] Ready {state_dir.relative_to(target)}/"
          f" (DOORS upload state + future resumable bookkeeping)")
    if mirror_enabled:
        print(f"  [OK] Bosch tree mirror pre-configured "
              f"(pdm_file = {payload['paths']['pdm_file']}).")
        print("       paths.* carry {product_type_upper/lower/suffix} placeholders;")
        print("       Phase 2/3 fan-out and expand them per-product at run time.")
    else:
        print("  [..] Bosch tree mirror NOT configured -- paths.* left empty.")
        print("       Phases 1/2/3 still run (outputs-only). To mirror later,")
        print("       hand-edit config/project.json::paths.* or rerun")
        print("       --init-project from a directory that contains the tree.")
    # v1.22.0 per-product detector output (INFO first, CONFIRM, FYI)
    info_msgs: list[str] = list(detection_messages.get("info", []))
    confirm_msgs: list[str] = list(detection_messages.get("confirm", []))
    fyi_msgs: list[str] = list(detection_messages.get("fyi", []))
    if info_msgs or confirm_msgs or fyi_msgs:
        print()
        print("Bosch tree per-product auto-detection (v1.22.0):")
        print("------------------------------------------------")
        for line in info_msgs:
            print(f"  {line}")
        if info_msgs and (confirm_msgs or fyi_msgs):
            print()
        for line in confirm_msgs:
            print(f"  {line}")
        if confirm_msgs and fyi_msgs:
            print()
        for line in fyi_msgs:
            print(f"  {line}")


def _build_config_from_inputs(
    target: Path,
    detected: Optional[tuple[str, str]],
    scan_root: Path,
    *,
    interactive: bool,
    name: Optional[str],
    customer_name: Optional[str],
    project_root: Optional[str],
    base_dir: Optional[str],
    input_did_json: str,
) -> tuple[dict, bool]:
    """Build the ``project.json`` payload either interactively or
    from CLI args, applying the v1.18.0 non-TTY fail-loud guard.

    Returns ``(payload, mirror_enabled)``. Raises:

    * :class:`_NonInteractiveMissingOverrides` when non-TTY + the
      operator omitted enough CLI flags that we'd have to ship
      placeholders. Mapped to exit 4 by the caller.
    * :class:`EOFError` / :class:`KeyboardInterrupt` from an
      aborted prompt loop. Mapped to exit 2.

    The ``input_did_json`` argument flows through to
    :func:`_build_starter_config` and lands in
    ``paths.input_did_json``.
    """
    if interactive:
        payload, mirror_enabled = _interactive_collect(
            target,
            detected,
            name_override=name,
            customer_override=customer_name,
            project_root_override=project_root,
        )
    else:
        missing: list[str] = []
        if not name:
            missing.append("--name")
        if not customer_name and detected is None:
            missing.append("--customer-name")
        if not project_root and detected is None:
            missing.append("--project-root")
        if missing:
            raise _NonInteractiveMissingOverrides(
                "Non-TTY environment detected; --init-project requires "
                f"these CLI flags when stdin is not a tty: {', '.join(missing)}.\n"
                f"  Detected Bosch tree under {scan_root}: "
                f"{'yes -- ' + str(detected) if detected else 'no'}\n"
                "  When the Bosch tree is detectable, --customer-name and "
                "--project-root may be omitted (defaults come from the scan).\n"
                "  --base-dir defaults to the workspace target.\n"
                "  v1.14.x's silent-default behaviour was removed in v1.18.0 "
                "to stop CI pipelines from shipping placeholder configs."
            )
        payload, mirror_enabled = _build_from_cli_args(
            target,
            name=name,
            customer_name=customer_name,
            project_root=project_root,
            base_dir=base_dir,
            detected=detected,
        )
    payload["paths"]["input_did_json"] = input_did_json
    return payload, mirror_enabled


class _NonInteractiveMissingOverrides(RuntimeError):
    """Raised by :func:`_build_config_from_inputs` when non-TTY mode
    lacks the CLI overrides needed to anchor ``paths.*`` against
    a real Bosch tree. Caller maps to exit 4 (v1.18.0 fail-loud)."""


def run_init_project(
    target_path: str,
    *,
    interactive: Optional[bool] = None,
    name: Optional[str] = None,
    customer_name: Optional[str] = None,
    project_root: Optional[str] = None,
    base_dir: Optional[str] = None,
    input_choice: Optional[str] = None,
) -> int:
    """Implement ``pipeline.py --init-project [PATH]`` as a resumable
    state machine.

    Each invocation advances the workspace by exactly one step:

    1. **FRESH** (no ``.DCOM_AI/DID_Toolkit_PRJ/``) → scaffold the skeleton +
       starter templates, ``[AGENT STOP]`` asking the operator to
       drop a questionnaire, exit 0.
    2. **FOLDERS_ONLY** (skeleton present, no questionnaire) →
       re-print the "drop a questionnaire" prompt, ``[AGENT STOP]``,
       exit 0.
    3. **QUESTIONNAIRE_READY** (questionnaire present, no
       ``project.json``) → confirm which questionnaire to use,
       scan the Bosch tree, write ``config/project.json`` with the
       choice baked into ``paths.input_did_json``, ``[AGENT STOP]``
       telling the operator to re-run ``--init-project`` to enter
       Phase 1, exit 0.
    4. **COMPLETE** (everything in place) → optionally surface
       Bosch-tree drift (TTY ``[Y/n] overwrite project.json?``;
       non-TTY emits a WARN and keeps the existing config), then
       auto-invoke :meth:`PipelineController.run_phase1` on the
       recorded questionnaire. Phase 1's own ``[AGENT STOP]`` at
       the xlsx-review gate closes the loop.

    Returns a process-style exit code so the caller can ``sys.exit``
    on it directly:

    * ``0`` — workspace advanced one state (or Phase 1 completed
      successfully when state was already COMPLETE).
    * ``1`` — Phase 1 failed (only reachable from the COMPLETE
      auto-chain branch).
    * ``2`` — irrecoverable error (target not writable, interactive
      input aborted, ``--input`` basename not found, etc.).
    * ``3`` — multiple questionnaires + non-TTY + no ``--input``
      override (matches the ``--list-inputs`` ambiguity contract).
    * ``4`` — non-TTY environment with insufficient CLI overrides
      when writing ``project.json`` (fail-loud guard).

    :param target_path: Where the workspace lives. ``"."`` / ``""``
      resolves against CWD. The directory is created lazily.
    :param interactive: ``None`` (default) auto-detects via
      :func:`sys.stdin.isatty`; ``True`` forces the prompt loop;
      ``False`` writes from CLI args alone.
    :param name: Override for the ``--name`` prompt. Required in
      non-TTY mode for the QUESTIONNAIRE_READY → write-config
      transition only.
    :param customer_name: Override for the customer-name prompt.
    :param project_root: Override for the Bosch project-root-tree
      prompt.
    :param base_dir: Override for ``paths.base_dir``.
    :param input_choice: ``--input <basename>`` override for the
      questionnaire picker. Required in non-TTY mode when multiple
      ``*_did.json`` files are present.
    """
    from config import save_project_config
    from config.schema import ProjectConfig
    from project_root import DCOM_AI_WORKSPACE_DIR

    target = Path(target_path or ".").expanduser().resolve()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error(
            f"Cannot create project container {target}: {exc}"
        )
        return 2

    workspace = target / DCOM_AI_WORKSPACE_DIR
    config_path = workspace / "config" / "project.json"

    if interactive is None:
        # Heuristic unchanged from pre-v1.28: any explicit CLI
        # override is a strong signal of non-interactive intent,
        # otherwise fall back to ``isatty()``. ``input_choice`` is
        # NOT considered an "identity override" here — it's a
        # picker disambiguator, valid in both modes.
        any_cli_override = any(v is not None for v in (
            name, customer_name, project_root, base_dir,
        ))
        interactive = (not any_cli_override) and bool(sys.stdin.isatty())

    state = _detect_init_state(workspace)
    logger.debug(f"--init-project state: {state} (target={target})")

    # ------------------------------------------------------------- #
    # STATE 1: FRESH — no ``.DCOM_AI/DID_Toolkit_PRJ/`` yet → scaffold + stop #
    # ------------------------------------------------------------- #
    if state == INIT_STATE_FRESH:
        try:
            config_dir, inputs_dir, outputs_dir, scripts_dir, state_dir = (
                _scaffold_workspace_skeleton(workspace, target)
            )
        except OSError as exc:
            logger.error(
                f"Cannot create did-toolkit workspace {workspace}: {exc}"
            )
            return 2
        print()
        print("  [!] No *_did.json detected yet under "
              f"{inputs_dir.relative_to(target)}/.")
        print("      Drop your questionnaire workbook (.xlsx / .xlsm) here")
        print("      and re-run `--init-project`; the agent will auto-extract")
        print("      the canonical JSON for you. If you already have a")
        print("      schema-compliant *_did.json, place it here directly.")
        print()
        print("[AGENT STOP] End this turn now. In your reply, ask the operator to")
        print("             drop a questionnaire workbook or a *_did.json into")
        print(f"             {inputs_dir}")
        print("             then re-run `--init-project` to advance the workspace.")
        return 0

    # Workspace exists from a prior run. Make sure the skeleton +
    # starter templates are still in place (operator may have
    # deleted them by accident) before continuing.
    try:
        config_dir, inputs_dir, outputs_dir, scripts_dir, state_dir = (
            _scaffold_workspace_skeleton(workspace, target, quiet=True)
        )
    except OSError as exc:
        logger.error(
            f"Cannot repair did-toolkit workspace {workspace}: {exc}"
        )
        return 2

    # ------------------------------------------------------------- #
    # STATE 2: FOLDERS_ONLY — skeleton present, no questionnaire    #
    # ------------------------------------------------------------- #
    if state == INIT_STATE_FOLDERS_ONLY:
        print()
        print(f"  [OK] Workspace already scaffolded at {workspace.relative_to(target)}/.")
        # Recycle the questionnaire pre-flight to surface raw
        # workbooks the operator may have dropped (which we DON'T
        # accept directly post-v1.27.0; steers them to write an
        # extractor adapter).
        try:
            _wait_for_questionnaire(inputs_dir, interactive=interactive)
        except (KeyboardInterrupt, EOFError):
            return 2
        # Re-check post-prompt — operator may have dropped the file
        # while the prompt was open.
        if _discover_questionnaires(inputs_dir):
            # State just advanced inside the prompt — fall through
            # so the QUESTIONNAIRE_READY branch picks it up.
            state = INIT_STATE_READY
        else:
            print()
            print("[AGENT STOP] End this turn now. Ask the operator to drop a")
            print(f"             questionnaire workbook or *_did.json into {inputs_dir}")
            print("             then re-run `--init-project` to advance.")
            return 0

    # ------------------------------------------------------------- #
    # STATE 3: QUESTIONNAIRE_READY — pick + scan + write config     #
    # ------------------------------------------------------------- #
    if state == INIT_STATE_READY:
        questionnaires = _discover_questionnaires(inputs_dir)
        try:
            chosen = _pick_questionnaire(
                questionnaires,
                interactive=interactive,
                cli_override=input_choice or "",
            )
        except _QuestionnaireAmbiguous as exc:
            logger.error(str(exc))
            return 3
        except FileNotFoundError as exc:
            logger.error(str(exc))
            return 2
        except (EOFError, KeyboardInterrupt):
            logger.error("Questionnaire picker aborted; no config written.")
            return 2

        scan_root = (
            Path(base_dir).expanduser().resolve() if base_dir else target
        )
        detected, _all_candidates = _scan_bosch_workspace_once(scan_root)

        try:
            payload, mirror_enabled = _build_config_from_inputs(
                target, detected, scan_root,
                interactive=interactive,
                name=name, customer_name=customer_name,
                project_root=project_root, base_dir=base_dir,
                input_did_json=chosen.name,
            )
        except _NonInteractiveMissingOverrides as exc:
            logger.error(str(exc))
            return 4
        except (EOFError, KeyboardInterrupt):
            logger.error("Interactive init aborted; no files written.")
            return 2

        detection_messages = payload.pop("__detection_messages__", None) or {}
        config = ProjectConfig.model_validate(payload)
        save_project_config(config_path, config)

        _print_init_completed_summary(
            config_path, inputs_dir, outputs_dir, scripts_dir, state_dir,
            target,
            mirror_enabled=mirror_enabled,
            payload=payload,
            detection_messages=detection_messages,
            chosen_questionnaire=chosen,
        )
        _maybe_report_coexistence(inputs_dir)
        print()
        print("Next: re-run `--init-project` to start Phase 1 against")
        print(f"      {chosen.name}, or invoke `--phase fscs` directly.")
        print()
        print("[AGENT STOP] End this turn now. Summarise the [OK] / [CONFIRM] /")
        print("             [FYI] lines above (including the chosen questionnaire")
        print("             and the per-product auto-detect verdicts), and ASK the")
        print("             operator whether to advance into Phase 1. Do NOT chain")
        print("             into Phase 1 on your own.")
        return 0

    # ------------------------------------------------------------- #
    # STATE 4: COMPLETE — drift check, then auto-Phase 1            #
    # ------------------------------------------------------------- #
    assert state == INIT_STATE_COMPLETE  # state machine exhaustiveness
    try:
        existing_payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error(
            f"Cannot read existing {config_path}: {exc}. "
            "Delete the file and re-run --init-project to regenerate."
        )
        return 2

    existing_paths = existing_payload.get("paths", {})
    scan_root = (
        Path(base_dir).expanduser().resolve() if base_dir else target
    )
    detected, _all_candidates = _scan_bosch_workspace_once(scan_root)

    # Optional drift handling (operator-driven; never auto-overwrites).
    drift_msg = _detect_bosch_tree_drift(detected, existing_paths)
    if drift_msg:
        print()
        print(f"  [WARN] {drift_msg}")
        if interactive:
            try:
                ans = input(
                    "         Overwrite project.json with the detected tree? [y/N]: "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                ans = "n"
            if ans in ("y", "yes"):
                try:
                    payload, mirror_enabled = _build_config_from_inputs(
                        target, detected, scan_root,
                        interactive=interactive,
                        name=name, customer_name=customer_name,
                        project_root=project_root, base_dir=base_dir,
                        input_did_json=existing_paths.get("input_did_json", ""),
                    )
                except (
                    _NonInteractiveMissingOverrides, EOFError, KeyboardInterrupt
                ) as exc:
                    logger.error(
                        f"Drift rewrite aborted ({exc!s}); keeping existing config."
                    )
                else:
                    detection_messages = payload.pop("__detection_messages__", None) or {}
                    config = ProjectConfig.model_validate(payload)
                    save_project_config(config_path, config)
                    print(f"  [OK] {config_path.relative_to(target)} regenerated.")
                    existing_paths = payload["paths"]
            else:
                print("         Keeping existing config.")
        else:
            print("         project.json kept (non-TTY can't prompt). Re-run")
            print("         --init-project in a terminal to overwrite, or hand-edit.")

    # Resolve questionnaire (honour recorded choice; allow CLI override
    # for the "I want a different one this round" case).
    _maybe_report_coexistence(inputs_dir)
    questionnaires = _discover_questionnaires(inputs_dir)
    if not questionnaires:
        # Operator deleted the questionnaire after init — state
        # machine fell out of COMPLETE between the classifier and
        # this branch (rare race). Drop back to the FOLDERS_ONLY
        # response rather than crashing.
        print()
        print("  [!] project.json present but no *_did.json under "
              f"{inputs_dir.relative_to(target)}/.")
        print("      Drop one and re-run --init-project to start Phase 1.")
        print()
        print("[AGENT STOP] End this turn now.")
        return 0

    try:
        chosen = _pick_questionnaire(
            questionnaires,
            interactive=interactive,
            recorded_choice=existing_paths.get("input_did_json", ""),
            cli_override=input_choice or "",
        )
    except _QuestionnaireAmbiguous as exc:
        logger.error(str(exc))
        return 3
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 2
    except (EOFError, KeyboardInterrupt):
        logger.error("Questionnaire picker aborted.")
        return 2

    # Auto-chain into Phase 1.
    print()
    print("=" * 60)
    print(f"Workspace already initialised; advancing into Phase 1 with")
    print(f"  {chosen.name}")
    print("=" * 60)

    from pipeline import PipelineController
    try:
        controller = PipelineController(cli_project_root=str(target))
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 2

    ok = controller.run_phase1(str(chosen))
    return 0 if ok else 1


__all__ = ["run_init_project"]
