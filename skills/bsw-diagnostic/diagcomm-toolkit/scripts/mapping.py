"""Declarative mapping between user-facing parameter keys and arxml nodes.

The declarative data lives in ``scripts/mapping.yaml`` (single source of
truth). This module loads that file at import time, validates a few
structural invariants, and exposes:

- ``PARAM_MAP``            -- list of dicts consumed by
                              ``arxml_patcher.apply_mapping()``
- ``TRANSFORMS`` /
  ``REVERSE_TRANSFORMS``   -- registered value transformers
- file alias constants     -- symbolic names kept for legacy imports

Entry schema (see mapping.yaml for full docs):
  param         dotted key into DiagComm_values.json
  file          alias key; resolved via DiagComm_values.json::paths
  locator       {type, def_suffix[, context_container_def_suffix,
                 ancestor_short_name, ancestor_short_name_prefix]}
  transform     name of a callable in TRANSFORMS
  multi         true -> update every match, false -> first match only
  optional      true -> zero-hit becomes WARN (default: error)
  derived       true -> synthetic key written by pipeline, hidden from
                       user-facing defaults

The actual XML traversal lives in ``arxml_patcher.py``.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - surfaced at runtime
    _REQ = (Path(__file__).resolve().parent / "requirements.txt").as_posix()
    raise SystemExit(
        "[mapping] PyYAML is required. Install it via:\n"
        f"  python -m pip install -r {_REQ}"
    ) from exc

# -------- value transformers --------------------------------------------------

def _hex_to_decimal(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    s = str(value).strip()
    if s.lower().startswith("0x"):
        return str(int(s, 16))
    # Tolerate plain decimal strings too
    return str(int(s, 16) if any(c in s.lower() for c in "abcdef") else int(s))


def _format_autosar_float(f: float) -> str:
    """Render ``f`` as an AUTOSAR ECUC-FLOAT literal.

    Uses ``format(f, "g")`` for compactness, then guarantees a decimal
    point for every **non-zero** integral value: e.g. ``5.0`` serialises
    as ``"5.0"`` (not ``"5"``) so a node typed ``ECUC-FLOAT-PARAM-DEF``
    keeps its float typing in the on-disk arxml. ``0`` is the sole
    exception -- existing project arxml files almost universally store
    the zero literal as a bare ``"0"`` (BS, default NSdu timers, etc.),
    and emitting ``"0.0"`` would produce spurious diffs against that
    convention. Rewriting a ``"0"`` to ``"0"`` is a true no-op so the
    typing concern does not apply.
    """
    fl = float(f)
    if fl == 0.0:
        return "0"
    s = format(fl, "g")
    if "." not in s and "e" not in s and "E" not in s and "n" not in s:
        s = s + ".0"
    return s


def _float_seconds(value: Any) -> str:
    """Format a raw-seconds numeric as an ECUC-FLOAT literal. Kept for
    completeness; new timer mappings should use ``_ms_to_seconds`` instead
    because all user-facing timing inputs are specified in milliseconds."""
    return _format_autosar_float(float(value))


def _ms_to_seconds(value: Any) -> str:
    """Convert a millisecond input to the seconds literal used by AUTOSAR.

    All diagnostic timing parameters in this skill (N_*, P2, P2*, STmin)
    are entered in **milliseconds** by the user. AUTOSAR arxml stores the
    same values in **seconds**, so this transform divides by 1000 before
    formatting. The output is always a float literal (``"0.07"``,
    ``"5.0"``, ``"0.0"``) because the matching arxml nodes are typed
    ``ECUC-FLOAT-PARAM-DEF`` -- emitting ``"5"`` for ``5000 ms`` would
    silently change the literal's XSD type even though the numerical
    value is identical.
    """
    return _format_autosar_float(float(value) / 1000.0)


def _int_str(value: Any) -> str:
    return str(int(value))


def _can_id_type(value: Any) -> str:
    v = str(value).lower().replace(" ", "")
    mapping = {"11bit": "STANDARD", "29bit": "EXTENDED",
               "standard": "STANDARD", "extended": "EXTENDED",
               "11": "STANDARD", "29": "EXTENDED"}
    if v not in mapping:
        raise ValueError(f"CAN_ID_Format must be 11bit or 29bit, got {value!r}")
    return mapping[v]


def _addressing_format(value: Any) -> str:
    v = str(value).strip().lower().replace(" ", "").replace("_", "")
    mapping = {
        "normal": "CANTP_STANDARD",
        "normalfixed": "CANTP_NORMALFIXED",
        "extended": "CANTP_EXTENDED",
    }
    if v not in mapping:
        raise ValueError(
            f"Addressing_Method must be Normal/NormalFixed/Extended, got {value!r}")
    return mapping[v]


def _canfd_pdu_id_type(value: Any) -> str:
    """Map a single ``CAN_DLC.rx_frame_type`` / ``CAN_DLC.tx_frame_type``
    choice to the CanIf Pdu CanIdType enum.

    ClassicCAN -> STANDARD_CAN      (on RX: accept CAN + CAN-FD; on TX: CAN-only)
    CANFD      -> STANDARD_FD_CAN   (CANFD-only, both RX and TX)

    The same literal applies to both CanIfRxPduCanIdType and
    CanIfTxPduCanIdType for a given direction's frame_type, so one
    transform covers both sides. The global CanTpFlexibleDataRateSupport
    flag is *not* written by this function -- it is derived separately
    (see pipeline._inject_derived_values + the CAN_DLC.flexible_fd
    PARAM_MAP entry below).
    """
    v = str(value).strip().lower().replace(" ", "").replace("-", "")
    if v in {"canfd", "fd"}:
        return "STANDARD_FD_CAN"
    return "STANDARD_CAN"


def _bool_str(value: Any) -> str:
    """Coerce a truthy/falsy user input to the AUTOSAR BOOLEAN literal.

    Accepts: Python bool, 0/1, ``"true"``/``"false"``, ``"yes"``/``"no"``,
    ``"on"``/``"off"`` (all case-insensitive). Anything else raises ValueError.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    s = str(value).strip().lower()
    if s in {"true", "1", "yes", "y", "on"}:
        return "true"
    if s in {"false", "0", "no", "n", "off"}:
        return "false"
    raise ValueError(f"cannot coerce {value!r} to a boolean literal")


TRANSFORMS: dict[str, Callable[[Any], str]] = {
    "hex_to_decimal": _hex_to_decimal,
    "float_seconds": _float_seconds,
    "ms_to_seconds": _ms_to_seconds,
    "int_str": _int_str,
    "bool_str": _bool_str,
    "can_id_type": _can_id_type,
    "addressing_format": _addressing_format,
    "canfd_pdu_id_type": _canfd_pdu_id_type,
    "identity": lambda v: str(v),
}


# -------- reverse transforms --------------------------------------------------
# Used by the lazy-seed / ``pipeline.py reseed`` reverse walk to turn a
# *current arxml literal* back into a *user-facing value*, so we can
# (re)create ``inputs/DiagComm_values.json`` from whatever the project
# currently has on disk. Each reverse function takes the raw arxml text
# and returns a JSON-serialisable Python value that matches the schema
# ``type`` (float/int/hex-string/bool/enum-literal).


def _rev_hex_to_decimal(raw: str) -> str:
    """Decimal integer in arxml -> ``0x..`` hex string for the user.

    Pads to an even number of hex digits (minimum 2) so byte-sized
    values like ``0`` come back as ``"0x00"`` instead of ``"0x0"``,
    matching the schema default format.
    """
    n = int(str(raw).strip())
    hex_digits = f"{n:X}" or "0"
    if len(hex_digits) % 2 == 1:
        hex_digits = "0" + hex_digits
    if len(hex_digits) < 2:
        hex_digits = hex_digits.rjust(2, "0")
    return "0x" + hex_digits


def _rev_ms_to_seconds(raw: str) -> float:
    """Seconds literal in arxml -> ms number for the user."""
    v = float(str(raw).strip()) * 1000.0
    return int(v) if v.is_integer() else v


def _rev_float_seconds(raw: str) -> float:
    v = float(str(raw).strip())
    return int(v) if v.is_integer() else v


def _rev_int_str(raw: str) -> int:
    return int(str(raw).strip())


def _rev_bool_str(raw: str) -> bool:
    return str(raw).strip().lower() == "true"


def _rev_can_id_type(raw: str) -> str:
    v = str(raw).strip().upper()
    return {"STANDARD": "11bit", "EXTENDED": "29bit"}.get(v, v)


def _rev_canfd_pdu_id_type(raw: str) -> str:
    """CanIf Pdu CanIdType literal -> user-facing frame-type label.

    STANDARD_FD_CAN -> CANFD
    STANDARD_CAN    -> ClassicCAN

    Any other AUTOSAR literal (EXTENDED_CAN, EXTENDED_FD_CAN, ...) falls
    back to ClassicCAN; those variants are not supported by this toolkit
    today, and the forward transform only ever emits the two canonical
    values above, so the reverse mapping is intentionally narrow.
    """
    v = str(raw).strip().upper().replace(" ", "")
    if v == "STANDARD_FD_CAN":
        return "CANFD"
    return "ClassicCAN"


def _rev_addressing_format(raw: str) -> str:
    v = str(raw).strip().upper()
    return {
        "CANTP_STANDARD": "Normal",
        "CANTP_NORMALFIXED": "NormalFixed",
        "CANTP_EXTENDED": "Extended",
    }.get(v, v)


REVERSE_TRANSFORMS: dict[str, Callable[[str], Any]] = {
    "hex_to_decimal": _rev_hex_to_decimal,
    "float_seconds": _rev_float_seconds,
    "ms_to_seconds": _rev_ms_to_seconds,
    "int_str": _rev_int_str,
    "bool_str": _rev_bool_str,
    "can_id_type": _rev_can_id_type,
    "addressing_format": _rev_addressing_format,
    # canfd_pdu_id_type is reversible even though CAN_DLC.{rx,tx}_frame_type
    # are flagged prompt_required: the PR flag is now only an advisory
    # hint, and the lazy-seed reverse walk pre-fills every field from
    # ARXML for consistency.
    "canfd_pdu_id_type": _rev_canfd_pdu_id_type,
    "identity": lambda v: str(v),
}


# -------- file aliases --------------------------------------------------------

# Resolved by pipeline from config.paths at runtime.
CANTP_COMMON = "cantp_common"                # RBAPLCust/cfg/Common/CanTp_CusDiag_EcucValues.arxml
CANTP_FEATURE_FILE = "cantp_feature_file"    # Cubas/cfg/CanTp_Feature_EcucValues.arxml
DCM_COMMON = "dcm_common"                    # RBAPLCust/cfg/Common/Dcm_CusDiag_Can_EcucValues.arxml
DCM_FEATURE_FILE = "dcm_feature_file"        # Cubas/cfg/Dcm_Feature_EcucValues.arxml
DCM_SERVICES_COMMON = "dcm_services_common"  # .../Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml
CAN_PT_FILE = "can_pt_file"                  # RBAPLCust/cfg/<PT>/Can<can_channel>_CusDiag_EcucValues_<PT>.arxml


# -------- mapping table -------------------------------------------------------

_MAPPING_YAML = Path(__file__).resolve().parent / "mapping.yaml"

_ALLOWED_LOCATOR_KEYS: set[str] = {
    "type",
    "def_suffix",
    "context_container_def_suffix",
    "ancestor_short_name",
    "ancestor_short_name_prefix",
}
_ALLOWED_LOCATOR_TYPES: set[str] = {
    "def_suffix",
    "def_suffix_any",
    "def_suffix_under_short_name",
}
_ALLOWED_ENTRY_KEYS: set[str] = {
    "param", "file", "locator", "transform", "multi", "optional", "derived",
}


def _load_param_map(yaml_path: Path) -> list[dict[str, Any]]:
    """Load + validate ``mapping.yaml``.

    Validation is intentionally narrow -- it only catches typos that
    would otherwise surface as confusing runtime KeyError / missing-
    transform errors later in the pipeline. Deeper semantics (does
    the def_suffix actually exist in the project's arxml?) is the job
    of ``landing-report`` / ``validate``.
    """
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"mapping.yaml not found at {yaml_path}. "
            f"This file is the single source of truth for PARAM_MAP; "
            f"if you are porting the skill, copy scripts/mapping.yaml "
            f"from the reference checkout."
        )
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    raw = data.get("params")
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            "mapping.yaml: expected a non-empty `params:` list at the top level"
        )
    out: list[dict[str, Any]] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"mapping.yaml[{idx}]: entry is not a mapping")
        unknown = set(entry) - _ALLOWED_ENTRY_KEYS
        if unknown:
            raise ValueError(
                f"mapping.yaml[{idx}] ({entry.get('param', '?')!r}): "
                f"unknown key(s) {sorted(unknown)}; allowed: "
                f"{sorted(_ALLOWED_ENTRY_KEYS)}"
            )
        for required in ("param", "file", "locator", "transform"):
            if required not in entry:
                raise ValueError(
                    f"mapping.yaml[{idx}]: missing required key "
                    f"{required!r} (entry: {entry!r})"
                )
        locator = entry["locator"]
        if not isinstance(locator, dict):
            raise ValueError(
                f"mapping.yaml[{idx}] ({entry['param']!r}): locator must be a mapping"
            )
        unknown_loc = set(locator) - _ALLOWED_LOCATOR_KEYS
        if unknown_loc:
            raise ValueError(
                f"mapping.yaml[{idx}] ({entry['param']!r}): unknown locator "
                f"key(s) {sorted(unknown_loc)}; allowed: "
                f"{sorted(_ALLOWED_LOCATOR_KEYS)}"
            )
        if locator.get("type") not in _ALLOWED_LOCATOR_TYPES:
            raise ValueError(
                f"mapping.yaml[{idx}] ({entry['param']!r}): locator.type "
                f"{locator.get('type')!r} not in {sorted(_ALLOWED_LOCATOR_TYPES)}"
            )
        if entry["transform"] not in TRANSFORMS:
            raise ValueError(
                f"mapping.yaml[{idx}] ({entry['param']!r}): transform "
                f"{entry['transform']!r} is not registered in TRANSFORMS "
                f"(known: {sorted(TRANSFORMS)})"
            )
        out.append(entry)
    return out


PARAM_MAP: list[dict[str, Any]] = _load_param_map(_MAPPING_YAML)


def expand_path(template: str, product_type: str, can_channel: int) -> str:
    """Resolve ``{product_type}`` and ``{can_channel}`` placeholders."""
    return template.format(product_type=product_type, can_channel=can_channel)


def get_nested(values: dict[str, Any], dotted: str) -> Any:
    cur: Any = values
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur
