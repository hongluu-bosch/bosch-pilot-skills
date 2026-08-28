"""Unit test: DID name-collision protection for C-file output.

When two DIDs collapse to the same ``_capitalize_first(_clean_name(...))``
stem, the generator must disambiguate the .c filenames by prepending the
hex ID (which is guaranteed unique by ``pipeline.validate_input`` /
FSCS parsing). Without this guard the second DID silently overwrites
the first's .c file.

Non-colliding DIDs still use the short legacy filename
``RBAPLCUST_RDBI_<Name>.c`` to preserve backward compatibility.

Phase 3 writes ``.c`` files **only** into the Bosch project tree
(there is no ``outputs/.../c_code/`` mirror). Tests therefore
configure ``paths.base_dir = tmp_path`` and a fixed
``paths.c_output_subdir = "c_code"`` template so the files land at
``tmp_path/c_code/*.c``, routed through the project-tree resolver.
"""

from __future__ import annotations

from pathlib import Path

from generate_implementation import DIDImplementationInfo, ImplementationGenerator


def _make_did(did_hex: str, did_name: str, rw: str = "R") -> DIDImplementationInfo:
    return DIDImplementationInfo(
        did_hex=did_hex,
        did_name=did_name,
        size_bytes="1",
        rw_state=rw,
        storage_pos="EEPROM",
        data_type="Unsigned",
        sessions=["defaultSession", "extendedDiagnosticSession"],
        security_level="L0",
    )


def _make_generator(tmp_path: Path) -> ImplementationGenerator:
    """Build an ImplementationGenerator whose project tree maps
    cleanly onto ``tmp_path/c_code/`` so the collision assertions stay
    identical to the pre-v1.27 layout."""
    config = {
        "paths": {
            "base_dir": str(tmp_path),
            "c_output_subdir": "c_code",
        },
    }
    return ImplementationGenerator(config=config)


def test_no_collision_keeps_short_filename(tmp_path: Path):
    """Distinct DID names keep the legacy ``RBAPLCUST_RDBI_<Name>.c`` form."""
    generator = _make_generator(tmp_path)
    dids = [
        _make_did("0xF190", "Counter"),
        _make_did("0xF191", "Selector"),
    ]

    generator.generate_from_dids(
        dids, tmp_path, product_type="DPB", dry_run=False,
    )

    produced = sorted(p.name for p in (tmp_path / "c_code").iterdir())
    assert "RBAPLCUST_RDBI_Counter.c" in produced
    assert "RBAPLCUST_RDBI_Selector.c" in produced
    assert not any(name.startswith("RBAPLCUST_RDBI_F190_") for name in produced)


def test_collision_falls_back_to_hex_disambiguated_filenames(tmp_path: Path):
    """Two DIDs that clean to the same stem must both land on disk.

    Before the collision guard, the second DID's file would overwrite the
    first. After the guard, both DIDs get a hex-prefixed filename and both
    files survive side by side.
    """
    generator = _make_generator(tmp_path)
    dids = [
        _make_did("0xF190", "Counter"),
        _make_did("0xF191", "Counter "),
    ]

    generator.generate_from_dids(
        dids, tmp_path, product_type="DPB", dry_run=False,
    )

    produced = sorted(p.name for p in (tmp_path / "c_code").iterdir())
    assert "RBAPLCUST_RDBI_F190_Counter.c" in produced, produced
    assert "RBAPLCUST_RDBI_F191_Counter.c" in produced, produced
    assert "RBAPLCUST_RDBI_Counter.c" not in produced


def test_collision_also_disambiguates_wdbi_files(tmp_path: Path):
    """RW DIDs emit both RDBI and WDBI files; both must be hex-disambiguated."""
    generator = _make_generator(tmp_path)
    dids = [
        _make_did("0xF18C", "ModeSelector", rw="RW"),
        _make_did("0xF18D", "Mode Selector", rw="RW"),
    ]

    generator.generate_from_dids(
        dids, tmp_path, product_type="DPB", dry_run=False,
    )

    produced = sorted(p.name for p in (tmp_path / "c_code").iterdir())
    assert "RBAPLCUST_RDBI_F18C_ModeSelector.c" in produced, produced
    assert "RBAPLCUST_RDBI_F18D_ModeSelector.c" in produced, produced
    assert "RBAPLCUST_WDBI_F18C_ModeSelector.c" in produced, produced
    assert "RBAPLCUST_WDBI_F18D_ModeSelector.c" in produced, produced
