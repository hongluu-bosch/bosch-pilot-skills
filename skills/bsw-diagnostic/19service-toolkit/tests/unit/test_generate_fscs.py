import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "scripts"))

from generate_fscs import _render_fscs_19


def test_render_fscs_19():
    doc = {
        "service": "19",
        "subfunction": "0x04",
        "dids": [
            {
                "did_hex": "0x1100",
                "did_name_en": "Wheel Speed",
                "size_bytes": 10,
                "read_fnc": "RBAPLCUST_1100_WheelSpeed_ReadData",
                "used": True
            }
        ]
    }
    text = _render_fscs_19(doc)
    assert "$59" in text
    assert "NumberOfIdentifiers = 1" in text
    assert "RBAPLCUST_1100_WheelSpeed_ReadData" in text


if __name__ == "__main__":
    test_render_fscs_19()
    print("test_render_fscs_19 passed")
