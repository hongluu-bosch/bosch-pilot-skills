"""
31service-toolkit - RID validation utilities.
"""

import re


def parse_rid(value_str):
    """
    Parse a RID string (decimal or hex with 0x prefix).
    Returns (decimal_value, error_message) tuple.
    If valid, error_message is None.
    """
    if value_str is None or str(value_str).strip() == "":
        return None, None  # Empty means no change

    value_str = str(value_str).strip()

    # Hex format: 0x1234 or 0X1234
    hex_match = re.match(r"^0x([0-9A-Fa-f]+)$", value_str)
    if hex_match:
        try:
            decimal = int(hex_match.group(1), 16)
        except ValueError:
            return None, f"Invalid hex format: {value_str}"
    else:
        # Decimal format
        try:
            decimal = int(value_str)
        except ValueError:
            return None, f"Invalid RID format (must be decimal or 0x hex): {value_str}"

    # Validate range: 0 - 65535 (16-bit RID)
    if decimal < 0 or decimal > 65535:
        return None, f"RID out of range (must be 0-65535 or 0x0000-0xFFFF): {value_str} ({decimal})"

    return decimal, None


def format_rid(decimal):
    """Format a decimal RID as both decimal and hex strings."""
    return f"{decimal}", f"0x{decimal:04X}"


def validate_batch(updates):
    """
    Validate a batch of RID updates.
    updates: list of (short_name, new_rid_str) tuples.
    Returns (valid_updates, errors) where:
      valid_updates: list of (short_name, decimal_value)
      errors: list of (short_name, error_message)
    """
    valid = []
    errors = []
    for short_name, rid_str in updates:
        decimal, err = parse_rid(rid_str)
        if err:
            errors.append((short_name, err))
        elif decimal is not None:
            valid.append((short_name, decimal))
    return valid, errors


if __name__ == "__main__":
    # Self-test
    test_cases = [
        "1234",
        "0x1234",
        "0XABCD",
        "65535",
        "0xFFFF",
        "65536",
        "0x10000",
        "abc",
        "0xGGGG",
        "",
        None,
    ]
    for tc in test_cases:
        dec, err = parse_rid(tc)
        status = "OK" if err is None else f"ERROR: {err}"
        print(f"  {tc!r:15} -> {dec} ({status})")
