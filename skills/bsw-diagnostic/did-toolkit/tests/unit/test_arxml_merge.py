"""Unit tests for :mod:`scripts.implementation.arxml_merge`.

Covers the pure merge logic in isolation from the orchestrator:

* ``extract_dcmdsp_short_names`` reports existing children in doc order,
* unique new containers splice in before ``</SUB-CONTAINERS>``,
* duplicates (same SHORT-NAME) get skipped,
* the surrounding bytes of the existing file stay untouched,
* malformed inputs raise ``ValueError`` with a helpful message.

We hand-craft minimal XML so the tests run in microseconds and do not
depend on the real Fe_Super files.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent.parent / "scripts")
)

from implementation.arxml_merge import (  # noqa: E402
    extract_dcmdsp_short_names,
    merge_arxml,
)


# Minimal skeleton: real Bosch files nest DcmDsp six levels deep; the
# merge logic only cares about the SHORT-NAME + SUB-CONTAINERS ids, so a
# flat target is enough for the unit tests.
TARGET_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<AUTOSAR xmlns="http://autosar.org/schema/r4.0">
  <AR-PACKAGES>
    <AR-PACKAGE>
      <SHORT-NAME>Project</SHORT-NAME>
      <ELEMENTS>
        <ECUC-CONTAINER-VALUE>
          <SHORT-NAME>DcmDsp</SHORT-NAME>
          <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp</DEFINITION-REF>
          <SUB-CONTAINERS>
{body}
          </SUB-CONTAINERS>
        </ECUC-CONTAINER-VALUE>
      </ELEMENTS>
    </AR-PACKAGE>
  </AR-PACKAGES>
</AUTOSAR>
"""


def _container(short_name: str, kind: str = "DcmDspData") -> str:
    return (
        f"            <ECUC-CONTAINER-VALUE>\n"
        f"              <SHORT-NAME>{short_name}</SHORT-NAME>\n"
        f"              <DEFINITION-REF DEST=\"ECUC-PARAM-CONF-CONTAINER-DEF\">"
        f"/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/{kind}</DEFINITION-REF>\n"
        f"            </ECUC-CONTAINER-VALUE>"
    )


def _wrap(body: str) -> str:
    return TARGET_TEMPLATE.format(body=body)


def test_extract_names_returns_document_order():
    xml = _wrap(
        "\n".join([_container("A_Data"), _container("B_Data"), _container("C_Data")])
    )
    assert extract_dcmdsp_short_names(xml) == ["A_Data", "B_Data", "C_Data"]


def test_extract_names_on_empty_sub_containers():
    xml = _wrap("")
    assert extract_dcmdsp_short_names(xml) == []


def test_extract_names_raises_on_missing_dcmdsp():
    xml = """<?xml version="1.0"?><AUTOSAR xmlns="http://autosar.org/schema/r4.0"/>"""
    assert extract_dcmdsp_short_names(xml) == []


def test_merge_inserts_unique_new_containers():
    target = _wrap(_container("Existing_Data"))
    gen = _wrap(
        "\n".join([_container("New1_Data"), _container("New2_Data")])
    )
    merged, inserted, skipped, names = merge_arxml(target, gen)
    assert inserted == 2
    assert skipped == 0
    assert names == ["New1_Data", "New2_Data"]
    # New containers must appear *after* the existing ones.
    assert merged.index("Existing_Data") < merged.index("New1_Data")
    assert merged.index("New1_Data") < merged.index("New2_Data")
    # And the close tag is still there, balanced.
    assert merged.count("<SUB-CONTAINERS>") == 1
    assert merged.count("</SUB-CONTAINERS>") == 1


def test_merge_skips_duplicates_by_short_name():
    target = _wrap("\n".join([_container("Keep_Data"), _container("Dup_Data")]))
    gen = _wrap("\n".join([_container("Dup_Data"), _container("Fresh_Data")]))
    merged, inserted, skipped, names = merge_arxml(target, gen)
    assert inserted == 1
    assert skipped == 1
    assert names == ["Fresh_Data"]
    # Dup_Data appears only once (the original) in the merged output.
    assert merged.count("<SHORT-NAME>Dup_Data</SHORT-NAME>") == 1


def test_merge_preserves_prefix_and_suffix_bytes():
    """Bytes outside DcmDsp/SUB-CONTAINERS must remain byte-identical."""
    target = _wrap(_container("Existing_Data"))
    gen = _wrap(_container("Fresh_Data"))
    merged, _, _, _ = merge_arxml(target, gen)

    # Before </SUB-CONTAINERS>: the Existing_Data block is untouched;
    # after </SUB-CONTAINERS> the closing AUTOSAR tag chain is untouched.
    assert "Existing_Data" in merged
    suffix = merged[merged.index("</SUB-CONTAINERS>"):]
    assert "</AUTOSAR>" in suffix


def test_merge_is_idempotent_on_second_pass():
    target = _wrap(_container("Existing_Data"))
    gen = _wrap(_container("Fresh_Data"))
    once, ins1, skip1, _ = merge_arxml(target, gen)
    twice, ins2, skip2, names2 = merge_arxml(once, gen)
    assert ins1 == 1 and skip1 == 0
    assert ins2 == 0 and skip2 == 1
    assert names2 == []
    assert once == twice


def test_merge_noop_when_generated_has_no_dcmdsp():
    target = _wrap(_container("Existing_Data"))
    broken_gen = (
        """<?xml version="1.0"?>"""
        """<AUTOSAR xmlns="http://autosar.org/schema/r4.0"/>"""
    )
    merged, inserted, skipped, names = merge_arxml(target, broken_gen)
    assert merged == target
    assert inserted == 0
    assert skipped == 0
    assert names == []


def test_merge_raises_on_malformed_target():
    broken_target = (
        """<?xml version="1.0"?>"""
        """<AUTOSAR xmlns="http://autosar.org/schema/r4.0"/>"""
    )
    gen = _wrap(_container("Fresh_Data"))
    with pytest.raises(ValueError):
        merge_arxml(broken_target, gen)
