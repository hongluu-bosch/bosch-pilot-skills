"""Unit tests for the OS-keychain credential cache in
``scripts/fscs/doors/doors_sync.py`` (since 2.3.0).

Covers:

* ``_try_import_keyring`` honouring ``--no-keyring``.
* ``_keyring_get / _keyring_set / _keyring_delete`` happy paths +
  graceful behaviour when ``keyring_mod is None``.
* ``_keyring_delete`` treats "no such entry" as benign success.
* ``_resolve_password`` 4-level fallback ordering (CLI > env >
  keyring > prompt).
* ``_looks_like_auth_failure`` matching English + Chinese tokens.
* ``main()`` admin-op short-circuits:
    - ``--forget-credentials`` (success / missing --user-nt / no entry)
    - ``--save-credentials --no-upload`` cold-start prime
      (success / missing --password / missing --user-nt)
    - ``--no-keyring`` flag actually disables the keyring import.

The cold-start short-circuit is the bug-class that diagcomm-toolkit
v1.19.3 fixed (silent failure when the cache-priming command tried to
do the full pipeline first). These tests pin the behaviour: the admin
ops MUST exit before reading mapping yaml / FSCS / state -- they
should work on a brand-new machine with nothing else on disk.
"""

from __future__ import annotations

import sys
import types
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import pytest

from fscs.doors import doors_sync


# --------------------------------------------------------------------- #
# Fake keyring backend                                                   #
# --------------------------------------------------------------------- #


class FakeKeyring:
    """In-memory stand-in for the ``keyring`` module.

    Records every call so tests can assert ordering. Behaves like a
    well-formed backend: ``get_password`` returns ``None`` for missing
    entries (the cross-backend invariant ``_keyring_delete`` relies
    on); ``delete_password`` raises if asked to drop a missing entry
    (mirroring real backend variance, which is why we always probe
    with ``get_password`` first).
    """

    def __init__(self) -> None:
        self.store: Dict[Tuple[str, str], str] = {}
        self.calls: List[Tuple[str, Tuple[Any, ...]]] = []

    def get_password(self, service: str, username: str) -> Optional[str]:
        self.calls.append(("get", (service, username)))
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.calls.append(("set", (service, username, password)))
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.calls.append(("delete", (service, username)))
        if (service, username) not in self.store:
            raise Exception("no such entry")
        del self.store[(service, username)]


@pytest.fixture
def fake_keyring() -> FakeKeyring:
    return FakeKeyring()


# --------------------------------------------------------------------- #
# _try_import_keyring                                                    #
# --------------------------------------------------------------------- #


def test_try_import_keyring_disabled_returns_none() -> None:
    assert doors_sync._try_import_keyring(disabled=True) is None


def test_try_import_keyring_returns_module_when_available() -> None:
    mod = doors_sync._try_import_keyring(disabled=False)
    # In CI without keyring installed this could return None -- accept
    # both, but in our pinned env keyring IS installed so prefer the
    # module. Either way the function must never raise.
    assert mod is None or hasattr(mod, "get_password")


def test_try_import_keyring_returns_none_when_missing(monkeypatch) -> None:
    # Simulate `import keyring` raising ImportError (host without the
    # optional dep).
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _fake_import(name, *a, **kw):
        if name == "keyring":
            raise ImportError("no keyring")
        return real_import(name, *a, **kw)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    assert doors_sync._try_import_keyring(disabled=False) is None


# --------------------------------------------------------------------- #
# _keyring_get / _keyring_set / _keyring_delete                          #
# --------------------------------------------------------------------- #


def test_keyring_get_returns_none_when_module_absent() -> None:
    assert doors_sync._keyring_get(None, "nt123") is None


def test_keyring_get_returns_none_for_empty_user() -> None:
    fake = FakeKeyring()
    fake.store[(doors_sync.KEYRING_SERVICE, "nt123")] = "secret"
    assert doors_sync._keyring_get(fake, "") is None


def test_keyring_get_returns_stored_password(fake_keyring: FakeKeyring) -> None:
    fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt123")] = "secret"
    assert doors_sync._keyring_get(fake_keyring, "nt123") == "secret"


def test_keyring_get_swallows_backend_exception(capsys) -> None:
    class BoomKeyring:
        def get_password(self, *_a, **_k):
            raise RuntimeError("backend dead")

    assert doors_sync._keyring_get(BoomKeyring(), "nt123") is None
    err = capsys.readouterr().err
    assert "WARN: keyring lookup failed" in err
    assert "backend dead" in err


def test_keyring_set_writes_to_backend(fake_keyring: FakeKeyring, capsys) -> None:
    ok = doors_sync._keyring_set(fake_keyring, "nt123", "hunter2")
    assert ok is True
    assert fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt123")] == "hunter2"
    out = capsys.readouterr().out
    assert "saved DOORS password" in out
    assert "did-toolkit:doors" in out


def test_keyring_set_says_updated_on_overwrite(fake_keyring: FakeKeyring, capsys) -> None:
    fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt123")] = "old"
    ok = doors_sync._keyring_set(fake_keyring, "nt123", "new")
    assert ok is True
    out = capsys.readouterr().out
    assert "updated DOORS password" in out


def test_keyring_set_warns_when_module_missing(capsys) -> None:
    ok = doors_sync._keyring_set(None, "nt123", "hunter2")
    assert ok is False
    err = capsys.readouterr().err
    assert "`keyring` not installed" in err


def test_keyring_set_no_op_for_empty_input(fake_keyring: FakeKeyring) -> None:
    assert doors_sync._keyring_set(fake_keyring, "", "secret") is False
    assert doors_sync._keyring_set(fake_keyring, "nt123", "") is False
    assert fake_keyring.store == {}


def test_keyring_delete_drops_existing_entry(fake_keyring: FakeKeyring, capsys) -> None:
    fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt123")] = "secret"
    ok = doors_sync._keyring_delete(fake_keyring, "nt123")
    assert ok is True
    assert (doors_sync.KEYRING_SERVICE, "nt123") not in fake_keyring.store
    out = capsys.readouterr().out
    assert "forgot DOORS password" in out


def test_keyring_delete_treats_missing_as_success(fake_keyring: FakeKeyring, capsys) -> None:
    """Cross-backend invariant: 'no such entry' is benign success.

    The user asked for the entry to be gone; it is gone (it never
    existed). ``_keyring_delete`` MUST NOT call ``delete_password``
    when the probe returns None -- backends raise inconsistent
    error messages and we don't want to surface those as failures.
    """
    ok = doors_sync._keyring_delete(fake_keyring, "nt123")
    assert ok is True
    out = capsys.readouterr().out
    assert "no keychain entry" in out
    # Crucially: only the probe ran, not delete_password.
    assert all(call[0] != "delete" for call in fake_keyring.calls)


def test_keyring_delete_warns_when_module_missing(capsys) -> None:
    ok = doors_sync._keyring_delete(None, "nt123")
    assert ok is False
    err = capsys.readouterr().err
    assert "`keyring` not installed" in err


# --------------------------------------------------------------------- #
# _resolve_password 4-level fallback                                     #
# --------------------------------------------------------------------- #


def test_resolve_password_cli_wins_over_everything(
    fake_keyring: FakeKeyring, monkeypatch
) -> None:
    monkeypatch.setenv("DOORS_PWD", "from_env")
    fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt123")] = "from_keyring"
    pwd, source = doors_sync._resolve_password(
        cli_password="from_cli",
        user_nt="nt123",
        keyring_mod=fake_keyring,
        allow_prompt=True,
    )
    assert (pwd, source) == ("from_cli", "cli")


def test_resolve_password_env_wins_over_keyring(
    fake_keyring: FakeKeyring, monkeypatch
) -> None:
    monkeypatch.setenv("DOORS_PWD", "from_env")
    fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt123")] = "from_keyring"
    pwd, source = doors_sync._resolve_password(
        cli_password=None,
        user_nt="nt123",
        keyring_mod=fake_keyring,
        allow_prompt=True,
    )
    assert (pwd, source) == ("from_env", "env")


def test_resolve_password_keyring_wins_over_prompt(
    fake_keyring: FakeKeyring, monkeypatch
) -> None:
    monkeypatch.delenv("DOORS_PWD", raising=False)
    fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt123")] = "from_keyring"
    pwd, source = doors_sync._resolve_password(
        cli_password=None,
        user_nt="nt123",
        keyring_mod=fake_keyring,
        allow_prompt=True,
    )
    assert (pwd, source) == ("from_keyring", "keyring")


def test_resolve_password_falls_through_to_prompt(
    fake_keyring: FakeKeyring, monkeypatch
) -> None:
    monkeypatch.delenv("DOORS_PWD", raising=False)
    # Empty keyring + TTY available + prompt allowed.
    with patch.object(doors_sync.sys.stdin, "isatty", return_value=True), \
         patch.object(doors_sync.getpass, "getpass", return_value="typed_pwd"):
        pwd, source = doors_sync._resolve_password(
            cli_password=None,
            user_nt="nt123",
            keyring_mod=fake_keyring,
            allow_prompt=True,
        )
    assert (pwd, source) == ("typed_pwd", "prompt")


def test_resolve_password_returns_none_when_no_tty(
    fake_keyring: FakeKeyring, monkeypatch
) -> None:
    monkeypatch.delenv("DOORS_PWD", raising=False)
    with patch.object(doors_sync.sys.stdin, "isatty", return_value=False):
        pwd, source = doors_sync._resolve_password(
            cli_password=None,
            user_nt="nt123",
            keyring_mod=fake_keyring,
            allow_prompt=True,
        )
    assert (pwd, source) == (None, "none")


def test_resolve_password_returns_none_when_prompt_disallowed(
    fake_keyring: FakeKeyring, monkeypatch
) -> None:
    monkeypatch.delenv("DOORS_PWD", raising=False)
    pwd, source = doors_sync._resolve_password(
        cli_password=None,
        user_nt="nt123",
        keyring_mod=fake_keyring,
        allow_prompt=False,
    )
    assert (pwd, source) == (None, "none")


# --------------------------------------------------------------------- #
# _looks_like_auth_failure                                               #
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("msg", [
    "401 Unauthorized",
    "HTTP 403 forbidden",
    "Invalid credentials",
    "authentication failed",
    "login failed",
    "wrong password",
    "Bad NT password",
    "用户名或密码错误",
    "认证失败",
    "密码错误",
])
def test_looks_like_auth_failure_positive(msg: str) -> None:
    assert doors_sync._looks_like_auth_failure(msg) is True


@pytest.mark.parametrize("msg", [
    "",
    "module locked",
    "format rejected",
    "Connection refused",
    "Internal Server Error",
    "Cannot find required Object",
    "timeout after 180s",
])
def test_looks_like_auth_failure_negative(msg: str) -> None:
    assert doors_sync._looks_like_auth_failure(msg) is False


# --------------------------------------------------------------------- #
# main() admin-op short-circuits                                         #
# --------------------------------------------------------------------- #
#
# These tests pin the v2.3.0 contract (mirrored from diagcomm-toolkit
# v1.19.3): the cache-priming / cache-clearing commands MUST exit
# before reading mapping.yaml / FSCS / project.json. They run on a
# brand-new project where none of those files exist yet.


def _patch_keyring(monkeypatch, fake_keyring: FakeKeyring) -> None:
    """Make ``_try_import_keyring`` return our fake instead of trying
    a real ``import keyring``."""
    monkeypatch.setattr(
        doors_sync, "_try_import_keyring",
        lambda disabled: None if disabled else fake_keyring,
    )


def test_forget_credentials_short_circuits_cold_start(
    monkeypatch, fake_keyring: FakeKeyring, capsys
) -> None:
    _patch_keyring(monkeypatch, fake_keyring)
    fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt123")] = "secret"

    rc = doors_sync.main([
        "--user-nt", "nt123",
        "--forget-credentials",
        # Deliberately NO --mapping / --project / --state -- if the
        # short-circuit isn't tight, argparse defaults point at
        # missing files and the test would fail.
    ])
    assert rc == 0
    assert (doors_sync.KEYRING_SERVICE, "nt123") not in fake_keyring.store
    out = capsys.readouterr().out
    assert "forgot DOORS password" in out


def test_forget_credentials_no_op_when_no_entry(
    monkeypatch, fake_keyring: FakeKeyring
) -> None:
    _patch_keyring(monkeypatch, fake_keyring)
    rc = doors_sync.main(["--user-nt", "nt123", "--forget-credentials"])
    assert rc == 0  # benign; nothing to forget is success


def test_forget_credentials_rejects_missing_user_nt(
    monkeypatch, fake_keyring: FakeKeyring, capsys
) -> None:
    _patch_keyring(monkeypatch, fake_keyring)
    monkeypatch.delenv("DOORS_USER_NT", raising=False)
    rc = doors_sync.main(["--forget-credentials"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--forget-credentials requires --user-nt" in err


def test_forget_credentials_accepts_env_user_nt(
    monkeypatch, fake_keyring: FakeKeyring
) -> None:
    _patch_keyring(monkeypatch, fake_keyring)
    monkeypatch.setenv("DOORS_USER_NT", "nt_env")
    fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt_env")] = "secret"
    rc = doors_sync.main(["--forget-credentials"])
    assert rc == 0
    assert (doors_sync.KEYRING_SERVICE, "nt_env") not in fake_keyring.store


def test_save_credentials_no_upload_primes_keychain(
    monkeypatch, fake_keyring: FakeKeyring, capsys
) -> None:
    _patch_keyring(monkeypatch, fake_keyring)
    rc = doors_sync.main([
        "--user-nt", "nt123",
        "--password", "hunter2",
        "--save-credentials",
        "--no-upload",
    ])
    assert rc == 0
    assert fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt123")] == "hunter2"
    out = capsys.readouterr().out
    assert "credential cache primed" in out


def test_save_credentials_no_upload_accepts_env_vars(
    monkeypatch, fake_keyring: FakeKeyring
) -> None:
    _patch_keyring(monkeypatch, fake_keyring)
    monkeypatch.setenv("DOORS_USER_NT", "nt_env")
    monkeypatch.setenv("DOORS_PWD", "env_secret")
    rc = doors_sync.main([
        "--save-credentials",
        "--no-upload",
    ])
    assert rc == 0
    assert fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt_env")] == "env_secret"


def test_save_credentials_no_upload_rejects_missing_password(
    monkeypatch, fake_keyring: FakeKeyring, capsys
) -> None:
    _patch_keyring(monkeypatch, fake_keyring)
    monkeypatch.delenv("DOORS_PWD", raising=False)
    rc = doors_sync.main([
        "--user-nt", "nt123",
        "--save-credentials",
        "--no-upload",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "needs both --user-nt and --password" in err


def test_save_credentials_no_upload_rejects_missing_user_nt(
    monkeypatch, fake_keyring: FakeKeyring, capsys
) -> None:
    _patch_keyring(monkeypatch, fake_keyring)
    monkeypatch.delenv("DOORS_USER_NT", raising=False)
    rc = doors_sync.main([
        "--password", "hunter2",
        "--save-credentials",
        "--no-upload",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "needs both --user-nt and --password" in err


def test_no_keyring_conflicts_with_save_credentials_admin_op(
    monkeypatch, capsys
) -> None:
    """Regression test (review fix): when the user passes both
    `--no-keyring` and `--save-credentials --no-upload`, the cold-
    start short-circuit must surface the *actual* conflict, not the
    misleading 'keyring not installed -- run pip install' message
    that `_keyring_set(None, ...)` would otherwise emit. The user
    deliberately disabled the only backend; telling them to install
    one is wrong advice.
    """
    rc = doors_sync.main([
        "--user-nt", "nt123",
        "--password", "hunter2",
        "--save-credentials",
        "--no-upload",
        "--no-keyring",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--no-keyring conflicts with --save-credentials" in err
    # Crucially: no misleading "install keyring" hint.
    assert "not installed" not in err
    assert "pip install" not in err


def test_no_keyring_conflicts_with_forget_credentials(
    monkeypatch, capsys
) -> None:
    """Same anti-misleading-message rule as the save-credentials
    path: --no-keyring + --forget-credentials should report the
    conflict, not pretend `keyring` needs installing."""
    rc = doors_sync.main([
        "--user-nt", "nt123",
        "--forget-credentials",
        "--no-keyring",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--no-keyring conflicts with --forget-credentials" in err
    assert "not installed" not in err
    assert "pip install" not in err


# --------------------------------------------------------------------- #
# _upload_one_with_pwd_refresh                                          #
# --------------------------------------------------------------------- #
#
# These tests mock upload_module + getpass to exhaustively cover the
# auth-retry branches. The helper is the most behaviour-critical new
# code in 2.3.0 (it touches the OS keychain and gates an LDAP/AD
# account against lock-out), so every branch needs a pinned test.


from pathlib import Path  # noqa: E402  (placed here for locality)


@pytest.fixture
def upload_call_log() -> List[Dict[str, Any]]:
    """Per-test list that captures every (excel_path, password) pair
    `upload_module` was called with -- lets us assert on retry behaviour
    without having to inspect the real (mocked) MCP transport."""
    return []


def _make_upload(
    responses: List[Dict[str, Any]],
    log: List[Dict[str, Any]],
):
    """Build a fake `upload_module` that returns ``responses`` in
    order and records each call's password into ``log``. Failing the
    test if more calls happen than responses are provided keeps the
    one-shot retry contract honest -- if a refactor introduces a
    silent loop, a test using this fake will IndexError immediately
    rather than silently exceed the LDAP attempt budget."""
    iterator = iter(responses)

    def _fake(*, excel_path, module_uuid, user_nt, password,
              server_url, init_timeout, upload_timeout):
        log.append({"excel": str(excel_path), "password": password})
        return next(iterator)

    return _fake


def test_upload_with_pwd_refresh_happy_path(
    monkeypatch, fake_keyring: FakeKeyring, upload_call_log
) -> None:
    monkeypatch.setattr(
        doors_sync, "upload_module",
        _make_upload([{"code": 0, "data": "ok"}], upload_call_log),
    )
    result, pwd, source = doors_sync._upload_one_with_pwd_refresh(
        excel_path=Path("foo.xlsx"),
        module_uuid="UUID",
        user_nt="nt1",
        password="cached_pwd",
        pwd_source="keyring",
        server_url="http://x",
        init_timeout=1,
        upload_timeout=1,
        keyring_mod=fake_keyring,
    )
    assert result["code"] == 0
    assert (pwd, source) == ("cached_pwd", "keyring")
    assert len(upload_call_log) == 1  # zero retries on success
    assert fake_keyring.store == {}   # keychain untouched on first-try success


def test_upload_with_pwd_refresh_non_auth_failure_raises(
    monkeypatch, fake_keyring: FakeKeyring, upload_call_log
) -> None:
    """Non-auth failure (network / format / locked module) must
    propagate as RuntimeError without retrying -- those problems
    aren't fixed by typing a new password and the helper must NOT
    silently mask them."""
    monkeypatch.setattr(
        doors_sync, "upload_module",
        _make_upload(
            [{"code": 1, "message": "Connection refused"}], upload_call_log,
        ),
    )
    with pytest.raises(RuntimeError, match="Connection refused"):
        doors_sync._upload_one_with_pwd_refresh(
            excel_path=Path("foo.xlsx"),
            module_uuid="UUID",
            user_nt="nt1",
            password="cached_pwd",
            pwd_source="keyring",
            server_url="http://x",
            init_timeout=1,
            upload_timeout=1,
            keyring_mod=fake_keyring,
        )
    assert len(upload_call_log) == 1
    assert fake_keyring.store == {}


def test_upload_with_pwd_refresh_prompt_source_no_retry(
    monkeypatch, fake_keyring: FakeKeyring, upload_call_log, capsys
) -> None:
    """source='prompt' MUST NOT retry on auth failure -- the user
    just typed it; another prompt won't help and risks NT lock-out."""
    monkeypatch.setattr(
        doors_sync, "upload_module",
        _make_upload([{"code": 1, "message": "401 Unauthorized"}], upload_call_log),
    )
    with pytest.raises(RuntimeError, match="401 Unauthorized"):
        doors_sync._upload_one_with_pwd_refresh(
            excel_path=Path("foo.xlsx"),
            module_uuid="UUID",
            user_nt="nt1",
            password="typed_pwd",
            pwd_source="prompt",
            server_url="http://x",
            init_timeout=1,
            upload_timeout=1,
            keyring_mod=fake_keyring,
        )
    assert len(upload_call_log) == 1
    err = capsys.readouterr().err
    assert "Not retrying" in err
    assert "NT account" in err


def test_upload_with_pwd_refresh_cli_source_no_retry(
    monkeypatch, fake_keyring: FakeKeyring, upload_call_log, capsys
) -> None:
    """source='cli' MUST NOT auto-prompt -- the user passed an
    explicit value, respect that and surface the failure."""
    monkeypatch.setattr(
        doors_sync, "upload_module",
        _make_upload([{"code": 1, "message": "Invalid credentials"}], upload_call_log),
    )
    with pytest.raises(RuntimeError, match="Invalid credentials"):
        doors_sync._upload_one_with_pwd_refresh(
            excel_path=Path("foo.xlsx"),
            module_uuid="UUID",
            user_nt="nt1",
            password="cli_pwd",
            pwd_source="cli",
            server_url="http://x",
            init_timeout=1,
            upload_timeout=1,
            keyring_mod=fake_keyring,
        )
    assert len(upload_call_log) == 1
    err = capsys.readouterr().err
    assert "supplied via --password" in err


def test_upload_with_pwd_refresh_no_tty_no_retry(
    monkeypatch, fake_keyring: FakeKeyring, upload_call_log, capsys
) -> None:
    """source='keyring' but no TTY (CI / piped shell) -- can't
    prompt, so explain how to refresh manually and exit. Crucially,
    keyring is NOT touched."""
    fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt1")] = "cached_pwd"
    monkeypatch.setattr(
        doors_sync, "upload_module",
        _make_upload([{"code": 1, "message": "401 Unauthorized"}], upload_call_log),
    )
    with patch.object(doors_sync.sys.stdin, "isatty", return_value=False):
        with pytest.raises(RuntimeError, match="401 Unauthorized"):
            doors_sync._upload_one_with_pwd_refresh(
                excel_path=Path("foo.xlsx"),
                module_uuid="UUID",
                user_nt="nt1",
                password="cached_pwd",
                pwd_source="keyring",
                server_url="http://x",
                init_timeout=1,
                upload_timeout=1,
                keyring_mod=fake_keyring,
            )
    assert len(upload_call_log) == 1
    err = capsys.readouterr().err
    assert "no TTY" in err
    assert "--save-credentials" in err
    # CRUCIAL: stale keychain stays put -- we don't second-guess it
    # without a fresh password from the operator.
    assert fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt1")] == "cached_pwd"


def test_upload_with_pwd_refresh_keyring_then_prompt_succeeds(
    monkeypatch, fake_keyring: FakeKeyring, upload_call_log, capsys
) -> None:
    """The headline case: cached keyring password is stale, operator
    types a fresh one, retry succeeds, keychain is silently refreshed
    so the next run is back to zero-prompt."""
    fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt1")] = "stale_pwd"
    monkeypatch.setattr(
        doors_sync, "upload_module",
        _make_upload(
            [
                {"code": 1, "message": "Unauthorized"},   # cached fails
                {"code": 0, "data": "ok"},                # prompt succeeds
            ],
            upload_call_log,
        ),
    )
    with patch.object(doors_sync.sys.stdin, "isatty", return_value=True), \
         patch.object(doors_sync.getpass, "getpass", return_value="fresh_pwd"):
        result, pwd, source = doors_sync._upload_one_with_pwd_refresh(
            excel_path=Path("foo.xlsx"),
            module_uuid="UUID",
            user_nt="nt1",
            password="stale_pwd",
            pwd_source="keyring",
            server_url="http://x",
            init_timeout=1,
            upload_timeout=1,
            keyring_mod=fake_keyring,
        )
    assert result["code"] == 0
    assert pwd == "fresh_pwd"
    assert source == "prompt-refresh"
    # Exactly two upload attempts -- the LDAP-safe upper bound.
    assert len(upload_call_log) == 2
    assert upload_call_log[0]["password"] == "stale_pwd"
    assert upload_call_log[1]["password"] == "fresh_pwd"
    # Keychain refreshed silently with the new password.
    assert fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt1")] == "fresh_pwd"


def test_upload_with_pwd_refresh_keyring_then_prompt_also_fails(
    monkeypatch, fake_keyring: FakeKeyring, upload_call_log, capsys
) -> None:
    """Cached fails, prompt also fails -- raise. Crucially, the
    keychain is NOT touched (unlike the success path which refreshes
    it). The operator has to log into DOORS Web to fix the
    underlying problem before another run."""
    fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt1")] = "stale_pwd"
    monkeypatch.setattr(
        doors_sync, "upload_module",
        _make_upload(
            [
                {"code": 1, "message": "Unauthorized"},
                {"code": 1, "message": "401 still wrong"},
            ],
            upload_call_log,
        ),
    )
    with patch.object(doors_sync.sys.stdin, "isatty", return_value=True), \
         patch.object(doors_sync.getpass, "getpass", return_value="also_wrong"):
        with pytest.raises(RuntimeError, match="401 still wrong"):
            doors_sync._upload_one_with_pwd_refresh(
                excel_path=Path("foo.xlsx"),
                module_uuid="UUID",
                user_nt="nt1",
                password="stale_pwd",
                pwd_source="keyring",
                server_url="http://x",
                init_timeout=1,
                upload_timeout=1,
                keyring_mod=fake_keyring,
            )
    assert len(upload_call_log) == 2
    # Critical safety property: keychain is NOT updated when the
    # prompt-supplied password is also rejected.
    assert fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt1")] == "stale_pwd"
    err = capsys.readouterr().err
    assert "new password was also rejected" in err
    assert "NT account locked" in err


def test_upload_with_pwd_refresh_empty_prompt_no_retry(
    monkeypatch, fake_keyring: FakeKeyring, upload_call_log
) -> None:
    """Operator hits enter at the prompt -- treat as cancel, not
    retry. Don't waste an LDAP attempt on an empty password."""
    fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt1")] = "stale_pwd"
    monkeypatch.setattr(
        doors_sync, "upload_module",
        _make_upload([{"code": 1, "message": "Unauthorized"}], upload_call_log),
    )
    with patch.object(doors_sync.sys.stdin, "isatty", return_value=True), \
         patch.object(doors_sync.getpass, "getpass", return_value=""):
        with pytest.raises(RuntimeError, match="Unauthorized"):
            doors_sync._upload_one_with_pwd_refresh(
                excel_path=Path("foo.xlsx"),
                module_uuid="UUID",
                user_nt="nt1",
                password="stale_pwd",
                pwd_source="keyring",
                server_url="http://x",
                init_timeout=1,
                upload_timeout=1,
                keyring_mod=fake_keyring,
            )
    assert len(upload_call_log) == 1  # no second attempt
    assert fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt1")] == "stale_pwd"


def test_upload_with_pwd_refresh_ctrl_c_at_prompt_no_retry(
    monkeypatch, fake_keyring: FakeKeyring, upload_call_log, capsys
) -> None:
    """Operator hits Ctrl+C at the prompt -- abort cleanly, raise
    the original auth failure, do NOT touch the keychain."""
    fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt1")] = "stale_pwd"
    monkeypatch.setattr(
        doors_sync, "upload_module",
        _make_upload([{"code": 1, "message": "Unauthorized"}], upload_call_log),
    )
    def _ctrl_c(prompt):
        raise KeyboardInterrupt()
    with patch.object(doors_sync.sys.stdin, "isatty", return_value=True), \
         patch.object(doors_sync.getpass, "getpass", _ctrl_c):
        with pytest.raises(RuntimeError, match="Unauthorized"):
            doors_sync._upload_one_with_pwd_refresh(
                excel_path=Path("foo.xlsx"),
                module_uuid="UUID",
                user_nt="nt1",
                password="stale_pwd",
                pwd_source="keyring",
                server_url="http://x",
                init_timeout=1,
                upload_timeout=1,
                keyring_mod=fake_keyring,
            )
    assert len(upload_call_log) == 1
    assert fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt1")] == "stale_pwd"
    err = capsys.readouterr().err
    assert "aborted by user" in err


def test_update_links_with_pwd_refresh_happy_path(
    monkeypatch, fake_keyring: FakeKeyring
) -> None:
    """v2.3.1 regression: link upload also goes through the retry
    helper so the "all-NOOP + still-need-link-upload" corner case
    (everything else skipped, link is the first auth-bearing call)
    still gets the one-shot prompt + keychain-refresh path."""
    log: List[Dict[str, Any]] = []

    def _fake_update_links(*, excel_path, user_nt, password, module_uuid,
                           server_url, init_timeout, upload_timeout):
        log.append({"excel": str(excel_path), "password": password})
        return {"code": 0, "data": "ok"}

    monkeypatch.setattr(doors_sync, "update_links", _fake_update_links)
    result, pwd, source = doors_sync._update_links_with_pwd_refresh(
        excel_path=Path("links.xlsx"),
        module_uuid="LINK-UUID",
        user_nt="nt1",
        password="cached_pwd",
        pwd_source="keyring",
        server_url="http://x",
        init_timeout=1,
        upload_timeout=1,
        keyring_mod=fake_keyring,
    )
    assert result["code"] == 0
    assert (pwd, source) == ("cached_pwd", "keyring")
    assert len(log) == 1


def test_update_links_with_pwd_refresh_stale_keychain_then_retry(
    monkeypatch, fake_keyring: FakeKeyring
) -> None:
    """The motivating case for the v2.3.1 link-upload retry path:
    every per-service upload skipped (rows_written == 0 across the
    board) means the link upload is the first call that exercises
    the password. If the keychain is stale at that one site, the
    operator must still get the one-shot prompt instead of a hard
    RuntimeError."""
    fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt1")] = "stale_pwd"
    log: List[Dict[str, Any]] = []
    responses = iter([
        {"code": 1, "message": "401 Unauthorized"},
        {"code": 0, "data": "ok"},
    ])

    def _fake_update_links(*, excel_path, user_nt, password, module_uuid,
                           server_url, init_timeout, upload_timeout):
        log.append({"password": password})
        return next(responses)

    monkeypatch.setattr(doors_sync, "update_links", _fake_update_links)
    with patch.object(doors_sync.sys.stdin, "isatty", return_value=True), \
         patch.object(doors_sync.getpass, "getpass", return_value="fresh_pwd"):
        result, pwd, source = doors_sync._update_links_with_pwd_refresh(
            excel_path=Path("links.xlsx"),
            module_uuid="LINK-UUID",
            user_nt="nt1",
            password="stale_pwd",
            pwd_source="keyring",
            server_url="http://x",
            init_timeout=1,
            upload_timeout=1,
            keyring_mod=fake_keyring,
        )
    assert result["code"] == 0
    assert pwd == "fresh_pwd"
    assert source == "prompt-refresh"
    assert len(log) == 2
    assert log[0]["password"] == "stale_pwd"
    assert log[1]["password"] == "fresh_pwd"
    # Keychain refreshed silently after retry success.
    assert fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt1")] == "fresh_pwd"


def test_upload_with_pwd_refresh_env_source_can_retry(
    monkeypatch, fake_keyring: FakeKeyring, upload_call_log
) -> None:
    """source='env' (e.g. $DOORS_PWD set in CI but stale) is also
    eligible for the retry path -- it's a 'cached' source from the
    helper's perspective. Pin this so a refactor that special-cases
    only 'keyring' as retry-eligible breaks the test loudly."""
    monkeypatch.setattr(
        doors_sync, "upload_module",
        _make_upload(
            [
                {"code": 1, "message": "Unauthorized"},
                {"code": 0, "data": "ok"},
            ],
            upload_call_log,
        ),
    )
    with patch.object(doors_sync.sys.stdin, "isatty", return_value=True), \
         patch.object(doors_sync.getpass, "getpass", return_value="fresh_pwd"):
        result, pwd, source = doors_sync._upload_one_with_pwd_refresh(
            excel_path=Path("foo.xlsx"),
            module_uuid="UUID",
            user_nt="nt1",
            password="stale_env_pwd",
            pwd_source="env",
            server_url="http://x",
            init_timeout=1,
            upload_timeout=1,
            keyring_mod=fake_keyring,
        )
    assert result["code"] == 0
    assert pwd == "fresh_pwd"
    assert source == "prompt-refresh"
    # env-sourced run also writes the fresh password into keychain so
    # next interactive run benefits even if the env var wasn't set.
    assert fake_keyring.store[(doors_sync.KEYRING_SERVICE, "nt1")] == "fresh_pwd"
