from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional


def resolve_snapshot_c_output_dir(config: Dict, product_type: str) -> Path:
    base_dir = Path(config["base_dir"])
    project_root = config.get("project_root", "")
    customer = config.get("customer_name", "customer")
    per_product = config.get("per_product", {}).get(product_type, {})
    rel_path: Optional[str] = per_product.get("snapshot_c_output_subdir")
    if rel_path is None:
        template = config.get("paths", {}).get(
            "snapshot_c_output_subdir",
            f"rb/as/{customer}/core/app/dcom/RBAPLCust/src/{{product_type}}",
        )
        rel_path = template.replace("{product_type}", product_type)
    return base_dir / project_root / rel_path
