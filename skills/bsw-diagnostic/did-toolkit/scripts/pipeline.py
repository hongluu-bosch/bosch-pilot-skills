#!/usr/bin/env python3
"""
DID Toolkit - Main Pipeline Controller

Phases (each run independently — there is no ``--phase all``; the
pipeline stops between phases by design so the operator can review
before paying the cost of the next step):

* Phase 1 (``--phase fscs``)         — questionnaire → fscs.json + fscs_edit.xlsx, then STOP.
* XLSX import (``--phase xlsx-import``) — edited workbook → fscs.json + FSCS_*.txt, then STOP.
* Phase 2 (``--phase arxml``)       — FSCS → ARXML (per-product fan-out).
* Phase 3 (``--phase implementation``) — FSCS → C / headers / PDM (per-product fan-out).
* Phase 4 (``--phase doors``)       — FSCS_*.txt → DOORS workbook (opt-in).

Usage:
    python scripts/pipeline.py --phase fscs
    # ... operator reviews outputs/fscs/fscs_edit.xlsx, edits used flags, ...
    python scripts/pipeline.py --phase xlsx-import
    # ... operator decides between Phase 2/3 generation and Phase 4 DOORS ...
    python scripts/pipeline.py --phase arxml
    python scripts/pipeline.py --phase implementation
"""

import argparse
import json
import os
import sys
import logging
from pathlib import Path
from typing import Dict, List, Optional

# Must run before ``logging.basicConfig`` latches onto ``sys.stderr``'s
# encoding; otherwise the StreamHandler caches a cp1252 / cp936 encoder
# and CJK text (``did_name_zh``, review warnings) comes out as
# ``\uXXXX`` noise on Windows consoles.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from io_encoding import reconfigure_stdio_utf8  # noqa: E402
reconfigure_stdio_utf8()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('DID-Pipeline')

def _select_input_or_exit(candidates: List[Path], inputs_dir: Path) -> Path:
    """Resolve a multi-candidate ``inputs/`` situation to one file.

    Behaviour by execution context (introduced in v1.12.0):

    * **Interactive TTY** — present a numbered menu, read the
      operator's choice via ``input()``, accept ``q`` / ``Ctrl-C`` to
      abort. Re-prompts on invalid entries up to 3 times before
      bailing out.
    * **Non-interactive (CI, Cursor agent's ``Shell`` tool, redirected
      stdin)** — print a clear ERROR listing every candidate and the
      two remediation paths (``--input <path>`` for a one-shot, or the
      ``--list-inputs`` + plain-text prompt-and-stop flow documented
      in ``SKILL.md`` for the agent), then ``sys.exit(3)``. The exit
      code lines up with the rest of the toolkit's "invalid input"
      family (3 = invalid input file).

    The previous behaviour (WARN + silent alphabetical auto-pick,
    v1.7 — v1.11) was discarded because the silent pick caused
    operators to not notice a wrong-file selection until the
    downstream artefacts were already committed.
    """
    candidate_names = [p.name for p in candidates]
    interactive = sys.stdin.isatty() and sys.stdout.isatty()

    if not interactive:
        logger.error(
            f"Multiple input candidates in {inputs_dir} and no --input was "
            f"passed:\n"
            + "\n".join(f"  - {name}" for name in candidate_names)
        )
        logger.error(
            "Cannot prompt: stdin is not a TTY (CI / agent shell / "
            "redirected stdin)."
        )
        logger.error(
            "Fix it one of two ways:\n"
            "  • One-shot:        python scripts/pipeline.py --input "
            "inputs/<name> --phase ...\n"
            "  • Agent (Cursor):  call `python scripts/pipeline.py "
            "--list-inputs` to enumerate, then list the candidates in "
            "plain text in your reply and STOP the turn so the "
            "operator can pick one; re-invoke with --input <chosen "
            "path> in the next turn. (Do NOT use the AskQuestion tool "
            "— the operator wants a conversational prompt.) See "
            "SKILL.md > 'Multiple questionnaires in inputs/'."
        )
        sys.exit(3)

    print()
    print(f"Multiple input candidates found in {inputs_dir}:", file=sys.stderr)
    for idx, name in enumerate(candidate_names, start=1):
        print(f"  [{idx}] {name}", file=sys.stderr)
    print("  [q] abort", file=sys.stderr)

    for attempt in range(3):
        try:
            raw = input(f"Pick one (1-{len(candidates)}): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted by operator.", file=sys.stderr)
            sys.exit(3)
        if raw in {"q", "quit", "exit"}:
            print("Aborted by operator.", file=sys.stderr)
            sys.exit(3)
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(candidates):
                return candidates[n - 1]
        print(
            f"  -> '{raw}' is not a valid choice "
            f"(enter 1-{len(candidates)} or q).",
            file=sys.stderr,
        )
    logger.error("No valid choice after 3 attempts; aborting.")
    sys.exit(3)


class PipelineController:
    """Main controller for DID generation pipeline.

    v1.14.0 splits the historical ``base_dir`` into two roots:

    * :attr:`skill_root` — where the toolkit code lives
      (``scripts/`` / ``reference/`` / ``templates/`` / ``tests/``).
      Constant per install; never relocated.
    * :attr:`project_root` — where the operator's data lives
      (``inputs/`` / ``outputs/`` / ``config/``). Re-pointed per run
      via ``--project-root``, ``$DID_TOOLKIT_PROJECT_ROOT``, or
      auto-discovery from CWD.

    :attr:`base_dir` is preserved as an alias for ``project_root`` so
    every v1.13.x call site (``self.base_dir / 'inputs'``, etc.)
    keeps working without churn. The legacy single-workspace
    install (skill folder == project folder) remains the default
    when no project root is configured.
    """

    def __init__(
        self,
        *,
        project_root: Optional[Path] = None,
        cli_project_root: Optional[str] = None,
    ):
        """Construct a controller, optionally overriding the project root.

        :param project_root: Pre-resolved project workspace path.
            When provided, used as-is (no env var / CWD walk). The
            top-level ``main`` passes this after parsing CLI args so
            argument resolution happens in exactly one place.
        :param cli_project_root: Raw value of ``--project-root`` from
            argparse. Used when ``project_root`` is ``None`` to
            trigger the standard four-tier resolution from
            :func:`scripts.project_root.resolve_project_root`.
        """
        self.skill_root = Path(__file__).resolve().parent.parent
        if project_root is not None:
            self.project_root = Path(project_root).resolve()
        else:
            from project_root import resolve_project_root
            self.project_root = resolve_project_root(
                cli_arg=cli_project_root,
                skill_root=self.skill_root,
            )
        # Backward-compat alias: every v1.13.x call site uses
        # ``base_dir`` as the data anchor (inputs/outputs/config),
        # which is exactly what ``project_root`` is now.
        self.base_dir = self.project_root
        # Tracks which optional JSON paths have already triggered a
        # "file absent -- using defaults" INFO message, so Phase 2 and
        # Phase 3 don't both shout the same reminder when e.g.
        # config/project.json isn't set up yet. See ``_load_json``.
        self._missing_config_paths: set = set()

    def load_project_config(self):
        """Load the active project config as a strongly-typed Pydantic model.

        v1.13.0 strong-typing entry point, v1.14.0-aware: honours
        :attr:`active_config_path` when set by the multi-config
        selector (``--config``, single-match auto, or TTY menu).
        Falls back to ``<project_root>/config/project.json`` for the
        single-workspace common case.

        Returns a :class:`scripts.config.ProjectConfig` instance —
        defaults when the file is missing or empty (the historical
        "unconfigured install is a valid posture" rule), validated
        when present.

        Coexists with the legacy dict accessor :meth:`_load_json`
        during the v1.13.x transition: callers that haven't yet been
        migrated can keep using ``self._load_json('config/project.json')``
        without breakage; new call sites (Phase 2 ``product_type``
        filter, the cross-product reviewer, etc.) should prefer this
        method so they get ``extra='forbid'`` typo checking, the
        ``schema_version`` migration hook, and per-run config
        selection.
        """
        from config import load_project_config as _load_typed
        path = getattr(self, 'active_config_path', None) \
            or self.base_dir / 'config' / 'project.json'
        return _load_typed(path)

    def discover_input_candidates(self) -> Dict[str, list]:
        """Enumerate auto-discovery candidates under ``inputs/``.

        Phase 1 only accepts schema-compliant ``*_did.json``. The
        skill ships no built-in workbook parser, so ``.xlsx`` /
        ``.xlsm`` questionnaires must first be normalised into
        ``*_did.json`` by an agent-written
        ``.DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py`` adapter (see
        ``reference/excel-ingestion.md``).

        Returns a dict with a single key:

        * ``"json"`` — sorted list of ``Path`` for schema-compliant
          DID inputs (``*_did.json``).

        The list is sorted alphabetically so repeated runs see the
        same order on every filesystem (Windows: usually alphabetical,
        ext4: not). Used by ``main()``'s auto-detect branch and by the
        ``--list-inputs`` flag (the agent contract is: list the
        candidates in plain text in the assistant reply and stop the
        turn — do **not** call ``AskQuestion`` — so the operator can
        pick one when ``inputs/`` has more than one).
        """
        inputs_dir = self.base_dir / 'inputs'
        if not inputs_dir.is_dir():
            return {"json": []}
        jsons = sorted(
            p for p in inputs_dir.iterdir()
            if p.is_file()
            and p.suffix.lower() == ".json"
            and "did" in p.name.lower()
        )
        return {"json": jsons}

    def _load_json(self, path: str) -> Dict:
        """Load a JSON file; return ``{}`` on any error.

        The two Phase 2/3 callers treat a missing ``config/project.json``
        as *expected* (that is how the toolkit reports "use outputs/
        mode only, no project mirroring") and every ``--config`` CLI
        help line explicitly promises "when missing the file is
        silently skipped". Logging ``FileNotFoundError`` as a WARNING
        therefore alarms new users on their first run before they have
        had a chance to call ``--init-project`` -- a fresh
        ``pipeline.py --phase fscs`` is supposed to show a green
        ``SUCCESS`` line and nothing red.

        So we split the two failure modes:

        * ``FileNotFoundError`` -> one-time ``INFO`` hint on the first
          miss (skipped on subsequent calls in the same process so Phase
          2 + Phase 3 don't duplicate the message), ``DEBUG`` on repeat.
          This is an expected-default-path event, not a degradation.
        * Any other exception (JSON syntax error, permission denied,
          unreadable bytes, ...) -> ``WARNING``. These *are* genuine
          problems the operator needs to see.

        v1.14.0: when called with the canonical
        ``'config/project.json'`` and the active multi-config
        selector picked a different file (e.g. ``project.dpb.json``),
        we transparently redirect to the active path so legacy
        callers honour the per-run selection without needing to be
        rewritten.
        """
        if path == 'config/project.json':
            active = getattr(self, 'active_config_path', None)
            if active is not None:
                full_path = Path(active)
            else:
                full_path = self.base_dir / path
        else:
            full_path = self.base_dir / path
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            missed = self._missing_config_paths
            if path not in missed:
                logger.info(
                    f"{path} not present -- falling back to defaults "
                    f"(run 'python scripts/pipeline.py --init-project' "
                    f"to create one)."
                )
                missed.add(path)
            else:
                logger.debug(f"{path} still absent; using defaults.")
            return {}
        except Exception as e:
            logger.warning(f"Could not load {path}: {e}")
            return {}
    
    def validate_input(self, input_path: str) -> bool:
        """Validate input DID source.

        Only schema-compliant ``*_did.json`` is accepted. ``.xlsx``
        / ``.xlsm`` inputs are rejected — the skill ships no
        built-in workbook parser so it stays generic. Operators
        starting from a questionnaire workbook write an agent-driven
        adapter at ``.DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py`` that
        emits the canonical JSON (see
        ``reference/excel-ingestion.md``).

        The shape check (``did_hex`` / ``did_name_en`` / ``size_bytes``
        required on every record) is then applied to the JSON.

        Relative paths are resolved against ``self.base_dir`` (the
        ``.DCOM_AI/DID_Toolkit_PRJ/`` workspace) instead of the
        process cwd. That keeps the auto-detect path (logged as
        ``inputs/<customer>_did.json``) consistent with the actual
        on-disk location at
        ``<container>/.DCOM_AI/DID_Toolkit_PRJ/inputs/<customer>_did.json`` —
        the agent typically runs ``pipeline.py`` from
        ``<container>``, not from inside the workspace. Absolute
        paths are honoured as-is.
        """
        raw = Path(input_path)
        path = raw if raw.is_absolute() else (self.base_dir / raw)
        suffix = path.suffix.lower()
        try:
            if suffix in {".xlsx", ".xlsm"}:
                logger.error(
                    f"Input {path.name!r}: direct Excel ingestion is "
                    "not supported. Phase 1 only accepts schema-"
                    "compliant *_did.json. Normalise the questionnaire "
                    "via a .DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py "
                    "adapter first (see reference/excel-ingestion.md)."
                )
                return False

            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, list):
                logger.error("Input JSON must be a list of DIDs")
                return False
            required = ['did_hex', 'did_name_en', 'size_bytes']
            for idx, did in enumerate(data):
                if not isinstance(did, dict):
                    logger.error(f"DID {idx} is not an object")
                    return False
                for field in required:
                    if field not in did:
                        logger.error(f"DID {idx} missing field: {field}")
                        return False
            logger.info(f"Validation passed: {len(data)} DIDs")
            return True
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            return False
    
    def _run_arxml_review(
        self,
        arxml_path: Path,
        fscs_json: Path,
        *,
        product_type: Optional[str] = None,
        config=None,
        report_path: Optional[Path] = None,
    ):
        """Run ARXML content review after Phase 2.

        Mirrors :meth:`_run_fscs_review`: delegates to
        ``review_arxml.run_review`` so the CLI and pipeline share one
        orchestration path; failures are logged and swallowed since the
        review is advisory. Since Part 6, the reviewer reads the Phase 1
        ``fscs.json`` instead of raw ``inputs/*.json`` so Phase 2 and
        Phase 3 cross-check against the same authoritative set of DIDs.

        :param product_type: Forwarded to ``run_review`` so the
            reviewer's ``emitted`` set agrees with the v1.13.0
            product-scope filter the generator just applied. Pass
            the same value handed to ``ARXMLGenerator.generate``.
        :param config: Forwarded so the v1.13.0 cross-product SCOPE
            auditor (differential C) can inspect *other* product
            ARXMLs under the same project tree. Skipped when
            ``None`` or when the ARXML template has no
            ``{product_type}`` placeholder (single-product layout).
        :param report_path: Where to write the review report.
            Defaults to ``outputs/arxml/arxml_review_report.txt``;
            v1.24.0 fan-out callers pass the per-product file with a
            ``_<suffix>`` tag (``outputs/arxml/<folder>/
            arxml_review_report_<suffix>.txt``) so each PT's review
            lands beside its own ARXML and ESP/ESPCL co-tenants in
            the shared ``ESP/`` folder don't overwrite each other.
        """
        logger.info("=" * 60)
        logger.info("Running ARXML Content Review...")
        logger.info("=" * 60)
        if report_path is None:
            report_path = self.base_dir / 'outputs' / 'arxml' / 'arxml_review_report.txt'
        if not fscs_json.is_file():
            logger.warning(
                f"ARXML Review skipped: fscs.json not found at {fscs_json}"
            )
            return
        try:
            from review_arxml import run_review
            result = run_review(
                arxml_path=arxml_path,
                fscs_json=fscs_json,
                output_path=report_path,
                product_type=product_type,
                config=config,
            )
            if result['has_issues']:
                logger.warning(f"⚠️  ARXML Review 发现 {result['summary']['total']} 个问题 (详见 {report_path})")
            else:
                logger.info("✅ ARXML Review 通过")
            logger.info(f"Review 报告: {report_path}")
        except Exception as e:
            logger.error(f"ARXML Review 执行失败: {e}")
            logger.warning("ARXML Review 失败，继续执行后续 Phase")

    def _run_impl_review(self, impl_dir: Path, fscs_json: Path):
        """Run implementation content review after Phase 3.

        Same pattern as :meth:`_run_arxml_review`; delegates to
        ``review_impl.run_review`` and never raises out of the pipeline.
        Reads Phase 1's ``fscs.json`` so the expected DID set matches
        exactly what Phase 3 was asked to emit from.
        """
        logger.info("=" * 60)
        logger.info("Running Implementation Content Review...")
        logger.info("=" * 60)
        report_path = impl_dir / 'impl_review_report.txt'
        if not fscs_json.is_file():
            logger.warning(
                f"Implementation Review skipped: fscs.json not found at {fscs_json}"
            )
            return
        try:
            from review_impl import run_review
            result = run_review(
                impl_dir=impl_dir,
                fscs_json=fscs_json,
                output_path=report_path,
            )
            if result['has_issues']:
                logger.warning(f"⚠️  Implementation Review 发现 {result['summary']['total']} 个问题 (详见 {report_path})")
            else:
                logger.info("✅ Implementation Review 通过")
            logger.info(f"Review 报告: {report_path}")
        except Exception as e:
            logger.error(f"Implementation Review 执行失败: {e}")
            logger.warning("Implementation Review 失败，不影响后续步骤")

    def _run_fscs_review(self, input_path: str, fscs_json: Path):
        """Run FSCS content review after Phase 1.

        Delegates to :func:`review_fscs.run_review` so the CLI entry point
        (``python scripts/review_fscs.py ...``) and this pipeline hook share
        a single orchestration path. Failures are logged and swallowed on
        purpose — review is advisory and must not block downstream phases.
        """
        logger.info("=" * 60)
        logger.info("Running FSCS Content Review...")
        logger.info("=" * 60)

        report_path = self.base_dir / 'outputs' / 'fscs' / 'fscs_review_report.txt'
        try:
            from review_fscs import run_review

            # Empty / missing input_path -> None so run_review skips the
            # consistency check (the one check that actually needs the
            # raw inputs). Business + compliance checks still run.
            # Resolve relative paths against self.base_dir so the
            # auto-detect contract (paths relative to the
            # .DCOM_AI/DID_Toolkit_PRJ/ workspace) keeps working when
            # pipeline.py is invoked from the project container
            # directory rather than from inside the workspace.
            if input_path:
                raw = Path(input_path)
                input_json_arg: Optional[Path] = (
                    raw if raw.is_absolute() else (self.base_dir / raw)
                )
            else:
                input_json_arg = None
            result = run_review(
                fscs_json=fscs_json,
                input_json=input_json_arg,
                output_path=report_path,
            )

            if result['has_issues']:
                summary = result['summary']
                logger.warning("⚠️  FSCS Review发现问题:")
                logger.warning(f"   业务不合规: {summary['business']}个")
                logger.warning(f"   配置异常: {summary['compliance']}个")
                logger.warning(f"   一致性异常: {summary['consistency']}个")
                logger.warning(f"\n详细报告: {report_path}")
                logger.warning("注: 问题不影响后续Phase执行，但建议修正")
            else:
                logger.info("✅ FSCS Review通过，所有检查符合标准")

            logger.info(f"Review报告: {report_path}")

        except Exception as e:
            logger.error(f"FSCS Review执行失败: {e}")
            logger.warning("FSCS Review失败，继续执行后续Phase")
    
    # ------------------------------------------------------------------
    # Phase 1 housekeeping
    # ------------------------------------------------------------------

    def _clean_phase1_outputs(
        self,
        fscs_dir: Path,
        *,
        drop_json: bool,
    ) -> None:
        """Remove stale Phase 1 artefacts prior to a fresh generation.

        Phase 1 v1.1 semantics: every rerun must leave the
        ``outputs/fscs/`` directory containing only artefacts produced
        by *this* invocation. That prevents the "FSCS_22.txt looks
        current but fscs.json was regenerated yesterday" class of
        inconsistency and makes the report numbers trustworthy.

        ``fscs.json`` is a special case: we normally keep it so the
        generator can snapshot ``used`` flags from it (per-DID operator
        selections made through xlsx-import). Only ``drop_json=True``
        (i.e. ``--reset-used``) removes it, which forces every DID
        back to ``used_22 = used_2e = True`` for the upcoming build.
        """
        # ``FSCS_*.txt`` are no longer produced by Phase 1; they come
        # out of the xlsx-import action. Any copy on disk is stale by
        # definition once we regenerate fscs.json, so remove them
        # unconditionally to avoid confusing downstream reviewers.
        candidates = [
            fscs_dir / "FSCS_22.txt",
            fscs_dir / "FSCS_2E.txt",
            fscs_dir / "fscs_review_report.txt",
            fscs_dir / "fscs_generation_report.txt",
            fscs_dir / "fscs_edit.xlsx",
        ]
        if drop_json:
            candidates.append(fscs_dir / "fscs.json")

        for path in candidates:
            if not path.is_file():
                continue
            try:
                path.unlink()
            except OSError as exc:  # pragma: no cover -- filesystem edge
                if path.name == "fscs_edit.xlsx" and self._looks_like_file_in_use(exc):
                    raise RuntimeError(
                        "outputs/fscs/fscs_edit.xlsx is open in another program. "
                        "Close Excel/WPS/the editor that is viewing the workbook, "
                        "then rerun Phase 1 so the edit table can be regenerated."
                    ) from exc
                logger.warning(f"Could not remove stale {path.name}: {exc}")

    @staticmethod
    def _looks_like_file_in_use(exc: OSError) -> bool:
        """Heuristic: is this OSError a Windows file-sharing violation?

        Windows raises ``OSError(22, ..., winerror=32)`` for the
        "another process has the file open" case; we match on
        ``winerror`` when present and fall back to the errno/message
        pair on POSIX. Returns False for every other OSError so the
        caller can fall through to the generic warning.
        """
        winerror = getattr(exc, "winerror", None)
        if winerror == 32:  # ERROR_SHARING_VIOLATION
            return True
        # POSIX equivalents for a locked file vary (EBUSY, ETXTBSY).
        if exc.errno in (16, 26):
            return True
        return False

    def run_phase1(
        self,
        input_path: str,
        *,
        reset_used: bool = False,
        run_review: bool = True,
        product_type: Optional[str] = None,
    ) -> bool:
        """Run Phase 1: generate the authoritative ``fscs.json``.

        v1.4 behaviour:

        * Writes ``outputs/fscs/fscs_edit.xlsx`` after ``fscs.json`` so the
          operator can edit the FSCS projection in Excel/WPS.
        * Still does not write ``FSCS_22.txt`` / ``FSCS_2E.txt`` here --
          those files are produced by ``--phase xlsx-import`` after
          the operator-edited workbook is validated back into
          ``fscs.json``.
        * **Auto-runs the FSCS business review** at the end of generation
          (v1.2 restores this, dropped in v1.1). The review is advisory
          and never blocks Phase 1's return value; a failure is logged
          as WARNING and swallowed. Operators opt out with
          ``--no-review`` / ``DID_NO_REVIEW=1`` or call the standalone
          ``--phase review`` later. The xlsx-import action also re-runs
          review automatically so the on-disk report stays in sync with
          the latest ``fscs.json``.
        * Always writes ``outputs/fscs/fscs_generation_report.txt`` so
          the operator can see which records were filtered or skipped.
          That report is distinct from ``fscs_review_report.txt``: the
          former describes *input ingestion* (validation gate), the
          latter is the *advisory business audit* (review).

        :param input_path: Source ``inputs/*.json``.
        :param reset_used: When True, discard ``used`` flags from any
            pre-existing ``fscs.json`` (including deleting the file
            before generation) and let every DID start ``used=True``.
        :param run_review: When True (default) run the FSCS content
            review after generation. ``main`` flips this off for
            ``--no-review`` and ``DID_NO_REVIEW=1``.
        """
        logger.info("=" * 60)
        logger.info("Phase 1: Generating fscs.json")
        logger.info("=" * 60)

        try:
            sys.path.insert(0, str(self.skill_root / 'scripts'))
            from generate_fscs import FSCSGenerator

            fscs_dir = self.base_dir / 'outputs' / 'fscs'
            fscs_dir.mkdir(parents=True, exist_ok=True)
            output_json = fscs_dir / 'fscs.json'
            output_xlsx = fscs_dir / 'fscs_edit.xlsx'
            report_path = fscs_dir / 'fscs_generation_report.txt'

            # Cleanup *before* generation so a half-finished run leaves
            # a predictable directory state. Drop fscs.json too only
            # when the operator explicitly asked to reset selections.
            self._clean_phase1_outputs(fscs_dir, drop_json=reset_used)
            if reset_used:
                logger.info(
                    "--reset-used: discarded previous fscs.json; all DIDs "
                    "will start with used_22 = used_2e = True."
                )

            generator = FSCSGenerator()
            # Resolve relative input_path against self.base_dir so
            # the auto-detect contract (which produces a path
            # relative to .DCOM_AI/DID_Toolkit_PRJ/) keeps working
            # when pipeline.py is invoked from the project container
            # — not from inside the workspace.
            raw_input = Path(input_path)
            resolved_input = (
                raw_input if raw_input.is_absolute()
                else self.base_dir / raw_input
            )
            result = generator.generate(
                input_path=resolved_input,
                output_path_json=output_json,
                report_path=report_path,
                reset_used=reset_used,
                # v1.16.0: when the operator passes --product-type to
                # Phase 1, freshly-built DIDs whose source records
                # carry no per-DID product_type get auto-stamped with
                # this value, matching the v1.13.x single-product
                # zero-edits ergonomic. None ⇒ leave product_type
                # blank (applies-to-all) on new DIDs.
                default_product_type=product_type,
            )

            logger.info(f"Generated: {output_json}")
            logger.info(f"Report:    {report_path}")
            logger.info(
                f"Kept: {result['kept']}  "
                f"Filtered (supported_by_ecu=N): {result['filtered']}  "
                f"Skipped (schema errors): {result['skipped']}"
            )
            logger.info(
                f"Service 22 (Read):  supported={result['supported_22']}  "
                f"effective={result['effective_22']}"
            )
            logger.info(
                f"Service 2E (Write): supported={result['supported_2e']}  "
                f"effective={result['effective_2e']}"
            )
            if result['skipped']:
                logger.warning(
                    f"{result['skipped']} record(s) skipped; see {report_path} "
                    f"for did_hex + validation details."
                )

            # Auto-review (v1.2). Review is an advisory audit bound to
            # the current ``fscs.json`` -- it must follow every
            # regeneration so the on-disk report never lags the source.
            # Operators with a reason to skip (CI speed, already have a
            # fresh report) flip ``run_review=False`` via
            # ``--no-review`` / ``DID_NO_REVIEW=1``. Failures are
            # advisory and never change this method's return value;
            # ``_run_fscs_review`` already swallows exceptions and
            # downgrades to WARNING.
            if run_review:
                self._run_fscs_review(input_path, output_json)
            else:
                logger.info(
                    "Skipping auto-review (--no-review / DID_NO_REVIEW=1). "
                    "Run `python scripts/pipeline.py --phase review` to "
                    "generate the report on demand."
                )

            from fscs.xlsx_edit import export_fscs_xlsx
            try:
                exported = export_fscs_xlsx(output_json, output_xlsx)
            except PermissionError as exc:
                raise RuntimeError(
                    "Could not write outputs/fscs/fscs_edit.xlsx because it is "
                    "open in another program. Close Excel/WPS/the editor that is "
                    "viewing the workbook, then rerun Phase 1."
                ) from exc
            logger.info(f"XLSX edit table: {output_xlsx} ({exported} DID rows)")

            # Phase 1 is a STOP gate. The pipeline does not
            # auto-chain into Phase 2/3 — operators must review the
            # generated FSCS, edit the workbook (used flags,
            # Product_Type, behaviour text, ...), and then
            # explicitly run ``--phase xlsx-import`` to apply edits.
            # This footer spells out both the immediate next step
            # and the downstream branch points so the operator
            # knows the full menu without re-reading SKILL.md.
            logger.info("")
            logger.info("=" * 60)
            logger.info("[STOP] Phase 1 complete — review before continuing.")
            logger.info("=" * 60)
            logger.info("Step A — open the workbook and check / edit:")
            logger.info("           outputs/fscs/fscs_edit.xlsx")
            logger.info("         (used_flag scopes the DOORS / ARXML / C build;")
            logger.info("          Product_Type picks DPB/ESP/ESPCL/IPB/RBU/Common.)")
            logger.info("Step B — also eyeball the auto-generated review:")
            logger.info("           outputs/fscs/fscs_review_report.txt")
            logger.info("Step C — import your edits (rewrites fscs.json + FSCS_*.txt):")
            logger.info("           python scripts/pipeline.py --phase xlsx-import")
            logger.info("         which itself stops again to let you choose between")
            logger.info("         DOORS (Phase 4) and ARXML/impl (Phase 2/3).")
            logger.info("")
            logger.info("(Run Phase 1 again any time — used_flag selections are")
            logger.info(" carried forward across re-runs unless you pass --reset-used.)")
            logger.info("")
            # v1.25.0 agent turn-stopping contract: every [AGENT
            # STOP] directive is what tells the LLM driving this
            # skill (Claude / Cursor / GPT / ...) to END the
            # current assistant turn and wait for the operator to
            # decide. Without this, some hosts read the [STOP]
            # narrative above as advisory and just keep firing
            # tool calls — which is exactly the "default run all
            # phases" behaviour v1.25.0 was built to remove.
            # The phrasing matches the SKILL.md "Agent
            # turn-stopping contract" section verbatim so an
            # agent that has only read the tool output (not the
            # SKILL.md) still knows what to do.
            logger.info("[AGENT STOP] End this turn now. In your reply, surface")
            logger.info("             outputs/fscs/fscs_edit.xlsx + the review report")
            logger.info("             above and ASK the operator to edit (used_flag,")
            logger.info("             Product_Type, behavior, …). Do NOT chain into")
            logger.info("             `--phase xlsx-import` yourself — wait for the")
            logger.info("             operator to reply 'done' / '继续' / 'import' /")
            logger.info("             similar; only then re-invoke pipeline.py.")

            return True

        except Exception as e:
            logger.error(f"Phase 1 failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    # ------------------------------------------------------------------
    # Standalone "phases" added in v1.1
    # ------------------------------------------------------------------

    def run_review_only(self, input_path: Optional[str]) -> bool:
        """Run the FSCS business review against an existing ``fscs.json``.

        Exposed as ``--phase review`` so operators can retrigger the
        review after hand-editing ``fscs.json`` or after bulk-changing
        ``used`` selections in the workbook, without regenerating
        Phase 1.

        Hard-gated on ``outputs/fscs/fscs.json`` for the same reason
        Phase 2/3 are: review without a canonical input is meaningless.
        """
        logger.info("=" * 60)
        logger.info("Phase: FSCS Content Review (standalone)")
        logger.info("=" * 60)

        fscs_json = self.base_dir / 'outputs' / 'fscs' / 'fscs.json'
        if not fscs_json.is_file():
            logger.error(
                "--phase review requires outputs/fscs/fscs.json but it is missing.\n"
                "  Run Phase 1 first: python scripts/pipeline.py --phase fscs"
            )
            return False

        sys.path.insert(0, str(self.skill_root / 'scripts'))
        # Pass empty string through unchanged -- _run_fscs_review hands
        # it to run_review as None (see that method for the skip rule).
        self._run_fscs_review(input_path or '', fscs_json)
        return True

    def run_xlsx_import(self, xlsx_path: Optional[str], input_path: Optional[str]) -> bool:
        """Apply the operator-edited XLSX workbook back to ``fscs.json``.

        It validates the workbook against the existing authoritative
        JSON, then atomically rewrites ``fscs.json`` plus the two
        derived ``FSCS_*.txt`` views. Review is refreshed after the
        write. The workbook is re-exported at the end so the on-disk
        copy always reflects the freshly-canonicalised model.
        """
        logger.info("=" * 60)
        logger.info("Phase: Import edited FSCS XLSX")
        logger.info("=" * 60)

        sys.path.insert(0, str(self.skill_root / 'scripts'))
        fscs_json = self.base_dir / 'outputs' / 'fscs' / 'fscs.json'
        if xlsx_path:
            xlsx_file = Path(xlsx_path)
            if not xlsx_file.is_absolute():
                xlsx_file = self.base_dir / xlsx_file
        else:
            xlsx_file = self.base_dir / 'outputs' / 'fscs' / 'fscs_edit.xlsx'

        if xlsx_file.suffix.lower() == ".csv":
            logger.error(
                "fscs_edit.csv is no longer supported. Re-run "
                "`python scripts/pipeline.py --phase fscs` to "
                "produce fscs_edit.xlsx, then re-invoke --phase "
                "xlsx-import. The xlsx workbook carries drop-down "
                "validations and auto-fit column widths a plain CSV "
                "could not."
            )
            return False

        if not fscs_json.is_file():
            logger.error(
                "--phase xlsx-import requires outputs/fscs/fscs.json but it is missing.\n"
                "  Run Phase 1 first: python scripts/pipeline.py --phase fscs"
            )
            return False
        if not xlsx_file.is_file():
            logger.error(
                f"--phase xlsx-import requires an edited workbook at {xlsx_file}.\n"
                "  Run Phase 1 first to export outputs/fscs/fscs_edit.xlsx, "
                "or pass --xlsx <path>."
            )
            return False

        try:
            from fscs.xlsx_edit import export_fscs_xlsx, import_fscs_xlsx
            from fscs.save import fscs_paths, save_all

            doc = import_fscs_xlsx(fscs_json, xlsx_file)
            paths = fscs_paths(self.base_dir / 'outputs')
            save_all(doc, paths)
            try:
                export_fscs_xlsx(fscs_json, xlsx_file)
            except PermissionError as exc:
                raise RuntimeError(
                    f"XLSX import updated fscs.json and FSCS text files, but "
                    f"could not normalize {xlsx_file} because it is open in "
                    "another program. Close Excel/WPS/the editor and rerun "
                    "`python scripts/pipeline.py --phase xlsx-import`."
                ) from exc
            logger.info(f"Imported XLSX edits from: {xlsx_file}")
            logger.info("Updated: outputs/fscs/fscs.json")
            logger.info("Updated: outputs/fscs/FSCS_22.txt")
            logger.info("Updated: outputs/fscs/FSCS_2E.txt")
            self._run_fscs_review(input_path or '', fscs_json)

            # xlsx-import is the SECOND stop gate. The pipeline does
            # not auto-chain into Phase 2/3 or Phase 4 — operators
            # must inspect the freshly-rebuilt FSCS_22.txt /
            # FSCS_2E.txt preview and decide whether to push the
            # FSCS to DOORS (Phase 4) or build the ARXML / C
            # artefacts (Phase 2/3). Emit a compact used-DID
            # summary so the operator can sanity-check the scope
            # before paying the cost of the next phase.
            self._print_xlsx_import_stop_summary(doc)
            return True
        except Exception as exc:  # noqa: BLE001 - CLI boundary
            logger.error(f"XLSX import failed: {exc}")
            import traceback
            traceback.print_exc()
            return False

    def _print_xlsx_import_stop_summary(self, doc) -> None:
        """Emit the xlsx-import stop-gate footer.

        Walks the freshly-rebuilt :class:`FSCSDocument` and prints a
        compact summary of:

        * **Total DID count** and how many of them are scoped IN
          for each UDS service (effective = ``supported AND used``).
        * **Per-product breakdown** — one line per ``Product_Type``
          actually present in the work-set so the operator can
          confirm the multi-product fan-out target list before
          spending Phase 2/3 time. ``None`` / unset is reported as
          ``Common`` (the v1.21+ work-set rule).
        * **The two follow-up choices** — Phase 4 (DOORS) and
          Phase 2/3 (ARXML / impl). Each is a concrete copy-paste
          command so the operator never has to grep SKILL.md.

        Failures are swallowed (the summary is advisory, not part
        of the xlsx-import contract): if walking the doc throws for
        any reason we just print a minimal footer pointing at the
        canonical commands and keep going.

        Note: the function deliberately does NOT prompt or block —
        the stop gate is "print and return"; the operator
        re-invokes the CLI for the next phase. Blocking here would
        deadlock CI / agent shells (the same reason init's
        questionnaire prompt is also TTY-gated).
        """
        try:
            total = len(doc.dids)
            eff_22 = sum(1 for d in doc.dids if d.service_22.effective)
            eff_2e = sum(1 for d in doc.dids if d.service_2e.effective)

            # Per-product breakdown: count each DID that is
            # effective for at least one service. Empty product_type
            # collapses to ``Common`` so the count matches what
            # Phase 2/3's work-set will actually iterate over.
            from collections import Counter
            product_counter: Counter = Counter()
            for d in doc.dids:
                if not (d.service_22.effective or d.service_2e.effective):
                    continue
                tag = (d.product_type or "Common").strip() or "Common"
                product_counter[tag] += 1
        except Exception:  # noqa: BLE001 - summary is advisory only
            logger.info("")
            logger.info("=" * 60)
            logger.info("[STOP] XLSX import complete — choose your next action.")
            logger.info("=" * 60)
            logger.info(
                "  (DID summary unavailable; the import itself succeeded.)"
            )
            self._print_xlsx_import_branch_menu()
            return

        logger.info("")
        logger.info("=" * 60)
        logger.info("[STOP] XLSX import complete — review the used-DID scope below.")
        logger.info("=" * 60)
        logger.info(f"  Total DIDs in fscs.json:        {total}")
        logger.info(f"  Effective for Service 0x22 (Read):  {eff_22}")
        logger.info(f"  Effective for Service 0x2E (Write): {eff_2e}")
        if product_counter:
            logger.info("  Per-product work-set (Phase 2/3 will fan out over these):")
            for tag, count in sorted(product_counter.items()):
                logger.info(f"    - {tag:<10s} {count} DID(s)")
        else:
            logger.info(
                "  [warn] No DID is currently effective — every row in "
                "fscs_edit.xlsx has used_flag=FALSE or supported=False."
            )
            logger.info(
                "         Re-open outputs/fscs/fscs_edit.xlsx, flip used flags "
                "back on, then re-run --phase xlsx-import."
            )
        logger.info("")
        logger.info("Eyeball the freshly-built DOORS-ready text views:")
        logger.info("  outputs/fscs/FSCS_22.txt")
        logger.info("  outputs/fscs/FSCS_2E.txt")
        logger.info("")
        self._print_xlsx_import_branch_menu()

    def _print_xlsx_import_branch_menu(self) -> None:
        """Print the "DOORS vs ARXML/impl" branch menu used by the
        xlsx-import stop gate.

        Extracted from :meth:`_print_xlsx_import_stop_summary` so
        the no-summary fallback path emits the same operator-facing
        menu without copy-paste drift.
        """
        logger.info("Choose your next step:")
        logger.info("  Option A — push FSCS to DOORS (Phase 4, opt-in):")
        logger.info("    Smoke (no MCP):    python scripts/pipeline.py --phase doors --no-upload --no-anchor")
        logger.info("    Verify anchors:    python scripts/pipeline.py --phase doors --no-upload")
        logger.info("    Full upload:       python scripts/pipeline.py --phase doors --user-nt <NT>")
        logger.info("    (fill inputs/doors_mapping.yaml first:")
        logger.info("       doors.document_uuid + links.link_module_uuid)")
        logger.info("  Option B — generate ARXML + C implementation (Phase 2 + Phase 3):")
        logger.info("    python scripts/pipeline.py --phase arxml")
        logger.info("    python scripts/pipeline.py --phase implementation")
        logger.info("")
        logger.info(
            "(Both options are independent and idempotent — DOORS push doesn't")
        logger.info(
            " touch the ARXML/C artefacts, and ARXML/C don't touch DOORS state.)")
        logger.info("")
        # Agent turn-stopping contract — see the matching SKILL.md
        # section. The xlsx-import stop gate is where the operator
        # has to choose between DOORS and ARXML/impl;
        # auto-picking one and chaining commands would silently
        # bypass that decision. Same phrasing as the Phase 1 STOP
        # so different LLM hosts trip on a consistent pattern.
        logger.info("[AGENT STOP] End this turn now. In your reply, surface the")
        logger.info("             per-product work-set above + the Option A / Option B")
        logger.info("             menu and ASK the operator to pick. Do NOT chain into")
        logger.info("             `--phase doors` / `--phase arxml` / `--phase")
        logger.info("             implementation` yourself — only run the option the")
        logger.info("             operator picks (one phase per turn).")

    def run_doors_sync(
        self,
        *,
        user_nt: Optional[str],
        password: Optional[str],
        no_upload: bool,
        no_fetch: bool = False,
        no_links: bool = False,
        no_anchor: bool = False,
        refresh: bool = False,
        plan_only: bool = False,
        force_reinsert: bool = False,
        save_credentials: bool = False,
        forget_credentials: bool = False,
        no_keyring: bool = False,
    ) -> bool:
        """Build and optionally upload the DID FSCS DOORS workbooks.

        v1.10 (per-DID two-row layout) replaces the old single-row
        insert/update state machine: every run regenerates the full
        per-service workbook set under ``outputs/doors/`` (one xlsx per
        service) plus a link xlsx that ties each DID's CS row back to
        its FS row, then uploads them to DOORS via three MCP calls
        (``upload_doors_module`` x2, ``update_doors_links`` x1).

        ``--no-anchor`` is the cheapest smoke test (no MCP, placeholder
        Destination Object). ``--no-upload`` builds + reports without
        touching DOORS but still fetches the export so anchor lookup
        runs end-to-end.

        v1.17.0 adds two surgical CLI knobs that thread straight to
        ``doors_sync.py``:

        * ``plan_only=True`` -> compute the INSERT/UPDATE/NOOP/STALE
          plan against the recorded ``state/doors_upload_state.json``
          and exit 0 without writing xlsx, fetching, uploading or
          touching links. Operator-facing dry-run.
        * ``force_reinsert=True`` -> wipe the per-DID landings for
          the active module *before* the diff, so every DID classifies
          as INSERT next pass. Use after the operator deleted /
          re-pointed the DOORS module by hand.
        """

        logger.info("=" * 60)
        logger.info("Phase: Build / Upload DID FSCS to DOORS")
        logger.info("=" * 60)

        import subprocess

        # v1.16.0: thread workspace-rooted overrides so the DOORS
        # sync writes / reads under the active workspace
        # (self.base_dir) rather than the skill's outputs/ folder.
        # Without this, every run from a v1.14.0+ workspace ends up
        # spraying artefacts into the skill itself and reading the
        # wrong fscs.json -- which is also why RB_Product would come
        # out empty (per-DID product_type lives in fscs.json now).
        ws = self.base_dir
        cmd = [
            sys.executable,
            str(self.skill_root / "scripts" / "fscs" / "doors" / "doors_sync.py"),
            "--mapping",   str(ws / "inputs"  / "doors_mapping.yaml"),
            "--project",   str(ws / "config"  / "project.json"),
            "--state",     str(ws / "state"   / "doors_upload_state.json"),
            "--export",    str(ws / "outputs" / "doors" / "doors_export.json"),
            "--out-dir",   str(ws / "outputs" / "doors"),
            "--report",    str(ws / "outputs" / "doors" / "doors_payload_report.txt"),
            "--txt-22",    str(ws / "outputs" / "fscs"  / "FSCS_22.txt"),
            "--txt-2e",    str(ws / "outputs" / "fscs"  / "FSCS_2E.txt"),
            "--fscs-json", str(ws / "outputs" / "fscs"  / "fscs.json"),
        ]
        if user_nt:
            cmd.extend(["--user-nt", user_nt])
        if password:
            cmd.extend(["--password", password])
        if no_upload:
            cmd.append("--no-upload")
        if no_fetch:
            cmd.append("--no-fetch")
        if no_links:
            cmd.append("--no-links")
        if no_anchor:
            cmd.append("--no-anchor")
        if refresh:
            cmd.append("--refresh")
        if plan_only:
            cmd.append("--plan-only")
        if force_reinsert:
            cmd.append("--force-reinsert")
        if save_credentials:
            cmd.append("--save-credentials")
        if forget_credentials:
            cmd.append("--forget-credentials")
        if no_keyring:
            cmd.append("--no-keyring")

        result = subprocess.run(cmd, cwd=str(self.base_dir), text=True)
        return result.returncode == 0

    def _print_phase3_agent_todo(
        self,
        fill_targets: List[str],
        stub_targets: List[str],
        skipped_files: List[str],
    ) -> None:
        """Emit the v1.27.0 Phase 3 continuous-flow ``[AGENT TODO]`` footer.

        Phase 3 no longer ``[AGENT STOP]``s after the framework write —
        the contract is that the same agent turn proceeds to fill the
        non-empty behaviours inline. This footer is the handover note:

        * **X fill** — DIDs whose FSCS behaviour text is non-empty and
          non-default; the agent should expand the inline
          ``TODO(agent)`` block into real code in the same turn.
        * **Y stub** — DIDs whose behaviour text is empty / default;
          leave the inline ``TODO(agent)`` block intact so the
          operator can edit ``fscs_edit.xlsx`` later and re-run
          ``--phase xlsx-import`` + ``--phase implementation``.
        * **Skipped** — pre-existing ``.c`` files in the Bosch tree
          left untouched (skip-on-conflict).
        """
        logger.info("")
        logger.info("=" * 60)
        logger.info(
            f"Phase 3 framework complete — "
            f"fill={len(fill_targets)}  stub={len(stub_targets)}  "
            f"skipped={len(skipped_files)}"
        )
        logger.info("=" * 60)
        if fill_targets:
            logger.info("DIDs awaiting agent fill-in (behaviour text present):")
            for line in fill_targets[:20]:
                logger.info(f"  - {line}")
            if len(fill_targets) > 20:
                logger.info(f"  ... (+{len(fill_targets) - 20} more, see generation_report.txt)")
        if stub_targets:
            logger.info(
                f"DIDs left as TODO stubs ({len(stub_targets)} — behaviour empty/default)."
            )
        if skipped_files:
            logger.info(
                f"Pre-existing .c files in Bosch tree skipped ({len(skipped_files)} — see report)."
            )
        logger.info("")
        # v1.27.0 continuous-flow contract: no [AGENT STOP] here.
        # The agent should keep working in this same turn to fill
        # the ``TODO(agent)`` blocks in every ``fill`` target,
        # then summarise filled vs. left-as-stub at the end of
        # its reply for operator review.
        logger.info("[AGENT TODO] Stay in this turn. Open each Bosch-tree .c file")
        logger.info("             listed above (or in the per-product")
        logger.info("             generation_report.txt) and expand the inline")
        logger.info("             TODO(agent) block into real code using the")
        logger.info("             embedded FSCS behaviour + storage hint + DID")
        logger.info("             metadata. Leave stub targets alone (their")
        logger.info("             behaviour text is empty / default — the operator")
        logger.info("             will fill it in fscs_edit.xlsx later). End your")
        logger.info("             reply with a 'filled vs stubbed' summary so the")
        logger.info("             operator can spot-check before closing the loop.")

    def run_phase2(self, input_path: Optional[str] = None,
                   dry_run: bool = False) -> bool:
        """Run Phase 2: Generate ARXML — project tree is the sole sink.

        Every per-product iteration writes the merged ARXML
        **directly** into the Bosch project tree (the path resolved
        from ``paths.arxml_file`` / ``paths.per_product.<PT>.arxml_file``
        composed with ``paths.base_dir``). Reports
        (``validation_report_<suffix>.txt``,
        ``arxml_review_report_<suffix>.txt``) still land under
        ``.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<folder>/`` so the operator has a
        local audit trail without polluting the project tree.

        Skip-on-conflict: existing ``SHORT-NAME`` containers under
        ``DcmDsp/SUB-CONTAINERS`` win; only previously-absent
        containers are spliced in. The merge is non-destructive, so
        there is no rolling backup — the pre-existing file IS the
        backup.

        ``input_path`` is only consumed by the post-phase ARXML Review.
        """
        logger.info("=" * 60)
        logger.info("Phase 2: Generating ARXML (project-tree sink, per-product fan-out)")
        logger.info("=" * 60)

        try:
            # Hard gate: Phase 1 must have produced fscs.json. After
            # Part 6 of the governance migration fscs.json is the *only*
            # runtime source for Phase 2/3 -- missing JSON means the
            # pipeline wasn't run in order, so fail loudly with a
            # remediation hint rather than silently degrading.
            fscs_json = self.base_dir / 'outputs' / 'fscs' / 'fscs.json'
            if not fscs_json.is_file():
                logger.error(
                    "Phase 2 requires outputs/fscs/fscs.json but it is missing.\n"
                    "  Run Phase 1 first: python scripts/pipeline.py -p fscs -i <your-did>.json\n"
                    "  Or migrate a legacy project with: python scripts/fscs_import.py "
                    "--fscs-22 outputs/fscs/FSCS_22.txt --fscs-2e outputs/fscs/FSCS_2E.txt "
                    "-o outputs/fscs/fscs.json"
                )
                return False

            from generate_arxml import ARXMLGenerator
            from fscs import (
                compute_workset,
                load_fscs,
                phase2_alias_target_for,
                UnknownProductTypeError,
            )
            from implementation.paths import (
                product_type_arxml_folder,
                product_type_suffix,
            )

            # Drift WARN: if the user ran Phase 1 and then hand-edited
            # FSCS_*.txt, the .txt view diverges from fscs.json. We still
            # consume the JSON (authoritative), but surface the divergence
            # so reviewers don't trust stale text. Swallow any failure —
            # drift detection is advisory, never blocking.
            try:
                from fscs.drift import check_fscs_drift

                check_fscs_drift(self.base_dir / 'outputs')
            except Exception as drift_exc:  # pragma: no cover - defensive
                logger.warning(f"FSCS drift check skipped: {drift_exc}")

            # v1.21.0 fan-out: derive the work-set from fscs.json
            # rather than from a CLI flag. Empty work-set is a
            # warn-and-skip (Q5) so downstream phases (DOORS) still
            # have a fully-rendered fscs.json to consume.
            try:
                document = load_fscs(fscs_json=fscs_json)
                workset = compute_workset(document)
            except UnknownProductTypeError as exc:
                logger.error(
                    "Phase 2 abort: unrecognised product_type in fscs.json. "
                    f"{exc} Fix the offending DID's `Product_Type` cell in "
                    "outputs/fscs/fscs_edit.xlsx (or set it to `Common`), "
                    "then re-run `pipeline.py --phase xlsx-import` before "
                    "trying Phase 2 again."
                )
                return False

            if workset.is_empty():
                logger.warning(
                    f"Phase 2 skipped: work-set is empty "
                    f"({workset.used_did_count} used DID(s), but none "
                    "carry a recognised `Product_Type`). Edit "
                    "outputs/fscs/fscs_edit.xlsx -> Product_Type column, "
                    "then `pipeline.py --phase xlsx-import` to refresh "
                    "fscs.json. Phase 2 nominally succeeded so downstream "
                    "phases (Phase 4 / DOORS) can still run."
                )
                return True

            project = self._load_json('config/project.json')

            # v1.27.0: project tree is mandatory. base_dir must exist
            # or the merge target is meaningless. Fail loud so the
            # operator fixes config/project.json before paying the
            # build cost.
            paths_cfg = project.get('paths', {}) if isinstance(project, dict) else {}
            base_dir_raw = paths_cfg.get('base_dir', '')
            if not base_dir_raw:
                logger.error(
                    "Phase 2 requires paths.base_dir in config/project.json "
                    "(the project tree is the sole ARXML sink). "
                    "Run `pipeline.py --init-project <path>` to scaffold a "
                    "fresh workspace, or edit the existing config so "
                    "paths.base_dir points at the Bosch project tree."
                )
                return False
            if not Path(base_dir_raw).is_absolute():
                resolved_base = (self.base_dir / base_dir_raw).resolve()
                project.setdefault('paths', {})['base_dir'] = str(resolved_base)
                base_dir_raw = str(resolved_base)
            base_dir_path = Path(base_dir_raw)
            if not base_dir_path.exists():
                logger.error(
                    f"Phase 2: paths.base_dir does not exist on disk: "
                    f"{base_dir_raw!r}. Mount / clone the Bosch tree at "
                    "this path or fix config/project.json before re-running."
                )
                return False

            try:
                typed_config = self.load_project_config()
            except Exception as _cfg_exc:  # noqa: BLE001 -- defensive
                logger.warning(
                    f"无法以强类型方式加载 config/project.json，跳过 cross-product "
                    f"SCOPE 审计: {_cfg_exc}"
                )
                typed_config = None

            generator = ARXMLGenerator(config=project)

            # v1.24.0: Phase-2-only product **path** alias. Some PTs
            # share another PT's Bosch ARXML folder — currently only
            # ``ESPCL → ESP``. The alias source PT (ESPCL) still
            # iterates with its own DID set (single-target filter,
            # ESPCL+Common DIDs only — same as every other PT), but:
            #   * Local output dir = ``outputs/arxml/<alias_target>/``
            #     (so ESP and ESPCL share ``outputs/arxml/ESP/``).
            #   * Bosch mirror dir = ``cfg/<alias_target>/`` via the
            #     ``{product_type_arxml_folder}`` placeholder in
            #     ``paths.arxml_file``.
            # Both filenames carry the per-PT ``{product_type_suffix}``
            # tag (``_ESP`` / ``_ESPCL``) so the two iterations don't
            # clobber each other in the shared folder. This is a path
            # alias only — Phase 3 ignores it (ESPCL keeps its own
            # ``src/ESPCL/`` mirror and ``esp10cl/dcompr/cfg/...``
            # ConfigSettings).
            #
            # The alias is structural: ESPCL always writes into ESP's
            # folder regardless of whether ESP itself is in the
            # workset (the operator might be building ESPCL only).
            # We log unconditionally per alias source so the
            # destination is never a surprise.
            for src in workset.products:
                tgt = phase2_alias_target_for(src)
                if tgt:
                    logger.info(
                        f"  [ALIAS] {src} → {tgt} (Phase 2 path alias): "
                        f"{src}'s ARXML / reports will land in "
                        f"outputs/arxml/{tgt}/ (local) and "
                        f"cfg/{tgt}/ (Bosch), with _{src} filename suffix."
                    )

            # v1.22.0: pre-filter the work-set against
            # ``paths.per_product.<PT>.arxml_file == null`` so a PT
            # the operator pinned as "no Bosch ARXML target" doesn't
            # waste a build cycle.
            from implementation.paths import resolve_mirror_path, MirrorResolution

            scheduled: list[str] = []
            skipped_via_per_product: list[str] = []
            for product in workset.products:
                _, verdict = resolve_mirror_path(project, "arxml_file", product)
                if verdict is MirrorResolution.SKIP:
                    skipped_via_per_product.append(product)
                else:
                    scheduled.append(product)

            if skipped_via_per_product:
                for product in skipped_via_per_product:
                    logger.info(
                        f"  [SKIP] {product}: paths.per_product.{product}.arxml_file"
                        f" = null — no Bosch ARXML target for this product, "
                        f"skipping entire Phase 2 iteration (no "
                        f"outputs/arxml/.../DID_Config_{product}.arxml produced)."
                    )

            logger.info(
                f"Work-set: {len(workset.products)} product(s) "
                f"({', '.join(workset.products)})"
                + (f"; built: {len(scheduled)}; skipped via per_product: "
                   f"{len(skipped_via_per_product)}"
                   if skipped_via_per_product else "")
            )

            any_failure = False
            total_inserted = 0
            total_skipped_containers = 0
            for product in scheduled:
                logger.info("-" * 60)
                # v1.24.0 fan-out path computation:
                #   folder = product_type_arxml_folder(product) — ESPCL→ESP
                #   suffix = product_type_suffix(product)       — DPB/ESP/
                #                                                 ESPCL/IPB/
                #                                                 RBU/SingleCANID
                # In v1.27.0 the folder/suffix pair is reused for the
                # local report directory under .DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/
                # (so reviewer + validation reports stay co-located)
                # but the ARXML itself is written into the Bosch tree
                # via ``resolve_mirror_path`` — there is no more
                # ``outputs/arxml/.../DID_Config_<suffix>.arxml`` mirror.
                folder = product_type_arxml_folder(product)
                suffix = product_type_suffix(product)
                report_dir = self.base_dir / 'outputs' / 'arxml' / folder
                report_dir.mkdir(parents=True, exist_ok=True)
                validation_report_path = report_dir / f'validation_report_{suffix}.txt'
                review_report = report_dir / f'arxml_review_report_{suffix}.txt'

                rel_target, _verdict = resolve_mirror_path(
                    project, "arxml_file", product,
                )
                # ``scheduled`` pre-filtered SKIP; UNSET / OVERRIDE /
                # TEMPLATE all yield a non-None path (UNSET is filtered
                # by the empty-template guard below).
                if rel_target is None:
                    logger.warning(
                        f"  [SKIP] {product}: paths.arxml_file is empty "
                        "and no per_product override is set; nothing to "
                        "write. Edit config/project.json paths.arxml_file "
                        "to point at the Bosch DID ARXML template."
                    )
                    continue

                project_target = (base_dir_path / rel_target).resolve()

                if folder != product:
                    logger.info(
                        f"  [build] product={product} → folder={folder} "
                        f"(Phase 2 path alias); writing into project tree."
                    )
                else:
                    logger.info(f"  [build] product={product}")
                logger.info(f"  Project target: {project_target}")
                logger.info(f"  Report dir:     {report_dir}")

                try:
                    result = generator.generate(
                        output_path=project_target,
                        product_type=product,
                        validation_report_path=validation_report_path,
                        report_dir=report_dir,
                        dry_run=dry_run,
                        fscs_json_path=fscs_json,
                    )
                except Exception as gen_exc:  # noqa: BLE001
                    any_failure = True
                    logger.error(
                        f"  Phase 2 build for {product!r} failed: {gen_exc}"
                    )
                    import traceback
                    traceback.print_exc()
                    continue

                logger.info(f"  Valid DIDs: {result.get('total', 0)}")
                logger.info(f"    Read Only:  {result.get('read_only', 0)}")
                logger.info(f"    Read/Write: {result.get('read_write', 0)}")
                inserted = int(result.get('project_inserted', 0))
                skipped_containers = int(result.get('project_skipped', 0))
                total_inserted += inserted
                total_skipped_containers += skipped_containers
                logger.info(
                    f"    Inserted: {inserted}, "
                    f"Already-present (skipped): {skipped_containers}"
                )

                self._run_arxml_review(
                    project_target, fscs_json,
                    product_type=product,
                    config=typed_config,
                    report_path=review_report,
                )

            logger.info("")
            logger.info("=" * 60)
            logger.info(
                "Phase 2 complete: "
                f"+{total_inserted} new container(s), "
                f"{total_skipped_containers} pre-existing skipped."
            )
            logger.info("=" * 60)
            logger.info("Next step (choose one):")
            logger.info("  Phase 3 — generate C / headers / PDM:")
            logger.info("    python scripts/pipeline.py --phase implementation")
            logger.info("  Phase 4 — push FSCS to DOORS (independent):")
            logger.info("    python scripts/pipeline.py --phase doors --user-nt <NT>")
            logger.info("")
            logger.info("[AGENT STOP] End this turn. In your reply, surface the")
            logger.info("             per-product project-tree targets and skip counts")
            logger.info("             above and ASK the operator whether to proceed to")
            logger.info("             Phase 3 (impl) now or to inspect the merged ARXML")
            logger.info("             first. Do NOT chain into `--phase implementation`")
            logger.info("             yourself — wait for the operator's go-ahead.")
            return not any_failure

        except Exception as e:
            logger.error(f"Phase 2 failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def run_phase3(self, dry_run: bool = False,
                   input_path: Optional[str] = None) -> bool:
        """Run Phase 3: Generate Implementation — project-tree sink + continuous fill-in.

        Contract:

        * C source, PDM, and headers are written **directly** to the
          Bosch project tree via ``resolve_mirror_path``.
          Skip-on-conflict: per-DID ``.c`` files already present on
          disk are left alone; PDM entries already present are not
          re-appended; header entries already wired are not
          re-merged. Skips are tallied in the per-product generation
          report. The merge is non-destructive, so there is no
          rolling backup.
        * Every generated stub carries an inline ``TODO(agent)``
          block with the full context (storage classification, FSCS
          behaviour, DID metadata) so the agent can fill in the
          implementation without leaving the file.
        * Phase 3 closes with an ``[AGENT TODO]`` summary listing
          ``X fill / Y stub`` targets (no ``[AGENT STOP]`` between
          framework and fill-in) so the agent proceeds straight
          into filling the non-empty behaviours in the same turn.
        """
        logger.info("=" * 60)
        logger.info("Phase 3: Generating Implementation (project-tree sink, continuous fill-in)")
        logger.info("=" * 60)

        try:
            # Hard gate (same rule as Phase 2): Phase 1's fscs.json is
            # the authoritative input. Both Phase 2 and Phase 3 read the
            # same document so naming/shape stays consistent across
            # ARXML and generated C. Missing JSON ⇒ abort with hint.
            fscs_json = self.base_dir / 'outputs' / 'fscs' / 'fscs.json'
            if not fscs_json.is_file():
                logger.error(
                    "Phase 3 requires outputs/fscs/fscs.json but it is missing.\n"
                    "  Run Phase 1 first: python scripts/pipeline.py -p fscs -i <your-did>.json\n"
                    "  Or migrate a legacy project with: python scripts/fscs_import.py "
                    "--fscs-22 outputs/fscs/FSCS_22.txt --fscs-2e outputs/fscs/FSCS_2E.txt "
                    "-o outputs/fscs/fscs.json"
                )
                return False

            from generate_implementation import ImplementationGenerator
            from fscs import compute_workset, load_fscs, UnknownProductTypeError

            # v1.21.0 fan-out: same work-set computation as Phase 2.
            # Empty work-set is warn-and-skip (Q5).
            try:
                document = load_fscs(fscs_json=fscs_json)
                workset = compute_workset(document)
            except UnknownProductTypeError as exc:
                logger.error(
                    "Phase 3 abort: unrecognised product_type in fscs.json. "
                    f"{exc} Fix the offending DID's `Product_Type` cell in "
                    "outputs/fscs/fscs_edit.xlsx (or set it to `Common`), "
                    "then re-run `pipeline.py --phase xlsx-import` before "
                    "trying Phase 3 again."
                )
                return False

            if workset.is_empty():
                logger.warning(
                    f"Phase 3 skipped: work-set is empty "
                    f"({workset.used_did_count} used DID(s), but none "
                    "carry a recognised `Product_Type`). Edit "
                    "outputs/fscs/fscs_edit.xlsx -> Product_Type column, "
                    "then `pipeline.py --phase xlsx-import` to refresh "
                    "fscs.json. Phase 3 nominally succeeded so downstream "
                    "phases (Phase 4 / DOORS) can still run."
                )
                return True

            project = self._load_json('config/project.json')

            # v1.27.0: same hard-gate as Phase 2 — the project tree is
            # the sole sink, so a missing / absent ``paths.base_dir``
            # makes Phase 3 a no-op. Fail loud before iterating.
            paths_cfg = project.get('paths', {}) if isinstance(project, dict) else {}
            base_dir_raw = paths_cfg.get('base_dir', '')
            if not base_dir_raw:
                logger.error(
                    "Phase 3 requires paths.base_dir in config/project.json "
                    "(the project tree is the sole sink). "
                    "Run `pipeline.py --init-project <path>` to scaffold a "
                    "fresh workspace, or edit the existing config so "
                    "paths.base_dir points at the Bosch project tree."
                )
                return False
            if not Path(base_dir_raw).is_absolute():
                resolved_base = (self.base_dir / base_dir_raw).resolve()
                project.setdefault('paths', {})['base_dir'] = str(resolved_base)
                base_dir_raw = str(resolved_base)
            if not Path(base_dir_raw).exists():
                logger.error(
                    f"Phase 3: paths.base_dir does not exist on disk: "
                    f"{base_dir_raw!r}. Mount / clone the Bosch tree at "
                    "this path or fix config/project.json before re-running."
                )
                return False

            generator = ImplementationGenerator(config=project)

            logger.info(
                f"Work-set: {len(workset.products)} product(s) "
                f"({', '.join(workset.products)})"
            )

            any_failure = False
            total_fill: List[str] = []
            total_stub: List[str] = []
            total_skipped_files: List[str] = []
            for product in workset.products:
                logger.info("-" * 60)
                logger.info(f"  [build] product={product}")
                # v1.27.0: per-product report dir lives under
                # .DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/. The C / PDM /
                # header artefacts themselves are written into the
                # Bosch tree by the orchestrator (skip-on-conflict).
                report_dir = (self.base_dir / 'outputs' / 'implementation'
                              / product)
                report_dir.mkdir(parents=True, exist_ok=True)

                try:
                    result = generator.generate(
                        output_dir=report_dir,
                        product_type=product,
                        dry_run=dry_run,
                        fscs_json_path=fscs_json,
                    )
                except Exception as gen_exc:  # noqa: BLE001
                    any_failure = True
                    logger.error(
                        f"  Phase 3 build for {product!r} failed: {gen_exc}"
                    )
                    import traceback
                    traceback.print_exc()
                    continue

                total_files = (result.get('read_functions', 0)
                               + result.get('write_functions', 0))
                logger.info(
                    f"  Generated C functions: {total_files} "
                    f"(read={result.get('read_functions', 0)}, "
                    f"write={result.get('write_functions', 0)})"
                )
                logger.info(f"  Valid DIDs: {result.get('total', 0)}")
                logger.info(f"  Report dir: {report_dir}")
                fill_targets = result.get('agent_fill_targets', []) or []
                stub_targets = result.get('agent_stub_targets', []) or []
                skipped_files = result.get('skipped_c_files', []) or []
                total_fill.extend(fill_targets)
                total_stub.extend(stub_targets)
                total_skipped_files.extend(skipped_files)
                logger.info(
                    f"  Agent fill-in queue: {len(fill_targets)} DID(s) "
                    f"with behaviour text; {len(stub_targets)} DID(s) "
                    f"left as TODO stubs (behaviour empty / default)."
                )
                if skipped_files:
                    logger.info(
                        f"  Skipped {len(skipped_files)} pre-existing .c file(s) "
                        f"in project tree (see generation_report.txt)."
                    )

                self._run_impl_review(report_dir, fscs_json)

            self._print_phase3_agent_todo(total_fill, total_stub, total_skipped_files)
            return not any_failure

        except Exception as e:
            logger.error(f"Phase 3 failed: {e}")
            import traceback
            traceback.print_exc()
            return False


def main():
    parser = argparse.ArgumentParser(
        description='DID Toolkit - Generation Pipeline (see `--version` for the shipped release)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples (pipeline is gated, no auto-chain):
  # Phase 1 (default) — build fscs.json + fscs_edit.xlsx, then STOP.
  python scripts/pipeline.py --phase fscs

  # XLSX import — apply your workbook edits + rewrite FSCS_*.txt, then STOP.
  python scripts/pipeline.py --phase xlsx-import

  # After the xlsx-import STOP, branch:
  python scripts/pipeline.py --phase doors --no-upload --no-anchor   # smoke
  python scripts/pipeline.py --phase doors --user-nt <NT>            # full DOORS
  python scripts/pipeline.py --phase arxml                           # ARXML (Phase 2)
  python scripts/pipeline.py --phase implementation                  # C + headers (Phase 3)

  # Validate input only
  python scripts/pipeline.py --validate

  # Re-run the FSCS business review on an existing fscs.json
  python scripts/pipeline.py --phase review
        """
    )

    parser.add_argument('--version', '-V',
                        action='store_true',
                        help='Print "did-toolkit X.Y.Z" and verify that SKILL.md, '
                             'VERSION, and CHANGELOG.md agree; exit non-zero on '
                             'drift. See scripts/version.py for details.')

    parser.add_argument('--input', '-i',
                        default=None,
                        help='Input DID JSON file (schema-compliant '
                             '*_did.json; see reference/input-format.md). '
                             'If omitted, auto-detect the single '
                             '*_did.json under .DCOM_AI/DID_Toolkit_PRJ/inputs/. '
                             'Direct .xlsx / .xlsm ingestion is not '
                             'supported — normalise via '
                             '.DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py '
                             'first.')

    parser.add_argument('--xlsx',
                        default=None,
                        help='XLSX file for --phase xlsx-import. Defaults to outputs/fscs/fscs_edit.xlsx.')

    parser.add_argument('--phase', '-p',
                        choices=['fscs', 'arxml', 'implementation',
                                 'review', 'xlsx-import', 'doors'],
                        default='fscs',
                        help='Pipeline phase to run (default: fscs). '
                             'There is no "all" auto-chain; each phase '
                             'runs independently with explicit STOP gates '
                             'between Phase 1 -> xlsx-import -> Phase 2/3 / '
                             'Phase 4 so the operator can review the FSCS '
                             'before paying generation cost. "review" '
                             'reruns the FSCS business review against the '
                             'existing fscs.json. "xlsx-import" applies '
                             'outputs/fscs/fscs_edit.xlsx back into '
                             'fscs.json and writes FSCS_22/2E.txt. "doors" '
                             'builds or uploads the DOORS workbook.')
    
    # The project tree is the only sink; the merge is non-destructive
    # (skip-on-conflict), and reports live under .DCOM_AI/DID_Toolkit_PRJ/outputs/ for
    # the local audit trail. Phase 2/3 fan out across every product
    # carried by a ``used`` DID in fscs.json.
    parser.add_argument('--dry-run', action='store_true',
                        help='Phase 2 + Phase 3: preview project-tree writes '
                             'without touching disk. Reports under '
                             '.DCOM_AI/DID_Toolkit_PRJ/outputs/ are still produced.')

    parser.add_argument('--validate', '-v',
                        action='store_true',
                        help='Only validate input, do not generate')

    parser.add_argument('--list-inputs',
                        action='store_true',
                        help='Print every Phase-1 candidate under '
                             '.DCOM_AI/DID_Toolkit_PRJ/inputs/ (one absolute path per '
                             'line, schema-compliant *_did.json only) '
                             'and exit. Intended for agent use: '
                             'enumerate, then list candidates in a '
                             'plain-text reply and stop so the operator '
                             'can pick (no AskQuestion); re-invoke with '
                             '--input <chosen path> next turn. '
                             'Side-effect free.')

    parser.add_argument('--reset-used',
                        action='store_true',
                        help='Phase 1 only: discard the "used" selections '
                             'from any pre-existing fscs.json. Every DID '
                             'starts the new build with used_22 = used_2e '
                             '= True. Without this flag, Phase 1 carries '
                             'the operator\'s workbook selections forward.')

    # v1.2: Phase 1 auto-runs FSCS content review after generation. The
    # flag + env var let CI / headless loops opt out without losing the
    # explicit ``--phase review`` path, which stays usable for on-demand
    # re-runs. Phase 2 / Phase 3 ARXML + Impl reviews are not affected
    # by this flag; they have their own advisory hooks.
    parser.add_argument('--no-review',
                        action='store_true',
                        help='Phase 1 only (v1.2): skip the auto-run of '
                             'the FSCS content review after generation. '
                             'Equivalent to DID_NO_REVIEW=1. xlsx-import '
                             'still refreshes review; use `--phase review` '
                             'later to regenerate fscs_review_report.txt '
                             'on demand.')

    parser.add_argument('--user-nt',
                        default=None,
                        help='DOORS NT account for --phase doors '
                             'uploads (or set $DOORS_USER_NT).')
    parser.add_argument('--password',
                        default=None,
                        help='DOORS password for --phase doors. '
                             'Resolution order (since 2.3.0): '
                             '--password > $DOORS_PWD > OS keychain > '
                             'interactive prompt. Pair with '
                             '--save-credentials to cache it; subsequent '
                             'runs become zero-prompt.')
    parser.add_argument('--save-credentials',
                        action='store_true',
                        help='--phase doors: persist (user_nt, password) '
                             'in the OS keychain (Windows Credential '
                             'Manager / macOS Keychain / Linux Secret '
                             'Service). Combine with --no-upload to '
                             'prime the cache without doing any upload '
                             '(cold-start workflow on a new machine).')
    parser.add_argument('--forget-credentials',
                        action='store_true',
                        help='--phase doors: delete the keychain entry '
                             'for --user-nt and exit. Does not build, '
                             'does not upload, does not fetch. No-op '
                             'if no entry exists.')
    parser.add_argument('--no-keyring',
                        action='store_true',
                        help='--phase doors: bypass the OS keychain '
                             'entirely (do not read, do not write). '
                             'Useful for CI / debugging / hosts with '
                             'no Secret Service backend.')
    parser.add_argument('--no-upload',
                        action='store_true',
                        help='--phase doors: build and lint the per-service '
                             'workbooks (outputs/doors/doors_upload_22.xlsx and '
                             'doors_upload_2E.xlsx) without uploading to DOORS.')
    parser.add_argument('--no-fetch',
                        action='store_true',
                        help='--phase doors: reuse the existing '
                             'outputs/doors/doors_export.json instead of '
                             'calling MCP get_doors_module first.')
    parser.add_argument('--no-links',
                        action='store_true',
                        help='--phase doors: skip the post-upload FS->CS '
                             'link reconciliation + update_doors_links call.')
    parser.add_argument('--no-anchor',
                        action='store_true',
                        help='--phase doors: build with placeholder anchor '
                             '(implies --no-upload --no-links). Cheapest '
                             'smoke test; no MCP traffic.')
    parser.add_argument('--refresh',
                        action='store_true',
                        help='--phase doors: call refresh_doors_module before '
                             'fetch so the server re-pulls from live DOORS '
                             '(slower; use after a manual edit).')
    # v1.17.0 state-machine pass-through.
    parser.add_argument('--plan-only',
                        action='store_true',
                        help='--phase doors: compute the INSERT/UPDATE/NOOP/STALE '
                             'plan against state/doors_upload_state.json and exit; '
                             'no xlsx written, no fetch, no upload, no links.')
    parser.add_argument('--force-reinsert',
                        action='store_true',
                        help='--phase doors: wipe the recorded landings for the '
                             'active module before the diff runs, so every effective '
                             'DID classifies as INSERT. Use after a DOORS-side '
                             'teardown or module re-pointing.')

    parser.add_argument('--verbose',
                        action='store_true',
                        help='Verbose output')

    # v1.14.0: project-root override. When omitted, the controller
    # falls back through $DID_TOOLKIT_PROJECT_ROOT, then a CWD-walk
    # for ``config/project.json``, then the skill folder itself
    # (legacy single-workspace mode). See scripts/project_root.py
    # for the resolution policy.
    parser.add_argument('--project-root',
                        default=None,
                        metavar='PATH',
                        help='Path to the did-toolkit project workspace '
                             '(directory containing config/, inputs/, '
                             'outputs/). Overrides $DID_TOOLKIT_PROJECT_ROOT '
                             'and CWD auto-discovery. Use --init-project to '
                             'scaffold a new workspace.')
    parser.add_argument('--init-project',
                        nargs='?',
                        const='.',
                        default=None,
                        metavar='PATH',
                        help='Scaffold a new did-toolkit workspace at PATH '
                             '(defaults to CWD): creates config/project.json, '
                             'auto-detects an adjacent Bosch BSW tree to '
                             'pre-populate paths.* (with {product_type_*} '
                             'placeholders), and creates empty inputs/ and '
                             'outputs/ directories. TTY runs prompt for '
                             'identity fields; non-TTY runs require '
                             '--name (plus --customer-name / --project-root '
                             'when no Bosch tree is detected) and exit 4 '
                             'otherwise. Sole workspace-init entry point.')
    parser.add_argument('--name',
                        default=None,
                        metavar='NAME',
                        help='Workspace name override for --init-project. '
                             'Required in non-TTY mode. Not persisted in '
                             'project.json — gates the fail-loud '
                             'non-interactive guard so CI scripts have '
                             'an explicit "I know what I want" signal.')
    parser.add_argument('--customer-name',
                        default=None,
                        metavar='NAME',
                        help='Bosch BSW customer directory name (e.g. '
                             'rbcn) for --init-project. Used at build '
                             'time to materialise paths.* literal '
                             'segments (not persisted as a top-level '
                             'config field). Required in non-TTY mode '
                             'unless a Bosch tree is structurally '
                             'detected.')
    parser.add_argument('--init-project-root',
                        default=None,
                        metavar='NAME',
                        help='Bosch project-root tree name (e.g. '
                             'Fe_Super) for --init-project. Used at '
                             'build time to materialise paths.* literal '
                             'segments (not persisted as a top-level '
                             'config field). Required in non-TTY mode '
                             'unless a Bosch tree is structurally '
                             'detected. Distinct from --project-root '
                             'which selects the workspace for any other '
                             'phase.')
    parser.add_argument('--base-dir',
                        default=None,
                        metavar='PATH',
                        help='Override for paths.base_dir (the directory '
                             'under which Phase 2/3 expect to find the '
                             'Bosch tree at <base_dir>/<project_root>/'
                             'rb/as/<customer>/...). Defaults to the '
                             '--init-project target directory.')
    parser.add_argument('--non-interactive',
                        action='store_true',
                        help='Force --init-project into the non-interactive '
                             'fail-loud branch even when stdin appears to '
                             'be a tty. Useful for CI runners on Windows / '
                             'PowerShell, where isatty() can mis-report '
                             'subprocess.DEVNULL stdin as a tty and '
                             'silently deadlock the prompt loop.')
    parser.add_argument('--config',
                        default=None,
                        metavar='PATH',
                        help='Explicit project config to use this run, '
                             'overriding multi-config auto-discovery. '
                             'Relative paths resolve against the project '
                             'workspace; absolute paths pass through. '
                             'Example: --config config/project.dpb.json.')
    parser.add_argument('--list-configs',
                        action='store_true',
                        help='Enumerate every config/project*.json in the '
                             'workspace as TAG<TAB>RELATIVE-PATH lines '
                             '(one per line, sorted) and exit. Mirrors '
                             '--list-inputs; intended for the agent driver '
                             'to prompt the operator when more than one '
                             'config exists.')
    # There is no ``--list-briefs`` flag. Per-DID context lives in an
    # inline ``TODO(agent)`` block embedded directly in each generated
    # ``.c`` file (storage class, FSCS behaviour text, and DID metadata
    # are all captured in the block). The agent reads the stub file
    # itself — there is no separate ``_briefs/`` directory.

    args = parser.parse_args()

    # --version short-circuits all pipeline logic. We *also* validate
    # cross-file consistency so operators can't accidentally ship a
    # release where SKILL.md says 1.0.0, VERSION says 1.0.1, and
    # CHANGELOG has a stale header. See scripts/version.py.
    if args.version:
        from version import check_version_consistency
        ok, diagnostics = check_version_consistency()
        print(diagnostics[0])
        for line in diagnostics[1:]:
            print(line, file=sys.stderr)
        sys.exit(0 if ok else 2)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # ``--init-project`` bypasses the standard project-root resolution
    # because the whole point is to *create* a workspace that doesn't
    # exist yet. Hand it to the dedicated entry point so the
    # controller never tries to load missing configs.
    if args.init_project is not None:
        from init_project import run_init_project
        # --init-project is a resumable state machine. If
        # ``--input <basename>`` was supplied, forward it so the
        # questionnaire picker (numbered, in TTY) or the recorded-
        # choice resolver (auto-Phase-1 branch) can short-circuit
        # the operator prompt. ``args.input`` is the shared --input
        # flag (also consumed by --phase fscs); both consumers
        # tolerate an unset value.
        sys.exit(run_init_project(
            args.init_project,
            interactive=False if args.non_interactive else None,
            name=args.name,
            customer_name=args.customer_name,
            project_root=args.init_project_root,
            base_dir=args.base_dir,
            input_choice=args.input,
        ))

    try:
        controller = PipelineController(cli_project_root=args.project_root)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        sys.exit(2)

    # ``--list-configs`` enumerates project*.json under the resolved
    # workspace's config/ folder, one ``TAG<TAB>PATH`` line per match,
    # sorted, exit 0 even when the list is empty (an empty workspace
    # is a valid posture). Mirrors ``--list-inputs``.
    if args.list_configs:
        from config_selector import discover_configs, format_candidates
        candidates = discover_configs(controller.project_root)
        for line in format_candidates(candidates, controller.project_root):
            print(line)
        sys.exit(0)

    # Pick the active config file once, up front, so every phase that
    # reads project.json sees the same payload. The selector handles
    # --config explicit, single-match auto, multi-match TTY menu, and
    # multi-match agent-ambiguity-error itself.
    try:
        from config_selector import select_config
        controller.active_config_path = select_config(
            cli_arg=args.config,
            project_root=controller.project_root,
        )
    except FileNotFoundError as exc:
        logger.error(str(exc))
        sys.exit(2)

    # ``--list-inputs`` is the agent's enumeration entry point for
    # the multi-questionnaire selection contract. Side-effect free,
    # always exit 0 (a missing inputs/ folder is treated as
    # 'no candidates' rather than an error so the agent can branch
    # on empty stdout). The output is a flat newline-delimited list
    # of schema-compliant ``*_did.json`` absolute POSIX paths only.
    if args.list_inputs:
        groups = controller.discover_input_candidates()
        for path in groups["json"]:
            print(path.resolve().as_posix())
        sys.exit(0)

    # ``xlsx-import`` / ``review`` / ``doors`` read generated artefacts directly and
    # never touch the raw inputs, so skip the auto-detect + validate
    # flow that would otherwise error out when ``inputs/`` is empty.
    # Review *does* use input_path for its JSON cross-check when one is
    # available, so we pass args.input through if the operator supplied
    # it, but we don't require it.
    needs_input = args.phase in {'fscs', 'arxml', 'implementation'}

    if needs_input and args.input is None:
        # v1.27.0: only ``*_did.json`` is accepted (the v1.8 .xlsx tier
        # is gone — the built-in GAC / Olympus parsers were removed so
        # the skill stays generic). Multi-candidate handling stays
        # strict: TTY shells get an interactive numbered menu; non-TTY
        # shells (CI, agent's Shell tool) get a hard error pointing at
        # --list-inputs + plain-text prompt-and-stop (the agent
        # contract documented in SKILL.md — no AskQuestion).
        # Single-candidate behaviour is unchanged.
        groups = controller.discover_input_candidates()
        candidates = groups["json"]
        inputs_dir = controller.base_dir / 'inputs'
        if not candidates:
            logger.error(
                f"No *_did.json found in {inputs_dir}. "
                f"Place a schema-compliant DID JSON there or pass "
                "--input explicitly. (Direct .xlsx ingestion is not "
                "supported; normalise a questionnaire via "
                ".DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py first.)"
            )
            sys.exit(1)

        if len(candidates) == 1:
            chosen = candidates[0]
        else:
            chosen = _select_input_or_exit(candidates, inputs_dir)

        args.input = str(chosen.relative_to(controller.base_dir).as_posix())
        logger.info(f"Auto-detected input: {args.input}")

    # Standalone phases that don't touch the raw input go through their
    # own dispatch and exit before the input-validation gate below,
    # which would otherwise reject them (args.input is None).
    if args.phase == 'xlsx-import':
        ok = controller.run_xlsx_import(args.xlsx, args.input)
        sys.exit(0 if ok else 1)
    if args.phase == 'review':
        ok = controller.run_review_only(args.input)
        sys.exit(0 if ok else 1)
    if args.phase == 'doors':
        ok = controller.run_doors_sync(
            user_nt=args.user_nt,
            password=args.password,
            no_upload=args.no_upload,
            no_fetch=args.no_fetch,
            no_links=args.no_links,
            no_anchor=args.no_anchor,
            refresh=args.refresh,
            plan_only=getattr(args, 'plan_only', False),
            force_reinsert=getattr(args, 'force_reinsert', False),
            save_credentials=getattr(args, 'save_credentials', False),
            forget_credentials=getattr(args, 'forget_credentials', False),
            no_keyring=getattr(args, 'no_keyring', False),
        )
        sys.exit(0 if ok else 1)

    if not controller.validate_input(args.input):
        logger.error("Input validation failed")
        sys.exit(1)

    if args.validate:
        logger.info("Validation complete")
        sys.exit(0)
    
    # v1.2: review auto-runs at the end of Phase 1 unless explicitly
    # suppressed. There is no "force-on" flag because True is the default.
    review_suppress = os.environ.get('DID_NO_REVIEW', '').strip().lower() in {
        '1', 'true', 'yes', 'on',
    }
    run_review_decision = not (args.no_review or review_suppress)

    # v1.25.0: the legacy ``--phase all`` auto-chain was removed.
    # Each ``--phase <name>`` invocation runs exactly one phase and
    # returns; the STOP-gate footers in Phase 1 and xlsx-import
    # spell out the next command so the operator can decide between
    # ARXML/impl generation and DOORS upload without re-reading
    # SKILL.md. ``--phase fscs`` is the new default when no phase
    # is supplied (the entry point of the gated pipeline).
    if args.phase == 'fscs':
        ok = controller.run_phase1(
            args.input,
            reset_used=args.reset_used,
            run_review=run_review_decision,
            # Phase 1's freshly-built DIDs that lack an explicit
            # ``Product_Type`` tag fall through to ``product_type=None``
            # which the work-set collapses to ``Common`` ("applies to
            # all" semantics). Operators tag specific products in
            # fscs_edit.xlsx after Phase 1; xlsx-import re-renders
            # fscs.json.
            product_type=None,
        )
        sys.exit(0 if ok else 1)

    if args.phase == 'arxml':
        ok = controller.run_phase2(
            input_path=args.input,
            dry_run=args.dry_run,
        )
        sys.exit(0 if ok else 1)

    if args.phase == 'implementation':
        ok = controller.run_phase3(
            dry_run=args.dry_run,
            input_path=args.input,
        )
        sys.exit(0 if ok else 1)

    # Should be unreachable — argparse already validated args.phase
    # against the allowed choices set, and every choice is handled
    # either above (this block) or in the earlier standalone
    # branches (xlsx-import / review / doors). Keep an explicit fail
    # so a future ``choices=...`` typo surfaces loudly rather than
    # silently exiting 0.
    logger.error(f"Unhandled --phase value: {args.phase!r}")
    sys.exit(1)


if __name__ == '__main__':
    main()
