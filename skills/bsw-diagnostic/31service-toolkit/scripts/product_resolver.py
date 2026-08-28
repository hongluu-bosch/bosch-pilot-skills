"""
31service-toolkit - Product name resolver.
Extracts explicitly mentioned product types from natural language requirements,
detects ambiguous / similar product names, and resolves modification scope.

Rules:
1. Exact match (case-insensitive) against available products.
2. Products NOT mentioned are automatically excluded (default unchanged).
3. Similarity detection: prefix containment (shorter is prefix of longer, e.g. IPB vs IPB11).
   When ambiguity is detected and user only mentioned one, agent must prompt.
4. Otherwise, distinct product names are treated as independent entities.
"""

import re


# Known aliases that map to multiple product types.
# Format: alias_lower -> [list of product names it could refer to]
KNOWN_ALIASES = {
    "xpb": ["IPB", "DPB"],
}


def is_similar_product(name1: str, name2: str) -> bool:
    """
    Determine if two product names are considered 'similar' and need
    user clarification when only one is explicitly mentioned.

    Criteria:
      a) Prefix containment: shorter is prefix of longer (IPB / IPB11)
    """
    n1 = name1.strip()
    n2 = name2.strip()
    if n1.lower() == n2.lower():
        return True

    # a) Prefix containment
    if n1.lower().startswith(n2.lower()) or n2.lower().startswith(n1.lower()):
        return True

    return False


def _find_special_ambiguities(mentioned: set, available: set) -> list:
    """
    Detect special cases where a mentioned name could map to multiple
    available products via shared substrings (e.g. XPB -> IPB + DPB).
    Returns list of tuples: (mentioned_name, [matched_available_names]).
    """
    ambiguities = []
    for m in mentioned:
        m_lower = m.lower()
        matches = [a for a in available if m_lower in a.lower() or a.lower() in m_lower]
        # Filter out exact matches and self-matches
        non_exact = [a for a in matches if a.lower() != m_lower]
        if len(non_exact) > 1:
            ambiguities.append((m, non_exact))
    return ambiguities


def extract_products(text: str, available_products: list) -> list:
    """
    Extract product names explicitly mentioned in the user's text.
    Uses case-insensitive exact matching against available_products.

    Returns a list of matched product names (using the casing from available_products),
    in the order they first appear in the text (duplicates removed).
    """
    if not text or not available_products:
        return []

    matched = []
    matched_lower = set()
    # Build a regex that matches any of the available product names as whole words
    # Sort by length descending so longer names match first (IPB11 before IPB)
    sorted_products = sorted(available_products, key=lambda x: len(x), reverse=True)
    escaped = [re.escape(p) for p in sorted_products]
    pattern = re.compile(
        r'(?<![A-Za-z0-9_])(?:' + '|'.join(escaped) + r')(?![A-Za-z0-9_])',
        re.IGNORECASE
    )

    for m in pattern.finditer(text):
        # Map back to original casing
        orig = next((p for p in available_products if p.lower() == m.group(0).lower()), m.group(0))
        if orig.lower() not in matched_lower:
            matched_lower.add(orig.lower())
            matched.append(orig)

    # Also scan for known aliases that map to multiple products
    for alias, candidates in KNOWN_ALIASES.items():
        alias_pat = re.compile(
            r'(?<![A-Za-z0-9_])' + re.escape(alias) + r'(?![A-Za-z0-9_])',
            re.IGNORECASE
        )
        if alias_pat.search(text):
            alias_upper = alias.upper()
            if alias_upper.lower() not in matched_lower:
                matched_lower.add(alias_upper.lower())
                matched.append(alias_upper)

    return matched


def resolve_products(text: str, available_products: list) -> dict:
    """
    Main entry point for product resolution.

    Args:
        text: user natural language requirement
        available_products: list of product type strings from scan (e.g. ['IPB','IPB11','Common','ESP','ESPCL'])

    Returns dict with keys:
        - explicit_products: set of product names the user explicitly mentioned
        - ambiguous_pairs: list of tuples (mentioned, [similar_available_products])
                           that require user clarification
        - suggested_modify: set of products that would be modified if ambiguities
                            are resolved in the most restrictive way (only exact matches)
    """
    if not available_products:
        return {
            "explicit_products": [],
            "ambiguous_pairs": [],
            "suggested_modify": []
        }

    explicit = extract_products(text, available_products)

    # Find similar products for each explicitly mentioned one
    ambiguous_pairs = []
    for m in explicit:
        similar = []
        for a in available_products:
            if a.lower() == m.lower():
                continue
            if is_similar_product(m, a):
                similar.append(a)
        if similar:
            ambiguous_pairs.append((m, similar))

    # Handle known aliases (e.g. XPB -> IPB, DPB)
    for m in explicit:
        m_lower = m.lower()
        if m_lower in KNOWN_ALIASES:
            ambiguous_pairs.append((m, KNOWN_ALIASES[m_lower]))

    # Special shared-substring ambiguities (fallback for unknown aliases)
    special = _find_special_ambiguities(explicit, set(available_products))
    for m, matches in special:
        # Merge into ambiguous_pairs if not already present
        existing = next((ap for ap in ambiguous_pairs if ap[0].lower() == m.lower()), None)
        if existing:
            merged = list(set(existing[1] + matches))
            ambiguous_pairs = [ap for ap in ambiguous_pairs if ap[0].lower() != m.lower()]
            ambiguous_pairs.append((m, merged))
        else:
            ambiguous_pairs.append((m, matches))

    # Suggested modify: only the explicitly mentioned exact matches
    suggested = list(explicit)

    return {
        "explicit_products": explicit,
        "ambiguous_pairs": ambiguous_pairs,
        "suggested_modify": suggested
    }


def format_ambiguity_prompt(ambiguous_pairs: list) -> str:
    """
    Generate a human-readable prompt asking the user to clarify ambiguous products.
    """
    if not ambiguous_pairs:
        return ""

    lines = ["检测到产品名称歧义，请确认修改范围："]
    for mentioned, similar in ambiguous_pairs:
        similar_str = ", ".join(similar)
        lines.append(f"  - 您提到了 '{mentioned}'，但项目中还存在相近产品：{similar_str}")
        lines.append(f"    请回复 '只改 {mentioned}' 或 '{mentioned} 和 {similar_str} 都改'")
    return "\n".join(lines)


if __name__ == "__main__":
    # Self-test
    available = ["IPB", "IPB11", "Common", "ESP", "ESPCL", "DPB", "RBU"]
    test_cases = [
        "把所有IPB的RID顺序分配到 0x3000-0x30FF",
        "把ESP和RBU的RID平移到 0xF100",
        "把XPB的RID改成 0xA100",  # ambiguous: could be IPB or DPB
        "修改所有RID",  # no explicit product
    ]
    for tc in test_cases:
        result = resolve_products(tc, available)
        print(f"Input: {tc!r}")
        print(f"  explicit_products: {result['explicit_products']}")
        print(f"  ambiguous_pairs: {result['ambiguous_pairs']}")
        print(f"  suggested_modify: {result['suggested_modify']}")
        if result['ambiguous_pairs']:
            print(format_ambiguity_prompt(result['ambiguous_pairs']))
        print()
