# ARXML Structure Reference

Authoritative hard-coded ARXML container structures used by `scripts/generate_arxml.py` (via `scripts/templates/arxml/*.j2`). Read this when debugging a malformed ARXML, adjusting a container template, or validating the merge contract into the Bosch project-tree file.

## Overall Structure

The generated ARXML follows this hierarchy:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<AUTOSAR xmlns="http://autosar.org/schema/r4.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://autosar.org/schema/r4.0 AUTOSAR_00048.xsd">
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
                                <!-- All DcmDspData containers -->
                                <!-- DcmDspDidInfo shared containers -->
                                <!-- All DcmDspDid containers -->
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
</AUTOSAR>
```

## Container Templates

### DcmDspData (Read-Only)

For Read-only DIDs (Service 0x22 only):

```xml
<ECUC-CONTAINER-VALUE>
  <SHORT-NAME>{data_container_name}</SHORT-NAME>
  <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspData</DEFINITION-REF>
  <PARAMETER-VALUES>
    <ECUC-TEXTUAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-ENUMERATION-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspData/DcmDspDataEndianness</DEFINITION-REF>
      <VALUE>BIG_ENDIAN</VALUE>
    </ECUC-TEXTUAL-PARAM-VALUE>
    <ECUC-TEXTUAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-FUNCTION-NAME-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspData/DcmDspDataReadFnc</DEFINITION-REF>
      <VALUE>{read_func}</VALUE>
    </ECUC-TEXTUAL-PARAM-VALUE>
    <ECUC-NUMERICAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-INTEGER-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspData/DcmDspDataSize</DEFINITION-REF>
      <VALUE>{size_bits}</VALUE>
    </ECUC-NUMERICAL-PARAM-VALUE>
    <ECUC-TEXTUAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-ENUMERATION-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspData/DcmDspDataType</DEFINITION-REF>
      <VALUE>{data_type}</VALUE>
    </ECUC-TEXTUAL-PARAM-VALUE>
    <ECUC-TEXTUAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-ENUMERATION-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspData/DcmDspDataUsePort</DEFINITION-REF>
      <VALUE>USE_DATA_SYNCH_FNC</VALUE>
    </ECUC-TEXTUAL-PARAM-VALUE>
  </PARAMETER-VALUES>
</ECUC-CONTAINER-VALUE>
```

**Parameters:**
- `{data_container_name}`: `RBAPLCUST_{did}_{name}Data` (e.g., `RBAPLCUST_0101_VariantCodingData`)
- `{read_func}`: `RBAPLCUST_{did}_{name}_ReadData`
- `{size_bits}`: Size in bits (bytes × 8)
- `{data_type}`: `UINT8_N` (default for all types)

### DcmDspData (Read/Write)

For Read/Write DIDs (Service 0x22 + 0x2E):

```xml
<ECUC-CONTAINER-VALUE>
  <SHORT-NAME>{data_container_name}</SHORT-NAME>
  <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspData</DEFINITION-REF>
  <PARAMETER-VALUES>
    <ECUC-TEXTUAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-ENUMERATION-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspData/DcmDspDataEndianness</DEFINITION-REF>
      <VALUE>BIG_ENDIAN</VALUE>
    </ECUC-TEXTUAL-PARAM-VALUE>
    <ECUC-TEXTUAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-FUNCTION-NAME-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspData/DcmDspDataReadFnc</DEFINITION-REF>
      <VALUE>{read_func}</VALUE>
    </ECUC-TEXTUAL-PARAM-VALUE>
    <ECUC-NUMERICAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-INTEGER-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspData/DcmDspDataSize</DEFINITION-REF>
      <VALUE>{size_bits}</VALUE>
    </ECUC-NUMERICAL-PARAM-VALUE>
    <ECUC-TEXTUAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-ENUMERATION-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspData/DcmDspDataType</DEFINITION-REF>
      <VALUE>{data_type}</VALUE>
    </ECUC-TEXTUAL-PARAM-VALUE>
    <ECUC-TEXTUAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-ENUMERATION-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspData/DcmDspDataUsePort</DEFINITION-REF>
      <VALUE>USE_DATA_SYNCH_FNC</VALUE>
    </ECUC-TEXTUAL-PARAM-VALUE>
    <ECUC-TEXTUAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-FUNCTION-NAME-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspData/DcmDspDataWriteFnc</DEFINITION-REF>
      <VALUE>{write_func}</VALUE>
    </ECUC-TEXTUAL-PARAM-VALUE>
  </PARAMETER-VALUES>
</ECUC-CONTAINER-VALUE>
```

**Additional Parameter:**
- `{write_func}`: `RBAPLCUST_{did}_{name}_WriteData`

### DcmDspDid (Read-Only)

For Read-only DIDs:

```xml
<ECUC-CONTAINER-VALUE>
  <SHORT-NAME>{did_container_name}</SHORT-NAME>
  <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid</DEFINITION-REF>
  <PARAMETER-VALUES>
    <ECUC-NUMERICAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-INTEGER-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid/DcmDspDidIdentifier</DEFINITION-REF>
      <VALUE>{did_id}</VALUE>
    </ECUC-NUMERICAL-PARAM-VALUE>
    <ECUC-TEXTUAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-ENUMERATION-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid/DcmDspDidUsePort</DEFINITION-REF>
      <VALUE>USE_DATA_ELEMENT_SPECIFIC_INTERFACES</VALUE>
    </ECUC-TEXTUAL-PARAM-VALUE>
    <ECUC-NUMERICAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-BOOLEAN-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid/DcmRbAtomicSenderReceiverCommunication</DEFINITION-REF>
      <VALUE>false</VALUE>
    </ECUC-NUMERICAL-PARAM-VALUE>
  </PARAMETER-VALUES>
  <REFERENCE-VALUES>
    <ECUC-REFERENCE-VALUE>
      <DEFINITION-REF DEST="ECUC-REFERENCE-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid/DcmDspDidInfoRef</DEFINITION-REF>
      <VALUE-REF DEST="ECUC-CONTAINER-VALUE">/RB/UBK/Project/EcucModuleConfigurationValuess/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo_Read</VALUE-REF>
    </ECUC-REFERENCE-VALUE>
  </REFERENCE-VALUES>
  <SUB-CONTAINERS>
    <ECUC-CONTAINER-VALUE>
      <SHORT-NAME>DcmDspDidSignal_0</SHORT-NAME>
      <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid/DcmDspDidSignal</DEFINITION-REF>
      <PARAMETER-VALUES>
        <ECUC-NUMERICAL-PARAM-VALUE>
          <DEFINITION-REF DEST="ECUC-INTEGER-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid/DcmDspDidSignal/DcmDspDidDataPos</DEFINITION-REF>
          <VALUE>0</VALUE>
        </ECUC-NUMERICAL-PARAM-VALUE>
      </PARAMETER-VALUES>
      <REFERENCE-VALUES>
        <ECUC-REFERENCE-VALUE>
          <DEFINITION-REF DEST="ECUC-REFERENCE-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid/DcmDspDidSignal/DcmDspDidDataRef</DEFINITION-REF>
          <VALUE-REF DEST="ECUC-CONTAINER-VALUE">/RB/UBK/Project/EcucModuleConfigurationValuess/Dcm/DcmConfigSet/DcmDsp/{data_ref_name}</VALUE-REF>
        </ECUC-REFERENCE-VALUE>
      </REFERENCE-VALUES>
    </ECUC-CONTAINER-VALUE>
  </SUB-CONTAINERS>
</ECUC-CONTAINER-VALUE>
```

**Parameters:**
- `{did_container_name}`: `{data_container_name}Did` (e.g., `RBAPLCUST_0101_VariantCodingDataDid`)
- `{did_id}`: Decimal DID identifier (e.g., 257 for 0x0101)
- `{data_ref_name}`: Reference to corresponding DcmDspData container

**Reference:** Points to `DcmDspDidInfo_Read` shared container.

### DcmDspDid (Read/Write)

For Read/Write DIDs:

```xml
<ECUC-CONTAINER-VALUE>
  <SHORT-NAME>{did_container_name}</SHORT-NAME>
  <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid</DEFINITION-REF>
  <PARAMETER-VALUES>
    <ECUC-NUMERICAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-INTEGER-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid/DcmDspDidIdentifier</DEFINITION-REF>
      <VALUE>{did_id}</VALUE>
    </ECUC-NUMERICAL-PARAM-VALUE>
    <ECUC-TEXTUAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-ENUMERATION-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid/DcmDspDidUsePort</DEFINITION-REF>
      <VALUE>USE_DATA_ELEMENT_SPECIFIC_INTERFACES</VALUE>
    </ECUC-TEXTUAL-PARAM-VALUE>
    <ECUC-NUMERICAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-BOOLEAN-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid/DcmRbAtomicSenderReceiverCommunication</DEFINITION-REF>
      <VALUE>false</VALUE>
    </ECUC-NUMERICAL-PARAM-VALUE>
  </PARAMETER-VALUES>
  <REFERENCE-VALUES>
    <ECUC-REFERENCE-VALUE>
      <DEFINITION-REF DEST="ECUC-REFERENCE-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid/DcmDspDidInfoRef</DEFINITION-REF>
      <VALUE-REF DEST="ECUC-CONTAINER-VALUE">/RB/UBK/Project/EcucModuleConfigurationValuess/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo_ReadAndWrite</VALUE-REF>
    </ECUC-REFERENCE-VALUE>
  </REFERENCE-VALUES>
  <SUB-CONTAINERS>
    <ECUC-CONTAINER-VALUE>
      <SHORT-NAME>DcmDspDidSignal_0</SHORT-NAME>
      <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid/DcmDspDidSignal</DEFINITION-REF>
      <PARAMETER-VALUES>
        <ECUC-NUMERICAL-PARAM-VALUE>
          <DEFINITION-REF DEST="ECUC-INTEGER-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid/DcmDspDidSignal/DcmDspDidDataPos</DEFINITION-REF>
          <VALUE>0</VALUE>
        </ECUC-NUMERICAL-PARAM-VALUE>
      </PARAMETER-VALUES>
      <REFERENCE-VALUES>
        <ECUC-REFERENCE-VALUE>
          <DEFINITION-REF DEST="ECUC-REFERENCE-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDid/DcmDspDidSignal/DcmDspDidDataRef</DEFINITION-REF>
          <VALUE-REF DEST="ECUC-CONTAINER-VALUE">/RB/UBK/Project/EcucModuleConfigurationValuess/Dcm/DcmConfigSet/DcmDsp/{data_ref_name}</VALUE-REF>
        </ECUC-REFERENCE-VALUE>
      </REFERENCE-VALUES>
    </ECUC-CONTAINER-VALUE>
  </SUB-CONTAINERS>
</ECUC-CONTAINER-VALUE>
```

**Reference:** Points to `DcmDspDidInfo_ReadAndWrite` shared container.

## Shared Containers

These containers are generated once and referenced by multiple DIDs.

### DcmDspDidInfo_Read

For Read-only DIDs:

```xml
<ECUC-CONTAINER-VALUE>
  <SHORT-NAME>DcmDspDidInfo_Read</SHORT-NAME>
  <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo</DEFINITION-REF>
  <PARAMETER-VALUES>
    <ECUC-NUMERICAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-BOOLEAN-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo/DcmDspDidDynamicallyDefined</DEFINITION-REF>
      <VALUE>false</VALUE>
    </ECUC-NUMERICAL-PARAM-VALUE>
  </PARAMETER-VALUES>
  <SUB-CONTAINERS>
    <ECUC-CONTAINER-VALUE>
      <SHORT-NAME>DcmDspDidRead</SHORT-NAME>
      <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo/DcmDspDidRead</DEFINITION-REF>
    </ECUC-CONTAINER-VALUE>
  </SUB-CONTAINERS>
</ECUC-CONTAINER-VALUE>
```

**Characteristics:**
- No session or security restrictions for read operations
- Simple structure with only `DcmDspDidRead` sub-container

### DcmDspDidInfo_ReadAndWrite

For Read/Write DIDs:

```xml
<ECUC-CONTAINER-VALUE>
  <SHORT-NAME>DcmDspDidInfo_ReadAndWrite</SHORT-NAME>
  <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo</DEFINITION-REF>
  <PARAMETER-VALUES>
    <ECUC-NUMERICAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-BOOLEAN-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo/DcmDspDidDynamicallyDefined</DEFINITION-REF>
      <VALUE>false</VALUE>
    </ECUC-NUMERICAL-PARAM-VALUE>
  </PARAMETER-VALUES>
  <SUB-CONTAINERS>
    <ECUC-CONTAINER-VALUE>
      <SHORT-NAME>DcmDspDidWrite</SHORT-NAME>
      <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo/DcmDspDidWrite</DEFINITION-REF>
      <REFERENCE-VALUES>
        <ECUC-REFERENCE-VALUE>
          <DEFINITION-REF DEST="ECUC-REFERENCE-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo/DcmDspDidWrite/DcmDspDidWriteSessionRef</DEFINITION-REF>
          <VALUE-REF DEST="ECUC-CONTAINER-VALUE">/RB/UBK/Project/EcucModuleConfigurationValuess/Dcm/DcmConfigSet/DcmDsp/DcmDspSession/EXTENDED_DIAGNOSTIC_SESSION</VALUE-REF>
        </ECUC-REFERENCE-VALUE>
        <ECUC-REFERENCE-VALUE>
          <DEFINITION-REF DEST="ECUC-REFERENCE-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo/DcmDspDidWrite/DcmDspDidWriteSecurityLevelRef</DEFINITION-REF>
          <VALUE-REF DEST="ECUC-CONTAINER-VALUE">/RB/UBK/Project/EcucModuleConfigurationValuess/Dcm/DcmConfigSet/DcmDsp/DcmDspSecurity/DCM_SEC_LEV_L1</VALUE-REF>
        </ECUC-REFERENCE-VALUE>
      </REFERENCE-VALUES>
    </ECUC-CONTAINER-VALUE>
    <ECUC-CONTAINER-VALUE>
      <SHORT-NAME>DcmDspDidRead</SHORT-NAME>
      <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo/DcmDspDidRead</DEFINITION-REF>
    </ECUC-CONTAINER-VALUE>
  </SUB-CONTAINERS>
</ECUC-CONTAINER-VALUE>
```

**Characteristics:**
- Write operations require:
  - **Session**: `EXTENDED_DIAGNOSTIC_SESSION`
  - **Security Level**: `DCM_SEC_LEV_L1`
- Contains both `DcmDspDidWrite` (with restrictions) and `DcmDspDidRead` (no restrictions)

## Generation Order

The script generates containers in this sequence:

1. **All DcmDspData containers** (one per DID)
2. **Shared DcmDspDidInfo containers** (2 total: Read + ReadAndWrite)
3. **All DcmDspDid containers** (one per DID, referencing Data and DidInfo)

## Naming (summary)

| Element | Pattern | Example |
|---------|---------|---------|
| Data Container | `RBAPLCUST_{DID}_{Name}Data` | `RBAPLCUST_0101_VariantCodingData` |
| Did Container | `{DataName}Did` | `RBAPLCUST_0101_VariantCodingDataDid` |
| Read Function | `RBAPLCUST_{DID}_{Name}_ReadData` | `RBAPLCUST_0101_VariantCoding_ReadData` |
| Write Function | `RBAPLCUST_{DID}_{Name}_WriteData` | `RBAPLCUST_0101_VariantCoding_WriteData` |
| DID Decimal | Hex→Decimal | 0x0101 → 257 |

**Note**: DID identifier uses 4-digit uppercase hex (e.g., `0101`, `F110`). Full naming contract in [`naming.md`](naming.md).

## Comment Standards

- All function bodies must have comments
- Include: DID identifier, operation type, data source
- Use TODO markers for manual implementation points
- German comments for file headers: `/*DE|...*/`
