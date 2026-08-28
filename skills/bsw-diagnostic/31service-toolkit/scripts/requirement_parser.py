"""
31service-toolkit - Natural language requirement parser.
Parses user prompt text into structured command objects.
Supports 7 command types:
  A. sequential_assign  - assign all RIDs sequentially within a range
  B. offset_shift       - shift all RIDs by offset to start at a value
  C. clamp              - clamp RIDs within a range
  D. explicit_map       - map specific old RIDs to new values
  E. pattern_map        - map RIDs matching a pattern (e.g. 0xF1xx -> 0xA1xx)
  F. name_map           - map specific routine names to new RIDs
  G. add_routine        - add a new DcmDspRoutine entry
"""

import re
from validate_rid import parse_rid
from product_resolver import resolve_products


def _parse_range(text):
    """Parse a range like '0xF100-0xF1FF' or '61728-61951'. Returns (start, end) or (None, None, err)."""
    # Try hex patterns: 0xF100-0xF1FF, 0xF100~0xF1FF, 0xF100至0xF1FF, 0xF100到0xF1FF
    patterns = [
        r"(0x[0-9A-Fa-f]+)\s*[-~至到]\s*(0x[0-9A-Fa-f]+)",
        r"(0x[0-9A-Fa-f]+)\s+to\s+(0x[0-9A-Fa-f]+)",
        r"(\d+)\s*[-~至到]\s*(\d+)",
        r"(\d+)\s+to\s+(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            s, e = m.group(1), m.group(2)
            start, err1 = parse_rid(s)
            end, err2 = parse_rid(e)
            if err1 or err2:
                return None, None, f"Invalid range values: {s}, {e}"
            if start > end:
                start, end = end, start
            return start, end, None
    return None, None, "Could not parse range"


def _parse_explicit_mappings(text):
    """Parse explicit old->new mappings like '0xF100改成0xA100' or 'map 0xF100 to 0xA100'."""
    mappings = {}
    # Chinese: 把 0xF100 改成 0xA100, 将 0xF100 改为 0xA100
    chinese_pat = re.compile(
        r"(?:把|将)\s*([0-9A-Fa-fxX]+)\s*改[成为]\s*([0-9A-Fa-fxX]+)",
        re.IGNORECASE
    )
    # English: map 0xF100 to 0xA100, 0xF100 -> 0xA100
    english_pat = re.compile(
        r"(?:map\s+)?([0-9A-Fa-fxX]+)\s*(?:->|to)\s*([0-9A-Fa-fxX]+)",
        re.IGNORECASE
    )

    for pat in [chinese_pat, english_pat]:
        for m in pat.finditer(text):
            old_str, new_str = m.group(1), m.group(2)
            old_dec, err1 = parse_rid(old_str)
            new_dec, err2 = parse_rid(new_str)
            if err1 or err2:
                continue
            mappings[old_dec] = new_dec

    return mappings


def _parse_name_mappings(text):
    """Parse name->new RID mappings like 'Routine_FactoryReset改成0xA100'."""
    mappings = {}
    # Chinese: 把 Routine_Xxx 改成 0xA100
    # English: set Routine_Xxx to 0xA100, Routine_Xxx -> 0xA100
    patterns = [
        re.compile(r"(?:把|将)\s*([A-Za-z_][A-Za-z0-9_]*)\s*改[成为]\s*([0-9A-Fa-fxX]+)", re.IGNORECASE),
        re.compile(r"(?:set|map)\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:to|->)\s*([0-9A-Fa-fxX]+)", re.IGNORECASE),
        re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:->|to)\s*([0-9A-Fa-fxX]+)", re.IGNORECASE),
    ]

    for pat in patterns:
        for m in pat.finditer(text):
            name, new_str = m.group(1), m.group(2)
            # Validate name looks like a routine name, not a number
            if re.match(r"^[0-9a-fA-FxX]+$", name):
                continue
            new_dec, err = parse_rid(new_str)
            if err:
                continue
            mappings[name] = new_dec

    return mappings


def _parse_add_routine(text):
    """
    Parse 'add new routine' commands.

    Recognized patterns:
      Chinese: 新增/添加/创建 + [Product] + Routine/Routine + <Name> + [RID <value>]
      English: add/create/new + routine + <name> + [to/for <product>] + [RID <value>]

    Signal descriptions:
      - Start 输入 / Start input: <signal_string>
      - Start 输出 / Start output: <signal_string>
      - Stop 输出 / Stop output: <signal_string>
      - Result 输出 / Result output / Request result: <signal_string>

    Returns dict with keys: product, rid, routine_name, signals_start_in,
    signals_start_out, signals_stop_out, signals_result_out
    or None if text doesn't match add routine pattern.
    """
    text_stripped = text.strip()

    # --- Detect add routine intent ---
    add_keywords_zh = r"(?:新增|添加|创建)"
    add_keywords_en = r"(?:\badd\b|\bcreate\b|\bnew\b)"

    has_add_intent = re.search(add_keywords_zh, text_stripped, re.IGNORECASE) or \
                     re.search(add_keywords_en, text_stripped, re.IGNORECASE)

    if not has_add_intent:
        return None

    # Must also contain "routine" or "Routine" (in English) or be a clear routine creation context
    has_routine_keyword = re.search(r"\broutine\b|Routine|例行程序|例程", text_stripped, re.IGNORECASE)
    if not has_routine_keyword:
        return None

    # --- Extract RID ---
    rid_decimal = None
    # Patterns: RID 0xF200, rid 0xF200, RID=0xF200
    rid_patterns = [
        r"(?:RID|rid)\s*[:=]?\s*(0x[0-9A-Fa-f]+|\d+)",
        r"(?:RID|rid)\s+(?:is|为|等于)?\s*(0x[0-9A-Fa-f]+|\d+)",
    ]
    for pat in rid_patterns:
        m = re.search(pat, text_stripped, re.IGNORECASE)
        if m:
            rid_decimal, err = parse_rid(m.group(1))
            if not err:
                break

    # If no explicit RID keyword, try to find any standalone hex/decimal that could be RID
    if rid_decimal is None:
        # Look for hex/decimal numbers that aren't part of signal specs
        # Avoid matching numbers inside signal specs like UINT8_N(64bit)
        for m in re.finditer(r"\b(0x[0-9A-Fa-f]+)\b", text_stripped, re.IGNORECASE):
            rid_decimal, err = parse_rid(m.group(1))
            if not err:
                break

    # --- Extract routine name ---
    routine_name = None
    # Pattern: Routine <Name>, routine <Name>, routine_name=<Name>, routine name=<Name>
    name_patterns = [
        r"routine_name\s*[:=]\s*([A-Za-z_][A-Za-z0-9_]*)\b",
        r"(?:routine\s+name|RoutineName)\s*[:=]\s*([A-Za-z_][A-Za-z0-9_]*)\b",
        r"(?:Routine|例行程序|例程)\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    ]
    for pat in name_patterns:
        m = re.search(pat, text_stripped, re.IGNORECASE)
        if m:
            candidate = m.group(1)
            # Exclude common keywords and product types that might be misidentified
            excluded_keywords = (
                "RID", "START", "STOP", "RESULT", "INPUT", "OUTPUT", "TO", "FOR", "IN", "WITH",
                "COMMON", "IPB", "IPB11", "ESP", "ESPCL", "DPB", "RBU", "TPMS"
            )
            if candidate.upper() not in excluded_keywords:
                routine_name = candidate
                break

    if routine_name is None:
        # Fallback: look for a capitalized word that might be the routine name
        # Pattern: after product name, look for the next capitalized identifier
        # This is heuristic
        words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text_stripped)
        for w in words:
            w_upper = w.upper()
            if w_upper in ("ROUTINE", "RID", "START", "STOP", "RESULT", "INPUT", "OUTPUT",
                           "ADD", "CREATE", "NEW", "TO", "FOR", "IN", "WITH", "AND",
                           "COMMON", "IPB", "IPB11", "ESP", "ESPCL", "DPB", "RBU", "TPMS"):
                continue
            # Looks like a routine name
            if len(w) > 2 and (w[0].isupper() or "_" in w):
                routine_name = w
                break

    if routine_name is None:
        return None  # Can't identify a routine name

    # --- Extract signals ---
    def _extract_signal_section(text, keywords):
        """Extract signal string after keywords. Supports =, :, or space separator."""
        for kw in keywords:
            # Match keyword followed by =, :, or space.
            # Capture value until the next signals_ keyword or end of string.
            # Use negative lookahead to prevent swallowing subsequent signals_ sections.
            pattern = rf"{kw}(?:\s*[:=]\s*|\s+)((?:(?!signals_).)*?)(?=\s+signals_|\s*$)"
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                return val if val else None
        return None

    signals_start_in = _extract_signal_section(text_stripped, [
        r"signals_start_in", r"Start\s*输入", r"Start\s*input", r"输入信号"
    ])
    signals_start_out = _extract_signal_section(text_stripped, [
        r"signals_start_out", r"Start\s*输出", r"Start\s*output", r"输出信号"
    ])
    signals_stop_out = _extract_signal_section(text_stripped, [
        r"signals_stop_out", r"Stop\s*输出", r"Stop\s*output"
    ])
    signals_result_out = _extract_signal_section(text_stripped, [
        r"signals_result_out", r"Result\s*输出", r"Result\s*output", r"Request\s*result", r"结果输出"
    ])

    return {
        "rid": rid_decimal,
        "routine_name": routine_name,
        "signals_start_in": signals_start_in,
        "signals_start_out": signals_start_out,
        "signals_stop_out": signals_stop_out,
        "signals_result_out": signals_result_out,
    }


def _parse_pattern(text):
    """Parse pattern mapping like '0xF1xx改成0xA1xx'. Returns (old_pattern, new_pattern) or None."""
    # Match patterns with xx/?? wildcards in both old and new
    # Format: 0x + 2 fixed hex digits + 2 wildcards, e.g. 0xF1xx
    pat = re.compile(
        r"(0x[0-9A-Fa-f]{2}[xX?]{2})\s*(?:全部?)?(?:改[成为]|to|->|with)\s*(0x[0-9A-Fa-f]{2}[xX?]{2})",
        re.IGNORECASE
    )
    m = pat.search(text)
    if m:
        return m.group(1).upper().replace("?", "X"), m.group(2).upper().replace("?", "X")
    return None, None


def parse_requirement(text, available_products=None):
    """
    Parse user natural language requirement text.
    Returns dict with keys: command_type, targets, parameters, raw_text,
    explicit_products, ambiguous, modify_products
    or raises ValueError with descriptive message if unparseable.
    """
    if not text or not str(text).strip():
        raise ValueError("Requirement text is empty.")

    text_lower = text.lower()
    text_upper = text.upper()

    # --- Product resolution ---
    product_info = resolve_products(text, available_products or [])
    explicit_products = product_info["explicit_products"]
    ambiguous_pairs = product_info["ambiguous_pairs"]
    suggested_modify = product_info["suggested_modify"]

    # --- Type A: Sequential assign ---
    # Keywords: 顺序分配, assign sequentially, sequential allocation, etc.
    # Also allow plain "分配" if a range is present and no other command type matches.
    has_sequential_keyword = re.search(r"顺序分配|顺序分[配给]|\bsequential(?:ly)?\b", text, re.IGNORECASE)
    has_assign_keyword = re.search(r"\b(?:assign|allocate|map|distribute)\b|分配|分给|改成|改为|调整", text, re.IGNORECASE)
    # If no sequential keyword, check if there's a range and no other obvious command keywords
    if has_sequential_keyword and has_assign_keyword:
        # Direct sequential match
        pass
    elif has_assign_keyword:
        # Try to detect if it's a range assignment even without explicit sequential keyword
        # e.g., "把 IPB 的 RID 分配到 0x3000-0x30FF"
        # We only do this if there's a range in the text AND no explicit old->new mappings
        # (to avoid misclassifying explicit_map intents that happen to mention a range)
        start_test, end_test, err_test = _parse_range(text)
        if err_test is None and not _parse_explicit_mappings(text):
            # Treat as sequential assign
            has_sequential_keyword = True
    
    if has_sequential_keyword and has_assign_keyword:
        start, end, err = _parse_range(text)
        if err:
            raise ValueError(f"Could not parse range for sequential assignment: {err}")
        return {
            "command_type": "sequential_assign",
            "targets": "all",
            "parameters": {"start": start, "end": end},
            "raw_text": text,
            "explicit_products": list(explicit_products),
            "ambiguous": ambiguous_pairs,
            "modify_products": list(suggested_modify)
        }

    # --- Type B: Offset shift ---
    # Keywords: 平移, 偏移, shift, offset to
    if re.search(r"平移|偏移|\bshift\b|\boffset\b", text, re.IGNORECASE):
        # Find the first valid RID value in the text that serves as target
        # Try to match patterns like "to 0xB000", "start at 0xB000", or just the number
        shift_val_pat = re.compile(
            r"(?:to|at|by|为|到|至)\s*(?:start\s+at\s+)?(0x[0-9A-Fa-f]+|\d{3,})",
            re.IGNORECASE
        )
        m = shift_val_pat.search(text)
        if m:
            target_dec, err = parse_rid(m.group(1))
            if not err:
                return {
                    "command_type": "offset_shift",
                    "targets": "all",
                    "parameters": {"target_start": target_dec},
                    "raw_text": text,
                    "explicit_products": list(explicit_products),
                    "ambiguous": ambiguous_pairs,
                    "modify_products": list(suggested_modify)
                }
        # Fallback: just find any hex/decimal number in the text
        for match in re.finditer(r"(0x[0-9A-Fa-f]+|\d{3,})", text, re.IGNORECASE):
            target_dec, err = parse_rid(match.group(1))
            if not err:
                return {
                    "command_type": "offset_shift",
                    "targets": "all",
                    "parameters": {"target_start": target_dec},
                    "raw_text": text,
                    "explicit_products": list(explicit_products),
                    "ambiguous": ambiguous_pairs,
                    "modify_products": list(suggested_modify)
                }

    # --- Type C: Clamp / range restrict ---
    # Keywords: 确保在, 限制在, clamp, restrict to
    if re.search(r"确保.*在.*内|限制在|clamp|restrict\s+(?:to|within)", text, re.IGNORECASE):
        start, end, err = _parse_range(text)
        if err:
            raise ValueError(f"Could not parse range for clamp: {err}")
        return {
            "command_type": "clamp",
            "targets": "all",
            "parameters": {"min": start, "max": end},
            "raw_text": text,
            "explicit_products": list(explicit_products),
            "ambiguous": ambiguous_pairs,
            "modify_products": list(suggested_modify)
        }

    # --- Type E: Pattern map (check before explicit to avoid mis-match) ---
    old_pat, new_pat = _parse_pattern(text)
    if old_pat and new_pat:
        # Validate they are valid patterns with xx
        if "X" in old_pat and "X" in new_pat:
            return {
                "command_type": "pattern_map",
                "targets": "all",
                "parameters": {
                    "old_pattern": old_pat,
                    "new_pattern": new_pat
                },
                "raw_text": text,
                "explicit_products": list(explicit_products),
                "ambiguous": ambiguous_pairs,
                "modify_products": list(suggested_modify)
            }

    # --- Type D: Explicit map ---
    explicit_mappings = _parse_explicit_mappings(text)
    if explicit_mappings:
        return {
            "command_type": "explicit_map",
            "targets": list(explicit_mappings.keys()),
            "parameters": {"mappings": explicit_mappings},
            "raw_text": text,
            "explicit_products": list(explicit_products),
            "ambiguous": ambiguous_pairs,
            "modify_products": list(suggested_modify)
        }

    # --- Type F: Name map ---
    name_mappings = _parse_name_mappings(text)
    if name_mappings:
        return {
            "command_type": "name_map",
            "targets": list(name_mappings.keys()),
            "parameters": {"mappings": name_mappings},
            "raw_text": text,
            "explicit_products": list(explicit_products),
            "ambiguous": ambiguous_pairs,
            "modify_products": list(suggested_modify)
        }

    # --- Type G: Add new routine ---
    add_routine_info = _parse_add_routine(text)
    if add_routine_info:
        # Extract product from explicit_products or use first available
        product = None
        if explicit_products:
            product = list(explicit_products)[0]

        return {
            "command_type": "add_routine",
            "targets": [add_routine_info["routine_name"]],
            "parameters": {
                "product": product,
                "rid": add_routine_info["rid"],
                "routine_name": add_routine_info["routine_name"],
                "signals_start_in": add_routine_info["signals_start_in"],
                "signals_start_out": add_routine_info["signals_start_out"],
                "signals_stop_out": add_routine_info["signals_stop_out"],
                "signals_result_out": add_routine_info["signals_result_out"],
            },
            "raw_text": text,
            "explicit_products": list(explicit_products),
            "ambiguous": ambiguous_pairs,
            "modify_products": list(suggested_modify)
        }

    raise ValueError(
        "Could not understand requirement. Supported patterns:\n"
        "  - Sequential assign: '把所有RID顺序分配到 0xF100-0xF1FF'\n"
        "  - Offset shift: '把所有RID平移到 0xF100 起始'\n"
        "  - Clamp: '确保所有RID在 0xF100-0xF1FF 范围内'\n"
        "  - Explicit map: '把 0xF100 改成 0xA100，0xF101 改成 0xA101'\n"
        "  - Pattern map: '把 0xF1xx 全部改成 0xA1xx'\n"
        "  - Name map: '把 Routine_FactoryReset 改成 0xA100'\n"
        "  - Add routine: '新增 IPB Routine MyRoutine RID 0xF200'"
    )


def compute_new_rid(routine, command, all_routines_sorted=None):
    """
    Compute new RID for a single routine based on parsed command.
    routine: dict with keys: short_name, rid_decimal, rid_hex, product_type, arxml_path
    all_routines_sorted: full list sorted by (product_type, rid_decimal) for sequential assign
    Returns (new_rid_decimal, error_message). error_message is None if OK.
    """
    ctype = command["command_type"]
    params = command["parameters"]
    current = routine["rid_decimal"]

    if ctype == "offset_shift":
        target_start = params["target_start"]
        if all_routines_sorted is None:
            return None, "Offset shift requires full routine list"
        # Find current minimum
        min_rid = min(r["rid_decimal"] for r in all_routines_sorted)
        offset = target_start - min_rid
        new_rid = current + offset
        if new_rid < 0 or new_rid > 65535:
            return None, f"Shifted RID {new_rid} out of 0-65535 range for routine {routine['short_name']}"
        return new_rid, None

    elif ctype == "clamp":
        min_v = params["min"]
        max_v = params["max"]
        if current < min_v:
            return min_v, None
        elif current > max_v:
            return max_v, None
        else:
            return current, None  # No change

    elif ctype == "explicit_map":
        mappings = params["mappings"]
        if current in mappings:
            return mappings[current], None
        return current, None  # No change

    elif ctype == "pattern_map":
        old_pat = params["old_pattern"]
        new_pat = params["new_pattern"]
        # Pattern format: e.g. "F1XX" means match high nibble F, next nibble 1, low byte any
        # We compare hex string without 0x prefix
        current_hex = f"{current:04X}"
        # Build regex from pattern
        regex_parts = []
        for ch in old_pat:
            if ch == "X":
                regex_parts.append("[0-9A-Fa-f]")
            else:
                regex_parts.append(ch)
        regex_str = "^" + "".join(regex_parts) + "$"
        if re.match(regex_str, current_hex, re.IGNORECASE):
            # Build new hex: replace non-X positions from new_pat, keep X positions from current
            new_hex_chars = []
            for i, pch in enumerate(new_pat):
                if pch == "X":
                    new_hex_chars.append(current_hex[i])
                else:
                    new_hex_chars.append(pch)
            new_hex = "".join(new_hex_chars)
            new_dec = int(new_hex, 16)
            return new_dec, None
        return current, None  # No change

    elif ctype == "name_map":
        mappings = params["mappings"]
        name = routine["short_name"]
        if name in mappings:
            return mappings[name], None
        # Case-insensitive fallback
        for k, v in mappings.items():
            if k.lower() == name.lower():
                return v, None
        return current, None  # No change

    return None, f"Unknown command type: {ctype}"


if __name__ == "__main__":
    # Self-test
    test_cases = [
        "把所有RID顺序分配到 0xF100-0xF1FF",
        "把所有RID平移到 0xF100 起始",
        "确保所有RID在 0xF100-0xF1FF 范围内",
        "把 0xF100 改成 0xA100，0xF101 改成 0xA101",
        "把 0xF1xx 全部改成 0xA1xx",
        "把 Routine_FactoryReset 改成 0xA100",
        "map 0xF200 to 0xA200",
        "shift to 0xB000",
        "clamp to 0x1000-0x1FFF",
    ]
    for tc in test_cases:
        try:
            result = parse_requirement(tc)
            print(f"OK: {tc!r}")
            print(f"    -> {result['command_type']} {result['parameters']}")
        except ValueError as e:
            print(f"ERR: {tc!r}")
            print(f"    -> {e}")
