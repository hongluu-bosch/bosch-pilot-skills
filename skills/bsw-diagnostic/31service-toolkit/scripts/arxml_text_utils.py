"""
31service-toolkit - ARXML text replacement utilities.
Shared pure-text RID replacement logic used by both diff_generator and update_arxml.
Locates the VALUE by routine context, not by old value matching.
"""

import re

__all__ = ["replace_routine_rid_in_text", "find_matching_container_end"]


def replace_routine_rid_in_text(content, routine_name, new_rid):
    """
    Locate the routine container by SHORT-NAME, then find the
    DcmDspRoutineIdentifier parameter and replace its VALUE.

    Returns modified content or None if failed.
    """
    # Step 1: Find the routine's SHORT-NAME tag
    short_name_tag = f"<SHORT-NAME>{routine_name}</SHORT-NAME>"
    sn_pos = content.find(short_name_tag)
    if sn_pos == -1:
        return None

    # Step 2: Find the end of this ECUC-CONTAINER-VALUE (the routine container)
    # We look for the </ECUC-CONTAINER-VALUE> that closes this routine
    # The routine container is a direct child, so we need to count nested containers
    search_start = sn_pos + len(short_name_tag)
    container_end = find_matching_container_end(content, search_start)
    if container_end == -1:
        return None

    container_text = content[sn_pos:container_end]

    # Step 3: Find DcmDspRoutineIdentifier DEFINITION-REF within this container
    identifier_pos = container_text.find("DcmDspRoutineIdentifier")
    if identifier_pos == -1:
        return None

    # Step 4: Find the next <VALUE>...</VALUE> after the identifier
    # Use regex to handle any whitespace/newlines between tags
    sub_region = container_text[identifier_pos:]
    match = re.search(r"<VALUE>([^<]*)</VALUE>", sub_region)
    if not match:
        return None

    # Step 5: Replace only this VALUE within the container
    old_value_tag = match.group(0)  # e.g., "<VALUE>61961</VALUE>"
    new_value_tag = f"<VALUE>{new_rid}</VALUE>"
    new_sub_region = sub_region.replace(old_value_tag, new_value_tag, 1)
    new_container_text = container_text[:identifier_pos] + new_sub_region

    # Step 6: Rebuild the full content
    new_content = content[:sn_pos] + new_container_text + content[container_end:]
    return new_content


def find_matching_container_end(content, start_pos):
    """
    Find the position of </ECUC-CONTAINER-VALUE> that closes the current container.
    Handles nested containers by counting open/close tags.
    Returns the position right after the closing tag, or -1 if not found.
    """
    open_tag = "<ECUC-CONTAINER-VALUE"
    close_tag = "</ECUC-CONTAINER-VALUE>"

    depth = 0
    pos = start_pos
    while True:
        next_open = content.find(open_tag, pos)
        next_close = content.find(close_tag, pos)

        if next_close == -1:
            return -1

        if next_open != -1 and next_open < next_close:
            depth += 1
            pos = next_open + len(open_tag)
        else:
            if depth == 0:
                return next_close + len(close_tag)
            depth -= 1
            pos = next_close + len(close_tag)
