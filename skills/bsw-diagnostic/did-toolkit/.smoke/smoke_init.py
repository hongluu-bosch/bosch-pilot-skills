"""init-project smoke harness (resumable state machine).

Drives the five-scenario matrix that pins the four ``--init-project``
states defined in :mod:`init_project`:

* **case 1** -- FRESH transition: empty workspace + non-TTY + full
  overrides + no questionnaire -> exit 0, ``.DCOM_AI/DID_Toolkit_PRJ/`` skeleton
  scaffolded, NO ``project.json`` yet (the state machine refuses to
  write a config without a questionnaire in place).
* **case 2** -- FOLDERS_ONLY -> fail-loud exit 4: skeleton present +
  questionnaire missing + non-TTY without ``--name`` -> exit 4. The
  fail-loud guard fires at the QUESTIONNAIRE_READY transition. (We
  seed a questionnaire then immediately re-discover from a fresh
  tempdir so the lack-of-name is the rejection cause.)
* **case 3** -- QUESTIONNAIRE_READY happy path: seeded questionnaire
  + full overrides + no detectable tree -> exit 0, ``project.json``
  written, ``paths.input_did_json`` records the chosen basename,
  starter templates copied. Mirror disabled so ``paths.*`` literals
  stay empty.
* **case 4** -- QUESTIONNAIRE_READY with detected tree: seeded
  questionnaire + Bosch tree materialised + ``--name`` only -> exit
  0, ``paths.*`` literals carry ``{product_type_*}`` placeholders
  and the detected ``(project_root, customer)`` pair.
* **case 5** -- COMPLETE auto-chain: re-run on the case-4 workspace
  -> ``--init-project`` advances into Phase 1 (or surfaces a Phase
  1 error code). We just check stdout for the "advancing into Phase
  1" banner so the smoke doesn't depend on the test fixture being
  fully Phase-1-clean. The unit tests cover the success/failure
  exit-code mapping in detail (``patch`` of ``run_phase1``).

Workspace layout: artefacts (``config/`` / ``inputs/`` / ``outputs/``
/ ``scripts/`` / ``state/``) live under ``<target>/.DCOM_AI/DID_Toolkit_PRJ/``, so
every on-disk assertion below resolves through the ``_workspace``
helper.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
PIPELINE = SKILL / "scripts" / "pipeline.py"
PYTHON = sys.executable

# The workspace lives under ``<target>/.DCOM_AI/DID_Toolkit_PRJ/``.
# Mirrors the constants in scripts/project_root.py so the smoke
# harness doesn't depend on the toolkit being importable from the
# harness's sys.path.
DCOM_AI_UMBRELLA = ".DCOM_AI"
TOOLKIT_SUBDIR = "DID_Toolkit_PRJ"
DCOM_AI = f"{DCOM_AI_UMBRELLA}/{TOOLKIT_SUBDIR}"

# The QUESTIONNAIRE_READY transition refuses to advance until a
# schema-compliant ``*_did.json`` is sitting under
# ``.DCOM_AI/DID_Toolkit_PRJ/inputs/``. For smoke purposes we use the bundled
# fixture (which is Phase-1-valid) so case 5 can also exercise the
# COMPLETE auto-chain end to end.
TINY_DID_FIXTURE = SKILL / "tests" / "fixtures" / "tiny_did.json"


def _workspace(target: Path) -> Path:
    """Return the workspace path for a given ``--init-project`` target.

    ``target`` is the project container (where ``rb/as/...`` lives);
    the workspace is two levels deeper, inside
    ``.DCOM_AI/DID_Toolkit_PRJ/``.
    """
    return target / DCOM_AI_UMBRELLA / TOOLKIT_SUBDIR


def _seed_questionnaire(target: Path, *, filename: str = "acme_did.json") -> Path:
    """Drop a Phase-1-valid ``*_did.json`` under ``.DCOM_AI/DID_Toolkit_PRJ/inputs/``
    so the state machine lands in QUESTIONNAIRE_READY on the next
    ``--init-project`` invocation. The skeleton dirs are created
    lazily because case 3 / case 4 seed BEFORE the first
    ``--init-project`` run.
    """
    inputs_dir = _workspace(target) / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    dst = inputs_dir / filename
    shutil.copy2(TINY_DID_FIXTURE, dst)
    return dst


def _run(argv: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        [PYTHON, str(PIPELINE), *argv],
        capture_output=True, text=True,
        encoding="latin-1",
        check=False,
        # ensure non-TTY by passing stdin=DEVNULL
        stdin=subprocess.DEVNULL,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _materialise_bosch(workspace: Path, root: str = "Fe_Super",
                       customer: str = "rbcn") -> None:
    (workspace / root / "rb" / "as" / customer
     / "core" / "app" / "dcom" / "RBAPLCust").mkdir(parents=True)


def main() -> int:
    failures: list[str] = []

    # ---- 1) FRESH -> FOLDERS_ONLY scaffold-only -------------------
    # An empty project container is legal. --init-project scaffolds
    # .DCOM_AI/DID_Toolkit_PRJ/ and STOPs, asking the operator to drop a
    # questionnaire. Even with full identity overrides we don't
    # write project.json yet -- the questionnaire is still missing.
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "ws"
        rc, out, err = _run([
            "--init-project", str(target),
            "--non-interactive",
            "--name", "MyProj",
            "--customer-name", "rbcn",
            "--init-project-root", "Fe_Super",
        ])
        if rc != 0:
            failures.append(
                f"[case1] expected exit 0 on fresh scaffold, got {rc}; "
                f"stderr={err!r}"
            )
        ws = _workspace(target)
        if not (ws / "inputs").is_dir():
            failures.append("[case1] .DCOM_AI/DID_Toolkit_PRJ/inputs/ not scaffolded")
        if (ws / "config" / "project.json").exists():
            failures.append(
                "[case1] project.json written prematurely "
                "(state machine should refuse until *_did.json arrives)"
            )
        if "drop" not in out.lower() and "questionnaire" not in out.lower():
            failures.append(
                "[case1] expected stdout hint to mention dropping a "
                f"questionnaire; got {out!r}"
            )
        if not any(f.startswith("[case1]") for f in failures):
            print("[case1] OK: fresh scaffold; no project.json until questionnaire arrives")

    # ---- 2) FOLDERS_ONLY: fail-loud without --name + tree ---------
    # The fail-loud guard fires at the QUESTIONNAIRE_READY ->
    # write-config transition. Seed a questionnaire then re-invoke
    # without --name and without a detectable Bosch tree -> exit 4
    # (no project.json written).
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "ws"
        target.mkdir()
        _seed_questionnaire(target)
        rc, _, err = _run([
            "--init-project", str(target),
            "--non-interactive",
        ])
        if rc != 4:
            failures.append(f"[case2] expected exit 4, got {rc}; stderr={err!r}")
        if (_workspace(target) / "config" / "project.json").exists():
            failures.append("[case2] project.json written despite fail-loud")
        if not any(f.startswith("[case2]") for f in failures):
            print("[case2] OK: QUESTIONNAIRE_READY without --name exits 4, writes nothing")

    # ---- 3) QUESTIONNAIRE_READY -> COMPLETE (no tree) -------------
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "ws"
        target.mkdir()
        seeded = _seed_questionnaire(target, filename="acme_did.json")
        rc, _, err = _run([
            "--init-project", str(target),
            "--non-interactive",
            "--name", "MyProj",
            "--customer-name", "rbcn",
            "--init-project-root", "Fe_Super",
        ])
        if rc != 0:
            failures.append(f"[case3] expected exit 0, got {rc}; stderr={err!r}")
        ws = _workspace(target)
        config_path = ws / "config" / "project.json"
        if not config_path.is_file():
            failures.append("[case3] missing .DCOM_AI/DID_Toolkit_PRJ/config/project.json")
        else:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            paths = payload["paths"]
            if paths["pdm_file"] != "":
                failures.append(f"[case3] expected empty pdm_file, got {paths['pdm_file']!r}")
            if paths["c_output_subdir"] != "":
                failures.append(f"[case3] expected empty c_output_subdir, got {paths['c_output_subdir']!r}")
            # paths.input_did_json must record the chosen
            # questionnaire's basename for the COMPLETE-state re-run
            # path to know what to feed Phase 1.
            if paths.get("input_did_json") != seeded.name:
                failures.append(
                    f"[case3] expected paths.input_did_json={seeded.name!r}, "
                    f"got {paths.get('input_did_json')!r}"
                )
            for sub in ("inputs", "outputs", "scripts", "state"):
                if not (ws / sub).is_dir():
                    failures.append(f"[case3] .DCOM_AI/DID_Toolkit_PRJ/{sub}/ missing")
            tpl = ws / "scripts" / "extract_customer.py.template"
            if not tpl.is_file():
                failures.append(
                    "[case3] missing .DCOM_AI/DID_Toolkit_PRJ/scripts/"
                    "extract_customer.py.template"
                )
            doors_tpl = ws / "inputs" / "doors_mapping.yaml.template"
            if not doors_tpl.is_file():
                failures.append(
                    "[case3] missing .DCOM_AI/DID_Toolkit_PRJ/inputs/"
                    "doors_mapping.yaml.template"
                )
        if not any(f.startswith("[case3]") for f in failures):
            print("[case3] OK: QUESTIONNAIRE_READY -> COMPLETE; mirror disabled, paths.* empty")

    # ---- 4) QUESTIONNAIRE_READY -> COMPLETE (with tree) -----------
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "ws"
        target.mkdir()
        # The Bosch tree lives at the CONTAINER (next to .DCOM_AI/DID_Toolkit_PRJ/),
        # NOT inside the workspace itself. paths.base_dir = container.
        _materialise_bosch(target, "Fe_Super_TestRelease", "rbcn_premium")
        _seed_questionnaire(target)
        rc, _, err = _run([
            "--init-project", str(target),
            "--non-interactive",
            "--name", "MyProj",
        ])
        if rc != 0:
            failures.append(f"[case4] expected exit 0, got {rc}; stderr={err!r}")
        ws = _workspace(target)
        config_path = ws / "config" / "project.json"
        if not config_path.is_file():
            failures.append("[case4] missing .DCOM_AI/DID_Toolkit_PRJ/config/project.json")
        else:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            paths = payload["paths"]
            if not paths["pdm_file"].endswith("RBDCOM_Customer.pdm"):
                failures.append(f"[case4] pdm_file unexpected: {paths['pdm_file']!r}")
            if "{product_type_upper}" not in paths["c_output_subdir"]:
                failures.append(f"[case4] c_output_subdir missing placeholder: {paths['c_output_subdir']!r}")
            if "{product_type_arxml_folder}" not in paths["arxml_file"]:
                failures.append(f"[case4] arxml_file missing folder placeholder: {paths['arxml_file']!r}")
            if "{product_type_suffix}" not in paths["arxml_file"]:
                failures.append(f"[case4] arxml_file missing suffix placeholder: {paths['arxml_file']!r}")
            if "{product_type_lower}" not in paths["config_settings_h"]:
                failures.append(f"[case4] config_settings_h missing placeholder: {paths['config_settings_h']!r}")
            expected_segment = "Fe_Super_TestRelease/rb/as/rbcn_premium/"
            if expected_segment not in paths["pdm_file"]:
                failures.append(
                    f"[case4] expected detected pair baked into pdm_file "
                    f"as {expected_segment!r}; got {paths['pdm_file']!r}"
                )
            if "project" in payload:
                failures.append(
                    "[case4] rejected-legacy-field check: payload still "
                    "carries a 'project' block"
                )
            if "project_root" in paths:
                failures.append(
                    "[case4] rejected-legacy-field check: paths.* still "
                    "carries 'project_root'"
                )
        if not any(f.startswith("[case4]") for f in failures):
            print("[case4] OK: QUESTIONNAIRE_READY + tree -> mirror enabled, placeholders set")

        # ---- 5) COMPLETE auto-chain into Phase 1 ------------------
        # Re-run --init-project on the workspace from case 4. The
        # state machine now detects COMPLETE and auto-invokes
        # PipelineController.run_phase1 against the recorded
        # questionnaire. We don't assert Phase 1 success/failure
        # (depends on the fixture's exact data shape, which is
        # outside the smoke harness's remit); we just look for the
        # "advancing into Phase 1" stdout banner that the state
        # machine prints right before the auto-chain.
        rc, out, err = _run([
            "--init-project", str(target),
            "--non-interactive",
        ])
        # Phase 1 may legitimately return 0 OR 1 depending on the
        # fixture; both prove the auto-chain branch executed. What
        # we refuse is "exit 0 with no banner" (= classic scaffold
        # branch ran again instead of advancing).
        banner = "advancing into Phase 1"
        if banner not in out:
            failures.append(
                f"[case5] expected stdout banner {banner!r} on COMPLETE "
                f"re-run; got stdout={out!r}"
            )
        else:
            print("[case5] OK: COMPLETE auto-chain printed Phase 1 banner")

    if failures:
        print()
        print("FAILURES:")
        for f in failures:
            print(" ", f)
        return 1
    print()
    print("SMOKE: all 5 init-project scenarios pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
