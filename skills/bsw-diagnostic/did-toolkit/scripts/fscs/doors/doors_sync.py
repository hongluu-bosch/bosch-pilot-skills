#!/usr/bin/env python3
"""DID FSCS -> DOORS sync orchestrator.

Single command that walks the full DOORS pipeline. v1.27.0 workspace
layout: every read / write target listed below is resolved against
the active project workspace at
``<container>/.DCOM_AI/DID_Toolkit_PRJ/``; the
``pipeline.py --phase doors`` orchestrator wires the exact paths via
``--mapping`` / ``--out-dir`` / ``--state`` / ... so standalone
invocations of this script should pass them explicitly too. The
``SKILL_ROOT / ...`` defaults further down are stale fallbacks kept
only for argparse — they don't reflect the real workspace location.

    1. Resolve module / link UUIDs from
       ``.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml``.
    2. Fetch the DOORS module via MCP ``get_doors_module``
       -> ``.DCOM_AI/DID_Toolkit_PRJ/outputs/doors/doors_export.json``
       (skipped with ``--no-fetch`` if the export is already fresh.)
    3. Resolve per-service anchors (``anchors.service_22`` /
       ``service_2e``) from the keyword text the user supplied.
    4. Build TWO content workbooks (one per service) under
       ``.DCOM_AI/DID_Toolkit_PRJ/outputs/doors/``, with the per-DID two-row layout.
    5. Upload each content workbook via MCP ``upload_doors_module``
       (``--no-upload`` skips this and step 6/7).
    6. Re-fetch the module, walk its rows, pair each DID's FS row with
       the row that follows it (the CS row we just inserted) by
       matching on Object Heading text. Persist the (cs_abs, fs_abs)
       map to ``.DCOM_AI/DID_Toolkit_PRJ/outputs/doors/doors_link_entries.json``.
    7. Build the link xlsx (CS -> FS for every paired DID) and POST it
       via MCP ``update_doors_links`` (skipped if ``links.enabled`` is
       false or ``links.link_module_uuid`` is blank).
    8. Persist a state entry under
       ``.DCOM_AI/DID_Toolkit_PRJ/state/doors_upload_state.json`` so future runs can
       short-circuit when the FSCS hash hasn't moved.

Common invocations (since 2.3.0 the password is sourced through a
4-level fallback: ``--password`` > ``$DOORS_PWD`` > OS keychain >
interactive prompt; ``<skill>`` is e.g.
``~/.cursor/skills/did-toolkit``)::

    # Build only (no MCP calls; useful smoke test).
    python <skill>/scripts/fscs/doors/doors_sync.py --no-upload --no-fetch

    # First time on this machine: cache the password in the OS
    # keychain (Windows Credential Manager / macOS Keychain / Linux
    # Secret Service) so subsequent runs are zero-prompt:
    python <skill>/scripts/fscs/doors/doors_sync.py \\
        --user-nt <NT> --password <pwd> --save-credentials --no-upload

    # Every run after the cache is set: zero password prompts, zero
    # env vars.
    python <skill>/scripts/fscs/doors/doors_sync.py --user-nt <NT>

    # Skip the link upload (e.g. while debugging anchor lookup).
    python <skill>/scripts/fscs/doors/doors_sync.py --user-nt <NT> --no-links

    # Forget the cached password on this machine.
    python <skill>/scripts/fscs/doors/doors_sync.py --user-nt <NT> --forget-credentials

Exit codes:
    0  build (and upload + links, when not skipped) succeeded
    1  degraded (upload partial, link skipped due to missing config, ...)
    2  fatal -- read the report
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from anchor import load_export, resolve_anchors  # noqa: E402
from build_doors_payload import (  # noqa: E402
    BuildResult,
    DEFAULT_EXPORT,
    DEFAULT_FSCS_JSON,
    DEFAULT_MAPPING,
    DEFAULT_OUT_DIR,
    DEFAULT_PROJECT,
    DEFAULT_REPORT,
    DEFAULT_TXT_22,
    DEFAULT_TXT_2E,
    build_payload,
)
from diff import ActionPlan, format_plan_summary, format_plan_table  # noqa: E402
from doors_fetch import fetch_module  # noqa: E402
from doors_links import LinkEntry, build_link_xlsx, reconcile_did_rows  # noqa: E402
from doors_state import (  # noqa: E402
    ServiceLanding,
    State,
    _normalise_hex,
    load_state,
    now_utc_iso,
    reset_module,
    save_state,
)
from doors_upload_mcp import update_links, upload_module  # noqa: E402
from fscs_split import split_file  # noqa: E402
from mcp_transport import DEFAULT_SERVER_URL  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STATE = SKILL_ROOT / "state" / "doors_upload_state.json"
DEFAULT_LINK_XLSX = DEFAULT_OUT_DIR / "doors_upload_links.xlsx"
DEFAULT_LINK_ENTRIES_JSON = DEFAULT_OUT_DIR / "doors_link_entries.json"


# ----------------------------------------------------------------------- #
# yaml loader                                                             #
# ----------------------------------------------------------------------- #


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("PyYAML missing; install with: python -m pip install pyyaml") from exc
    if not path.is_file():
        raise FileNotFoundError(f"mapping file missing: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(loaded, dict):
        raise ValueError("doors_mapping.yaml must be a top-level mapping")
    return loaded


def _writeback_state_post_upload(
    *,
    state: State,
    module_uuid: str,
    plan: ActionPlan,
    link_entries: List[LinkEntry],
) -> int:
    """Persist post-upload landings into ``state`` for ``module_uuid``.

    Walks the action plan and folds the freshly-fetched
    ``link_entries`` (FS+CS AbsoluteNumbers) into the per-DID state
    so the next ``--phase doors`` run can classify INSERT vs UPDATE
    vs NOOP correctly.

    * **INSERT**  – pull (fs_abs, cs_abs) from the matching link
      entry whose ``service`` matches the action; record
      current_hash + timestamp. If no service-tagged entry
      matches we fall back to a hex-only lookup (legacy callers
      that still pass ``service=""`` entries) and WARN; if even
      that misses we skip the pair (operator can re-upload
      without state corruption — next run will INSERT again).
    * **UPDATE**  – AbsoluteNumber doesn't change (DOORS overwrites
      in place), so we just refresh content_hash + timestamp from
      the action's ``current_hash``.
    * **NOOP**    – existing landing untouched (we don't even
      refresh the timestamp; the recorded one is genuinely the
      "last time this DID changed in DOORS").
    * **STALE**   – warn-only (delete deferred to v1.18.x
      ``--prune-stale``); the orphaned record stays in state so
      the operator can find it.

    Returns the number of (DID, service) landings written.

    v1.17.1: lookup is keyed by ``(service, did_hex)`` instead of
    ``did_hex`` alone so a DID effective in both services records
    its TWO physically distinct landings correctly. The
    orchestrator now passes service-tagged ``LinkEntry`` instances
    by carving the fresh export into per-service row slices via
    ``reconcile_did_rows(service_ranges=...)``. The legacy
    hex-only fallback survives for any caller that still emits
    ``service=""`` entries (smoke tests, hand-driven repairs).
    """
    module = state.for_module(module_uuid)
    module.last_uploaded_at = now_utc_iso()

    landings_by_pair: Dict[tuple, tuple] = {}
    landings_by_did_only: Dict[str, tuple] = {}   # legacy fallback bucket
    for entry in link_entries:
        canonical = _normalise_hex(entry.did_hex)
        if entry.service:
            # The orchestrator stamps "22" / "2E" via service_ranges
            # in v1.17.1; the legacy "_annotate_service" could still
            # produce "22+2E" for hex-only matches, so split on '+'
            # and record under each service independently.
            for svc in entry.service.split("+"):
                svc = svc.strip().upper()
                if svc:
                    landings_by_pair[(svc, canonical)] = (entry.fs_abs, entry.cs_abs)
        # Always also stash a hex-only copy so the v1.16.0 fallback
        # path keeps working when someone hands us an unannotated
        # entries list (e.g. CLI dump replayed via doors_links.py).
        landings_by_did_only[canonical] = (entry.fs_abs, entry.cs_abs)

    timestamp = now_utc_iso()
    n = 0
    for action in plan.actions:
        canonical = _normalise_hex(action.did_hex)
        if action.action == "INSERT":
            key = (action.service.upper(), canonical)
            landing = landings_by_pair.get(key)
            if landing is None and landings_by_did_only:
                # Legacy fallback: caller didn't tag entries with
                # services. Better to record SOMETHING than to
                # leave a fresh INSERT unrecorded; operators with
                # split-anchor projects will see this WARN and
                # know to re-run with the v1.17.1 orchestrator.
                landing = landings_by_did_only.get(canonical)
                if landing is not None:
                    print(
                        f"[doors_sync] WARN: post-upload reconcile produced no "
                        f"service-tagged landing for {canonical}/{action.service}; "
                        "falling back to hex-only match (this can mis-record when "
                        "the same DID is in both services with different anchors). "
                        "Upgrade the orchestrator caller to pass service_ranges "
                        "to reconcile_did_rows.",
                        file=sys.stderr,
                    )
            if landing is None:
                print(
                    f"[doors_sync] WARN: post-upload reconcile missed INSERT "
                    f"for {canonical}/{action.service}; state not updated for "
                    "this pair (next run will INSERT again).",
                    file=sys.stderr,
                )
                continue
            fs_abs, cs_abs = landing
            module.remember(
                canonical, action.service,
                ServiceLanding(
                    fs_abs=fs_abs, cs_abs=cs_abs,
                    content_hash=action.current_hash,
                    last_uploaded_at=timestamp,
                ),
            )
            n += 1
        elif action.action == "UPDATE":
            module.remember(
                canonical, action.service,
                ServiceLanding(
                    fs_abs=action.fs_abs, cs_abs=action.cs_abs,
                    content_hash=action.current_hash,
                    last_uploaded_at=timestamp,
                ),
            )
            n += 1
        elif action.action == "STALE":
            print(
                f"[doors_sync] WARN: STALE record for {canonical}/{action.service} "
                "(no longer effective in current FSCS); record kept until "
                "v1.18.x --prune-stale lands.",
                file=sys.stderr,
            )
        # NOOP: leave existing landing alone.

    return n


def _module_uuid(mapping: Dict[str, Any], *, allow_placeholder: bool = False) -> str:
    doors = mapping.get("doors") if isinstance(mapping.get("doors"), dict) else {}
    uuid = str(doors.get("document_uuid") or "").strip()
    placeholder = (not uuid) or ("PUT-" in uuid) or ("TODO" in uuid)
    if placeholder:
        if allow_placeholder:
            return uuid or "(placeholder)"
        raise ValueError(
            ".DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml needs a real "
            "`doors.document_uuid` (currently a placeholder)."
        )
    return uuid


# ----------------------------------------------------------------------- #
# credential cache (OS keychain via `keyring`)                            #
# ----------------------------------------------------------------------- #
#
# Goal: let the user run --phase doors without ever putting the DOORS
# password on the CLI / in $env / in any file. The `keyring` library
# brokers the OS-native secret store:
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
# If an upload fails with what looks like an auth error AND the
# password came from cache (steps 2 or 3), `_upload_one_with_pwd_refresh`
# prompts ONCE for a new password and retries. On retry success the
# new password silently overwrites the keychain entry. On retry
# failure the keychain is NOT touched. We never retry more than once
# per run -- DOORS / LDAP / AD typically lock the NT account after
# 3-5 failed attempts.

KEYRING_SERVICE = "did-toolkit:doors"

# Tokens that strongly suggest the upload server rejected the
# (user_nt, password) pair specifically (vs. a network or server-side
# error). Tested case-insensitively against the response message.
_AUTH_FAIL_RE = re.compile(
    r"\b(401|403|unauthor(?:i[sz]ed|ised)|invalid credentials|"
    r"authentication failed|login failed|"
    r"bad (?:nt )?(?:password|credentials)|"
    r"wrong (?:password|credentials)|"
    r"密码错误|用户名或密码错误|认证失败)\b",
    re.IGNORECASE,
)


def _looks_like_auth_failure(message: str) -> bool:
    """Heuristic: did the upload reject the (user_nt, password) pair?

    Conservative: a single token match anywhere in the message is
    enough. False positives only cost the user one extra prompt; false
    negatives just mean we don't auto-refresh and the user has to rerun
    with `--save-credentials` themselves.
    """
    return bool(_AUTH_FAIL_RE.search(message or ""))


def _try_import_keyring(disabled: bool):
    """Return the ``keyring`` module, or ``None`` if unavailable / disabled.

    Centralises the optional-dependency dance so ``_resolve_password``,
    the admin ops, and the auth-fail retry path all see the same
    yes/no answer for this run.
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
            "credentials. Run: python -m pip install -r "
            "<skill>/scripts/requirements.txt",
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
    the entry to be gone, and it is. We probe with ``get_password``
    first (cross-backend reliable: every keyring backend returns
    None for a missing entry) and only call ``delete_password`` when
    something is actually there. This avoids depending on per-backend
    error messages of ``PasswordDeleteError``, which differ wildly
    between Windows / macOS / Linux Secret Service.
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


# ----------------------------------------------------------------------- #
# fetch                                                                   #
# ----------------------------------------------------------------------- #


def _fetch_export(
    *,
    module_uuid: str,
    user_nt: str,
    server_url: str,
    init_timeout: int,
    call_timeout: int,
    refresh: bool,
    out_path: Path,
) -> Path:
    print(f"[doors_sync] fetching module {module_uuid} (refresh={refresh})...")
    payload = fetch_module(
        module_uuid=module_uuid,
        user_nt=user_nt,
        server_url=server_url,
        init_timeout=init_timeout,
        call_timeout=call_timeout,
        refresh=refresh,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    code = payload.get("code")
    print(f"[doors_sync]   -> code={code} message={payload.get('message', '')!r}; "
          f"saved to {out_path}")
    if code != 0:
        raise RuntimeError(f"get_doors_module failed: {payload.get('message')}")
    return out_path


# ----------------------------------------------------------------------- #
# upload                                                                  #
# ----------------------------------------------------------------------- #


def _upload_one(
    *,
    excel_path: Path,
    module_uuid: str,
    user_nt: str,
    password: str,
    server_url: str,
    init_timeout: int,
    upload_timeout: int,
) -> Dict[str, Any]:
    print(f"[doors_sync] uploading {excel_path.name} -> {module_uuid}...")
    result = upload_module(
        excel_path=excel_path,
        module_uuid=module_uuid,
        user_nt=user_nt,
        password=password,
        server_url=server_url,
        init_timeout=init_timeout,
        upload_timeout=upload_timeout,
    )
    if result.get("code") != 0:
        raise RuntimeError(
            f"upload_doors_module failed for {excel_path.name}: {result.get('message')}"
        )
    print(f"[doors_sync]   -> SUCCESS  data={result.get('data')!r}")
    return result


def _call_doors_with_pwd_refresh(
    *,
    call_fn,                # zero-arg callable returning {code, message, ...}
    op_label: str,          # "upload_doors_module" / "update_doors_links"
    artefact_label: str,    # "foo.xlsx" / "links.xlsx" -- for messages
    user_nt: str,
    password: str,
    pwd_source: str,
    keyring_mod,
    on_password_change,     # callable(new_pwd) -> rerun result; lets the
                            # second attempt swap the password into call_fn
) -> Tuple[Dict[str, Any], str, str]:
    """Run a DOORS API call, and on auth failure prompt ONCE for a
    refreshed password and retry. On retry success, write the new
    password to the OS keychain (so the next run is back to zero-
    prompt).

    Returns ``(result_dict, final_password, final_pwd_source)``.
    On non-auth failure (network / format / locked module) the
    underlying RuntimeError propagates -- the caller's ``try/except``
    surfaces it like before.

    Why "once" specifically: most enterprise DOORS deployments delegate
    auth to LDAP / AD, which lock the NT account after 3-5 wrong
    passwords. We must spend at most 2 attempts here (the cached one
    + one user-typed one). If both fail with auth errors the user has
    to fix the underlying problem (typo'd NT, locked account, etc.)
    before another run, NOT keep retrying inside one process.

    v2.3.1: extracted from ``_upload_one_with_pwd_refresh`` so the
    link upload can share the same retry path. The corner case it
    covers: when both per-service workbooks have ``rows_written == 0``
    (all DIDs classify NOOP), the per-service uploads are skipped and
    the link upload becomes the FIRST auth-bearing call of the run --
    if it hits stale-keychain rejection there, the operator deserves
    the same one-shot prompt as the per-service upload would have
    given them.
    """
    result = call_fn()
    if result.get("code") == 0:
        print(f"[doors_sync]   -> SUCCESS  data={result.get('data')!r}")
        return result, password, pwd_source

    message = str(result.get("message") or "")
    if not _looks_like_auth_failure(message):
        # Non-auth failure: let the caller raise / handle as before.
        raise RuntimeError(
            f"{op_label} failed for {artefact_label}: {message}"
        )

    if pwd_source == "prompt":
        print(
            "\n[doors_sync] DOORS rejected the password just entered. "
            "Not retrying -- repeated wrong passwords risk locking the "
            "NT account. Verify the password (DOORS Web login) and rerun.",
            file=sys.stderr,
        )
        raise RuntimeError(
            f"{op_label} failed for {artefact_label}: {message}"
        )

    if pwd_source == "cli":
        print(
            "\n[doors_sync] DOORS rejected the password supplied via "
            "--password. Not auto-prompting (you passed an explicit "
            "value -- fix it and rerun, or omit --password to use "
            "$DOORS_PWD / keychain / interactive prompt).",
            file=sys.stderr,
        )
        raise RuntimeError(
            f"{op_label} failed for {artefact_label}: {message}"
        )

    if not sys.stdin.isatty():
        print(
            "\n[doors_sync] DOORS rejected the cached credentials "
            f"(source={pwd_source}) and there's no TTY for an interactive "
            "prompt (CI / non-interactive shell). Rerun with "
            "`--password <new> --save-credentials` to refresh the keychain.",
            file=sys.stderr,
        )
        raise RuntimeError(
            f"{op_label} failed for {artefact_label}: {message}"
        )

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
        raise RuntimeError(
            f"{op_label} failed for {artefact_label}: {message}"
        )
    if not new_pwd:
        print("[doors_sync] empty password; not retrying.", file=sys.stderr)
        raise RuntimeError(
            f"{op_label} failed for {artefact_label}: {message}"
        )

    print("[doors_sync] retrying with the new password ...")
    result2 = on_password_change(new_pwd)
    if result2.get("code") == 0:
        # Refresh keychain so next run is back to zero-prompt. Best-
        # effort: a write failure here is logged but not fatal -- the
        # call itself already succeeded.
        _keyring_set(keyring_mod, user_nt, new_pwd)
        print(f"[doors_sync]   -> SUCCESS  data={result2.get('data')!r}")
        return result2, new_pwd, "prompt-refresh"

    message2 = str(result2.get("message") or "")
    if _looks_like_auth_failure(message2):
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
    raise RuntimeError(
        f"{op_label} failed for {artefact_label}: {message2}"
    )


def _upload_one_with_pwd_refresh(
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
) -> Tuple[Dict[str, Any], str, str]:
    """Auth-retrying wrapper for :func:`upload_module`. Thin shim
    around :func:`_call_doors_with_pwd_refresh` -- kept as a named
    helper for call-site clarity and stable test API."""
    print(f"[doors_sync] uploading {excel_path.name} -> {module_uuid}...")

    def _attempt(pwd):
        return upload_module(
            excel_path=excel_path,
            module_uuid=module_uuid,
            user_nt=user_nt,
            password=pwd,
            server_url=server_url,
            init_timeout=init_timeout,
            upload_timeout=upload_timeout,
        )

    return _call_doors_with_pwd_refresh(
        call_fn=lambda: _attempt(password),
        op_label="upload_doors_module",
        artefact_label=excel_path.name,
        user_nt=user_nt,
        password=password,
        pwd_source=pwd_source,
        keyring_mod=keyring_mod,
        on_password_change=_attempt,
    )


def _update_links_with_pwd_refresh(
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
) -> Tuple[Dict[str, Any], str, str]:
    """Auth-retrying wrapper for :func:`update_links`. v2.3.1 added
    so the corner case of "all per-service uploads skipped (NOOP) but
    link upload still fires" still gets the one-shot prompt + keychain
    refresh path -- otherwise stale credentials at that one call site
    would surface as a hard RuntimeError instead of a recoverable
    prompt."""
    print(f"[doors_sync] uploading links {excel_path.name} -> {module_uuid}...")

    def _attempt(pwd):
        return update_links(
            excel_path=excel_path,
            user_nt=user_nt,
            password=pwd,
            module_uuid=module_uuid,
            server_url=server_url,
            init_timeout=init_timeout,
            upload_timeout=upload_timeout,
        )

    return _call_doors_with_pwd_refresh(
        call_fn=lambda: _attempt(password),
        op_label="update_doors_links",
        artefact_label=excel_path.name,
        user_nt=user_nt,
        password=password,
        pwd_source=pwd_source,
        keyring_mod=keyring_mod,
        on_password_change=_attempt,
    )


# ----------------------------------------------------------------------- #
# link reconciliation                                                     #
# ----------------------------------------------------------------------- #


def _collect_did_headings() -> Dict[str, str]:
    """Build {did_hex -> heading_line} from the FSCS_22.txt and
    FSCS_2E.txt files. Used after a fresh fetch to pair FS rows with
    their CS rows."""
    out: Dict[str, str] = {}
    for path in (DEFAULT_TXT_22, DEFAULT_TXT_2E):
        if not path.is_file():
            continue
        for block in split_file(path):
            out[block.did_hex] = block.heading
    return out


def _annotate_service(
    entries: List[LinkEntry],
    *,
    fs22_dids: List[str],
    fs2e_dids: List[str],
) -> List[LinkEntry]:
    """Fill in the per-entry ``service`` field for any LinkEntry
    that came back unannotated.

    v1.17.1 split: when ``reconcile_did_rows(service_ranges=...)``
    already stamped a concrete ``"22"`` / ``"2E"`` based on the
    fresh-export anchor positions, we **leave it alone** —
    that's the authoritative tag from the actual upload landing.
    Entries with an empty ``service`` (legacy hex-only path,
    smoke tests, hand-driven dumps) get the v1.16.0 fallback:
    union to ``"22+2E"`` when the DID is in both effective
    sets, otherwise pick the single matching service.
    """
    s22 = set(fs22_dids)
    s2e = set(fs2e_dids)
    out: List[LinkEntry] = []
    for entry in entries:
        if entry.service:
            # Already authoritative -- don't second-guess it.
            out.append(entry)
            continue
        if entry.did_hex in s22 and entry.did_hex in s2e:
            service = "22+2E"
        elif entry.did_hex in s22:
            service = "22"
        elif entry.did_hex in s2e:
            service = "2E"
        else:
            service = ""
        out.append(LinkEntry(cs_abs=entry.cs_abs, fs_abs=entry.fs_abs,
                              did_hex=entry.did_hex, service=service))
    return out


def _persist_link_entries(entries: List[LinkEntry], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "did_hex": e.did_hex,
                    "service": e.service,
                    "fs_abs": e.fs_abs,
                    "cs_abs": e.cs_abs,
                }
                for e in entries
            ],
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


# ----------------------------------------------------------------------- #
# main                                                                    #
# ----------------------------------------------------------------------- #


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="did-toolkit/doors_sync.py",
        description="DID FSCS -> DOORS end-to-end sync orchestrator.",
    )
    p.add_argument("--mapping", default=str(DEFAULT_MAPPING))
    p.add_argument("--project", default=str(DEFAULT_PROJECT))
    p.add_argument("--state", default=str(DEFAULT_STATE))
    p.add_argument("--export", default=str(DEFAULT_EXPORT))
    p.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    p.add_argument("--report", default=str(DEFAULT_REPORT))
    # v1.16.0: explicit overrides for the three FSCS-side input
    # paths the build needs. Default to the skill-root constants so
    # standalone invocations from the skill folder keep working;
    # ``pipeline.py::run_doors_sync`` overrides them with workspace-
    # rooted paths so multi-project workspaces (v1.14.0) write into
    # their own outputs/ tree instead of leaking into the skill's.
    p.add_argument("--txt-22", default=str(DEFAULT_TXT_22),
                   help="Path to FSCS_22.txt (default: <skill_root>/outputs/fscs/FSCS_22.txt).")
    p.add_argument("--txt-2e", default=str(DEFAULT_TXT_2E),
                   help="Path to FSCS_2E.txt (default: <skill_root>/outputs/fscs/FSCS_2E.txt).")
    p.add_argument("--fscs-json", default=str(DEFAULT_FSCS_JSON),
                   help="Path to fscs.json. v1.16.0: source of per-DID product_type for "
                        "the RB_Product cell (default: <skill_root>/outputs/fscs/fscs.json).")
    p.add_argument("--user-nt", default=None,
                   help="DOORS NT username (or set $DOORS_USER_NT). "
                        "Required unless --no-upload AND --no-fetch, OR "
                        "running --forget-credentials.")
    p.add_argument("--password", default=None,
                   help="DOORS password. Resolution order: --password "
                        "> $DOORS_PWD > OS keychain > interactive prompt. "
                        "Pair with --save-credentials to cache it in the "
                        "OS keychain.")
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
             "(does not build, does not upload, does not fetch). "
             "Combine with --user-nt <NT> (or $DOORS_USER_NT). No-op "
             "if no entry exists.",
    )
    p.add_argument(
        "--no-keyring", action="store_true",
        help="Bypass the OS keychain entirely (do not read, do not "
             "write). Useful for CI, debugging, or when the host has "
             "no Secret Service backend.",
    )
    p.add_argument("--no-upload", action="store_true",
                   help="Build the workbooks but do not call MCP upload.")
    p.add_argument("--no-fetch", action="store_true",
                   help="Skip MCP fetch; reuse the existing outputs/doors/doors_export.json.")
    p.add_argument("--no-links", action="store_true",
                   help="Skip the link reconciliation + update_doors_links step.")
    p.add_argument("--no-anchor", action="store_true",
                   help="Build with placeholder anchors (implies --no-upload --no-links).")
    p.add_argument("--refresh", action="store_true",
                   help="Force refresh_doors_module before fetch (slower, server-side re-pull).")
    p.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    p.add_argument("--init-timeout", type=int, default=15)
    p.add_argument("--call-timeout", type=int, default=300)
    p.add_argument("--upload-timeout", type=int, default=180)
    # v1.17.0 state-machine CLI surface.
    p.add_argument(
        "--plan-only", action="store_true",
        help="Compute INSERT/UPDATE/NOOP/STALE plan against the recorded state, "
             "print it, exit 0. No xlsx writes, no fetch, no upload, no links. "
             "Implies --no-fetch --no-upload --no-links --no-anchor.",
    )
    p.add_argument(
        "--force-reinsert", action="store_true",
        help="Wipe the recorded landings for the active module before the build. "
             "Every effective DID then classifies as INSERT (the v1.16.0 default). "
             "Use after a DOORS-side teardown / module re-pointing.",
    )
    args = p.parse_args(argv)

    if args.plan_only:
        # Plan-only is a pure dry-run: nothing depends on a fetched
        # export, an authenticated upload, or a link reconciliation.
        # Auto-promote the related skip flags so an operator only
        # has to type the one flag they meant.
        args.no_fetch = True
        args.no_upload = True
        args.no_links = True
        args.no_anchor = True

    if args.no_anchor:
        args.no_upload = True
        args.no_links = True

    # ------------------------------------------------------------------ #
    # Credential-cache admin ops (since 2.3.0)                           #
    # ------------------------------------------------------------------ #
    # Both `--forget-credentials` and `--save-credentials --no-upload`
    # are self-contained admin ops -- they touch the OS keychain and
    # exit. They MUST short-circuit BEFORE the main try/except below,
    # because:
    #   1. They don't need the mapping yaml / state file / fetch / build.
    #   2. Calling build_payload on a brand-new project (no FSCS yet)
    #      would FileNotFoundError, the outer except would mask the
    #      real intent ("I just wanted to prime the keychain"), and
    #      the user would think the password wasn't saved -- which
    #      was the exact diagcomm-toolkit v1.19.3 bug. Don't repeat it.
    keyring_mod = _try_import_keyring(disabled=args.no_keyring)

    if args.forget_credentials:
        if args.no_keyring:
            # Don't tell the user to "install keyring" -- they
            # deliberately turned it off. Surface the actual conflict.
            print(
                "[doors_sync] ERROR: --no-keyring conflicts with "
                "--forget-credentials (nothing to delete from a backend "
                "you just disabled). Drop --no-keyring.",
                file=sys.stderr,
            )
            return 2
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

    if args.save_credentials and args.no_upload:
        # Cold-start admin op: no FSCS / no mapping needed. The agent
        # generates this command on a brand-new machine to prime the
        # OS keychain BEFORE running any pipeline command.
        if args.no_keyring:
            # Same anti-misleading-message rule as --forget-credentials
            # above: the user disabled the only backend we could write
            # to, so don't pretend `keyring` needs installing.
            print(
                "[doors_sync] ERROR: --no-keyring conflicts with "
                "--save-credentials (no backend to save into). Drop "
                "--no-keyring, or omit --save-credentials.",
                file=sys.stderr,
            )
            return 2
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

    try:
        mapping_path = Path(args.mapping)
        mapping = _load_yaml(mapping_path)
        module_uuid = _module_uuid(mapping, allow_placeholder=args.no_anchor)
        upload_cfg = mapping.get("upload") if isinstance(mapping.get("upload"), dict) else {}
        init_timeout = int(upload_cfg.get("init_timeout", args.init_timeout))
        upload_timeout = int(upload_cfg.get("upload_timeout", args.upload_timeout))

        # Resolve --user-nt once with env-var fallback so every MCP
        # call below sees a consistent identity (fetch / upload /
        # fresh fetch / update_links).
        user_nt = args.user_nt or os.environ.get("DOORS_USER_NT")

        # v1.17.0: load typed state up-front so we can both feed the
        # diff engine AND honour --force-reinsert before the build.
        state_path = Path(args.state)
        state = load_state(state_path)

        print("=" * 72)
        print("did-toolkit -> DOORS sync")
        print("=" * 72)
        print(f"mapping     : {mapping_path}")
        print(f"module_uuid : {module_uuid}")
        print(f"state file  : {state_path}")
        print(f"server      : {args.server_url}")
        print(f"no_fetch    : {args.no_fetch}   no_upload: {args.no_upload}   "
              f"no_links: {args.no_links}   no_anchor: {args.no_anchor}")
        print(f"plan_only   : {args.plan_only}   force_reinsert: {args.force_reinsert}")
        print("=" * 72)

        if args.force_reinsert:
            print(f"[doors_sync] --force-reinsert: wiping recorded landings for "
                  f"module {module_uuid!r} (all DIDs will classify as INSERT).")
            reset_module(state, module_uuid)
            # Persist the wipe immediately so a Ctrl+C between here and
            # the post-upload writeback can never leave the state with
            # stale landings the operator just told us to forget.
            save_state(state_path, state)

        if not args.no_anchor and not args.no_fetch:
            if not user_nt:
                raise ValueError(
                    "--user-nt (or $DOORS_USER_NT) required for fetch "
                    "(or pass --no-fetch)."
                )
            _fetch_export(
                module_uuid=module_uuid,
                user_nt=user_nt,
                server_url=args.server_url,
                init_timeout=init_timeout,
                call_timeout=args.call_timeout,
                refresh=args.refresh,
                out_path=Path(args.export),
            )

        result: BuildResult = build_payload(
            mapping_path=mapping_path,
            project_path=Path(args.project),
            export_path=Path(args.export),
            txt_22_path=Path(args.txt_22),
            txt_2e_path=Path(args.txt_2e),
            fscs_json_path=Path(args.fscs_json),
            out_dir=Path(args.out_dir),
            report_path=Path(args.report),
            services=("22", "2E"),
            require_anchors=not args.no_anchor,
            state=state,
            module_uuid=module_uuid,
            plan_only=args.plan_only,
        )

        # v1.17.0: surface the plan summary for every run so the
        # operator immediately sees what the state machine decided
        # before any upload happens.
        if result.action_plan is not None:
            print(f"[doors_sync] {format_plan_summary(result.action_plan)}")

        if args.plan_only:
            print()
            print(format_plan_table(result.action_plan)
                  if result.action_plan is not None
                  else "[doors_sync] (no plan available -- nothing to print)")
            print()
            print("[doors_sync] --plan-only: no xlsx written, no upload performed.")
            return 0

        for service, artefact in result.services.items():
            print(f"[doors_sync] built ${service}: {artefact.xlsx_path} "
                  f"({artefact.rows_written} rows; anchor={artefact.anchor.anchor_address or 'n/a'})")

        if args.no_upload:
            print("[doors_sync] --no-upload: built and reported, exiting "
                  "(state NOT updated -- nothing was actually pushed).")
            return 0

        if not user_nt:
            raise ValueError(
                "--user-nt (or $DOORS_USER_NT) required for upload "
                "(or pass --no-upload)."
            )

        password, pwd_source = _resolve_password(
            cli_password=args.password,
            user_nt=user_nt,
            keyring_mod=keyring_mod,
            allow_prompt=True,
        )
        if not password:
            raise ValueError(
                "no DOORS password available. Tried --password, "
                "$DOORS_PWD, OS keychain, interactive prompt -- all empty.\n"
                "  - First-time setup: rerun with `--password <pwd> "
                "--save-credentials --no-upload` to cache it in the OS "
                "keychain.\n"
                "  - CI / scripted: set $DOORS_PWD or pass `--password`.\n"
                "  - Build-only:    rerun with `--no-upload`."
            )
        print(f"[doors_sync] credentials: user_nt={user_nt!r} (source={pwd_source})")

        # Cache the resolved password BEFORE the upload runs. The
        # upload may legitimately fail (network, format, locked
        # module); we still want the password persisted so the next
        # run is back to zero-prompt. The auth-fail retry path
        # refreshes this entry separately if the user types a new
        # password.
        if args.save_credentials and pwd_source != "keyring":
            if args.no_keyring:
                # Don't surface the misleading "keyring not installed"
                # message from _keyring_set -- the user explicitly
                # asked us not to use it. Just say what we did (or
                # rather, didn't do).
                print(
                    "[doors_sync] WARN: --no-keyring suppresses "
                    "--save-credentials; password not cached this run.",
                    file=sys.stderr,
                )
            else:
                _keyring_set(keyring_mod, user_nt, password)

        # First service upload uses _upload_one_with_pwd_refresh so a
        # rejected cached password gets the one-shot prompt retry +
        # keychain refresh. Subsequent uploads (and the link upload
        # below) reuse the (possibly refreshed) password directly --
        # if the second/third upload fails with auth, the LDAP/AD
        # account state changed mid-run (rare); we surface the error
        # and stop rather than risk burning more attempts.
        first_done = False
        for service in ("22", "2E"):
            artefact = result.services.get(service)
            if not artefact or artefact.rows_written == 0:
                print(f"[doors_sync] no DIDs for ${service}; skipping upload of that workbook.")
                continue
            if not first_done:
                _result, password, pwd_source = _upload_one_with_pwd_refresh(
                    excel_path=artefact.xlsx_path,
                    module_uuid=module_uuid,
                    user_nt=user_nt,
                    password=password,
                    pwd_source=pwd_source,
                    server_url=args.server_url,
                    init_timeout=init_timeout,
                    upload_timeout=upload_timeout,
                    keyring_mod=keyring_mod,
                )
                first_done = True
            else:
                _upload_one(
                    excel_path=artefact.xlsx_path,
                    module_uuid=module_uuid,
                    user_nt=user_nt,
                    password=password,
                    server_url=args.server_url,
                    init_timeout=init_timeout,
                    upload_timeout=upload_timeout,
                )

        link_entries: List[LinkEntry] = []
        if not args.no_links:
            print("[doors_sync] re-fetching module to reconcile FS/CS AbsoluteNumbers ...")
            fresh = _fetch_export(
                module_uuid=module_uuid,
                user_nt=user_nt,
                server_url=args.server_url,
                init_timeout=init_timeout,
                call_timeout=args.call_timeout,
                refresh=True,
                out_path=Path(args.export),
            )
            rows = load_export(fresh)
            heading_field = (
                ((mapping.get("anchors") or {}).get("service_22") or {}).get(
                    "heading_field", "DescriptionOfRequirementRB"
                )
            )
            # v1.17.1: re-resolve anchors against the *fresh* export
            # so we can carve the row list into per-service slices.
            # Without this, a DID effective in BOTH services records
            # ONE landing for two services -> next UPDATE points at
            # the wrong physical row in DOORS. The resolution happens
            # under try/except so a transient anchor lookup failure
            # degrades gracefully to the v1.16.0 hex-only path
            # rather than blocking the whole upload.
            anchors_cfg_fresh = (
                mapping.get("anchors")
                if isinstance(mapping.get("anchors"), dict)
                else {}
            )
            service_ranges: Dict[str, tuple] = {}
            try:
                fresh_anchors = resolve_anchors(
                    rows, anchors_cfg_fresh, services=("22", "2E"),
                )
                # Map AbsoluteNumber -> row index so we can convert
                # AnchorMatch into [start, end) row ranges.
                abs_to_idx: Dict[str, int] = {}
                for i, r in enumerate(rows):
                    abs_no = str(r.get("AbsoluteNumber") or "")
                    if abs_no and abs_no not in abs_to_idx:
                        abs_to_idx[abs_no] = i
                anchored: List[tuple] = []
                for svc, am in fresh_anchors.items():
                    idx = abs_to_idx.get(am.anchor_address, -1)
                    if idx >= 0:
                        anchored.append((svc, idx))
                anchored.sort(key=lambda kv: kv[1])
                for i, (svc, idx) in enumerate(anchored):
                    start = idx + 1
                    end = anchored[i + 1][1] if i + 1 < len(anchored) else len(rows)
                    service_ranges[svc] = (start, end)
            except (LookupError, ValueError) as anchor_exc:
                print(
                    f"[doors_sync] WARN: per-service anchor resolution failed "
                    f"on the fresh export ({anchor_exc}); link reconcile will "
                    "fall back to hex-only matching (DIDs in BOTH services may "
                    "record only one landing).",
                    file=sys.stderr,
                )
            did_hex_to_heading = _collect_did_headings()
            link_entries = reconcile_did_rows(
                rows=rows,
                did_hex_to_heading=did_hex_to_heading,
                heading_field=heading_field,
                service_ranges=service_ranges or None,
            )
            # v1.17.1: when reconcile already stamped the service via
            # service_ranges, _annotate_service is a no-op (entries
            # keep their accurate "22" / "2E"). When ranges were
            # unavailable we still need it to convert hex-only
            # matches into the legacy "22+2E" union form.
            link_entries = _annotate_service(
                link_entries,
                fs22_dids=result.services.get("22").did_hexes if "22" in result.services else [],
                fs2e_dids=result.services.get("2E").did_hexes if "2E" in result.services else [],
            )
            _persist_link_entries(link_entries, DEFAULT_LINK_ENTRIES_JSON)
            print(f"[doors_sync]   reconciled {len(link_entries)} DID FS/CS pairs "
                  f"-> {DEFAULT_LINK_ENTRIES_JSON}")

            links_cfg = mapping.get("links") if isinstance(mapping.get("links"), dict) else {}
            if not links_cfg.get("enabled", True):
                print("[doors_sync] links.enabled=false in mapping; skipping link upload.")
            elif not str(links_cfg.get("link_module_uuid") or "").strip():
                print("[doors_sync] WARN: links.link_module_uuid is blank; skipping link upload "
                      "(entries persisted to disk for manual inspection).")
                return 1
            elif not link_entries:
                print("[doors_sync] WARN: zero FS/CS pairs reconciled; skipping link upload.")
                return 1
            else:
                rows_written = build_link_xlsx(
                    out_path=DEFAULT_LINK_XLSX,
                    entries=link_entries,
                    source_module_uuid=module_uuid,
                    target_module_uuid=module_uuid,
                    link_type=str(links_cfg.get("link_type") or "Realisation"),
                    link_module_uuid=str(links_cfg.get("link_module_uuid")),
                    direction=str(links_cfg.get("direction") or "cs_to_fs"),
                )
                print(f"[doors_sync] built link xlsx: {DEFAULT_LINK_XLSX} ({rows_written} rows)")
                # v2.3.1: route through the auth-retrying helper too,
                # so the corner case of "every per-service workbook
                # skipped (NOOP) but link upload still fires" gets
                # the same one-shot prompt + keychain refresh as a
                # service upload would. When the service uploads ran
                # first, password is already verified (or refreshed),
                # so the first attempt below succeeds and the helper
                # is a thin pass-through.
                link_result, password, pwd_source = _update_links_with_pwd_refresh(
                    excel_path=DEFAULT_LINK_XLSX,
                    module_uuid=str(links_cfg.get("link_module_uuid")),
                    user_nt=user_nt,
                    password=password,
                    pwd_source=pwd_source,
                    server_url=args.server_url,
                    init_timeout=init_timeout,
                    upload_timeout=upload_timeout,
                    keyring_mod=keyring_mod,
                )

        # v1.17.0: per-DID state writeback. Folds the action plan +
        # the freshly-fetched link entries into the typed
        # ``State`` (schema 3.0) so the next run's diff engine has
        # accurate (fs_abs, cs_abs, content_hash) for every landing.
        # A run with --no-links has no link_entries -> INSERTs can't
        # capture their fresh AbsoluteNumbers and the helper WARNs
        # per pair (UPDATEs / NOOPs are still recorded correctly).
        if result.action_plan is not None:
            n_landings = _writeback_state_post_upload(
                state=state,
                module_uuid=module_uuid,
                plan=result.action_plan,
                link_entries=link_entries,
            )
            save_state(state_path, state)
            print(f"[doors_sync] state updated: {state_path} "
                  f"({n_landings} landings recorded)")
        else:
            print(f"[doors_sync] WARN: no action plan produced; state NOT updated.",
                  file=sys.stderr)
        return 0

    except (FileNotFoundError, ValueError, LookupError, KeyError, RuntimeError) as exc:
        print(f"[doors_sync] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
