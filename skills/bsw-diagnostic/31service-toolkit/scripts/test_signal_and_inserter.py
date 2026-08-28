"""
31service-toolkit - Unit tests for signal_parser and arxml_inserter.

Run with: python -m pytest test_signal_and_inserter.py -v
"""

import sys
import os
import tempfile
import xml.etree.ElementTree as ET

# Ensure we can import sibling modules
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from signal_parser import parse_signal_string, get_default_signals
from arxml_inserter import build_routine_xml, insert_routine_into_file, validate_insertion


# ──────────────────────────────────────────────────────────────
# signal_parser tests
# ──────────────────────────────────────────────────────────────

class TestSignalParser:

    def test_none_input(self):
        sigs, err = parse_signal_string(None)
        assert sigs is None
        assert err is None

    def test_empty_string(self):
        sigs, err = parse_signal_string("")
        assert sigs is None
        assert err is None

    def test_whitespace_only(self):
        sigs, err = parse_signal_string("   ")
        assert sigs is None
        assert err is None

    def test_single_uint8(self):
        sigs, err = parse_signal_string("UINT8")
        assert err is None
        assert sigs == [{"type": "UINT8", "length": 8, "pos": 0}]

    def test_single_boolean(self):
        sigs, err = parse_signal_string("BOOLEAN")
        assert err is None
        assert sigs == [{"type": "BOOLEAN", "length": 8, "pos": 0}]

    def test_multiple_plus(self):
        sigs, err = parse_signal_string("UINT8 + UINT16 + UINT32")
        assert err is None
        assert len(sigs) == 3
        assert sigs[0] == {"type": "UINT8", "length": 8, "pos": 0}
        assert sigs[1] == {"type": "UINT16", "length": 16, "pos": 8}
        assert sigs[2] == {"type": "UINT32", "length": 32, "pos": 24}

    def test_multiple_comma(self):
        sigs, err = parse_signal_string("UINT8, UINT16, SINT32")
        assert err is None
        assert len(sigs) == 3
        assert sigs[2] == {"type": "SINT32", "length": 32, "pos": 24}

    def test_multiple_mixed_separators(self):
        sigs, err = parse_signal_string("UINT8 + UINT16, SINT8和BOOLEAN")
        assert err is None
        assert len(sigs) == 4

    def test_array_with_bit_unit(self):
        sigs, err = parse_signal_string("UINT8_N(64bit)")
        assert err is None
        assert sigs == [{"type": "UINT8_N", "length": 64, "pos": 0}]

    def test_array_with_byte_unit(self):
        sigs, err = parse_signal_string("UINT8_N(8Byte)")
        assert err is None
        assert sigs == [{"type": "UINT8_N", "length": 64, "pos": 0}]

    def test_array_missing_unit(self):
        sigs, err = parse_signal_string("UINT8_N(64)")
        assert sigs is None
        assert err is not None
        assert "missing unit" in err.lower()

    def test_unknown_type(self):
        sigs, err = parse_signal_string("UNKNOWN_TYPE")
        assert sigs is None
        assert err is not None
        assert "Unknown signal type" in err

    def test_case_insensitive(self):
        sigs, err = parse_signal_string("uint8 + Uint16")
        assert err is None
        assert sigs[0]["type"] == "UINT8"
        assert sigs[1]["type"] == "UINT16"

    def test_default_signals(self):
        sigs = get_default_signals()
        assert sigs == [{"type": "UINT8_N", "length": 8, "pos": 0}]


# ──────────────────────────────────────────────────────────────
# arxml_inserter tests
# ──────────────────────────────────────────────────────────────

class TestArxmlInserter:

    def test_build_routine_minimal(self):
        """Build routine with only required fields (defaults applied)."""
        xml = build_routine_xml("TestRoutine", 0xF200)
        assert "RBAPLCUST_TestRoutine" in xml
        assert "DcmDspStartRoutine" in xml
        assert "DcmDspStartRoutineOut" in xml
        # Default: no StopRoutine, no RequestRoutineResults
        assert "DcmDspStopRoutine" not in xml
        assert "DcmDspRequestRoutineResults" not in xml
        # Default start_out signal
        assert "UINT8_N" in xml
        assert "RBAPLCUST_TestRoutine_start" in xml

    def test_build_routine_with_all_signals(self):
        """Build routine with all signal types specified."""
        xml = build_routine_xml(
            "MyRoutine",
            0xF201,
            signals_start_in=[{"type": "UINT8", "length": 8, "pos": 0}],
            signals_start_out=[{"type": "UINT16", "length": 16, "pos": 0}],
            signals_stop_out=[{"type": "UINT8_N", "length": 8, "pos": 0}],
            signals_result_out=[{"type": "BOOLEAN", "length": 8, "pos": 0}]
        )
        assert "DcmDspStartRoutineIn" in xml
        assert "DcmDspStartRoutineOut" in xml
        assert "DcmDspStopRoutine" in xml
        assert "DcmDspRequestRoutineResults" in xml
        assert "RBAPLCUST_MyRoutine_start" in xml
        assert "RBAPLCUST_MyRoutine_stop" in xml
        assert "RBAPLCUST_MyRoutine_RequestResult" in xml

    def test_build_routine_with_prefix(self):
        """Routine name already has RBAPLCUST_ prefix."""
        xml = build_routine_xml("RBAPLCUST_AlreadyPrefixed", 0xF202)
        # Should not double-prefix
        assert "RBAPLCUST_AlreadyPrefixed" in xml
        assert "RBAPLCUST_RBAPLCUST_AlreadyPrefixed" not in xml
        # Function name should use base name only
        assert "RBAPLCUST_AlreadyPrefixed_start" in xml
        assert "RBAPLCUST_RBAPLCUST_AlreadyPrefixed_start" not in xml

    def test_build_routine_stop_without_result(self):
        """Stop routine present but no result routine."""
        xml = build_routine_xml(
            "StopOnly",
            0xF203,
            signals_stop_out=[{"type": "UINT8_N", "length": 8, "pos": 0}]
        )
        assert "DcmDspStopRoutine" in xml
        assert "DcmDspRequestRoutineResults" not in xml

    def test_xml_wellformedness(self):
        """Generated XML should be parseable by ElementTree."""
        xml = build_routine_xml("WellFormed", 0xF204,
                                signals_start_in=[{"type": "UINT8", "length": 8, "pos": 0}],
                                signals_start_out=[{"type": "UINT16", "length": 16, "pos": 0}])
        # Wrap in a dummy root for standalone parsing
        wrapped = f"<ROOT>\n{xml}\n</ROOT>"
        try:
            root = ET.fromstring(wrapped)
            assert root.tag == "ROOT"
        except ET.ParseError as e:
            raise AssertionError(f"Generated XML is not well-formed: {e}")

    def test_insert_and_validate(self):
        """Full round-trip: insert into file and validate."""
        # Create a minimal ARXML with DcmDsp container
        minimal_arxml = '''<?xml version="1.0" encoding="UTF-8"?>
<AUTOSAR xmlns="http://autosar.org/schema/r4.0">
  <AR-PACKAGES>
    <AR-PACKAGE>
      <SHORT-NAME>RB</SHORT-NAME>
      <AR-PACKAGES>
        <AR-PACKAGE>
          <SHORT-NAME>UBK</SHORT-NAME>
          <AR-PACKAGES>
            <AR-PACKAGE>
              <SHORT-NAME>Project</SHORT-NAME>
              <AR-PACKAGES>
                <AR-PACKAGE>
                  <SHORT-NAME>EcucModuleConfigurationValuess</SHORT-NAME>
                  <ELEMENTS>
                    <ECUC-MODULE-CONFIGURATION-VALUES>
                      <SHORT-NAME>Dcm</SHORT-NAME>
                      <DEFINITION-REF DEST="ECUC-MODULE-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm</DEFINITION-REF>
                      <CONTAINERS>
                        <ECUC-CONTAINER-VALUE>
                          <SHORT-NAME>DcmConfigSet</SHORT-NAME>
                          <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet</DEFINITION-REF>
                          <SUB-CONTAINERS>
                            <ECUC-CONTAINER-VALUE>
                              <SHORT-NAME>DcmDsp</SHORT-NAME>
                              <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp</DEFINITION-REF>
                              <SUB-CONTAINERS>
                                <ECUC-CONTAINER-VALUE>
                                  <SHORT-NAME>ExistingRoutine</SHORT-NAME>
                                  <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine</DEFINITION-REF>
                                  <PARAMETER-VALUES>
                                    <ECUC-NUMERICAL-PARAM-VALUE>
                                      <DEFINITION-REF DEST="ECUC-INTEGER-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspRoutineIdentifier</DEFINITION-REF>
                                      <VALUE>100</VALUE>
                                    </ECUC-NUMERICAL-PARAM-VALUE>
                                  </PARAMETER-VALUES>
                                </ECUC-CONTAINER-VALUE>
                              </SUB-CONTAINERS>
                            </ECUC-CONTAINER-VALUE>
                          </SUB-CONTAINERS>
                        </ECUC-CONTAINER-VALUE>
                      </CONTAINERS>
                    </ECUC-MODULE-CONFIGURATION-VALUES>
                  </ELEMENTS>
                </AR-PACKAGE>
              </AR-PACKAGES>
            </AR-PACKAGE>
          </AR-PACKAGES>
        </AR-PACKAGE>
      </AR-PACKAGES>
    </AR-PACKAGE>
  </AR-PACKAGES>
</AUTOSAR>'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".arxml", delete=False, encoding="utf-8") as f:
            f.write(minimal_arxml)
            tmp_path = f.name

        try:
            routine_xml = build_routine_xml("NewRoutine", 0xF210)
            success, err = insert_routine_into_file(tmp_path, routine_xml, dry_run=False)
            assert success, f"Insert failed: {err}"

            valid, val_err = validate_insertion(tmp_path, "RBAPLCUST_NewRoutine", 0xF210)
            assert valid, f"Validation failed: {val_err}"
        finally:
            os.unlink(tmp_path)

    def test_insert_dry_run(self):
        """Dry run should not modify file."""
        minimal_arxml = '''<?xml version="1.0" encoding="UTF-8"?>
<AUTOSAR xmlns="http://autosar.org/schema/r4.0">
  <AR-PACKAGES>
    <AR-PACKAGE>
      <SHORT-NAME>RB</SHORT-NAME>
      <AR-PACKAGES>
        <AR-PACKAGE>
          <SHORT-NAME>UBK</SHORT-NAME>
          <AR-PACKAGES>
            <AR-PACKAGE>
              <SHORT-NAME>Project</SHORT-NAME>
              <AR-PACKAGES>
                <AR-PACKAGE>
                  <SHORT-NAME>EcucModuleConfigurationValuess</SHORT-NAME>
                  <ELEMENTS>
                    <ECUC-MODULE-CONFIGURATION-VALUES>
                      <SHORT-NAME>Dcm</SHORT-NAME>
                      <DEFINITION-REF DEST="ECUC-MODULE-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm</DEFINITION-REF>
                      <CONTAINERS>
                        <ECUC-CONTAINER-VALUE>
                          <SHORT-NAME>DcmConfigSet</SHORT-NAME>
                          <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet</DEFINITION-REF>
                          <SUB-CONTAINERS>
                            <ECUC-CONTAINER-VALUE>
                              <SHORT-NAME>DcmDsp</SHORT-NAME>
                              <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp</DEFINITION-REF>
                              <SUB-CONTAINERS>
                                <ECUC-CONTAINER-VALUE>
                                  <SHORT-NAME>ExistingRoutine</SHORT-NAME>
                                  <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine</DEFINITION-REF>
                                  <PARAMETER-VALUES>
                                    <ECUC-NUMERICAL-PARAM-VALUE>
                                      <DEFINITION-REF DEST="ECUC-INTEGER-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspRoutineIdentifier</DEFINITION-REF>
                                      <VALUE>100</VALUE>
                                    </ECUC-NUMERICAL-PARAM-VALUE>
                                  </PARAMETER-VALUES>
                                </ECUC-CONTAINER-VALUE>
                              </SUB-CONTAINERS>
                            </ECUC-CONTAINER-VALUE>
                          </SUB-CONTAINERS>
                        </ECUC-CONTAINER-VALUE>
                      </CONTAINERS>
                    </ECUC-MODULE-CONFIGURATION-VALUES>
                  </ELEMENTS>
                </AR-PACKAGE>
              </AR-PACKAGES>
            </AR-PACKAGE>
          </AR-PACKAGES>
        </AR-PACKAGE>
      </AR-PACKAGES>
    </AR-PACKAGE>
  </AR-PACKAGES>
</AUTOSAR>'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".arxml", delete=False, encoding="utf-8") as f:
            f.write(minimal_arxml)
            tmp_path = f.name

        try:
            routine_xml = build_routine_xml("DryRunRoutine", 0xF211)
            success, err = insert_routine_into_file(tmp_path, routine_xml, dry_run=True)
            assert success, f"Dry-run insert failed: {err}"

            # File should be unchanged
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "RBAPLCUST_DryRunRoutine" not in content
        finally:
            os.unlink(tmp_path)

    def test_structure_sub_containers(self):
        """Verify SUB-CONTAINERS hierarchy is correct."""
        xml = build_routine_xml("SubTest", 0xF220,
                                signals_start_in=[{"type": "UINT8", "length": 8, "pos": 0}])
        lines = xml.split("\n")

        # Count SUB-CONTAINERS open/close
        opens = [l for l in lines if "<SUB-CONTAINERS>" in l]
        closes = [l for l in lines if "</SUB-CONTAINERS>" in l]
        assert len(opens) == len(closes), f"Mismatched SUB-CONTAINERS: {len(opens)} open, {len(closes)} close"

        # Expected: Routine(1), StartRoutine(1), StartRoutineIn(1), StartRoutineOut(1) = 4 pairs
        assert len(opens) == 4, f"Expected 4 SUB-CONTAINERS blocks, got {len(opens)}"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
