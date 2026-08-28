"""Cross-field / range validation for the diagcomm-toolkit pipeline.

These checks sit above the locator pipeline: they catch user-authored
mistakes that the schema's type system alone can't catch (hex ID that
doesn't fit the selected format, PaddingByte out of range, STmin above
the AUTOSAR / ISO 15765-2 hard cap, ClassicCAN frames trying to use
DL=64, ...). ``cmd_validate`` surfaces them as errors/warnings;
``cmd_apply`` treats the ``errors`` list as fail-fast.

Pure functions -- no filesystem / argparse / XML access, so easy to
unit-test without fixtures.
"""
from __future__ import annotations

from typing import Any


def _coerce_int(value: Any) -> int | None:
    """Parse a decimal / hex / int value the same way ``hex_to_decimal`` does.

    Returns ``None`` for empty / unparseable inputs so callers can surface
    a clean error message instead of a Python traceback.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.lower().startswith("0x"):
            return int(s, 16)
        if any(c in s.lower() for c in "abcdef"):
            return int(s, 16)
        return int(s, 10)
    except ValueError:
        return None


def _semantic_checks(values: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Cross-field / range checks that sit above the locator pipeline.

    Returns ``(errors, warnings)``. These checks run *in addition* to the
    schema presence / locator-match checks and are intended to catch
    user-authored mistakes that the schema's type system alone can't catch
    (hex ID that doesn't fit the selected format, PaddingByte out of
    range, STmin above the AUTOSAR / ISO 15765-2 hard cap, ...).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- CAN ID format vs ID range ----------------------------------------
    fmt = values.get("CAN_ID_Format")
    id_limit = None
    id_limit_label = ""
    if fmt == "11bit":
        id_limit = 0x7FF
        id_limit_label = "11-bit (max 0x7FF)"
    elif fmt == "29bit":
        id_limit = 0x1FFFFFFF
        id_limit_label = "29-bit (max 0x1FFFFFFF)"
    elif fmt is not None:
        warnings.append(
            f"CAN_ID_Format: unknown value {fmt!r} (expected 11bit | 29bit); "
            "skipping CAN ID range checks")

    if id_limit is not None:
        for key in ("CAN_Functional_Request_ID",
                    "CAN_Physical_Request_ID",
                    "CAN_Response_ID"):
            raw = values.get(key)
            if raw is None:
                continue
            n = _coerce_int(raw)
            if n is None:
                errors.append(f"{key}: cannot parse {raw!r} as an integer / hex")
                continue
            if n < 0:
                errors.append(f"{key} = {raw!r} (parsed {n}) is negative")
            elif n > id_limit:
                errors.append(
                    f"{key} = {raw!r} (parsed 0x{n:X}) exceeds the "
                    f"{id_limit_label} limit for CAN_ID_Format={fmt}"
                )

    # --- STmin hard cap (AUTOSAR / ISO 15765-2: 0.127 s = 127 ms) ---------
    stmin = values.get("STmin")
    if stmin is not None:
        try:
            st = float(stmin)
        except (TypeError, ValueError):
            errors.append(f"STmin: cannot parse {stmin!r} as a number")
        else:
            if st < 0:
                errors.append(f"STmin = {st} ms is negative")
            elif st > 127:
                errors.append(
                    f"STmin = {st} ms exceeds the 127 ms (0.127 s) AUTOSAR / "
                    f"ISO 15765-2 hard cap. Lower it before apply."
                )

    # --- PaddingByte 0..255 (hex or decimal) ------------------------------
    pad = values.get("PaddingByte")
    if pad is not None:
        n = _coerce_int(pad)
        if n is None:
            errors.append(f"PaddingByte: cannot parse {pad!r} as an integer / hex")
        elif n < 0 or n > 0xFF:
            errors.append(
                f"PaddingByte = {pad!r} (parsed {n}) is outside the "
                f"0..255 / 0x00..0xFF range."
            )

    # --- NRC78_Times 0..255 (ECUC-INTEGER, 1 byte) ------------------------
    nrc78 = values.get("NRC78_Times")
    if nrc78 is not None:
        n = _coerce_int(nrc78)
        if n is None:
            errors.append(f"NRC78_Times: cannot parse {nrc78!r} as an integer")
        elif n < 0 or n > 0xFF:
            errors.append(
                f"NRC78_Times = {nrc78!r} (parsed {n}) is outside the "
                f"0..255 range of DcmDslDiagRespMaxNumRespPend."
            )

    # --- CAN_DLC RX/TX cross-consistency ----------------------------------
    # ClassicCAN frames are physically limited to 8 bytes. Rejecting a
    # non-8 DL here means a user cannot produce an arxml that would fail
    # at CAN driver init. CANFD tolerates both 8 (short FD) and 64
    # (full FD) payloads, so we only guard the ClassicCAN rows.
    can_dlc = values.get("CAN_DLC")
    if isinstance(can_dlc, dict):
        pairs = (
            ("rx_frame_type", "rx_dl"),
            ("tx_frame_type", "tx_dl"),
        )
        for ft_key, dl_key in pairs:
            ft = can_dlc.get(ft_key)
            dl = can_dlc.get(dl_key)
            if ft == "ClassicCAN" and dl is not None and int(dl) != 8:
                errors.append(
                    f"CAN_DLC.{dl_key} must be 8 when CAN_DLC.{ft_key}="
                    f"ClassicCAN (physical Classic-CAN payload limit); "
                    f"got {dl}."
                )

    return errors, warnings
