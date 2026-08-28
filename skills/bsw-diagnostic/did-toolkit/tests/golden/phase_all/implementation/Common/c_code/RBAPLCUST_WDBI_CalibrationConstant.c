/**
 * @ingroup 'RBAPLCust'
 * @{
 *
 * RBAPLCUST_WDBI_CalibrationConstant.c
 * Contains function to write NVM Information into EEPROM
 *
 * RBAPLCUST_F1A1_CalibrationConstant_WriteData -- Write the CalibrationConstant Information
 *
 * \copyright
 * Robert Bosch GmbH reserves all rights even in the event of industrial property rights.
 * We reserve all rights of disposal such as copying and passing on to third parties.
 */


/* used interfaces */

#include "RBAPLCUST_Global.h"
#include "RBAPLCUST_NVMGeneric.h"

/* realized interfaces */

/* Assert supported configurations: switches, parameters, constants, ... */
RB_ASSERT_SWITCH_SETTINGS(RBFS_DCOM_CalibrationConstant,
						  RBFS_DCOM_CalibrationConstant_ON,
						  RBFS_DCOM_CalibrationConstant_OFF);

/* Value Range Definitions */
#define DID_F1A1_MIN		5
#define DID_F1A1_MAX		5

/*
 * --------------------------------------------------------------------------
 * FUNCTION_NAME:
 *  RBAPLCUST_F1A1_CalibrationConstant_WriteData
 * FUNCTION_NAME_END:
 * --------------------------------------------------------------------------
 * FUNCTION_DESCRIPTION:
 *  Write the CalibrationConstant Information
 * FUNCTION_DESCRIPTION_END:
 * --------------------------------------------------------------------------
 * FUNCTION_PARAMETER:
 *  Data --- information requested for updating CalibrationConstant information
 *  ErrorCode -- information about the error caused
 * FUNCTION_PARAMETER_END:
 * --------------------------------------------------------------------------
 * FUNCTION_RETURN:
 *  E_OK -- means the function is executed successfully
 *  E_NOT_OK -- means the function is not completed / error code
 * FUNCTION_RETURN_END:
 * --------------------------------------------------------------------------
 */

Std_ReturnType RBAPLCUST_F1A1_CalibrationConstant_WriteData (const uint8 * Data, Dcm_NegativeResponseCodeType * ErrorCode)
{
	/* Return value initialization */
	Std_ReturnType retVal = E_NOT_OK;
#if(RBFS_DCOM_CalibrationConstant == RBFS_DCOM_CalibrationConstant_ON)
	/* DID: 0xF1A1 - CalibrationConstant
	 * Operation: Write data to NVM (EEPROM) with numeric range validation
	 * Valid range: 5 ~ 5
	 * Size: 1 bytes
	 * NVM Block: NVM_ID_DCOM_CalibrationConstant */
	if((Data[0] <= DID_F1A1_MAX) && (Data[0] >= DID_F1A1_MIN))
	{
		/* Value within valid range - perform NVM write operation */
		retVal = DCOM_WriteDataByNVMId(NvMConf_NvMBlockDescriptor_NVM_ID_DCOM_CalibrationConstant, Data, ErrorCode);
	}
	else
	{
		/* Value out of range - return request out of range */
		*ErrorCode = DCM_E_REQUESTOUTOFRANGE;
	}
#else
	/* Feature switch disabled - return request out of range */
	*ErrorCode = DCM_E_REQUESTOUTOFRANGE;
#endif
	return retVal;
}

/** @}
 * End ingroup 'RBAPLCust'
 */
