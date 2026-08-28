"""Pin v1.27.0 inline TODO block for non-EEPROM read/write generators.

The stub body for non-EEPROM DIDs must:

* Still return ``E_NOT_OK`` (so a half-finished release is loud on
  the bench, not silently fake-success).
* Carry a ``TODO(agent):`` marker so an agent / reviewer can grep
  for unfilled stubs across a tree.
* Embed the storage classification verdict (``class : RAM`` /
  ``class : HardCode``) and the playbook reference inline. v1.27.0
  retired the per-DID ``_briefs/<hex>_<svc>.md`` file pointer; all
  context now lives inside the .c file's ``TODO(agent)`` comment.

EEPROM DIDs must remain untouched (no TODO marker leaks).
"""

from __future__ import annotations

import pytest

from implementation.generators import (
    _build_read_func_body,
    _build_write_func_body,
)
from implementation.models import DIDImplementationInfo


def _info(*, did_hex="3026", did_name="EpbActuatorState",
          storage_pos="RAM", size_bytes="1", rw_state="R",
          nvm_item="") -> DIDImplementationInfo:
    return DIDImplementationInfo(
        did_hex=did_hex,
        did_name=did_name,
        data_type="Unsigned",
        storage_pos=storage_pos,
        size_bytes=size_bytes,
        rw_state=rw_state,
        nvm_item=nvm_item,
    )


# ---------------------------------------------------------------------------
# Read stubs
# ---------------------------------------------------------------------------


def test_eeprom_read_body_does_not_carry_todo_marker():
    """Sanity: EEPROM path is unchanged from v1.14.x, must not start
    leaking the TODO(agent) marker meant for non-NVM stubs."""
    info = _info(storage_pos="EEPROM", nvm_item="NVM_ID_DCOM_X")
    body = _build_read_func_body(info, "DCOM_FS_X", "X")
    assert "TODO(agent)" not in body
    assert "DCOM_ReadDataByNVMId" in body


def test_ram_read_stub_has_todo_and_inline_context():
    info = _info(did_hex="3026", did_name="EpbActuatorState",
                 storage_pos="RAM", size_bytes="2", rw_state="R")
    body = _build_read_func_body(info, "DCOM_FS_EPB", "EpbActuatorState")

    assert "TODO(agent)" in body
    # v1.27.0: identity + storage class + playbook live in the
    # inline comment block; no external _briefs/ file pointer.
    assert "did_hex     : 3026" in body
    assert "class       : RAM" in body
    assert "reference/implementation-storage-positions.md" in body
    # Stays loud at runtime: still returns E_NOT_OK.
    assert "E_NOT_OK" in body


def test_rom_read_is_auto_generated_no_todo():
    """v2.4.0: ROM/Flash (HardCode) DIDs are fully auto-generated with
    macro assignments and no TODO(agent) stub."""
    info = _info(did_hex="F189", did_name="VersionDID",
                 storage_pos="ROM", size_bytes="15")
    body = _build_read_func_body(info, "DCOM_FS_VER", "VersionDID")
    # _storage_kind_label canonicalises ROM -> "ROM/Flash"
    assert "ROM/Flash" in body
    # v2.4.0: auto-generated HardCode body — no TODO(agent), no class label.
    assert "TODO(agent)" not in body
    assert "class       : HardCode" not in body
    assert "C_DID_VersionDID_Byte0_UB" in body
    assert "retVal = E_OK" in body


def test_rw_did_read_stub_carries_full_inline_context():
    """RW DIDs surface both 0x22 and 0x2E behaviour text blocks inline
    on the read side so the agent has a single source of truth in
    front of them while editing the read body."""
    info = _info(did_hex="3030", did_name="MutableRam",
                 storage_pos="RAM", size_bytes="4", rw_state="RW")
    read_body = _build_read_func_body(info, "DCOM_FS_M", "MutableRam")
    assert "did_hex     : 3030" in read_body
    # Both service behaviour blocks appear because rw_state == "RW".
    assert "Behavior 0x22 (Read)" in read_body
    assert "Behavior 0x2E (Write)" in read_body


# ---------------------------------------------------------------------------
# Write stubs
# ---------------------------------------------------------------------------


def test_non_eeprom_write_stub_has_todo_and_inline_context():
    info = _info(did_hex="3030", did_name="MutableRam",
                 storage_pos="RAM", size_bytes="4", rw_state="RW")
    body = _build_write_func_body(info, "DCOM_FS_M", "NVM_M", mode="non_eeprom")
    assert "TODO(agent)" in body
    assert "did_hex     : 3030" in body
    assert "class       : RAM" in body
    assert "implementation-storage-positions.md" in body
    assert "E_NOT_OK" in body


def test_eeprom_write_modes_do_not_leak_non_eeprom_marker():
    """The three EEPROM write modes (``enum`` / ``range`` / ``no_range``)
    must not pick up the non-EEPROM TODO marker."""
    info = _info(did_hex="F190", did_name="EepWritable",
                 storage_pos="EEPROM", size_bytes="2", rw_state="RW",
                 nvm_item="NVM_ID_DCOM_EEP")
    for mode in ("enum", "range", "no_range"):
        body = _build_write_func_body(info, "DCOM_FS_E", "NVM_ID_DCOM_EEP", mode)
        assert "TODO(agent)" not in body, f"leak in mode={mode}"
        assert "DCOM_WriteDataByNVMId" in body
