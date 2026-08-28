import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "scripts"))

from xlsx_parser import parse_freeze_frame_sheet


def test_parse_sample():
    fixture = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "sample_19.xlsx"
    doc = parse_freeze_frame_sheet(fixture, ["Common"])
    assert doc["service"] == "19"
    assert doc["subfunction"] == "0x04"
    dids = [d["did_hex"] for d in doc["dids"]]
    assert "0x1100" in dids
    assert "0x2113" not in dids, "strikethrough row must be ignored"
    assert doc["dids"][0]["size_bytes"] == 10


if __name__ == "__main__":
    test_parse_sample()
    print("test_parse_sample passed")
