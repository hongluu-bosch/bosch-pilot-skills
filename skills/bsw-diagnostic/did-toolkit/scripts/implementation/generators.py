"""Jinja2-backed artifact generators.

Every public function here is a **pure** function of its inputs:

* a populated :class:`DIDImplementationInfo`,
* optional overridable prefixes / writecycles value,

and returns a ready-to-write string. Side effects (file writes, logging)
live in :mod:`scripts.implementation.safety` and
:mod:`scripts.implementation.orchestrator`.

Every ``generate_*`` here delegates to one of the templates under
``scripts/templates/{impl,arxml}/*.j2`` via
:func:`scripts.templating.render`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from .models import DIDImplementationInfo
from .hardcode_parser import build_define_lines, parse_hardcode_values
from .naming import (
    FS_MACRO_PREFIX,
    capitalize_first,
    clean_name,
    get_fs_macro,
    get_func_name,
    get_nvm_id,
    get_range_macro_name,
)

# Import via scripts.templating so that both ``import`` styles resolve:
#   - package: ``from scripts.implementation.generators import ...``
#   - flat:    ``import generators`` (legacy test harness, sys.path fix-up)
try:
    from templating import render as _render  # flat path (scripts/ on sys.path)
except ImportError:  # pragma: no cover - only hit when package layout changes
    from scripts.templating import render as _render  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# v1.27.0: inline storage classification + behaviour-driven TODO blocks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StorageClassification:
    """Lightweight storage-class verdict used by the inline TODO block.

    Replaces the v1.15.0 ``_briefs/<HEX>_<svc>.md`` artefact: the
    classifier output (klass + RAM sub-pattern hint + rationale) is
    rendered directly inside the ``.c`` ``TODO(agent)`` comment block
    so the agent can fill in the body without opening a second file.
    """

    klass: str  # "NVM" / "HardCode" / "RAM"
    ram_subpattern: Optional[str]  # "A"/"B"/"C" or None
    rationale: str


_RAM_SUBPATTERN_HINTS = (
    (
        r"\bRBMESG[_\s]|\bRBBSM[_\s]|RBMESG_DefineMESGDef|RBMESG_RcvMESGDef",
        "C",
        "behavior mentions an RBMESG_ / RBBSM_ family signal — scalar / "
        "enum, IPB-style.",
    ),
    (
        r"NMSG_\w+_ST\b|DefineMESGDef\b|RcvMESGDef\b",
        "B",
        "behavior mentions an NMSG_..._ST struct message — ESP/DPB-style "
        "with Qualifier_N guard.",
    ),
    (
        r"\bget\w+\(|\bRBEcuSupply|ComScl_RawSignal|battery|voltage|"
        r"temperature|filtered|raw signal",
        "A",
        "behavior mentions a direct getter / raw signal — internal "
        "interface call.",
    ),
)


def classify_storage(did: DIDImplementationInfo) -> StorageClassification:
    """Classify a non-EEPROM DID for the inline TODO block.

    Mirrors :file:`reference/implementation-storage-positions.md`:

    * ``EEPROM``                 → ``NVM`` (no TODO; generator emits full body)
    * ``ROM`` / ``FLASH``        → ``HardCode`` (#define table in matching .h)
    * everything else            → ``RAM`` (internal-interface). RAM sub-pattern
                                   ``A`` / ``B`` / ``C`` is guessed from the
                                   joined behaviour text via the keyword
                                   heuristics in :data:`_RAM_SUBPATTERN_HINTS`.
    """
    pos = (did.storage_pos or "").upper()
    if pos == "EEPROM":
        return StorageClassification(
            klass="NVM",
            ram_subpattern=None,
            rationale="EEPROM/NVM-backed — fully generated, no TODO needed.",
        )
    if pos in ("ROM", "FLASH"):
        return StorageClassification(
            klass="HardCode",
            ram_subpattern=None,
            rationale=(
                "Read-only constant data. Generator auto-emits per-byte "
                "#define ladder in RBAPLCUST_RDBI_<DidName>.h from the "
                "FSCS HardCode: behavior block; the .c body copies via "
                "Data[i] = C_DID_..._UB macros. Agent reviews correctness."
            ),
        )

    behaviour = " ".join(b for b in (did.behavior_22, did.behavior_2e) if b)
    sub, why = None, "no behavior keyword matched a known RAM sub-pattern."
    for pattern, label, rationale in _RAM_SUBPATTERN_HINTS:
        if re.search(pattern, behaviour, re.IGNORECASE):
            sub, why = label, rationale
            break
    return StorageClassification(
        klass="RAM",
        ram_subpattern=sub,
        rationale=(
            f"Internal-interface read. RAM sub-pattern guess: "
            f"{sub or 'undetermined'} — {why}"
        ),
    )


def _looks_like_default_behaviour(text: str) -> bool:
    """Return True when ``text`` reads like an unedited FSCS placeholder.

    v1.27.0 contract: the agent must FILL IN the body when the
    operator wrote a real behaviour description, and leave the
    ``TODO(agent)`` stub when the description is empty or still the
    default text from Phase 1 / the questionnaire. This helper is
    what the inline TODO block uses to label the block as
    ``agent-fill: yes`` / ``agent-fill: no (TODO kept as stub)``.
    """
    if text is None:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    placeholder_markers = (
        "todo", "tbd", "to be defined", "to be determined",
        "n/a", "not defined", "(empty",
    )
    low = stripped.lower()
    if low in {"-", "—", "none", "null"}:
        return True
    for marker in placeholder_markers:
        if low == marker or low.startswith(marker + " ") or low.startswith(marker + ":"):
            return True
    return False


def _format_behaviour_block(label: str, text: str) -> List[str]:
    """Render a ``Behavior (<svc>):`` block inside the TODO comment.

    Empty / default behaviour collapses to a single ``(empty)`` line so
    the block doesn't grow huge for unrelated DIDs.
    """
    if _looks_like_default_behaviour(text):
        return [f"\t *   Behavior {label}: (empty / default — leave TODO as a stub)"]
    out: List[str] = [f"\t *   Behavior {label}:"]
    for line in text.splitlines() or [text]:
        out.append(f"\t *     {line.rstrip()}")
    return out


def _build_inline_todo_block(
    did: DIDImplementationInfo,
    kind: str,
    svc_label: str,
) -> str:
    """Build the multi-line ``TODO(agent)`` comment block.

    Carries everything the agent needs inline to draft the body:

    * DID identity (hex / EN+ZH name / data type / size / product),
    * storage classification + RAM sub-pattern guess,
    * mandatory style constraints (MISRA-C compliance + the
      ``*MESGDef`` macro placement / pairing rule for sub-pattern
      B and C bodies),
    * operator-supplied FSCS Behavior text for both services (or an
      explicit ``(empty / default)`` marker so the agent knows to
      leave the TODO stub instead of inventing data),
    * a pointer at the curated context-lookup paths
      (``implementation-storage-positions.md §5.1``) so the agent
      knows to search the seven seeded locations first instead of
      grep-ing the whole tree,
    * a one-line contract reminder so the agent doesn't forget to
      flip ``retVal = E_OK`` and remove the marker once the body is
      in place.
    """
    classification = classify_storage(did)
    has_real_22 = not _looks_like_default_behaviour(did.behavior_22)
    has_real_2e = not _looks_like_default_behaviour(did.behavior_2e)
    if did.rw_state == "RW":
        has_real_behaviour = has_real_22 or has_real_2e
    else:
        has_real_behaviour = has_real_22

    lines: List[str] = []
    lines.append(
        f"\t *   TODO(agent): replace this stub with the real {kind} "
        f"{svc_label} body."
    )
    lines.append("\t *   --- Identity --------------------------------------")
    lines.append(f"\t *   did_hex     : {did.did_hex}")
    lines.append(f"\t *   did_name    : {did.did_name}")
    if did.did_name_zh:
        lines.append(f"\t *   did_name_zh : {did.did_name_zh}")
    lines.append(f"\t *   data_type   : {did.data_type}")
    lines.append(f"\t *   size_bytes  : {did.size_bytes}")
    lines.append(f"\t *   storage_pos : {did.storage_pos}")
    if did.product_type:
        lines.append(f"\t *   product_type: {did.product_type}")
    lines.append("\t *   --- Storage class ---------------------------------")
    lines.append(f"\t *   class       : {classification.klass}")
    if classification.ram_subpattern:
        lines.append(f"\t *   RAM pattern : {classification.ram_subpattern}")
    lines.append(f"\t *   rationale   : {classification.rationale}")
    lines.append("\t *   --- Style constraints (mandatory) -----------------")
    lines.append(
        "\t *   - The function body MUST be MISRA-C compliant"
    )
    lines.append(
        "\t *     (one statement per line, explicit casts on mixed-"
    )
    lines.append(
        "\t *     type arithmetic, no fall-through in switch, every"
    )
    lines.append(
        "\t *     return path explicitly assigned, no unbalanced"
    )
    lines.append(
        "\t *     braces, no implicit conversions losing precision)."
    )
    lines.append(
        "\t *   - If the body uses any *MESGDef macro family"
    )
    lines.append(
        "\t *     (sub-pattern B: DefineMESGDef + RcvMESGDef pair,"
    )
    lines.append(
        "\t *     or sub-pattern C: RBMESG_DefineMESGDef +"
    )
    lines.append(
        "\t *     RBMESG_RcvMESGDef pair):"
    )
    lines.append(
        "\t *       * BOTH macros of the pair MUST be present —"
    )
    lines.append(
        "\t *         a Define without its matching Rcv (or vice"
    )
    lines.append(
        "\t *         versa) will fail to link."
    )
    lines.append(
        "\t *       * They MUST appear as the FIRST two statements"
    )
    lines.append(
        "\t *         inside the enclosing #if (RBFS_DCOMDomain"
    )
    lines.append(
        "\t *         == ...) guard, before any read / logic /"
    )
    lines.append(
        "\t *         assignment statement."
    )
    lines.append("\t *   --- FSCS Behavior (the implementation prompt) -----")
    lines.extend(_format_behaviour_block("0x22 (Read)", did.behavior_22))
    if did.rw_state == "RW":
        lines.extend(_format_behaviour_block("0x2E (Write)", did.behavior_2e))
    lines.append("\t *   --- Agent contract --------------------------------")
    lines.append(
        "\t *   Playbook    : reference/implementation-storage-positions.md"
    )
    lines.append(
        "\t *   Context paths (search these FIRST, see playbook §5.1):"
    )
    lines.append(
        "\t *     1. Fe_Super/rb/as/cnms_core/app/dcom"
    )
    lines.append(
        "\t *     2. Fe_Super/rb/as/core/app/dcom"
    )
    lines.append(
        "\t *     3. Fe_Super/rb/as/<customer>/core/app/dcom"
    )
    lines.append(
        "\t *     4. Fe_Super/rb/as/<customer>/<product>/app/asw/aswif"
    )
    lines.append(
        "\t *     5. Fe_Super/rb/as/<customer>/<product>/dcompr"
    )
    lines.append(
        "\t *     6. Fe_Super/rb/as/<customer>/<product>/cswpr"
    )
    lines.append(
        "\t *     7. Fe_Super/rb/as/<customer>/csw/project"
    )
    lines.append(
        "\t *     (<customer> baked into paths.base_dir at init time;"
    )
    lines.append(
        "\t *      <product> is the lower-case product slug — e.g."
    )
    lines.append(
        "\t *      'dpb' / 'esp' / 'ipb'. Edits to .bcfg / .h / RBFS_*"
    )
    lines.append(
        "\t *      switches follow playbook §5.2 — stop and ASK before"
    )
    lines.append(
        "\t *      touching operator-set values, customer-shipped"
    )
    lines.append(
        "\t *      headers, or unrelated DIDs.)"
    )
    if has_real_behaviour:
        lines.append(
            "\t *   Action      : behaviour is populated — replace this "
            "TODO with the real body, flip"
        )
        lines.append(
            "\t *                  retVal = E_NOT_OK -> E_OK, and delete "
            "this TODO(agent) line."
        )
    else:
        lines.append(
            "\t *   Action      : behaviour is empty / default — LEAVE "
            "this TODO(agent) stub in place."
        )
        lines.append(
            "\t *                  Edit the FSCS behavior text upstream "
            "first, then re-run Phase 3."
        )
    return "\n".join(lines)


# ----------------------------- PDM + header macros ---------------------------


def _storage_kind_label(storage_pos: str) -> str:
    """Human-readable storage-kind label for skeleton-code comments.

    ``EEPROM`` → full NvM-backed read/write body (uses its own literal).
    ``RAM``    → volatile runtime scratch; future release will emit an
                 in-memory get/set pair.
    ``ROM``    → compile-time-constant (``FLASH`` is canonicalised to
                 ``ROM`` at load time -- see ``fscs.schema``); future
                 release will emit a ``memcpy`` from a static const
                 table. The label lets reviewers tell the three apart
                 in the generated ``.c`` skeletons without having to
                 cross-reference ``fscs.json``.
    """
    kind = (storage_pos or "").upper()
    if kind == "RAM":
        return "RAM"
    if kind == "ROM":
        return "ROM/Flash"
    # Any other non-EEPROM value -- shouldn't reach here in practice
    # because pydantic's Literal already rejects unknown kinds, but
    # fail-soft so a future literal extension keeps working.
    return kind or "non-EEPROM"


def generate_pdm_entry(did: DIDImplementationInfo,
                       writecycles: int = 1000,
                       fs_prefix: str = FS_MACRO_PREFIX) -> str:
    """Render the PDM entry for an EEPROM DID (empty string for RAM/ROM)."""
    if did.storage_pos.upper() != 'EEPROM':
        return ""

    if did.nvm_item:
        nvm_id = get_nvm_id(did.nvm_item)
    else:
        nvm_id = capitalize_first(did.did_name)

    fs_macro = get_fs_macro(did.did_name, fs_prefix=fs_prefix)
    return _render("impl/pdm_entry.j2", {
        "fs_macro": fs_macro,
        "nvm_id": nvm_id,
        "writecycles": writecycles,
    })


def generate_config_macro(did: DIDImplementationInfo,
                          fs_prefix: str = FS_MACRO_PREFIX) -> str:
    """Render the ``Config.h`` Feature Switch macro block for a DID."""
    fs_macro = get_fs_macro(did.did_name, fs_prefix=fs_prefix)
    did_hex_clean = did.did_hex.replace('0x', '').upper()
    return _render("impl/config_macro.j2", {
        "fs_macro": fs_macro,
        "did_hex_clean": did_hex_clean,
        "did_name": did.did_name,
    })


def generate_config_settings_macro(did: DIDImplementationInfo,
                                   fs_prefix: str = FS_MACRO_PREFIX) -> str:
    """Render the ``ConfigSettings.h`` activation block for a DID."""
    fs_macro = get_fs_macro(did.did_name, fs_prefix=fs_prefix)
    did_hex_clean = did.did_hex.replace('0x', '').upper()
    return _render("impl/config_settings_macro.j2", {
        "fs_macro": fs_macro,
        "did_hex_clean": did_hex_clean,
        "did_name": did.did_name,
    })


def generate_element_defs(did: DIDImplementationInfo,
                          fs_prefix: str = FS_MACRO_PREFIX) -> str:
    """Render the ``ConfigElements.h`` ON/OFF definitions block for a DID."""
    fs_macro = get_fs_macro(did.did_name, fs_prefix=fs_prefix)
    on_def = f"{fs_macro}_ON"
    off_def = f"{fs_macro}_OFF"
    did_hex_clean = did.did_hex.replace('0x', '').upper()
    on_padding = max(1, 72 - len(on_def))
    off_padding = max(1, 72 - len(off_def))
    return _render("impl/element_defs.j2", {
        "fs_macro": fs_macro,
        "did_hex_clean": did_hex_clean,
        "did_name": did.did_name,
        "on_def": on_def,
        "off_def": off_def,
        "on_padding_str": ' ' * on_padding,
        "off_padding_str": ' ' * off_padding,
    })


def generate_range_macros(did: DIDImplementationInfo) -> str:
    """Render value-range ``#define`` block for a DID.

    Only EEPROM DIDs that actually have a Value Range produce macros;
    everything else returns ``""``. Matches the inputs expected by the
    ARXML/Implementation reviewers in :mod:`scripts.review_impl`.
    """
    if did.storage_pos.upper() != 'EEPROM' or not did.value_range:
        return ""

    macros = []
    if did.is_enum and did.enum_values:
        for i, val in enumerate(did.enum_values):
            macro_name = get_range_macro_name(did.did_hex, f"VAL_{i}")
            macros.append(f"#define {macro_name}\t\t{val}")
    elif did.numeric_min and did.numeric_max:
        min_macro = get_range_macro_name(did.did_hex, "MIN")
        max_macro = get_range_macro_name(did.did_hex, "MAX")
        macros.append(f"#define {min_macro}\t\t{did.numeric_min}")
        macros.append(f"#define {max_macro}\t\t{did.numeric_max}")

    return '\n'.join(macros) + '\n\n' if macros else ""


# ----------------------------- C source (RDBI/WDBI) --------------------------


def generate_enum_conditions(did: DIDImplementationInfo) -> str:
    """Build the ``(Data[0] == X) || (Data[0] == Y) || ...`` guard.

    Used by :func:`generate_write_code` for enum-ranged DIDs. Returns
    empty string when ``did.enum_values`` is empty.
    """
    if not did.enum_values:
        return ""
    conditions = []
    for i, _ in enumerate(did.enum_values):
        macro_name = get_range_macro_name(did.did_hex, f"VAL_{i}")
        conditions.append(f"(Data[0] == {macro_name})")
    return ' || '.join(conditions)


def _build_read_func_body(did: DIDImplementationInfo, fs_macro: str,
                          func_name_only: str) -> str:
    """Build the ``ReadData`` function body (between the outer ``{...}``)."""
    pos = did.storage_pos.upper()
    if pos == 'EEPROM':
        nvm_id = did.nvm_item.strip() if did.nvm_item else f"NVM_{func_name_only}"
        return (
            "\t/* Return value initialization */\n"
            "\tStd_ReturnType retVal = E_NOT_OK;\n"
            f"#if({fs_macro} == {fs_macro}_ON)\n"
            f"\t/* DID: {did.did_hex} - {did.did_name}\n"
            "\t * Operation: Read data from NVM (EEPROM)\n"
            f"\t * NVM Block: {nvm_id}\n"
            f"\t * Size: {did.size_bytes} bytes\n"
            "\t * Default value: 0xFF */\n"
            f"\tretVal = DCOM_ReadDataByNVMId(NvMConf_NvMBlockDescriptor_{nvm_id}, "
            f"Data, NVM_CFG_NV_BLOCK_LENGTH_{nvm_id}, 0xFF);\n"
            "#endif\n"
            "\treturn retVal;"
        )

    if pos in ("ROM", "FLASH"):
        # v2.4.0: HardCode DIDs — auto-generate the Data[i] = C_DID_..._UB;
        # copy body.  The matching header is generated separately by
        # :func:`generate_did_header`.
        size_bytes = int(did.size_bytes or 0)
        data_lines = "\n".join(
            f"\tData[{i}] = C_DID_{func_name_only}_Byte{i}_UB;"
            for i in range(size_bytes)
        )
        return (
            "\t/* Return value initialization */\n"
            "\tStd_ReturnType retVal = E_NOT_OK;\n"
            f"#if({fs_macro} == {fs_macro}_ON)\n"
            f"\t/* DID: {did.did_hex} - {did.did_name}\n"
            "\t * Operation: Read data (ROM/Flash storage)\n"
            f"\t * Size: {did.size_bytes} bytes\n"
            "\t * Source: C_DID_..._UB macros in matching .h */\n"
            f"{data_lines}\n"
            "\tretVal = E_OK;\n"
            "#endif\n"
            "\treturn retVal;"
        )

    # RAM — keep the TODO(agent) stub for agent fill-in.
    kind = _storage_kind_label(did.storage_pos)
    todo_block = _build_inline_todo_block(did, kind, "read")
    return (
        "\t/* Return value initialization */\n"
        "\tStd_ReturnType retVal = E_NOT_OK;\n"
        f"#if({fs_macro} == {fs_macro}_ON)\n"
        f"\t/* DID: {did.did_hex} - {did.did_name}\n"
        f"\t * Operation: Read data ({kind} storage)\n"
        f"\t * Size: {did.size_bytes} bytes\n"
        "\t *\n"
        f"{todo_block} */\n"
        "#endif\n"
        "\treturn retVal;"
    )


def generate_read_code(did: DIDImplementationInfo,
                       fs_prefix: str = FS_MACRO_PREFIX) -> str:
    """Render the full RDBI ``.c`` source for a DID."""
    is_eeprom = did.storage_pos.upper() == 'EEPROM'
    func_name = get_func_name(did)
    func_name_only = capitalize_first(clean_name(did.did_name))
    fs_macro = get_fs_macro(did.did_name, fs_prefix=fs_prefix)

    func_body = _build_read_func_body(did, fs_macro, func_name_only)
    return _render("impl/read_code.j2", {
        "is_eeprom": is_eeprom,
        "storage_pos": did.storage_pos.upper(),
        "func_name": func_name,
        "func_name_only": func_name_only,
        "fs_macro": fs_macro,
        "func_body": func_body,
    })


def _build_write_func_body(did: DIDImplementationInfo, fs_macro: str,
                           nvm_id: str, mode: str) -> str:
    """Build the WDBI function body. ``mode`` in
    ``non_eeprom | enum | range | no_range``."""
    if mode == "non_eeprom":
        kind = _storage_kind_label(did.storage_pos)
        # Inline TODO block (no brief pointer). ROM + RW is a
        # configuration smell (ROM is read-only); the behaviour block
        # surfaces it so the operator either drops the write side or
        # reclassifies the DID.
        todo_block = _build_inline_todo_block(did, kind, "write")
        return (
            "\t/* Return value initialization */\n"
            "\tStd_ReturnType retVal = E_NOT_OK;\n"
            f"#if({fs_macro} == {fs_macro}_ON)\n"
            f"\t/* DID: {did.did_hex} - {did.did_name}\n"
            f"\t * Operation: Write data ({kind} storage)\n"
            f"\t * Size: {did.size_bytes} bytes\n"
            "\t *\n"
            f"{todo_block} */\n"
            "#endif\n"
            "\treturn retVal;"
        )
    if mode == "enum":
        enum_conditions = generate_enum_conditions(did)
        enum_values_str = ', '.join(did.enum_values)
        return (
            "\t/* Return value initialization */\n"
            "\tStd_ReturnType retVal = E_NOT_OK;\n"
            f"#if({fs_macro} == {fs_macro}_ON)\n"
            f"\t/* DID: {did.did_hex} - {did.did_name}\n"
            "\t * Operation: Write data to NVM (EEPROM) with enum value validation\n"
            f"\t * Valid values: {enum_values_str}\n"
            f"\t * Size: {did.size_bytes} bytes\n"
            f"\t * NVM Block: {nvm_id} */\n"
            f"\tif({enum_conditions})\n"
            "\t{\n"
            "\t\t/* Valid enum value - perform NVM write operation */\n"
            f"\t\tretVal = DCOM_WriteDataByNVMId(NvMConf_NvMBlockDescriptor_{nvm_id}, Data, ErrorCode);\n"
            "\t}\n"
            "\telse\n"
            "\t{\n"
            "\t\t/* Invalid enum value - return request out of range */\n"
            "\t\t*ErrorCode = DCM_E_REQUESTOUTOFRANGE;\n"
            "\t}\n"
            "#else\n"
            "\t/* Feature switch disabled - return request out of range */\n"
            "\t*ErrorCode = DCM_E_REQUESTOUTOFRANGE;\n"
            "#endif\n"
            "\treturn retVal;"
        )
    if mode == "range":
        min_macro = get_range_macro_name(did.did_hex, "MIN")
        max_macro = get_range_macro_name(did.did_hex, "MAX")
        return (
            "\t/* Return value initialization */\n"
            "\tStd_ReturnType retVal = E_NOT_OK;\n"
            f"#if({fs_macro} == {fs_macro}_ON)\n"
            f"\t/* DID: {did.did_hex} - {did.did_name}\n"
            "\t * Operation: Write data to NVM (EEPROM) with numeric range validation\n"
            f"\t * Valid range: {did.numeric_min} ~ {did.numeric_max}\n"
            f"\t * Size: {did.size_bytes} bytes\n"
            f"\t * NVM Block: {nvm_id} */\n"
            f"\tif((Data[0] <= {max_macro}) && (Data[0] >= {min_macro}))\n"
            "\t{\n"
            "\t\t/* Value within valid range - perform NVM write operation */\n"
            f"\t\tretVal = DCOM_WriteDataByNVMId(NvMConf_NvMBlockDescriptor_{nvm_id}, Data, ErrorCode);\n"
            "\t}\n"
            "\telse\n"
            "\t{\n"
            "\t\t/* Value out of range - return request out of range */\n"
            "\t\t*ErrorCode = DCM_E_REQUESTOUTOFRANGE;\n"
            "\t}\n"
            "#else\n"
            "\t/* Feature switch disabled - return request out of range */\n"
            "\t*ErrorCode = DCM_E_REQUESTOUTOFRANGE;\n"
            "#endif\n"
            "\treturn retVal;"
        )
    # mode == "no_range"
    return (
        "\t/* Return value initialization */\n"
        "\tStd_ReturnType retVal = E_NOT_OK;\n"
        f"#if({fs_macro} == {fs_macro}_ON)\n"
        f"\t/* DID: {did.did_hex} - {did.did_name}\n"
        "\t * Operation: Write data to NVM (EEPROM) without value range restriction\n"
        f"\t * Size: {did.size_bytes} bytes\n"
        f"\t * NVM Block: {nvm_id} */\n"
        f"\tretVal = DCOM_WriteDataByNVMId(NvMConf_NvMBlockDescriptor_{nvm_id}, Data, ErrorCode);\n"
        "#else\n"
        "\t/* Feature switch disabled - return request out of range */\n"
        "\t*ErrorCode = DCM_E_REQUESTOUTOFRANGE;\n"
        "#endif\n"
        "\treturn retVal;"
    )


def _build_write_value_range_block(did: DIDImplementationInfo, mode: str) -> str:
    """Build the ``/* Value Range Definitions */`` section for WDBI.

    Returns the text to splice between ``RB_ASSERT_SWITCH_SETTINGS(...);``
    and the function header comment block -- including the surrounding
    blank lines so the template never has to reason about newlines.
    """
    if mode in ("non_eeprom", "no_range"):
        return "\n\n"
    lines = ["", "/* Value Range Definitions */"]
    if mode == "enum":
        for i, val in enumerate(did.enum_values):
            macro_name = get_range_macro_name(did.did_hex, f"VAL_{i}")
            lines.append(f"#define {macro_name}\t\t{val}")
    elif mode == "range":
        min_macro = get_range_macro_name(did.did_hex, "MIN")
        max_macro = get_range_macro_name(did.did_hex, "MAX")
        lines.append(f"#define {min_macro}\t\t{did.numeric_min}")
        lines.append(f"#define {max_macro}\t\t{did.numeric_max}")
    return "\n".join(lines) + "\n\n"


def generate_write_code(did: DIDImplementationInfo,
                        fs_prefix: str = FS_MACRO_PREFIX) -> str:
    """Render the full WDBI ``.c`` source for a RW DID (empty for R-only)."""
    if did.rw_state != 'RW':
        return ""

    is_eeprom = did.storage_pos.upper() == 'EEPROM'
    func_name = get_func_name(did)
    func_name_only = capitalize_first(clean_name(did.did_name))
    fs_macro = get_fs_macro(did.did_name, fs_prefix=fs_prefix)

    if not is_eeprom:
        mode = "non_eeprom"
        nvm_id = ""
    else:
        nvm_id = did.nvm_item.strip() if did.nvm_item else f"NVM_ID_DCOM_{func_name}"
        if did.is_enum and did.enum_values:
            mode = "enum"
        elif did.numeric_min and did.numeric_max:
            mode = "range"
        else:
            mode = "no_range"

    func_body = _build_write_func_body(did, fs_macro, nvm_id, mode)
    value_range_block = _build_write_value_range_block(did, mode)

    return _render("impl/write_code.j2", {
        "is_eeprom": is_eeprom,
        "func_name": func_name,
        "func_name_only": func_name_only,
        "fs_macro": fs_macro,
        "func_body": func_body,
        "value_range_block": value_range_block,
    })


def generate_did_header(did: DIDImplementationInfo) -> str:
    """Render the per-DID ``RBAPLCUST_RDBI_<DidName>.h`` header.

    v2.4.0: For HardCode (ROM/Flash) DIDs, parses the FSCS behavior
    text and emits a ``#define C_DID_<Name>_Byte<N>_UB`` ladder.
    Returns empty string for non-HardCode DIDs.
    """
    pos = (did.storage_pos or "").upper()
    if pos not in ("ROM", "FLASH"):
        return ""

    func_name_only = capitalize_first(clean_name(did.did_name))
    behavior = did.behavior_22 or ""
    size_bytes = int(did.size_bytes or 0)

    byte_values = parse_hardcode_values(behavior, func_name_only, size_bytes)
    define_lines = build_define_lines(func_name_only, byte_values)

    did_hex_clean = did.did_hex.replace('0x', '').upper()
    return _render("impl/did_header.j2", {
        "did_hex": did_hex_clean,
        "did_name": did.did_name,
        "size_bytes": size_bytes,
        "func_name_only": func_name_only,
        "define_lines": '\n'.join(define_lines),
    })
