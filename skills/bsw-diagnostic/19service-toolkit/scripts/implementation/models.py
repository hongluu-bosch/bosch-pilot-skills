from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SnapshotDIDInfo:
    did_hex: str
    did_name_en: str
    did_name_zh: str
    size_bytes: int
    read_fnc: str
    product_type: str
    used: bool
    sub_fields: List[Dict[str, Any]] = field(default_factory=list)
    impl_signal_list: str = ""
    impl_notes: str = ""
