#!/usr/bin/env python3
"""diagcomm-toolkit -> DOORS sync orchestrator (Step 8 entry point).

This is the recommended single entry point for Step 8. It:

    1. Reads `inputs/DiagComm_values.json` (project.name, project.product_type, parameters).
    2. Reads `inputs/doors_mapping.yaml`   (module_uuid, columns, anchor, value_maps).
    3. Reads `state/doors_upload_state.json` (schema v3: one entry per
       module_uuid with covered_projects/products/arxml_paths,
       last_object_text, history).
    4. Classifies the change (see `doors_state.classify_change()`):

         first_insert            -> mode=insert
         params_and_pp_changed   -> mode=insert (genuinely new context)
         params_changed          -> mode=update, append delta block
         pp_only_changed         -> mode=update, append "new mapping" block
         fscs_only_changed       -> mode=update, append refreshed FSCS
         no_change               -> mode=update + skip flag (exit 1)

       Manual overrides: `--force-mode insert|update`, `--force-no-skip`.

    5. If `change_kind == no_change` AND no force flags -> short-circuit;
       no upload, exit 1.
    6. Calls `build_doors_payload.build_payload(...)` in-process,
       passing the state entry + change_kind so the row is built with:
         - RB_Product       = covered_products  U  current product
         - RB_Realizing_SWitem = covered_arxml_paths  U  current paths
         - Object Text      = last_object_text  +  appended block
    7. Calls `doors_upload.py` (subprocess; 180 s hard timeout) and
       parses the `Data: SUCCESS:<n>` line on success.
    8. **Insert-only**: reconciles the real DOORS AbsoluteNumber.

       The upload server's `SUCCESS:<n>` is an OPAQUE counter, NOT the
       AbsoluteNumber DOORS allocated. After a successful insert we
       therefore re-fetch the module via `doors_fetch.fetch_module`,
       diff its AbsoluteNumber set against `outputs/doors_export.json`
       (the snapshot used for the anchor lookup, captured BEFORE the
       upload), and pick the single new row as the real
       `last_success_abs`. If the diff yields multiple new rows
       (concurrent edits by other authors), the row whose Object Text
       starts with our freshly-written FSCS prefix wins. Cache lag
       (server returns 0 new rows because the upstream DOORS query
       hasn't replicated yet) triggers a bounded retry loop with
       sleeps; persistent failure falls back to the opaque counter
       and emits a loud WARN with manual-patch instructions.

       This step also overwrites `outputs/doors_export.json` with the
       fresh fetch on successful reconciliation, so the *next* run's
       anchor lookup and decision logic see a current snapshot.
    9. Persists state via `record_insert(...)` (insert mode -> reset
       covered_* lists to current single value, write the reconciled
       AbsoluteNumber) or `record_update(...)` (update mode -> grow
       covered_* lists, append history entry, refresh "current_*"
       markers, store the freshly-built Object Text as the next run's
       append target). `record_update` keeps the existing
       `last_success_abs` so the opaque-counter bug never reaches
       state on the update path.

Common invocations (since 1.17.0 the password is sourced through a
4-level fallback: --password > $DOORS_PWD > OS keychain > prompt):

    # Run every command from the project root (cd <project-root> first);
    # <skill> is your installed skill path, e.g.
    # ~/.cursor/skills/diagcomm-toolkit (Linux/macOS) or
    # %USERPROFILE%\.cursor\skills\diagcomm-toolkit (Windows).

    # Build only (no upload, no state write):
    python <skill>/scripts/doors_sync.py --no-upload

    # First time on this machine: cache the password in the OS keychain
    # (Windows Credential Manager / macOS Keychain / Linux Secret Service)
    # so subsequent runs are zero-prompt:
    python <skill>/scripts/doors_sync.py --user-nt <NT> --password <pwd> --save-credentials --no-upload

    # Every run after the cache is set: zero password prompts, zero env vars
    python <skill>/scripts/doors_sync.py --user-nt <NT>

    # Force re-insert even if state has an entry:
    python <skill>/scripts/doors_sync.py --force-mode insert ...

    # Forget the cached password on this machine:
    python <skill>/scripts/doors_sync.py --user-nt <NT> --forget-credentials

Exit codes:
    0  build (and optionally upload + state write) succeeded
    1  degraded: warnings, or short-circuit "no change"
    2  fatal: stop and read the report
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SKILL_ROOT = HERE.parent
# v2.0.0: outputs/, state/, .cache/ all live in the per-project workspace
# at <project>/.DCOM_AI/DiagComm_Toolkit_PRJ/. WORKSPACE_ROOT is
# cwd-anchored at import time -- callers cd into the project root
# before invoking the skill.
WORKSPACE_ROOT = (Path.cwd() / ".DCOM_AI" / "DiagComm_Toolkit_PRJ").resolve()
CACHE_DIR = WORKSPACE_ROOT / ".cache"
OUTPUTS_DIR = WORKSPACE_ROOT / "outputs"
STATE_DIR = WORKSPACE_ROOT / "state"
DEFAULT_VALUES = CACHE_DIR / "DiagComm_values.json"
DEFAULT_MAPPING = CACHE_DIR / "doors_mapping.yaml"
DEFAULT_STATE = STATE_DIR / "doors_upload_state.json"
DEFAULT_FSCS = OUTPUTS_DIR / "FSCS.txt"
DEFAULT_DIFF = OUTPUTS_DIR / "diff_report.txt"
DEFAULT_EXPORT = OUTPUTS_DIR / "doors_export.json"
DEFAULT_UPLOAD = OUTPUTS_DIR / "doors_upload.xlsx"
DEFAULT_REPORT = OUTPUTS_DIR / "doors_payload_report.txt"
UPLOAD_SCRIPT = HERE / "doors_upload.py"

# DOORS MCP server URL. Defaults to the internal team server; override
# per-environment via the DIAGCOMM_DOORS_MCP_URL env var or the
# --server-url CLI flag (CLI > env var > default).
DEFAULT_SERVER_URL = os.environ.get(
    "DIAGCOMM_DOORS_MCP_URL", "http://10.54.7.36:8000/mcp"
)

import doors_state  # noqa: E402


# -- input loaders -------------------------------------------------------- #


def _load_yaml(path: Path) -> Any:
    try:
        import yaml
    except ImportError:
        raise SystemExit(
            f"PyYAML missing. Run: python -m pip install -r "
            f"{(SKILL_ROOT / 'scripts' / 'requirements.txt').as_posix()}"
        )
    return yaml.safe_load(path.read_text(encoding="utf-8-sig"))


def _load_json(path: Path) -> Any:
    import json
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_v2_identity(cfg: Any) -> Tuple[str, str, Dict[str, Any]]:
    """Extract (project_name, product_type, parameters) from a values
    dict. Prefers v2 shape, falls back to v1 if a stray pre-1.13.0
    file slips through (e.g. a fixture used by an integration test).

    Returns "" / {} for missing parts so the caller can decide on a
    user-friendly placeholder.
    """
    if not isinstance(cfg, dict):
        return "", "", {}

    # v2: {project: {name, product_type}, parameters: {...}}
    project_block = cfg.get("project")
    parameters_block = cfg.get("parameters")
    project_name = ""
    product_type = ""
    parameters: Dict[str, Any] = {}

    if isinstance(project_block, dict):
        if isinstance(project_block.get("name"), str):
            project_name = project_block["name"]
        if isinstance(project_block.get("product_type"), str):
            product_type = project_block["product_type"]
    if isinstance(parameters_block, dict):
        parameters = parameters_block

    # v1 fallback
    if not project_name and isinstance(cfg.get("project_name"), str):
        project_name = cfg["project_name"]
    legacy_values = cfg.get("values") if isinstance(cfg.get("values"), dict) else None
    if legacy_values is not None:
        if not product_type and isinstance(legacy_values.get("product_type"), str):
            product_type = legacy_values["product_type"]
        if not parameters:
            parameters = {k: v for k, v in legacy_values.items() if k != "product_type"}

    return project_name, product_type, parameters


# -- decision driver ------------------------------------------------------ #


def _resolve_decision(
    state: Dict[str, Any],
    module_uuid: str,
    change_kind: str,
    cli_force_mode: Optional[str],
) -> Tuple[str, Optional[str], str]:
    """Combine the change_kind classification with optional CLI force
    flags. Returns (mode, target_abs, human_reason).

    The change_kind itself is preserved (and threaded through to
    build_doors_payload) so the Object Text append template still
    reflects the real semantic change even when the user forces
    insert/update.
    """
    if cli_force_mode:
        forced = cli_force_mode.lower()
        if forced not in ("insert", "update"):
            raise SystemExit(f"--force-mode must be insert|update, got {forced!r}")
        if forced == "update":
            abs_n = doors_state.get_last_abs(state, module_uuid)
            if not abs_n:
                raise SystemExit(
                    f"--force-mode update requested but state has no "
                    f"last_success_abs for module_uuid {module_uuid!r}. "
                    "Either run insert first, or pass --force-update-abs <n>."
                )
            return "update", abs_n, f"forced (--force-mode update) abs={abs_n!r}"
        return "insert", None, "forced (--force-mode insert)"
    return doors_state.decide_mode_from_kind(state, module_uuid, change_kind)


# -- credential cache (OS keychain via `keyring`) ------------------------ #
#
# Goal: let the user run Step 8 without ever putting the DOORS password
# on the CLI / in $env / in any file. The `keyring` library brokers
# the OS-native secret store:
#
#   Windows -> Credential Manager (DPAPI; user-bound, machine-bound).
#   macOS   -> Keychain Access.
#   Linux   -> Secret Service (gnome-keyring / KWallet).
#
# Resolution order in `_resolve_password`:
#
#   1. CLI `--password ...`        (explicit beats everything)
#   2. `$DOORS_PWD` env var        (CI / scripted runs)
#   3. keyring entry for user_nt   (the typical interactive case)
#   4. interactive `getpass`       (one-time fallback; offers to save)
#
# If the upload fails with what looks like an auth error AND the
# password came from cache (steps 2 or 3), `_upload_with_pwd_refresh`
# prompts ONCE for a new password and retries. On retry success the
# new password silently overwrites the keychain entry. On retry
# failure the keychain is NOT touched. We never retry more than once
# per run -- DOORS / LDAP / AD typically lock the NT account after
# 3-5 failed attempts.

KEYRING_SERVICE = "diagcomm-toolkit:doors"

# Tokens that strongly suggest the upload server rejected the
# (user_nt, password) pair specifically (vs. a network or server-side
# error). Tested against the lower-cased concatenation of subprocess
# stdout + stderr.
_AUTH_FAIL_RE = re.compile(
    r"\b(401|403|unauthor(?:i[sz]ed|ised)|invalid credentials|"
    r"authentication failed|login failed|"
    r"bad (?:nt )?(?:password|credentials)|"
    r"wrong (?:password|credentials)|"
    r"密码错误|用户名或密码错误|认证失败)\b",
    re.IGNORECASE,
)


def _looks_like_auth_failure(captured: str) -> bool:
    """Heuristic: did the upload subprocess fail because the password
    was rejected (vs. a network / server / xlsx-format problem)?

    Conservative: a single token match anywhere in stdout+stderr is
    enough. False positives only cost the user one extra prompt; false
    negatives just mean we don't auto-refresh and the user has to rerun
    with `--save-credentials` themselves.
    """
    return bool(_AUTH_FAIL_RE.search(captured or ""))


def _try_import_keyring(disabled: bool):
    """Return the `keyring` module, or ``None`` if unavailable / disabled.

    Centralises the optional-dependency dance so `_resolve_password`,
    `_save_to_keyring`, `_forget_keyring`, and the auth-fail retry path
    all see the same yes/no answer for this run.
    """
    if disabled:
        return None
    try:
        import keyring  # type: ignore
    except ImportError:
        return None
    return keyring


def _keyring_get(keyring_mod, user_nt: str) -> Optional[str]:
    if keyring_mod is None or not user_nt:
        return None
    try:
        return keyring_mod.get_password(KEYRING_SERVICE, user_nt)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[doors_sync] WARN: keyring lookup failed for {user_nt!r}: "
            f"{exc}; falling through to prompt.",
            file=sys.stderr,
        )
        return None


def _keyring_set(keyring_mod, user_nt: str, password: str) -> bool:
    """Persist (user_nt -> password) in the OS keychain.

    Returns True on success. Logs and returns False otherwise -- never
    raises, so a keychain glitch can never block an upload.
    """
    if keyring_mod is None:
        print(
            "[doors_sync] WARN: `keyring` not installed -- cannot save "
            f"credentials. Run: python -m pip install -r "
            f"{(SKILL_ROOT / 'scripts' / 'requirements.txt').as_posix()}",
            file=sys.stderr,
        )
        return False
    if not user_nt or not password:
        return False
    try:
        existing = keyring_mod.get_password(KEYRING_SERVICE, user_nt)
        keyring_mod.set_password(KEYRING_SERVICE, user_nt, password)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[doors_sync] WARN: keyring write failed for {user_nt!r}: {exc}",
            file=sys.stderr,
        )
        return False
    verb = "updated" if existing else "saved"
    print(
        f"[doors_sync] {verb} DOORS password for {user_nt!r} in OS keychain "
        f"(service={KEYRING_SERVICE!r})."
    )
    return True


def _keyring_delete(keyring_mod, user_nt: str) -> bool:
    """Delete the (KEYRING_SERVICE, user_nt) entry if it exists.

    Treats "no such entry" as benign success -- the caller asked for
    the entry to be gone, and it is. We probe with `get_password`
    first (cross-backend reliable: every keyring backend returns
    None for a missing entry) and only call `delete_password` when
    something is actually there. This avoids depending on per-backend
    error messages of `PasswordDeleteError`, which differ wildly:

      Windows  -> "diagcomm-toolkit:doors"   (just the service name)
      macOS    -> "Item not found (-25300)"
      Linux SS -> "No such item: <bus path>"
    """
    if keyring_mod is None:
        print(
            "[doors_sync] WARN: `keyring` not installed -- nothing to forget.",
            file=sys.stderr,
        )
        return False
    try:
        existing = keyring_mod.get_password(KEYRING_SERVICE, user_nt)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[doors_sync] WARN: keyring lookup failed for {user_nt!r}: {exc}",
            file=sys.stderr,
        )
        return False
    if existing is None:
        print(f"[doors_sync] no keychain entry for {user_nt!r}; nothing to forget.")
        return True
    try:
        keyring_mod.delete_password(KEYRING_SERVICE, user_nt)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[doors_sync] WARN: keyring delete failed for {user_nt!r}: {exc}",
            file=sys.stderr,
        )
        return False
    print(f"[doors_sync] forgot DOORS password for {user_nt!r} in OS keychain.")
    return True


def _resolve_password(
    *,
    cli_password: Optional[str],
    user_nt: str,
    keyring_mod,
    allow_prompt: bool,
) -> Tuple[Optional[str], str]:
    """Pick the password to use this run.

    Returns ``(password_or_None, source)`` where ``source`` is one of
    ``"cli" | "env" | "keyring" | "prompt" | "none"``. The source
    label gates the auth-fail retry: if ``source == "prompt"`` we do
    NOT prompt again on auth failure (the user just typed it; another
    prompt won't help and risks NT lock-out).
    """
    if cli_password:
        return cli_password, "cli"

    env_pwd = os.environ.get("DOORS_PWD")
    if env_pwd:
        return env_pwd, "env"

    cached = _keyring_get(keyring_mod, user_nt)
    if cached:
        return cached, "keyring"

    if not allow_prompt:
        return None, "none"
    if not sys.stdin.isatty():
        return None, "none"

    try:
        pwd = getpass.getpass(f"DOORS password for {user_nt}: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return None, "none"
    if not pwd:
        return None, "none"
    return pwd, "prompt"


# -- upload subprocess wrapper ------------------------------------------- #


_SUCCESS_RE = re.compile(r"SUCCESS:(\d+)")


def _run_upload(
    excel_path: Path,
    module_uuid: str,
    user_nt: str,
    password: str,
    server_url: str,
    init_timeout: int,
    upload_timeout: int,
) -> Tuple[int, Optional[str], str]:
    """Run doors_upload.py as a subprocess.

    Returns (exit_code, abs_n_or_None, captured_text).

    We use a subprocess (not import) so the existing console UX of
    doors_upload.py is preserved verbatim, and so that script's own
    HTTP/SSE timeouts apply unchanged.
    """
    cmd = [
        sys.executable,
        str(UPLOAD_SCRIPT),
        str(excel_path),
        module_uuid,
        user_nt,
        password,
        "--server-url", server_url,
        "--init-timeout", str(init_timeout),
        "--upload-timeout", str(upload_timeout),
    ]
    print("=" * 72)
    print("[doors_sync] handing off to doors_upload.py")
    print("=" * 72)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    captured = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        return proc.returncode, None, captured
    m = _SUCCESS_RE.search(captured)
    if not m:
        return 1, None, captured
    return 0, m.group(1), captured


def _upload_with_pwd_refresh(
    *,
    excel_path: Path,
    module_uuid: str,
    user_nt: str,
    password: str,
    pwd_source: str,
    server_url: str,
    init_timeout: int,
    upload_timeout: int,
    keyring_mod,
) -> Tuple[int, Optional[str], str, str]:
    """Run the upload, and on auth failure prompt ONCE for a refreshed
    password and retry. On retry success, write the new password to
    the OS keychain (so the next run is back to zero-prompt).

    Returns ``(rc, abs_n_or_None, captured_text, final_pwd_source)``.
    The caller never needs the password back, only the final source
    label (for logging).

    Why "once" specifically: most enterprise DOORS deployments delegate
    auth to LDAP / AD, which lock the NT account after 3-5 wrong
    passwords. We must spend at most 2 attempts here (the cached one
    + one user-typed one). If both fail with auth errors the user has
    to fix the underlying problem (typo'd NT, locked account, etc.)
    before another run, NOT keep retrying inside one process.
    """
    rc, abs_n, captured = _run_upload(
        excel_path=excel_path,
        module_uuid=module_uuid,
        user_nt=user_nt,
        password=password,
        server_url=server_url,
        init_timeout=init_timeout,
        upload_timeout=upload_timeout,
    )
    if rc == 0:
        return rc, abs_n, captured, pwd_source

    if not _looks_like_auth_failure(captured):
        return rc, abs_n, captured, pwd_source

    if pwd_source == "prompt":
        # User just typed it and it was still rejected -- the issue
        # isn't a stale cache. Asking again only burns NT attempts.
        print(
            "\n[doors_sync] DOORS rejected the password just entered. "
            "Not retrying -- repeated wrong passwords risk locking the "
            "NT account. Verify the password (DOORS Web login) and rerun.",
            file=sys.stderr,
        )
        return rc, abs_n, captured, pwd_source

    if pwd_source == "cli":
        # User passed `--password` explicitly; respect that and don't
        # surreptitiously prompt for a different one.
        print(
            "\n[doors_sync] DOORS rejected the password supplied via "
            "--password. Not auto-prompting (you passed an explicit "
            "value -- fix it and rerun, or omit --password to use "
            "$DOORS_PWD / keychain / interactive prompt).",
            file=sys.stderr,
        )
        return rc, abs_n, captured, pwd_source

    if not sys.stdin.isatty():
        print(
            "\n[doors_sync] DOORS rejected the cached credentials "
            f"(source={pwd_source}) and there's no TTY for an interactive "
            "prompt (CI / non-interactive shell). Rerun with "
            "`--password <new> --save-credentials` to refresh the keychain.",
            file=sys.stderr,
        )
        return rc, abs_n, captured, pwd_source

    print()
    print("=" * 72)
    print("[doors_sync] DOORS rejected the cached credentials.")
    print(
        "             Most likely the password was changed since the "
        "last successful upload."
    )
    print(
        "             Enter the current password to retry (will refresh "
        "the keychain on success)."
    )
    print("=" * 72)
    try:
        new_pwd = getpass.getpass(f"DOORS password for {user_nt}: ")
    except (EOFError, KeyboardInterrupt):
        print()
        print("[doors_sync] aborted by user; keychain NOT modified.",
              file=sys.stderr)
        return rc, abs_n, captured, pwd_source
    if not new_pwd:
        print("[doors_sync] empty password; not retrying.", file=sys.stderr)
        return rc, abs_n, captured, pwd_source

    print("[doors_sync] retrying upload with the new password ...")
    rc2, abs_n2, captured2 = _run_upload(
        excel_path=excel_path,
        module_uuid=module_uuid,
        user_nt=user_nt,
        password=new_pwd,
        server_url=server_url,
        init_timeout=init_timeout,
        upload_timeout=upload_timeout,
    )
    if rc2 == 0:
        # Refresh keychain so next run is back to zero-prompt.
        # Best-effort: a write failure here is logged but not fatal --
        # the upload itself already succeeded.
        _keyring_set(keyring_mod, user_nt, new_pwd)
        return rc2, abs_n2, captured2, "prompt-refresh"

    # Retry also failed.
    if _looks_like_auth_failure(captured2):
        print(
            "\n[doors_sync] the new password was also rejected. Likely causes:\n"
            "             1) `--user-nt` typo'd or wrong account\n"
            "             2) NT account locked after too many failed attempts\n"
            "             3) DOORS-side replication lag right after a "
            "password reset\n"
            "             Log into the DOORS Web UI once to confirm the "
            "credentials and unlock if needed, then rerun. The keychain "
            "was NOT modified.",
            file=sys.stderr,
        )
    return rc2, abs_n2, captured2, "prompt-failed"


# -- main ----------------------------------------------------------------- #


def _print_decision_banner(
    *,
    project: str,
    product: str,
    module_uuid: str,
    change_kind: str,
    mode: str,
    target_abs: Optional[str],
    reason: str,
    no_change: bool,
    state_entry: Optional[Dict[str, Any]],
) -> None:
    print("=" * 72)
    print("doors_sync -- Step 8 decision")
    print("=" * 72)
    print(f"  project        : {project}")
    print(f"  product        : {product}")
    print(f"  module_uuid    : {module_uuid}")
    print(f"  change_kind    : {change_kind}")
    print(
        f"  decided mode   : {mode}"
        + (f"   target_abs={target_abs}" if target_abs else "")
    )
    print(f"  reason         : {reason}")
    if state_entry:
        cov_proj = state_entry.get("covered_projects") or []
        cov_prod = state_entry.get("covered_products") or []
        cov_paths = state_entry.get("covered_arxml_paths") or []
        print(
            f"  state.covered  : {len(cov_proj)} project(s), "
            f"{len(cov_prod)} product(s), {len(cov_paths)} arxml path(s)"
        )
    if no_change:
        print(
            "  short-circuit  : YES -- "
            "every tracked field matches last success; nothing to upload."
        )
    print()
    if mode == "update":
        print(
            "  NOTE: update mode REGENERATES the entire row, but multi-value cells\n"
            "        (RB_Product, RB_Realizing_SWitem) and Object Text are appended\n"
            "        to the recorded history -- not overwritten. covered_* lists in\n"
            "        state grow monotonically per module_uuid.\n"
        )
    elif mode == "insert":
        print(
            "  NOTE: insert mode SEEDS A FRESH row. covered_*/last_object_text are\n"
            "        reset to the single current values; the previous row (if any)\n"
            "        in DOORS becomes orphaned (state no longer tracks it).\n"
        )


def _rebuild_state_inputs(
    *,
    change_kind: str,
    mode: str,
    state_entry: Optional[Dict[str, Any]],
    values_path: Path,
    fscs_path: Path,
    diff_path: Path,
) -> Tuple[str, List[str]]:
    """Recompute the Object Text + realizing-arxml-paths that
    `build_doors_payload.build_payload` would have written. We do this
    by re-importing the same helpers and running the same path -- the
    values are deterministic given the same inputs, so this is cheap
    and avoids widening the public build_payload return signature.

    The returned (object_text, realizing_paths) get persisted into the
    state entry by record_insert / record_update so the next run has
    the right append target and realizing-paths union seed.
    """
    import build_doors_payload as bdp  # local import: avoids circular

    cfg = bdp._load_values_with_config(values_path)
    project_name, product_type, parameters = _read_v2_identity(cfg)
    can_channel = parameters.get("CAN_Channel", 0) if isinstance(parameters, dict) else 0
    paths_block = cfg.get("paths") or {}
    realizing_arxmls = bdp._collect_realizing_arxmls(
        paths_block, product_type, can_channel,
    )

    if mode == "insert" or state_entry is None:
        prior_paths: List[str] = []
        prior_projects: List[str] = []
        prior_products: List[str] = []
        prior_object_text: Optional[str] = None
    else:
        prior_paths = list(state_entry.get("covered_arxml_paths") or [])
        prior_projects = list(state_entry.get("covered_projects") or [])
        prior_products = list(state_entry.get("covered_products") or [])
        prior_object_text = state_entry.get("last_object_text")

    final_paths = doors_state.union_preserve_order(prior_paths, realizing_arxmls)
    final_projects = doors_state.union_preserve_order(
        prior_projects, [project_name] if project_name else [],
    )
    final_products = doors_state.union_preserve_order(
        prior_products, [product_type] if product_type else [],
    )

    full_fscs_text, _ = bdp.parse_fscs(fscs_path)
    # MUST mirror build_doors_payload.build_payload: Object Text uses
    # the FSCS variant whose header reflects the row's accumulated
    # (project, product) coverage, not the single-project / single-
    # product snapshot that lives in `outputs/FSCS.txt`. Without this
    # rewrite the state's `last_object_text` would diverge from what
    # was actually pushed to DOORS, and the next `params_changed`
    # update would APPEND on top of stale (un-unioned) header text.
    fscs_for_object_text = bdp._rewrite_object_text_header(
        full_fscs_text, final_projects, final_products,
    )
    by_arxml = bdp.parse_diff_report(diff_path) if diff_path.exists() else {}
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    delta_block = bdp._build_delta_text(by_arxml, project_name, product_type, timestamp)
    final_object_text, _ = bdp._build_object_text_for_kind(
        change_kind=change_kind,
        full_fscs=fscs_for_object_text,
        delta_block=delta_block,
        project_name=project_name,
        product_type=product_type,
        timestamp=timestamp,
        prev_object_text=prior_object_text,
    )
    return final_object_text, final_paths


# ----------------------------------------------------------------------- #
# Post-insert reconciliation                                              #
# ----------------------------------------------------------------------- #
#
# `upload_doors_module` returns `Data: SUCCESS:<n>` where <n> is an
# OPAQUE upload-server counter (observed to increment 1-by-1 per
# successful call across modules and users). It is NOT the
# AbsoluteNumber DOORS allocates to the new row, and is not present in
# any field of the inserted row. Trusting it for `last_success_abs`
# is the bug that makes the *next* update fail with
# "Cannot find required Object with Absolute Number <n>".
#
# Fix: after a successful insert, fetch the module fresh, diff against
# the pre-upload export (`outputs/doors_export.json`), and use the
# single new AbsoluteNumber as the real `last_success_abs`. Update mode
# is unaffected -- it never trusts the upload counter; record_update
# preserves the existing last_success_abs.


def _abs_n_set_from_rows(rows: Any) -> Set[str]:
    """Pull the (string) AbsoluteNumber set from a DOORS rows list,
    skipping rows that don't carry one (defensive: real exports always
    do, but let's not crash on a malformed payload)."""
    if not isinstance(rows, list):
        return set()
    out: Set[str] = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        v = r.get("AbsoluteNumber")
        if isinstance(v, str) and v:
            out.add(v)
    return out


def _row_object_text(row: Dict[str, Any]) -> str:
    """The DOORS export historically stores the cell named "Object
    Text" under the key ``DescriptionOfRequirementRB``. We try the
    legacy aliases too so a future export schema bump doesn't silently
    break content matching here."""
    for k in ("DescriptionOfRequirementRB", "ObjectText", "Object Text"):
        v = row.get(k)
        if isinstance(v, str):
            return v
    return ""


def _reconcile_abs_after_insert(
    *,
    module_uuid: str,
    user_nt: str,
    server_url: str,
    init_timeout: int,
    fetch_timeout: int,
    refresh_timeout: int,
    max_attempts: int,
    sleep_between: int,
    prev_export_path: Path,
    expected_object_text: str,
) -> Tuple[Optional[str], Optional[Dict[str, Any]], str]:
    """Try to find the AbsoluteNumber of the row we just inserted.

    Returns ``(real_abs_n_or_None, fresh_module_payload_or_None,
    human_reason)``. The fresh payload (when present) is the full
    ``{code, message, data}`` dict suitable for overwriting
    ``outputs/doors_export.json`` so the next run gets a current
    snapshot for free.

    Strategy per attempt:
      1. ``fetch_module(refresh=True)`` (refresh failures are
         non-fatal; we still consume the cached read).
      2. Diff the AbsoluteNumber set against ``prev_export_path``.
      3. If exactly one new AbsoluteNumber: that's our row.
      4. If multiple new AbsoluteNumbers (concurrent insert by
         someone else): pick the one whose Object Text starts with
         ``expected_object_text``'s first 200 chars. If that
         disambiguates, return it.
      5. If zero new AbsoluteNumbers: cache lag. Sleep
         ``sleep_between`` and retry.

    Bounded by ``max_attempts``; on persistent failure returns
    ``(None, last_payload, reason)``.
    """
    # Read prev export once. Tolerant: a missing prev_export means
    # this is the very first run for this module on this machine, in
    # which case set-diff is meaningless and we have to fall back to
    # pure content-match.
    import doors_fetch  # local import: avoid module-level fetch dep on requests

    prev_abs: Set[str] = set()
    prev_export_present = prev_export_path.exists()
    if prev_export_present:
        try:
            prev_data = json.loads(prev_export_path.read_text(encoding="utf-8"))
            prev_abs = _abs_n_set_from_rows(
                (prev_data.get("data") or {}).get("rows")
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"[doors_sync] WARN: cannot read prev export at "
                f"{prev_export_path} ({exc}); reconcile falls back to "
                "pure content-match.",
                file=sys.stderr,
            )

    content_marker = (expected_object_text or "")[:200].strip()

    last_payload: Optional[Dict[str, Any]] = None
    last_reason = "no fetch attempt completed"

    for attempt in range(1, max_attempts + 1):
        print(
            f"[doors_sync][reconcile] attempt {attempt}/{max_attempts}: "
            "fetching module to locate inserted AbsoluteNumber..."
        )
        payload = doors_fetch.fetch_module(
            module_uuid=module_uuid,
            user_nt=user_nt,
            server_url=server_url,
            init_timeout=init_timeout,
            fetch_timeout=fetch_timeout,
            refresh=True,
            refresh_timeout=refresh_timeout,
            quiet=False,
        )
        last_payload = payload

        if payload.get("code") != 0:
            last_reason = (
                f"get_doors_module returned code={payload.get('code')} "
                f"message={payload.get('message')!r}"
            )
            print(f"[doors_sync][reconcile] {last_reason}")
            if attempt < max_attempts:
                time.sleep(sleep_between)
            continue

        rows = (payload.get("data") or {}).get("rows") or []
        new_abs = _abs_n_set_from_rows(rows)

        if prev_export_present:
            added = new_abs - prev_abs
        else:
            added = new_abs  # no prev to diff against

        if len(added) == 1:
            real = next(iter(added))
            return real, payload, (
                f"matched by AbsoluteNumber set diff "
                f"(prev={len(prev_abs)} -> now={len(new_abs)}, "
                f"+1 new) on attempt {attempt}"
            )

        if len(added) > 1:
            # Concurrent insert: disambiguate by content.
            candidates: List[str] = []
            for r in rows:
                if r.get("AbsoluteNumber") in added:
                    text = _row_object_text(r)
                    if content_marker and content_marker in text:
                        candidates.append(r["AbsoluteNumber"])
            if len(candidates) == 1:
                return candidates[0], payload, (
                    f"matched by content prefix among {len(added)} new "
                    f"rows on attempt {attempt}"
                )
            last_reason = (
                f"{len(added)} new rows in module since prev export, "
                f"content-match {'disambiguated 0' if not candidates else 'matched ' + str(len(candidates))} "
                "of them; cannot pick a unique AbsoluteNumber"
            )
            print(f"[doors_sync][reconcile] {last_reason}")
            return None, payload, last_reason

        # added == 0: cache lag (server hasn't replicated our insert
        # yet). Retry with sleep, since the upstream DOORS sync can
        # take a while.
        last_reason = (
            f"0 new AbsoluteNumbers visible in cache "
            f"(rows={len(rows)}, prev_rows={len(prev_abs)}); "
            "suspected cache lag"
        )
        print(f"[doors_sync][reconcile] {last_reason}")
        if attempt < max_attempts:
            time.sleep(sleep_between)

    return None, last_payload, last_reason


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="diagcomm-toolkit/doors_sync.py",
        description="Auto-decide insert/update, build the upload xlsx, "
                    "run the upload, and persist state.",
    )
    p.add_argument("--values", default=str(DEFAULT_VALUES))
    p.add_argument("--mapping", default=str(DEFAULT_MAPPING))
    p.add_argument("--state-file", default=str(DEFAULT_STATE))
    p.add_argument("--fscs", default=str(DEFAULT_FSCS))
    p.add_argument("--diff", default=str(DEFAULT_DIFF))
    p.add_argument("--export", default=str(DEFAULT_EXPORT))
    p.add_argument("--upload-out", default=str(DEFAULT_UPLOAD))
    p.add_argument("--report-out", default=str(DEFAULT_REPORT))
    p.add_argument(
        "--force-mode", choices=("insert", "update"), default=None,
        help="override the auto-decision (and the mapping yaml's `mode:`)",
    )
    p.add_argument(
        "--force-no-skip", action="store_true",
        help="upload even when fingerprints match the last success",
    )
    p.add_argument(
        "--no-upload", action="store_true",
        help="build only; do not call doors_upload.py and do not write state",
    )
    p.add_argument("--user-nt", default=None,
                   help="NT username for upload (or set $DOORS_USER_NT). "
                        "Required unless --no-upload / --forget-credentials.")
    p.add_argument("--password", default=None,
                   help="DOORS password. Resolution order: --password "
                        "> $DOORS_PWD > OS keychain > interactive prompt. "
                        "Pair with --save-credentials to cache it.")
    p.add_argument(
        "--save-credentials", action="store_true",
        help="After a successful resolution, persist (user_nt, password) "
             "in the OS keychain (Windows Credential Manager / macOS "
             "Keychain / Linux Secret Service). On subsequent runs the "
             "password is fetched from there with no prompt and no env "
             "var. Re-running with this flag and a different password "
             "OVERWRITES the existing entry -- this is how you refresh "
             "after a password change.",
    )
    p.add_argument(
        "--forget-credentials", action="store_true",
        help="Delete the keychain entry for --user-nt and exit "
             "(does not build, does not upload). Combine with "
             "--user-nt <NT>. No-op if no entry exists.",
    )
    p.add_argument(
        "--no-keyring", action="store_true",
        help="Bypass the OS keychain entirely (do not read, do not "
             "write). Useful for CI, debugging, or when the host has "
             "no Secret Service backend.",
    )
    p.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    p.add_argument("--init-timeout", type=int, default=15)
    p.add_argument("--upload-timeout", type=int, default=180)
    # Post-insert reconciliation (resolve the real AbsoluteNumber by
    # diffing fresh DOORS state against `outputs/doors_export.json`).
    # Update mode never trusts the upload counter, so these flags only
    # affect insert-mode behaviour.
    p.add_argument(
        "--no-reconcile", action="store_true",
        help="Skip post-insert reconciliation (DEBUG/TEST only). State "
             "will retain the opaque upload counter as last_success_abs "
             "and the next update WILL fail with 'Cannot find required "
             "Object' until you patch state by hand.",
    )
    p.add_argument(
        "--reconcile-attempts", type=int, default=3,
        help="Max fetch retries while waiting for the cache to catch "
             "up after an insert (default: 3). Each attempt costs at "
             "least one fetch round-trip plus refresh-server-side time.",
    )
    p.add_argument(
        "--reconcile-sleep", type=int, default=15,
        help="Seconds to sleep between reconcile attempts when 0 new "
             "rows are visible yet (default: 15).",
    )
    p.add_argument(
        "--reconcile-fetch-timeout", type=int, default=120,
        help="Per-fetch timeout for get_doors_module during reconcile "
             "(default: 120). The upstream refresh has its own 60s-ish "
             "ceiling baked into the MCP server; this only governs the "
             "client-side read deadline.",
    )
    p.add_argument(
        "--reconcile-refresh-timeout", type=int, default=70,
        help="Per-attempt timeout for refresh_doors_module during "
             "reconcile (default: 70). Server-side upstream timeout is "
             "60s; we add a small buffer so a slow socket close doesn't "
             "kill our retry budget.",
    )
    args = p.parse_args(argv)

    # Since 1.20.0 the on-disk values + mapping are auto-generated from
    # inputs/DiagComm.xlsx into .cache/. Refresh once at the top of the
    # run so a user who edited the Excel between calls sees their change
    # without an explicit "regenerate cache" step. Skipped when the user
    # pinned --values / --mapping to a non-default path (e.g. a fixture).
    try:
        if (Path(args.values).resolve() == DEFAULT_VALUES.resolve()
                and Path(args.mapping).resolve() == DEFAULT_MAPPING.resolve()):
            import excel_loader  # noqa: PLC0415  -- lazy: heavy openpyxl import
            excel_loader.load_or_refresh()
    except Exception as exc:  # noqa: BLE001
        print(
            f"[doors_sync] WARNING: cache refresh from inputs/DiagComm.xlsx "
            f"failed: {exc}\n"
            f"  proceeding with stale .cache/ files (if any). Re-run "
            f"`python {HERE / 'excel_loader.py'} dump` for a louder error.",
            file=sys.stderr,
        )

    keyring_mod = _try_import_keyring(disabled=args.no_keyring)

    # `--forget-credentials` is a self-contained admin op: do not build,
    # do not upload, do not touch any other state. Surface a clean exit
    # code so it can be wired into shell aliases / CI without dragging
    # in the rest of the pipeline.
    if args.forget_credentials:
        user_nt = args.user_nt or os.environ.get("DOORS_USER_NT")
        if not user_nt:
            print(
                "[doors_sync] ERROR: --forget-credentials requires --user-nt "
                "(or $DOORS_USER_NT) so we know which entry to delete.",
                file=sys.stderr,
            )
            return 2
        ok = _keyring_delete(keyring_mod, user_nt)
        return 0 if ok else 2

    # Cold-start admin op (since 1.19.3): `--save-credentials --no-upload`
    # is the recipe the agent generates on a brand-new machine to prime
    # the OS keychain BEFORE any pipeline run. At that point there is no
    # FSCS / diff / DOORS export on disk, so calling build_doors_payload
    # would just `_bail` (silently, since it only writes to the report
    # file). Short-circuit here so the cache-priming command behaves like
    # `--forget-credentials`: self-contained, no pipeline IO.
    if args.save_credentials and args.no_upload:
        user_nt = args.user_nt or os.environ.get("DOORS_USER_NT")
        password = args.password or os.environ.get("DOORS_PWD")
        if not user_nt or not password:
            print(
                "[doors_sync] ERROR: --save-credentials --no-upload needs "
                "both --user-nt and --password (or $DOORS_USER_NT / "
                "$DOORS_PWD). Nothing to cache.",
                file=sys.stderr,
            )
            return 2
        if not _keyring_set(keyring_mod, user_nt, password):
            return 2
        print(
            "[doors_sync] credential cache primed; subsequent runs without "
            "--password / --save-credentials will pick the password up "
            "from the OS keychain automatically."
        )
        return 0

    values_path = Path(args.values)
    mapping_path = Path(args.mapping)
    state_path = Path(args.state_file)
    fscs_path = Path(args.fscs)

    if not values_path.exists():
        print(f"[doors_sync] ERROR: values file missing: {values_path}", file=sys.stderr)
        return 2
    if not mapping_path.exists():
        print(f"[doors_sync] ERROR: mapping file missing: {mapping_path}", file=sys.stderr)
        return 2

    import build_doors_payload as _bdp_for_load  # noqa: E402  (local)
    values_obj = _bdp_for_load._load_values_with_config(values_path)
    project_name, product_type, values_block = _read_v2_identity(values_obj)
    if not project_name:
        project_name = "(unknown)"
    if not product_type:
        product_type = "(unknown)"

    mapping_obj = _load_yaml(mapping_path)
    if not isinstance(mapping_obj, dict):
        print("[doors_sync] ERROR: mapping yaml must be a top-level mapping",
              file=sys.stderr)
        return 2
    doors_block = mapping_obj.get("doors") or {}
    module_uuid = str(doors_block.get("document_uuid") or "").strip()
    if not module_uuid or "PUT-" in module_uuid:
        print(
            f"[doors_sync] ERROR: doors.document_uuid missing or placeholder "
            f"({module_uuid!r}). Edit {mapping_path} first.",
            file=sys.stderr,
        )
        return 2

    state = doors_state.load_state(state_path)

    fingerprint = doors_state.compute_param_fingerprint(values_block)
    fscs_sha = doors_state.compute_file_sha256(fscs_path) if fscs_path.exists() else None

    change_kind = doors_state.classify_change(
        state, module_uuid,
        project_name=project_name,
        product_type=product_type,
        param_fingerprint=fingerprint,
        fscs_sha256=fscs_sha,
    )

    mode, target_abs, reason = _resolve_decision(
        state, module_uuid, change_kind, args.force_mode,
    )

    no_change = (
        not args.force_mode
        and not args.force_no_skip
        and change_kind == doors_state.CHANGE_KIND_NONE
    )

    state_entry = doors_state.get_module_entry(state, module_uuid)

    _print_decision_banner(
        project=project_name, product=product_type, module_uuid=module_uuid,
        change_kind=change_kind, mode=mode, target_abs=target_abs,
        reason=reason, no_change=no_change, state_entry=state_entry,
    )

    if no_change:
        print("[doors_sync] No semantic changes since last upload. Skipping.")
        print("            Pass --force-no-skip to upload anyway.")
        return 1

    import build_doors_payload

    cli_updates: Dict[str, str] = {}
    if mode == "update":
        if not target_abs:
            print("[doors_sync] internal error: update mode without target_abs",
                  file=sys.stderr)
            return 2
        diff_path = Path(args.diff)
        if diff_path.exists():
            from build_doors_payload import parse_diff_report
            by_arxml = parse_diff_report(diff_path)
            for arxml in by_arxml:
                cli_updates[arxml] = target_abs
            # Empty by_arxml is OK in pp_only_changed / no_change kinds
            # (we'll route the AbsoluteNumber through cli_target_abs).
        else:
            print(
                f"[doors_sync] ERROR: diff_report missing at {diff_path}",
                file=sys.stderr,
            )
            return 2

    rc = build_doors_payload.build_payload(
        fscs_path=fscs_path,
        diff_path=Path(args.diff),
        export_path=Path(args.export),
        mapping_path=mapping_path,
        values_path=values_path,
        upload_out=Path(args.upload_out),
        report_out=Path(args.report_out),
        cli_mode=mode,
        cli_updates=cli_updates,
        existing_state=state_entry,
        change_kind=change_kind,
        cli_target_abs=target_abs if mode == "update" else None,
    )
    if rc == 2:
        print(
            f"[doors_sync] build_doors_payload failed (rc=2). "
            f"Details written to: {args.report_out}",
            file=sys.stderr,
        )
        return 2

    if args.no_upload:
        print("[doors_sync] --no-upload set: built xlsx, not uploading.")
        print(f"            artefact: {args.upload_out}")
        # Honour --save-credentials even on a no-upload run so users can
        # cache the password without doing a full upload (e.g. right
        # after a DOORS-side password reset, before they have any real
        # spec changes to push).
        if args.save_credentials:
            user_nt = args.user_nt or os.environ.get("DOORS_USER_NT")
            password = args.password or os.environ.get("DOORS_PWD")
            if user_nt and password:
                _keyring_set(keyring_mod, user_nt, password)
            else:
                print(
                    "[doors_sync] WARN: --save-credentials needs both "
                    "--user-nt and --password (or env vars); skipped.",
                    file=sys.stderr,
                )
        return rc

    user_nt = args.user_nt or os.environ.get("DOORS_USER_NT")
    if not user_nt:
        print(
            "[doors_sync] ERROR: --user-nt (or $DOORS_USER_NT) is required "
            "for upload. Use --no-upload if you only want to build the xlsx.",
            file=sys.stderr,
        )
        return 2

    password, pwd_source = _resolve_password(
        cli_password=args.password,
        user_nt=user_nt,
        keyring_mod=keyring_mod,
        allow_prompt=True,
    )
    if not password:
        print(
            "[doors_sync] ERROR: no DOORS password available. Tried "
            "--password, $DOORS_PWD, OS keychain, interactive prompt -- "
            "all empty.\n"
            "  - First-time setup: rerun with `--password <pwd> "
            "--save-credentials` to cache it in the OS keychain.\n"
            "  - CI / scripted: set $DOORS_PWD or pass `--password`.\n"
            "  - Build-only:   rerun with `--no-upload`.",
            file=sys.stderr,
        )
        return 2
    print(f"[doors_sync] credentials: user_nt={user_nt!r} (source={pwd_source})")

    # Optionally cache the resolved password BEFORE the upload runs.
    # The upload may legitimately fail (network, format, locked
    # module); we still want the password persisted so the user
    # doesn't have to re-type next run. Auth-failure retry path
    # refreshes this entry separately if the user types a new
    # password.
    if args.save_credentials and pwd_source != "keyring":
        _keyring_set(keyring_mod, user_nt, password)

    upload_rc, success_abs, _captured, _final_source = _upload_with_pwd_refresh(
        excel_path=Path(args.upload_out),
        module_uuid=module_uuid,
        user_nt=user_nt,
        password=password,
        pwd_source=pwd_source,
        server_url=args.server_url,
        init_timeout=args.init_timeout,
        upload_timeout=args.upload_timeout,
        keyring_mod=keyring_mod,
    )
    if upload_rc != 0 or not success_abs:
        print(
            f"[doors_sync] upload failed (rc={upload_rc}, "
            f"success_abs={success_abs!r}); state NOT updated.",
            file=sys.stderr,
        )
        return 2

    # Recover the freshly-built Object Text + realizing paths from the
    # build report so record_*() can persist exactly what DOORS now
    # holds. Reading the report is a touch indirect; the cleaner path
    # would be to capture them directly from build_payload's return.
    # We rebuild the tuple deterministically from inputs here so we
    # don't have to widen the build_payload signature again.
    final_object_text, final_realizing_paths = _rebuild_state_inputs(
        change_kind=change_kind,
        mode=mode,
        state_entry=state_entry,
        values_path=values_path,
        fscs_path=fscs_path,
        diff_path=Path(args.diff),
    )

    # Insert path: the upload server's SUCCESS:<n> counter is NOT the
    # AbsoluteNumber. Reconcile against a fresh module fetch before we
    # write `last_success_abs` to state, otherwise the next update is
    # guaranteed to fail looking up that counter as an AbsoluteNumber.
    if mode == "insert" and not args.no_reconcile:
        real_abs, fresh_payload, recon_reason = _reconcile_abs_after_insert(
            module_uuid=module_uuid,
            user_nt=user_nt,
            server_url=args.server_url,
            init_timeout=args.init_timeout,
            fetch_timeout=args.reconcile_fetch_timeout,
            refresh_timeout=args.reconcile_refresh_timeout,
            max_attempts=args.reconcile_attempts,
            sleep_between=args.reconcile_sleep,
            prev_export_path=Path(args.export),
            expected_object_text=final_object_text,
        )
        if real_abs:
            print(
                f"[doors_sync][reconcile] real AbsoluteNumber resolved: "
                f"{real_abs}  (upload counter was {success_abs!r}; "
                f"reason: {recon_reason})"
            )
            success_abs = real_abs
            # Promote the fresh fetch to outputs/doors_export.json so
            # the next run's anchor lookup and decision logic see a
            # current snapshot. Best-effort: a write failure here only
            # costs us a stale export on the next run.
            if isinstance(fresh_payload, dict):
                try:
                    Path(args.export).parent.mkdir(parents=True, exist_ok=True)
                    Path(args.export).write_text(
                        json.dumps(fresh_payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    print(f"[doors_sync][reconcile] refreshed {args.export}")
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[doors_sync][reconcile] WARN: could not refresh "
                        f"{args.export}: {exc}", file=sys.stderr,
                    )
        else:
            print(
                f"[doors_sync][reconcile] WARN: could not resolve real "
                f"AbsoluteNumber (reason: {recon_reason}). State will hold "
                f"the OPAQUE upload counter {success_abs!r} as "
                "last_success_abs; the next update WILL fail with "
                "'Cannot find required Object'. To recover:\n"
                "  1. Wait a minute (the upstream cache often catches "
                "up after a short delay).\n"
                f"  2. python {HERE / 'doors_fetch.py'} "
                f"{module_uuid} {user_nt} --refresh\n"
                "  3. Find the row you just inserted (e.g. by "
                "LastModifiedBy/On or Object Text content) and read "
                "its AbsoluteNumber from the export.\n"
                "  4. Edit state/doors_upload_state.json, set "
                f"modules[{module_uuid!r}].last_success_abs and the "
                "matching history entry's abs_n to that value.",
                file=sys.stderr,
            )

    if mode == "insert":
        doors_state.record_insert(
            state, module_uuid, success_abs,
            project_name=project_name,
            product_type=product_type,
            param_fingerprint=fingerprint,
            fscs_sha256=fscs_sha,
            object_text=final_object_text,
            realizing_arxml_paths=final_realizing_paths,
            change_kind=change_kind,
        )
    else:
        doors_state.record_update(
            state, module_uuid,
            project_name=project_name,
            product_type=product_type,
            param_fingerprint=fingerprint,
            fscs_sha256=fscs_sha,
            object_text=final_object_text,
            realizing_arxml_paths=final_realizing_paths,
            change_kind=change_kind,
        )
    doors_state.save_state(state_path, state)

    print()
    print("=" * 72)
    print(f"[doors_sync] state updated: module_uuid={module_uuid}")
    print(f"             project/product = {project_name} / {product_type}")
    print(f"             change_kind = {change_kind}")
    after = doors_state.get_module_entry(state, module_uuid) or {}
    # The opaque upload-server counter `success_abs` (e.g. 628) is NOT
    # the AbsoluteNumber DOORS allocated. In insert mode reconcile may
    # already have promoted it to the real number and assigned it to
    # `success_abs`; in update mode `record_update` deliberately
    # preserves the previously recorded `last_success_abs`. Either way,
    # the authoritative value lives in state -- read it from there so
    # the banner doesn't mislead the user about which row will be
    # targeted on the next run.
    persisted_abs = str(after.get("last_success_abs") or "").strip() or success_abs
    if mode == "update" and persisted_abs != str(success_abs):
        print(
            f"             last_success_abs={persisted_abs}  "
            f"(kept from prior insert; upload counter for this run was "
            f"{success_abs})"
        )
    else:
        print(f"             last_success_abs={persisted_abs}")
    print(f"             state file={state_path}")
    print(
        f"             covered_projects = {after.get('covered_projects')}"
    )
    print(
        f"             covered_products = {after.get('covered_products')}"
    )
    print(
        f"             covered_arxml_paths = {len(after.get('covered_arxml_paths') or [])} path(s)"
    )
    print("=" * 72)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
