"""DOORS upload diff engine (v1.17.0).

Pure function ``compute_action_plan`` that takes a snapshot of the
current FSCS render (per-DID×service content hashes) and the
previous-upload state (``doors_state.State``), and returns a
classification of every DID×service pair into one of four
buckets:

* **INSERT** — DID×service is not in the state for the active
  module. The row will land in the workbook with
  ``Destination Object = anchor.anchor_address`` and
  ``Absolute Number`` blank; DOORS appends after the anchor.
* **UPDATE** — DID×service is in the state but the rendered
  content hash drifted. The row will land in the workbook with
  ``Destination Object`` blank and
  ``Absolute Number = <recorded fs_abs / cs_abs>``; DOORS
  overwrites the existing row in place.
* **NOOP**   — DID×service is in the state and the hash matches.
  The row is omitted from the workbook entirely (per the
  v1.17.0 design decision: cheapest possible MCP call).
* **STALE**  — DID×service is in the state but the DID is no
  longer effective in the current FSCS for that service. WARN
  in stderr; nothing else (DOORS-side delete deferred to v1.18.x
  ``--prune-stale``).

Module-UUID handling
--------------------

The state file keys per-module substates by UUID. Calling
``compute_action_plan(state, module_uuid="MOD-A", ...)`` only
consults ``state.modules["MOD-A"]``; if that substate is empty or
absent, every effective DID resolves to INSERT (which is the
correct semantic — "no prior knowledge of this module").

The drift case the user worried about ("operator re-pointed at
a different module mid-flight") therefore self-resolves: a
fresh module UUID has no per-DID memory, so we never accidentally
apply MOD-A's recorded AbsoluteNumbers against MOD-B's rows.
A separate ``--force-reinsert`` CLI flag (Phase D) lets the
operator actively wipe the substate when that's the right
recovery posture.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Literal, Optional, Tuple

# Mirrors the sibling modules' convention so bare-name imports
# work both when invoked as ``python scripts/fscs/doors/diff.py``
# and when imported as ``fscs.doors.diff`` from a test harness or
# orchestrator (the workspace conftest only puts ``scripts/`` on
# sys.path, not ``scripts/fscs/doors/``).
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from doors_state import ServiceLanding, State, _normalise_hex  # noqa: E402


Action = Literal["INSERT", "UPDATE", "NOOP", "STALE"]
SERVICES: Tuple[str, ...] = ("22", "2E")


@dataclass(frozen=True)
class DIDAction:
    """One row in the per-DID×service action plan."""

    did_hex: str           # canonical "0xUPPER" form
    service: str           # "22" or "2E"
    action: Action

    # Populated for UPDATE / NOOP / STALE; None for INSERT.
    fs_abs: Optional[str] = None
    cs_abs: Optional[str] = None

    # Always populated for INSERT / UPDATE / NOOP (it's the hash
    # of the row pair the toolkit would write right now). None
    # for STALE because the DID is no longer in the current FSCS,
    # so there is no current rendering to hash.
    current_hash: Optional[str] = None

    # Populated only for UPDATE (the hash from the previous run --
    # included so the report can spell out *what* changed).
    previous_hash: Optional[str] = None


@dataclass
class ActionPlan:
    """Top-level result of :func:`compute_action_plan`."""

    module_uuid: str
    actions: List[DIDAction] = field(default_factory=list)

    # ----------------------------------------------------------------- #
    # convenience selectors -- the orchestrator + reporter both need    #
    # bucketed views and we'd rather centralise the filtering than      #
    # have every caller re-derive it (and risk a missed branch).        #
    # ----------------------------------------------------------------- #

    def of(self, action: Action) -> List[DIDAction]:
        return [a for a in self.actions if a.action == action]

    def for_service(self, service: str) -> List[DIDAction]:
        s = service.upper()
        return [a for a in self.actions if a.service.upper() == s]

    def for_workbook(self, service: str) -> List[DIDAction]:
        """Actions that should produce a row in this service's workbook.

        INSERT and UPDATE land rows; NOOP is omitted (per the
        v1.17.0 design decision); STALE is omitted (warn-only).
        """
        s = service.upper()
        return [
            a for a in self.actions
            if a.service.upper() == s and a.action in ("INSERT", "UPDATE")
        ]

    def summary(self) -> Dict[Action, int]:
        out: Dict[Action, int] = {"INSERT": 0, "UPDATE": 0, "NOOP": 0, "STALE": 0}
        for a in self.actions:
            out[a.action] += 1
        return out


# ----------------------------------------------------------------------- #
# the engine                                                              #
# ----------------------------------------------------------------------- #


def compute_action_plan(
    *,
    state: State,
    module_uuid: str,
    current_hashes: Dict[str, Dict[str, str]],
) -> ActionPlan:
    """Classify every DID×service into INSERT / UPDATE / NOOP / STALE.

    Parameters
    ----------
    state
        Loaded state object (from :func:`doors_state.load_state`).
        An empty :class:`State` (first-ever run, or
        ``--force-reinsert`` was just applied) means everything
        resolves to INSERT.
    module_uuid
        DOORS module UUID this run is targeting -- the
        per-module substate is the only one consulted.
    current_hashes
        Two-level dict: ``{service: {did_hex: content_hash}}``.
        Caller (Phase C: ``build_doors_payload``) computes the
        hash via :func:`content_hash.compute_pair_hash` for every
        DID×service pair that is effective in the current FSCS
        (``service_22.effective`` / ``service_2e.effective``).
        DIDs absent from this dict for a given service are
        considered "no longer effective for that service" and
        thus candidates for STALE classification.

    Returns
    -------
    :class:`ActionPlan`
        Always returns; never raises (errors at this layer would
        mean a dev-side bug, not an operator misconfiguration).
        The orchestrator wraps the call in a print of
        ``plan.summary()`` so the operator sees the bucketed
        counts before any upload.
    """
    module = state.for_module(module_uuid)

    # Track which (did_hex, service) pairs we saw in the current
    # FSCS so the STALE pass below can find what's recorded but
    # missing.
    seen: Dict[str, set] = {svc: set() for svc in SERVICES}

    plan = ActionPlan(module_uuid=module_uuid)

    for service in SERVICES:
        pairs = current_hashes.get(service, {}) or {}
        for raw_hex, current_hash in pairs.items():
            did_hex = _normalise_hex(raw_hex)
            seen[service].add(did_hex)
            recorded = module.landing(did_hex, service)

            if not recorded.is_recorded:
                plan.actions.append(DIDAction(
                    did_hex=did_hex, service=service,
                    action="INSERT",
                    current_hash=current_hash,
                ))
                continue

            if recorded.content_hash == current_hash:
                plan.actions.append(DIDAction(
                    did_hex=did_hex, service=service,
                    action="NOOP",
                    fs_abs=recorded.fs_abs, cs_abs=recorded.cs_abs,
                    current_hash=current_hash,
                    previous_hash=recorded.content_hash,
                ))
                continue

            plan.actions.append(DIDAction(
                did_hex=did_hex, service=service,
                action="UPDATE",
                fs_abs=recorded.fs_abs, cs_abs=recorded.cs_abs,
                current_hash=current_hash,
                previous_hash=recorded.content_hash,
            ))

    # STALE pass: every recorded landing not seen in the current
    # FSCS (for that service) is orphaned. Sorted here only so the
    # STALE tail of an otherwise FSCS-ordered plan stays
    # deterministic across runs (DIDs that have been deleted from
    # the FSCS no longer have a "natural" position).
    for did_hex, did_state in sorted(module.dids.items()):
        for service in SERVICES:
            recorded = did_state.for_service(service)
            if not recorded.is_recorded:
                continue
            if did_hex in seen[service]:
                continue
            plan.actions.append(DIDAction(
                did_hex=did_hex, service=service,
                action="STALE",
                fs_abs=recorded.fs_abs, cs_abs=recorded.cs_abs,
                previous_hash=recorded.content_hash,
            ))

    # NB: we deliberately preserve the iteration order of
    # ``current_hashes`` here. ``build_doors_payload`` populates
    # that dict by walking ``DIDBlock`` lists in FSCS-file order,
    # and the workbook layout downstream consumes
    # ``plan.for_workbook(service)`` directly -- so the natural
    # iteration order keeps the per-service workbook in
    # FSCS-file order, not alphabetical-by-hex order. Operators
    # who need the bucketed view should use
    # :func:`format_plan_table`, which sorts at render time.
    return plan


_ACTION_SORT: Dict[Action, int] = {
    "INSERT": 0,
    "UPDATE": 1,
    "NOOP":   2,
    "STALE":  3,
}


def format_plan_summary(plan: ActionPlan) -> str:
    """Render a one-line bucketed summary for stderr."""
    s = plan.summary()
    return (
        f"Plan ({plan.module_uuid}): "
        f"{s['INSERT']} INSERT / {s['UPDATE']} UPDATE / "
        f"{s['NOOP']} NOOP / {s['STALE']} STALE"
    )


def format_plan_table(plan: ActionPlan) -> str:
    """Render the full per-DID×service action table for ``--plan-only``.

    One line per action, tab-separated for grep-ability:
    ``ACTION<TAB>SERVICE<TAB>DID_HEX<TAB>FS_ABS<TAB>CS_ABS``. STALE
    rows surface their orphaned AbsoluteNumbers so the operator
    can decide whether to clean them up DOORS-side by hand.

    Rendering sorts by ``(action_bucket, service, did_hex)`` so the
    operator sees grouped INSERT/UPDATE/NOOP/STALE blocks rather
    than the FSCS-file-ordered raw plan -- the report is the only
    place we re-impose this order; the underlying ``plan.actions``
    stays in build order so the workbook layout matches FSCS.
    """
    lines = [format_plan_summary(plan), ""]
    if not plan.actions:
        lines.append("(empty plan -- nothing to push)")
        return "\n".join(lines)
    lines.append("ACTION\tSERVICE\tDID_HEX\tFS_ABS\tCS_ABS")
    for a in sorted(
        plan.actions,
        key=lambda x: (_ACTION_SORT[x.action], x.service, x.did_hex),
    ):
        lines.append(
            f"{a.action}\t{a.service}\t{a.did_hex}\t"
            f"{a.fs_abs or '-'}\t{a.cs_abs or '-'}"
        )
    return "\n".join(lines)


__all__ = [
    "Action",
    "DIDAction",
    "ActionPlan",
    "compute_action_plan",
    "format_plan_summary",
    "format_plan_table",
    "SERVICES",
]
