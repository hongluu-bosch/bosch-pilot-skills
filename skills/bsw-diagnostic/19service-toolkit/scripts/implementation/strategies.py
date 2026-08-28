from __future__ import annotations

from typing import List, Optional

from .analysis import Evidence
from .generator import (
    _build_getter_impl_content,
    _build_hybrid_three_byte_content,
    _build_mixed_pack_scaffold_content,
    _build_state_pack_scaffold_content,
    _build_simple_nibble_pack_content,
    _build_scalar_copy_sequence_content,
    _build_single_byte_bit_pack_content,
    _build_struct_be_with_qualifier_and_scaling_content,
    _build_struct_be_with_qualifier_content,
)
from .models import SnapshotDIDInfo


def build_real_content(did: SnapshotDIDInfo, record_numbers: List[str], evidence: Evidence) -> Optional[str]:
    if not evidence.can_generate or not evidence.strategy:
        return None

    items = [item.raw for item in evidence.signal_items]

    if evidence.strategy == "getter_scaled_byte":
        return _build_getter_impl_content(did, record_numbers, items[0])
    if evidence.strategy == "scalar_copy_sequence":
        return _build_scalar_copy_sequence_content(did, record_numbers, items)
    if evidence.strategy == "single_byte_bit_pack":
        return _build_single_byte_bit_pack_content(did, record_numbers, items)
    if evidence.strategy == "simple_nibble_pack":
        return _build_simple_nibble_pack_content(did, record_numbers, items)
    if evidence.strategy == "state_pack_scaffold":
        return _build_state_pack_scaffold_content(did, record_numbers, items)
    if evidence.strategy == "mixed_pack_scaffold":
        return _build_mixed_pack_scaffold_content(did, record_numbers, items)
    if evidence.strategy == "hybrid_three_byte":
        return _build_hybrid_three_byte_content(did, record_numbers, items)
    if evidence.strategy == "struct_be_with_qualifier":
        return _build_struct_be_with_qualifier_content(did, record_numbers, items)
    if evidence.strategy == "struct_be_with_qualifier_and_scaling":
        return _build_struct_be_with_qualifier_and_scaling_content(did, record_numbers, items)

    return None
