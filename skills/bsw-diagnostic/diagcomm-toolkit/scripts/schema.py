"""Convert assets/DiagComm.txt into a structured DiagComm_schema.json.

"DiagComm" (diagnostic communication) covers the CAN / CAN-TP / Dcm
layers configured for the CusDiag stack. The source txt lists parameter
names (one per line). Out-of-scope items (CAN Baudrate / CANFD Baudrate)
are excluded because they live outside the dcom tree and are handled by
a different skill.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TXT = SKILL_ROOT / "assets" / "DiagComm.txt"
DEFAULT_SCHEMA = SKILL_ROOT / "assets" / "DiagComm_schema.json"

# Parameters explicitly excluded from this skill (handled elsewhere).
EXCLUDED = {"CAN Baudrate", "CANFD Baudrate"}

# Canonical schema definitions keyed by the raw txt line prefix.
# Each entry produces a single field in DiagComm_schema.json.
FIELD_DEFS: dict[str, dict[str, Any]] = {
    # ``Product Type`` is a PROJECT-IDENTITY field (lives at
    # `inputs/DiagComm_values.json::project.product_type` since 1.13.0).
    # ``CAN Channel`` is a TRUE PARAMETER (lives at
    # `inputs/DiagComm_values.json::parameters.CAN_Channel`). Neither is
    # patched into any file; ``PARAM_MAP`` has no entry for them. Runtime
    # copies them into ``config`` so that path templates like
    # ``RBAPLCust/cfg/{product_type}/Can{can_channel}...`` resolve to the
    # right arxml. The user-owned values file is the single source of
    # truth for both.
    "Product Type": {
        "key": "product_type",
        "type": "enum",
        "allowed": ["DPB", "ESP", "IPB", "RBU"],
        "default": "DPB",
        "prompt_required": True,
        "description": "Platform variant that selects the per-product arxml folder. Stored at inputs/DiagComm_values.json::project.product_type (project identity, NOT a parameter). The matching path templates live in inputs/DiagComm_config.json::paths. Fills the {product_type} placeholder in paths.can_pt_file (typically RBAPLCust/cfg/<PT>/Can<ch>_CusDiag_EcucValues_<PT>.arxml). Prompt-required: the schema default is just a starting guess -- the right value is whichever folder the project actually ships under RBAPLCust/cfg/.",
    },
    "CAN Channel": {
        "key": "CAN_Channel",
        "type": "int",
        "default": 0,
        "description": "CAN controller channel index (0, 1, 2, ...). Stored at inputs/DiagComm_values.json::parameters.CAN_Channel (the single source of truth; CAN_Channel is treated as a real parameter and contributes to the param fingerprint); runtime copies it into config.options.can_channel so path templates from inputs/DiagComm_config.json::paths (e.g. Can{can_channel}_CusDiag_EcucValues_<PT>.arxml) resolve to the right file. Most projects only deliver Can0; higher indices require the matching arxml to exist.",
    },
    "CAN ID Format": {
        "key": "CAN_ID_Format",
        "type": "enum",
        "allowed": ["11bit", "29bit"],
        "default": "11bit",
        "maps_to": "CanIdType (STANDARD|EXTENDED)",
        "description": "11 = STANDARD, 29 = EXTENDED; applied to every CanHardwareObject/CanIdType in the product-specific Can arxml.",
    },
    "Addressing method": {
        "key": "Addressing_Method",
        "type": "enum",
        "allowed": ["Normal", "NormalFixed", "Extended"],
        "default": "Normal",
        "maps_to": "CanTpAddressingFormat (CANTP_STANDARD|CANTP_NORMALFIXED|CANTP_EXTENDED)",
        "description": "CAN-TP addressing format per ISO 15765-2.",
    },
    # CAN DLC is prompt-required across ALL sub-fields: RX/TX frame type
    # and DL are per-project choices, and the shown defaults must NOT be
    # auto-accepted. The pre-fill workflow skips the whole object.
    # The global FD flag (CanTpFlexibleDataRateSupport) is derived at
    # apply-time from (rx_frame_type, tx_frame_type) and has NO user-
    # facing field here.
    "CAN DLC": {
        "key": "CAN_DLC",
        "type": "object",
        "fields": {
            "rx_frame_type": {
                "type": "enum",
                "allowed": ["ClassicCAN", "CANFD"],
                "default": "ClassicCAN",
                "prompt_required": True,
                "description": "RX frame type. Drives CanIfRxPduCanIdType (STANDARD_CAN for ClassicCAN, STANDARD_FD_CAN for CANFD) under both CusDiagRCV (physical) and CusDiagRCVFunc (functional) Pdu containers in Can<CH>_CusDiag_EcucValues_<PT>.arxml. Also ORed with tx_frame_type to drive the global CanTpFlexibleDataRateSupport flag. Prompt-required.",
            },
            "tx_frame_type": {
                "type": "enum",
                "allowed": ["ClassicCAN", "CANFD"],
                "default": "ClassicCAN",
                "prompt_required": True,
                "description": "TX frame type. Drives CanIfTxPduCanIdType under the CusDiagXMT Pdu container. ORed with rx_frame_type to derive CanTpFlexibleDataRateSupport. Prompt-required.",
            },
            "rx_dl": {
                "type": "enum",
                "allowed": [8, 64],
                "default": 8,
                "prompt_required": True,
                "description": "RX Pdu payload length in bytes. Written to PduLength under every CusDiagRCV* / CusDiagRCVFunc* Pdu container (6 hits on the default 3-Pdu chain). Must be 8 when rx_frame_type=ClassicCAN; 8 or 64 when CANFD. Prompt-required.",
            },
            "tx_dl": {
                "type": "enum",
                "allowed": [8, 64],
                "default": 8,
                "prompt_required": True,
                "description": "TX Pdu payload length in bytes. Written to PduLength under every CusDiagXMT* Pdu container (3 hits on the default chain). Must be 8 when tx_frame_type=ClassicCAN; 8 or 64 when CANFD. Prompt-required.",
            },
        },
        "description": "Per-direction CAN DLC configuration for the CusDiag Pdu chain. RX and TX are configured independently to support asymmetric setups (e.g. RX=Classic-or-FD, TX=FD-only). CanTpFlexibleDataRateSupport is derived automatically from the pair.",
    },
    # The three CAN IDs are flagged prompt-required: the schema default
    # (OBD-II legislated IDs: 0x7DF / 0x7E0 / 0x7E8) is almost never the
    # right value for a custom diagnostic project, so downstream tooling
    # treats the flag as a "verify carefully" hint. Actual pre-fill
    # comes from the live ARXML via the lazy-seed reverse walk just
    # like every other field -- the PR flag no longer gates pre-fill,
    # only emphasis.
    "CAN Functional Request ID": {
        "key": "CAN_Functional_Request_ID",
        "type": "hex",
        "default": "0x7DF",
        "prompt_required": True,
        "maps_to": "CanHwFilterCode @ SHORT-NAME=CusDiagRCVFunc",
        "description": "Functional (broadcast) request ID; written as decimal into CanHwFilterCode. Prompt-required UI badge: schema default (0x7DF, OBD-II) is only a fallback when ARXML pre-fill fails; verify against the project-specific ID.",
    },
    "CAN Physical Request ID": {
        "key": "CAN_Physical_Request_ID",
        "type": "hex",
        "default": "0x7E0",
        "prompt_required": True,
        "maps_to": "CanHwFilterCode @ SHORT-NAME=CusDiagRCV",
        "description": "Physical request ID; written as decimal into CanHwFilterCode. Prompt-required UI badge: schema default (0x7E0, OBD-II) is only a fallback when ARXML pre-fill fails; verify against the project-specific ID.",
    },
    "CAN Response ID": {
        "key": "CAN_Response_ID",
        "type": "hex",
        "default": "0x7E8",
        "prompt_required": True,
        "maps_to": "CanId / CanHwFilterCode @ SHORT-NAME=CusDiagXMT (runtime discovery)",
        "description": "Response (TX) ID; exact node discovered at apply-time because it may be defined on the CanHwObject or on a Pdu-layer reference. Prompt-required UI badge: schema default (0x7E8, OBD-II) is only a fallback when ARXML pre-fill fails; verify against the project-specific ID.",
    },
    # --- Time parameters ----------------------------------------------------
    # IMPORTANT: all timing inputs are expressed in milliseconds (ms).
    # AUTOSAR arxml stores these values in seconds, so the apply pipeline
    # runs the ``ms_to_seconds`` transform (value / 1000) before writing.
    "N_As": {"key": "N_As", "type": "float", "unit": "ms", "default": 25,
             "maps_to": "CanTpNas (CanTpTxNSdu)",
             "description": "Network layer timing: time for sending a CAN frame (TX). Written as seconds in arxml."},
    "N_Ar": {"key": "N_Ar", "type": "float", "unit": "ms", "default": 25,
             "maps_to": "CanTpNar (CanTpRxNSdu)",
             "description": "Network layer timing: time for receiving a CAN frame (RX). Written as seconds in arxml."},
    "N_Bs": {"key": "N_Bs", "type": "float", "unit": "ms", "default": 75,
             "maps_to": "CanTpNbs (CanTpTxNSdu)",
             "description": "Time until reception of the next flow control N_PDU (TX). Written as seconds in arxml."},
    "N_Br": {"key": "N_Br", "type": "float", "unit": "ms", "default": 25,
             "maps_to": "CanTpNbr (CanTpRxNSdu)",
             "description": "Time until transmission of the next flow control N_PDU (RX). Written as seconds in arxml."},
    "N_Cs": {"key": "N_Cs", "type": "float", "unit": "ms", "default": 100,
             "maps_to": "CanTpNcs (CanTpTxNSdu)",
             "description": "Time until transmission of the next consecutive frame (TX). Written as seconds in arxml."},
    "N_Cr": {"key": "N_Cr", "type": "float", "unit": "ms", "default": 150,
             "maps_to": "CanTpNcr (CanTpRxNSdu)",
             "description": "Time until reception of the next consecutive frame (RX). Written as seconds in arxml."},
    # ``P2 Max`` / ``P2* Max`` inputs are the MAXIMUM server response times.
    # The skill writes them only to the ``*Max`` node family (protocol +
    # per-session). The ``*Adjust`` offset nodes are intentionally left
    # untouched.
    "P2 Max": {"key": "P2_Max", "type": "float", "unit": "ms", "default": 50,
               "maps_to": "DcmDspSessionP2ServerMax (per-session). DcmTimStrP2ServerAdjust is NOT modified.",
               "description": "Maximum P2 server response time (ms). Written as seconds to DcmDspSessionP2ServerMax in Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml for every session row."},
    "P2* Max": {"key": "P2_Star_Max", "type": "float", "unit": "ms", "default": 5000,
                "maps_to": "DcmDspSessionP2StarServerMax (per-session). DcmTimStrP2StarServerAdjust is NOT modified.",
                "description": "Maximum P2* (enhanced) server response time (ms). Written as seconds to DcmDspSessionP2StarServerMax in Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml for every session row."},
    "BS": {"key": "BS", "type": "int", "default": 0,
           "maps_to": "CanTpBs (CanTpRxNSdu)",
           "description": "Block Size (0 = unlimited). Integer, no unit conversion."},
    "STmin": {"key": "STmin", "type": "float", "unit": "ms",
              "default": 0, "min": 0, "max": 127,
              "maps_to": "CanTpStMin (CanTpRxNSdu)",
              "description": "Separation Time minimum between consecutive frames (ms). AUTOSAR / ISO 15765-2 hard-caps this at 127 ms (0.127 s); values above 127 are rejected by validate. Written as seconds in arxml."},
    # --- CanTp feature config (cfg/CanTp_Feature_EcucValues.arxml) ---------
    "PaddingByte": {"key": "PaddingByte", "type": "hex",
                    "default": "0x00", "min": 0, "max": 255,
                    "maps_to": "CanTpPaddingByte in CanTp_Feature_EcucValues.arxml",
                    "description": "Byte value used to pad under-sized CAN-TP frames. Accepts decimal (0..255) or hex (0x00..0xFF); stored as a decimal integer in arxml."},
    "StrictDlcCheck": {"key": "StrictDlcCheck", "type": "bool", "default": False,
                       "maps_to": "CanTpRbStrictDlcCheck in CanTp_Feature_EcucValues.arxml",
                       "description": "Enables strict DLC length checking on the CAN-TP layer. true/false (written as boolean literal)."},
    "NRC78 Times": {"key": "NRC78_Times", "type": "int",
                    "default": 10, "min": 0, "max": 255,
                    "maps_to": "DcmDslDiagRespMaxNumRespPend @ DcmDslDiagResp in Dcm_Feature_EcucValues.arxml",
                    "description": "Max number of NRC 0x78 (ResponsePending) responses the server may send before it must finally answer or abort. ISO 14229 does not hard-cap this; typical project values are 5..20. Integer (1 byte, 0..255), no unit conversion. Written to Cubas/cfg/Dcm_Feature_EcucValues.arxml."},
}


def _normalize_txt_line(line: str) -> str:
    """Strip trailing comments (after ':' or '#') to match FIELD_DEFS keys."""
    line = line.strip()
    if not line:
        return ""
    for sep in (":", "#"):
        if sep in line:
            line = line.split(sep, 1)[0].strip()
            break
    return line


def build_schema(txt_path: Path) -> dict[str, Any]:
    text = txt_path.read_text(encoding="utf-8")
    order: list[str] = []
    for raw in text.splitlines():
        name = _normalize_txt_line(raw)
        if not name:
            continue
        if name in EXCLUDED:
            continue
        if name in FIELD_DEFS:
            order.append(name)
        else:
            # Keep unknown lines as free-form string fields so the schema
            # remains a complete picture of the txt.
            order.append(name)

    fields: dict[str, Any] = {}
    for name in order:
        spec = FIELD_DEFS.get(name)
        if spec is None:
            fields[name.replace(" ", "_")] = {
                "type": "string",
                "description": f"Unrecognized parameter from assets/DiagComm.txt: '{name}'. Mapping not defined; skill will WARN at apply-time.",
                "source_name": name,
            }
            continue
        key = spec["key"]
        payload = {k: v for k, v in spec.items() if k != "key"}
        payload.setdefault("source_name", name)
        fields[key] = payload

    return {
        "$schema": "diagcomm-toolkit/DiagComm_schema/v1",
        "generated_from": str(txt_path.name),
        "excluded_parameters": sorted(EXCLUDED),
        "fields": fields,
    }


def generate(txt_path: Path = DEFAULT_TXT, out_path: Path = DEFAULT_SCHEMA) -> Path:
    schema = build_schema(txt_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" forces LF on Windows too; otherwise Python's text
    # mode translates "\n" -> "\r\n" and every gen-schema run churns
    # the file in git with a pointless CRLF/LF flip.
    out_path.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return out_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate DiagComm_schema.json from DiagComm.txt")
    parser.add_argument("--input", type=Path, default=DEFAULT_TXT)
    parser.add_argument("--output", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args()
    path = generate(args.input, args.output)
    print(f"[schema] wrote {path}")
