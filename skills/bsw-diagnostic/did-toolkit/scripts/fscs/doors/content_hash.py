"""Canonical content hash for the DOORS row pair (v1.17.0).

The diff engine (``diff.py``) decides INSERT vs UPDATE vs NOOP by
comparing a per-DID×service ``content_hash`` against the recorded
hash from the previous upload (``doors_state.py::ServiceLanding.
content_hash``). This module owns the hash function so the
canonicalisation rules are the single source of truth.

What goes into the hash
-----------------------

The hash input is the **rendered DOORS cell tuple** for the
DID×service pair, i.e. the 15 columns of the v1.16.0 17-column
template *minus* ``Destination Object`` and ``Absolute Number``.
The two excluded columns are the state machine's output, not
input -- including them would either break NOOP after the very
first UPDATE (because ``Absolute Number`` would change) or break
UPDATE after the very first INSERT (because ``Destination
Object`` becomes blank).

Concretely, a "row pair" is::

    {
      "FS": {
        "Number": "1",
        "isPicture": "no",
        "Object Heading": "Identifier $F190h - BaselineCounter",
        "Object Text": "",
        "RB_RS_CP_Status": "accepted",
        "RB_RS_MS_Status": "accepted",
        "RB_Product": "DPB",
        "RB_Configuration": "DCOM_ReferenceDiagnosis_CUST",
        "RB_Realizing_SWComponent": "RBAPLCUST, CUBAS",
        "RB_Realizing_SWitem": "Dcm_CusDiag_Services_EcucValues_DPB.arxml",
        "RB_VerificationType": "Test",
        "RB_VerificationCriteria": "No Additional Information Necessary",
        "RB_Analysis_Results": "Result / Size Estimate / Risk",
        "RB_Referenced_Testcase": "SwT",
        "RB_TestEnvironment": "Labcar/HIL"
      },
      "CS": { ... CS row, same 15 keys ... }
    }

Any change that would propagate into one of those 15 cells
changes the hash. In particular, mutating ``NVM_ID`` in fscs.json
flows through the renderer into ``Object Text`` (via the
Behaviour section) and DOES trigger an UPDATE -- this is the
operator's intent ("anything affecting the FSCS content
generation counts").

Canonicalisation
----------------

* Cell values are coerced to ``str`` and stripped of trailing
  whitespace per cell. (Leading whitespace is preserved -- DOORS
  is whitespace-significant for indented body text.)
* Missing cells are treated as the empty string. (A missing key
  must hash identically to an explicit ``""``.)
* The dict is rendered with ``json.dumps(..., sort_keys=True,
  ensure_ascii=False, separators=(",", ":"))`` to remove
  ordering / spacing variability.
* SHA-256 over the UTF-8-encoded canonical string. Returned as
  ``"sha256:" + hex_digest`` so future migration to a different
  algorithm (BLAKE3, etc.) is a one-line change at the consumer.

Determinism is the only correctness criterion: same cell tuple in
must produce the same hash byte-for-byte. The unit tests pin
that across reorderings, missing-vs-empty equivalence, and
unicode survival.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, Mapping, Optional


# The 15 cells the DOORS server actually shows the user, in the
# canonical order the diff engine cares about. ``Destination
# Object`` and ``Absolute Number`` are intentionally absent --
# they are the state-machine *output*, not input.
HASHED_COLUMNS = (
    "Number",
    "isPicture",
    "Object Heading",
    "Object Text",
    "RB_RS_CP_Status",
    "RB_RS_MS_Status",
    "RB_Product",
    "RB_Configuration",
    "RB_Realizing_SWComponent",
    "RB_Realizing_SWitem",
    "RB_VerificationType",
    "RB_VerificationCriteria",
    "RB_Analysis_Results",
    "RB_Referenced_Testcase",
    "RB_TestEnvironment",
)


HASH_PREFIX = "sha256:"


def _canonicalise_cells(cells: Mapping[str, Any]) -> Dict[str, str]:
    """Reduce one row's worth of cells to a deterministic ``{str: str}``.

    Missing keys land as ``""`` so a future row that fills in a
    blank cell still hashes identically to a row that omitted it
    today. Cell values are coerced via ``str()``; trailing
    whitespace per cell is stripped (Excel/xlsxwriter sometimes
    pads cells with a trailing newline).
    """
    out: Dict[str, str] = {}
    for col in HASHED_COLUMNS:
        raw = cells.get(col, "")
        if raw is None:
            raw = ""
        out[col] = str(raw).rstrip()
    return out


def compute_pair_hash(
    *,
    fs_cells: Mapping[str, Any],
    cs_cells: Mapping[str, Any],
) -> str:
    """SHA-256 over the canonical (FS, CS) cell pair.

    Both rows of a DID's two-row layout flow into the same hash so
    a CS-only edit (e.g. Behaviour section change without a heading
    change) still triggers an UPDATE. The pair is canonicalised as
    a sorted JSON dict for cross-platform / cross-Python-version
    determinism.
    """
    payload = {
        "FS": _canonicalise_cells(fs_cells),
        "CS": _canonicalise_cells(cs_cells),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return HASH_PREFIX + digest


def is_valid_hash(value: Optional[str]) -> bool:
    """True iff ``value`` is a well-formed hash string from this module."""
    if not isinstance(value, str):
        return False
    if not value.startswith(HASH_PREFIX):
        return False
    body = value[len(HASH_PREFIX):]
    if len(body) != 64:
        return False
    try:
        int(body, 16)
    except ValueError:
        return False
    return True


__all__ = [
    "HASHED_COLUMNS",
    "HASH_PREFIX",
    "compute_pair_hash",
    "is_valid_hash",
]
