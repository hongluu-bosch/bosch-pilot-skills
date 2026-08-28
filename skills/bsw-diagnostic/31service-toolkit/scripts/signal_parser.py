"""
31service-toolkit - Signal parser for natural language signal descriptions.

Parses user natural language signal definitions into structured signal specs
with auto-computed pos/len/type/endianness.

Supported syntax:
  - "UINT8 + UINT16 + UINT32"
  - "UINT8_N(64bit) + SINT16"
  - "BOOLEAN"
  - Separators: comma, +, 和

Array types MUST include unit: *_N(<value>bit) or *_N(<value>Byte)
"""

import re

# Valid primitive types and their bit lengths
PRIMITIVE_LENGTHS = {
    "UINT8": 8,
    "UINT16": 16,
    "UINT32": 32,
    "SINT8": 8,
    "SINT16": 16,
    "SINT32": 32,
    "BOOLEAN": 8,
}

# Types that support array form with explicit length
ARRAY_TYPES = {"UINT8_N", "UINT16_N", "UINT32_N", "SINT8_N", "SINT16_N", "SINT32_N", "BOOLEAN_N"}

# Separator patterns
SPLIT_PATTERNS = re.compile(r"[,+，]|和")


def parse_signal_string(signal_str):
    """
    Parse a signal definition string into a list of signal specs.

    Args:
        signal_str: e.g. "UINT8 + UINT16" or "UINT8_N(64bit)"

    Returns:
        (signals, error) where signals is a list of dicts:
          [{"type": "UINT8", "length": 8, "pos": 0}, ...]
        error is None if OK, else a string.
    """
    if signal_str is None:
        return None, None

    signal_str = str(signal_str).strip()
    if not signal_str:
        return None, None

    # Split by separators
    parts = [p.strip() for p in SPLIT_PATTERNS.split(signal_str) if p.strip()]
    if not parts:
        return None, "No valid signal types found in input"

    signals = []
    current_pos = 0

    for part in parts:
        sig, err = _parse_single_signal(part)
        if err:
            return None, err
        sig["pos"] = current_pos
        current_pos += sig["length"]
        signals.append(sig)

    return signals, None


def _parse_single_signal(token):
    """
    Parse a single signal token.

    Returns dict with keys: type, length
    or (None, error_message)
    """
    token = token.strip().upper()

    # Check for array form: TYPE_N(valueunit)
    array_match = re.match(r"^(\w+)_N\((\d+)\s*(BIT|BYTE|BITS|BYTES)\)$", token, re.IGNORECASE)
    if array_match:
        base_type = array_match.group(1).upper()
        value = int(array_match.group(2))
        unit = array_match.group(3).upper()

        if base_type + "_N" not in ARRAY_TYPES:
            return None, f"Invalid array type: {base_type}_N. Supported: {', '.join(sorted(ARRAY_TYPES))}"

        if unit in ("BYTE", "BYTES"):
            bit_length = value * 8
        else:
            bit_length = value

        return {"type": f"{base_type}_N", "length": bit_length}, None

    # Check for primitive type
    if token in PRIMITIVE_LENGTHS:
        return {"type": token, "length": PRIMITIVE_LENGTHS[token]}, None

    # Check if user tried array without unit (reject)
    if re.match(r"^\w+_N\(\d+\)$", token):
        return None, (
            f"Array type '{token}' is missing unit. "
            f"Use format: TYPE_N(<value>bit) or TYPE_N(<value>Byte). "
            f"Example: UINT8_N(64bit) or UINT8_N(8Byte)"
        )

    return None, f"Unknown signal type: '{token}'. Supported types: {', '.join(sorted(PRIMITIVE_LENGTHS.keys()))}"


def get_default_signals():
    """Return default signal spec: UINT8_N(8bit)."""
    return [{"type": "UINT8_N", "length": 8, "pos": 0}]


if __name__ == "__main__":
    # Self-test
    test_cases = [
        "UINT8 + UINT16",
        "UINT8_N(64bit)",
        "UINT8_N(8Byte)",
        "BOOLEAN + SINT32",
        "UINT8_N(64)",  # should fail - no unit
        "UNKNOWN_TYPE",  # should fail
        "",
        None,
    ]

    for tc in test_cases:
        print(f"\nInput: {tc!r}")
        signals, err = parse_signal_string(tc)
        if err:
            print(f"  ERROR: {err}")
        elif signals is None:
            print(f"  -> None (empty input)")
        else:
            for i, sig in enumerate(signals):
                print(f"  Signal {i}: type={sig['type']}, length={sig['length']}bit, pos={sig['pos']}")
