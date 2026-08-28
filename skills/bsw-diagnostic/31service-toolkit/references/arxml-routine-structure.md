# AUTOSAR Routine (DcmDspRoutine) Structure Reference

## Overview

In Bosch BSW projects, UDS Service 0x31 (RoutineControl) configurations are stored in `Dcm_CusDiag_Services*.arxml` files under:

```
rb/as/<bsw>/core/app/dcom/RBAPLCust/cfg/<ProductType>/
```

## Key XML Structure

### Namespace
All elements use the AUTOSAR R4.0 namespace:
```xml
xmlns="http://autosar.org/schema/r4.0"
```

### Routine Container

Each routine is an `ECUC-CONTAINER-VALUE` with `DEFINITION-REF` containing `DcmDspRoutine`:

```xml
<ECUC-CONTAINER-VALUE>
  <SHORT-NAME>RBAPLCUST_MyRoutine</SHORT-NAME>
  <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">
    /AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine
  </DEFINITION-REF>
  <PARAMETER-VALUES>
    <!-- RID Identifier (DECIMAL value) -->
    <ECUC-NUMERICAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-INTEGER-PARAM-DEF">
        /AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspRoutineIdentifier
      </DEFINITION-REF>
      <VALUE>61699</VALUE>
    </ECUC-NUMERICAL-PARAM-VALUE>
    
    <!-- Other routine parameters -->
    <ECUC-NUMERICAL-PARAM-VALUE>
      <DEFINITION-REF>DcmRbDspReqSequenceErrorEnabled</DEFINITION-REF>
      <VALUE>false</VALUE>
    </ECUC-NUMERICAL-PARAM-VALUE>
    ...
  </PARAMETER-VALUES>
  
  <SUB-CONTAINERS>
    <!-- Start Routine Config -->
    <ECUC-CONTAINER-VALUE>
      <SHORT-NAME>DcmDspStartRoutine</SHORT-NAME>
      ...
    </ECUC-CONTAINER-VALUE>
    
    <!-- Stop Routine Config (optional) -->
    <ECUC-CONTAINER-VALUE>
      <SHORT-NAME>DcmDspStopRoutine</SHORT-NAME>
      ...
    </ECUC-CONTAINER-VALUE>
  </SUB-CONTAINERS>
</ECUC-CONTAINER-VALUE>
```

## Important Notes

1. **RID Storage Format**: The `<VALUE>` under `DcmDspRoutineIdentifier` is stored as **decimal** in the arxml, even though RIDs are conventionally referred to in hexadecimal.

2. **Routine Name**: The `SHORT-NAME` is the unique identifier for the routine within the file. It typically follows the pattern `RBAPLCUST_<FunctionName>`.

3. **Product Type**: Determined from the directory structure under `cfg/`:
   - `cfg/Common/` → Common (shared across products)
   - `cfg/DPB/` → DPB
   - `cfg/ESP/` → ESP
   - `cfg/IPB/` → IPB
   - `cfg/RBU/` → RBU
   - `cfg/ESPCL/` → ESPCL (may be aliased to ESP)

4. **File Naming**: Service configuration files follow the pattern:
   - `Dcm_CusDiag_Services_EcucValues.arxml` (Common)
   - `Dcm_CusDiag_Services_EcucValues_<Product>.arxml` (Product-specific)
   - `Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml` (Single CAN ID variant)

5. **What We Modify**: Only the `DcmDspRoutineIdentifier` decimal value. We do NOT modify:
   - Routine SHORT-NAME
   - Start/Stop function names
   - Signal definitions (length, type, position)
   - Authorization references
   - Any other routine parameters

## 完整的 DcmDspRoutine XML 模板（新增）

以下是一个包含完整信号配置的 Routine 示例：

```xml
<ECUC-CONTAINER-VALUE>
  <SHORT-NAME>RBAPLCUST_MyRoutine</SHORT-NAME>
  <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">
    /AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine
  </DEFINITION-REF>
  <PARAMETER-VALUES>
    <ECUC-NUMERICAL-PARAM-VALUE>
      <DEFINITION-REF DEST="ECUC-INTEGER-PARAM-DEF">
        /AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspRoutineIdentifier
      </DEFINITION-REF>
      <VALUE>61696</VALUE>
    </ECUC-NUMERICAL-PARAM-VALUE>
    ...
  </PARAMETER-VALUES>
  <REFERENCE-VALUES>
    <ECUC-REFERENCE-VALUE>
      <DEFINITION-REF DEST="ECUC-REFERENCE-DEF">
        /AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspRoutineUsePort
      </DEFINITION-REF>
      <VALUE-REF DEST="ECUC-CONTAINER-VALUE">...</VALUE-REF>
    </ECUC-REFERENCE-VALUE>
    ...
  </REFERENCE-VALUES>
  <SUB-CONTAINERS>
    <ECUC-CONTAINER-VALUE>
      <SHORT-NAME>DcmDspStartRoutine</SHORT-NAME>
      <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">...</DEFINITION-REF>
      <PARAMETER-VALUES>...</PARAMETER-VALUES>
      <SUB-CONTAINERS>
        <ECUC-CONTAINER-VALUE>
          <SHORT-NAME>DcmDspStartRoutineIn</SHORT-NAME>
          <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">...</DEFINITION-REF>
          <SUB-CONTAINERS>
            <!-- Start input signals -->
            <ECUC-CONTAINER-VALUE>
              <SHORT-NAME>DcmDspStartRoutineInSignal_0</SHORT-NAME>
              ...
            </ECUC-CONTAINER-VALUE>
          </SUB-CONTAINERS>
        </ECUC-CONTAINER-VALUE>
        <ECUC-CONTAINER-VALUE>
          <SHORT-NAME>DcmDspStartRoutineOut</SHORT-NAME>
          <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">...</DEFINITION-REF>
          <SUB-CONTAINERS>
            <!-- Start output signals -->
            <ECUC-CONTAINER-VALUE>
              <SHORT-NAME>DcmDspStartRoutineOutSignal_0</SHORT-NAME>
              ...
            </ECUC-CONTAINER-VALUE>
          </SUB-CONTAINERS>
        </ECUC-CONTAINER-VALUE>
      </SUB-CONTAINERS>
    </ECUC-CONTAINER-VALUE>
    <!-- DcmDspStopRoutine (optional) -->
    <!-- DcmDspRequestRoutineResults (optional) -->
  </SUB-CONTAINERS>
</ECUC-CONTAINER-VALUE>
```

## 缩进层级参考

本项目 ARXML 文件的缩进深度（spaces）：

| 层级 | 缩进（spaces） | 说明 |
|------|---------------|------|
| Routine ECUC-CONTAINER-VALUE | 32 | 最外层 Routine 容器 |
| Routine 子元素 | 34 | SHORT-NAME, DEFINITION-REF, PARAMETER-VALUES 等 |
| StartRoutine ECUC-CONTAINER-VALUE | 36 | DcmDspStartRoutine 容器 |
| StartRoutine 子元素 | 38 | StartRoutine 内部的参数和引用 |
| Signal 容器 | 40 | DcmDspStartRoutineIn/Out 容器 |
| Signal 子元素 | 42 | Signal 容器内的参数 |
| Signal 参数 | 44 | 具体信号参数（pos, len, type 等） |
| Signal 参数值 | 46-50 | VALUE, DEFINITION-REF 等最深层元素 |
