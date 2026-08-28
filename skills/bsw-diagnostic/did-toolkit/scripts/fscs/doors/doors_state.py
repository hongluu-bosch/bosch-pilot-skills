"""Per-DID DOORS upload state (v1.17.0, schema 3.0).

Replaces the v1.10.x aggregate-only state file (``schema_version: 2``)
with a per-DID landing record so the v1.17.0 INSERT / UPDATE / NOOP
state machine can decide what to push:

* **INSERT** — DID not yet recorded for this service; row gets
  ``Destination Object = anchor.anchor_address`` so DOORS lays it
  down sequentially after the anchor.
* **UPDATE** — DID is recorded but its content hash drifted; row
  gets ``Absolute Number = <recorded fs_abs/cs_abs>`` and
  ``Destination Object`` blank so DOORS overwrites in place.
* **NOOP**   — DID is recorded and the hash matches; row is
  omitted from the workbook entirely.
* **STALE**  — DID is recorded but no longer effective in fscs;
  WARN-only (DOORS-side delete is deferred to v1.18.x).

The state file is **per-workspace** (lives at
``<workspace>/state/doors_upload_state.json``, threaded by
``pipeline.py::run_doors_sync`` since v1.16.0). Multiple DOORS
modules can co-exist under ``modules.<uuid>`` so an operator who
targets two DOORS modules from the same workspace doesn't get
their state cross-contaminated.

Schema 3.0 shape::

    {
      "schema_version": "3.0",
      "modules": {
        "<DOORS module UUID>": {
          "last_uploaded_at": "2026-05-13T14:00:00+00:00",
          "dids": {
            "0xF190": {
              "service_22": {
                "fs_abs": "401",
                "cs_abs": "402",
                "content_hash": "sha256:abcd...",
                "last_uploaded_at": "2026-05-13T14:00:00+00:00"
              },
              "service_2e": {
                "fs_abs": null, "cs_abs": null,
                "content_hash": null, "last_uploaded_at": null
              }
            }
          }
        }
      }
    }

Reads of v1.10.x (``schema_version: 2``) state files succeed, but
the per-DID memory comes back empty — so every DID looks like
INSERT on the next run, which is the correct semantic ("no
prior knowledge"). The aggregate counters from the v2 file are
discarded; the v1.17.0 reconcile-after-upload step writes a fresh
v3 file in their place.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


SCHEMA_VERSION = "3.0"


# --------------------------------------------------------------------------- #
# pure dataclasses (Pydantic would be a hammer for the cracker; the           #
# load/save shape is closed and small enough to handcraft)                    #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ServiceLanding:
    """Where a single DID×service landed in DOORS on the last upload.

    All four fields are ``None`` when the DID has not yet been
    pushed for this service (e.g. service_2e never effective). A
    half-populated state (one of fs_abs/cs_abs missing) is also
    legal -- the diff engine treats it as STALE and demotes the
    row back to INSERT next run rather than risking a malformed
    UPDATE pointed at a phantom AbsoluteNumber.
    """

    fs_abs: Optional[str] = None
    cs_abs: Optional[str] = None
    content_hash: Optional[str] = None
    last_uploaded_at: Optional[str] = None

    @property
    def is_recorded(self) -> bool:
        """True iff *all four* fields are populated."""
        return bool(self.fs_abs and self.cs_abs
                    and self.content_hash and self.last_uploaded_at)


@dataclass
class DIDState:
    """Per-DID landing record across the two services."""

    service_22: ServiceLanding = field(default_factory=ServiceLanding)
    service_2e: ServiceLanding = field(default_factory=ServiceLanding)

    def for_service(self, service: str) -> ServiceLanding:
        key = service.lower()
        if key in ("22", "service_22"):
            return self.service_22
        if key in ("2e", "service_2e"):
            return self.service_2e
        raise KeyError(f"unknown service {service!r}; expected '22' or '2E'")

    def with_service(self, service: str, landing: ServiceLanding) -> "DIDState":
        key = service.lower()
        if key in ("22", "service_22"):
            return DIDState(service_22=landing, service_2e=self.service_2e)
        if key in ("2e", "service_2e"):
            return DIDState(service_22=self.service_22, service_2e=landing)
        raise KeyError(f"unknown service {service!r}; expected '22' or '2E'")


@dataclass
class ModuleState:
    """All per-DID landings for a single DOORS module."""

    last_uploaded_at: Optional[str] = None
    dids: Dict[str, DIDState] = field(default_factory=dict)

    def landing(self, did_hex: str, service: str) -> ServiceLanding:
        """Return the landing record for ``did_hex × service``.

        Returns an empty :class:`ServiceLanding` when no record
        exists; the diff engine treats that as INSERT.
        """
        record = self.dids.get(_normalise_hex(did_hex))
        if record is None:
            return ServiceLanding()
        return record.for_service(service)

    def remember(self, did_hex: str, service: str,
                 landing: ServiceLanding) -> None:
        """Persist the landing for ``did_hex × service`` in-place."""
        key = _normalise_hex(did_hex)
        existing = self.dids.get(key, DIDState())
        self.dids[key] = existing.with_service(service, landing)


@dataclass
class State:
    """Top-level state file."""

    schema_version: str = SCHEMA_VERSION
    modules: Dict[str, ModuleState] = field(default_factory=dict)

    def for_module(self, module_uuid: str) -> ModuleState:
        """Return (creating if needed) the per-module substate."""
        if module_uuid not in self.modules:
            self.modules[module_uuid] = ModuleState()
        return self.modules[module_uuid]


# --------------------------------------------------------------------------- #
# normalisation                                                               #
# --------------------------------------------------------------------------- #


def _normalise_hex(did_hex: str) -> str:
    """Canonicalise to ``0xUPPER`` form so '0xf190' / '0XF190' / 'f190'
    all collapse to ``0xF190`` -- prevents two state entries for the
    same DID just because the operator typed it in a different case."""
    if not isinstance(did_hex, str) or not did_hex.strip():
        raise ValueError(f"did_hex must be a non-empty string; got {did_hex!r}")
    s = did_hex.strip()
    bare = s[2:] if s[:2].lower() == "0x" else s
    return f"0x{bare.upper()}"


# --------------------------------------------------------------------------- #
# load / save / migrate                                                       #
# --------------------------------------------------------------------------- #


def load_state(path: Path) -> State:
    """Load the state file at ``path``.

    Behaviour:

    * Missing file -> empty :class:`State`. (Brand-new workspace
      or operator deleted it via ``--force-reinsert``.)
    * Empty / whitespace-only file -> empty :class:`State`. Matches
      the "config posture" we use elsewhere in the toolkit.
    * Invalid JSON -> :class:`ValueError` with the underlying
      decoder message + the file path. The operator hand-edits
      the file at their own risk.
    * Unknown ``schema_version`` -> :class:`ValueError`. We refuse
      to silently coerce a future-version file we don't understand.
    * ``schema_version: 2`` (v1.10.x aggregate-only) -> empty
      :class:`State` with a stderr advisory. The aggregate
      counters are discarded; per-DID memory comes back empty so
      every DID resolves to INSERT next run.
    * ``schema_version: "3.0"`` -> parsed verbatim into a
      :class:`State`.
    """
    if not path.is_file():
        return State()

    raw = path.read_text(encoding="utf-8-sig")
    if not raw.strip():
        return State()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"corrupt DOORS state file {path}: {exc.msg} "
            f"(line {exc.lineno}, column {exc.colno})"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"DOORS state file {path} must be a JSON object at top level; "
            f"got {type(data).__name__}"
        )

    schema_in = str(data.get("schema_version", "")).strip()
    if schema_in in ("2", "2.0"):
        # v1.10.x aggregate-only file. Print a one-line advisory
        # so the operator notices the per-DID layer just initialised
        # itself; emit it on stderr so it doesn't pollute STDOUT
        # contracts (e.g. --plan-only output).
        import sys
        print(
            f"[doors_state] migrating v1.10.x state file (schema={schema_in!r}) "
            f"to v1.17.0 (schema={SCHEMA_VERSION!r}). Per-DID memory starts empty; "
            f"every DID will resolve to INSERT until the next upload reconcile.",
            file=sys.stderr,
        )
        return State()

    if schema_in == SCHEMA_VERSION:
        return _parse_v3(data, path)

    raise ValueError(
        f"DOORS state file {path} has unknown schema_version {schema_in!r}; "
        f"this toolkit knows {SCHEMA_VERSION!r} (v1.17.0+) and v2.0 (v1.10.x). "
        f"Run `pipeline.py --phase doors --force-reinsert` to reset."
    )


def _parse_v3(data: Dict[str, Any], path: Path) -> State:
    state = State(schema_version=SCHEMA_VERSION)
    modules_raw = data.get("modules") or {}
    if not isinstance(modules_raw, dict):
        raise ValueError(f"{path}: 'modules' must be a JSON object")

    for module_uuid, mod_raw in modules_raw.items():
        if not isinstance(mod_raw, dict):
            raise ValueError(
                f"{path}: modules[{module_uuid!r}] must be a JSON object"
            )
        ms = ModuleState(
            last_uploaded_at=mod_raw.get("last_uploaded_at"),
        )
        dids_raw = mod_raw.get("dids") or {}
        if not isinstance(dids_raw, dict):
            raise ValueError(
                f"{path}: modules[{module_uuid!r}].dids must be a JSON object"
            )
        for did_hex, did_raw in dids_raw.items():
            if not isinstance(did_raw, dict):
                raise ValueError(
                    f"{path}: modules[{module_uuid!r}].dids[{did_hex!r}] "
                    f"must be a JSON object"
                )
            ms.dids[_normalise_hex(did_hex)] = DIDState(
                service_22=_parse_landing(did_raw.get("service_22")),
                service_2e=_parse_landing(did_raw.get("service_2e")),
            )
        state.modules[module_uuid] = ms

    return state


def _parse_landing(raw: Any) -> ServiceLanding:
    if raw is None:
        return ServiceLanding()
    if not isinstance(raw, dict):
        raise ValueError(f"service entry must be a JSON object; got {type(raw).__name__}")
    return ServiceLanding(
        fs_abs=_str_or_none(raw.get("fs_abs")),
        cs_abs=_str_or_none(raw.get("cs_abs")),
        content_hash=_str_or_none(raw.get("content_hash")),
        last_uploaded_at=_str_or_none(raw.get("last_uploaded_at")),
    )


def _str_or_none(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def save_state(path: Path, state: State) -> None:
    """Persist ``state`` to ``path`` atomically.

    Atomic semantics: write to a sibling ``.tmp`` file then
    ``os.replace`` into place so a half-written file can never be
    observed by a concurrent reader (e.g. a parallel pipeline run
    in the same workspace -- not a typical workflow, but cheap to
    defend against).
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "modules": {
            module_uuid: _serialise_module(ms)
            for module_uuid, ms in sorted(state.modules.items())
        },
    }

    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"

    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(text)
        os.replace(str(tmp_path), str(path))
    except Exception:
        # Best-effort cleanup; the os.replace above is the only
        # observable side effect on success.
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def _serialise_module(ms: ModuleState) -> Dict[str, Any]:
    return {
        "last_uploaded_at": ms.last_uploaded_at,
        "dids": {
            did_hex: _serialise_did(ds)
            for did_hex, ds in sorted(ms.dids.items())
        },
    }


def _serialise_did(ds: DIDState) -> Dict[str, Any]:
    return {
        "service_22": _serialise_landing(ds.service_22),
        "service_2e": _serialise_landing(ds.service_2e),
    }


def _serialise_landing(ll: ServiceLanding) -> Dict[str, Any]:
    return {
        "fs_abs": ll.fs_abs,
        "cs_abs": ll.cs_abs,
        "content_hash": ll.content_hash,
        "last_uploaded_at": ll.last_uploaded_at,
    }


# --------------------------------------------------------------------------- #
# helpers used by doors_sync after the post-upload reconcile                  #
# --------------------------------------------------------------------------- #


def reset_module(state: State, module_uuid: str) -> None:
    """Drop every per-DID record for ``module_uuid``.

    Called by ``--force-reinsert`` and by the diff engine when it
    detects ``module_uuid`` drift between the mapping yaml and the
    state file (operator re-pointed at a different DOORS module --
    we refuse to overwrite a foreign module's rows).
    """
    state.modules.pop(module_uuid, None)


def now_utc_iso() -> str:
    """RFC-3339 UTC timestamp with second precision -- the format
    we already use everywhere in the toolkit (`generated_at`,
    `created_date`, ...). Centralising avoids drift between modules."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


__all__ = [
    "SCHEMA_VERSION",
    "ServiceLanding",
    "DIDState",
    "ModuleState",
    "State",
    "load_state",
    "save_state",
    "reset_module",
    "now_utc_iso",
]
