/**
 * @ingroup 'RBAPLCust'
 * @{
 *
 * RBAPLCUST_WDBI_ModeSelector.c
 * Contains function to write NVM Information into EEPROM
 *
 * RBAPLCUST_F18C_ModeSelector_WriteData -- Write the ModeSelector Information
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
RB_ASSERT_SWITCH_SETTINGS(RBFS_DCOM_ModeSelector,
						  RBFS_DCOM_ModeSelector_ON,
						  RBFS_DCOM_ModeSelector_OFF);

/* Value Range Definitions */
#define DID_F18C_VAL_0		0x00
#define DID_F18C_VAL_1		0x01
#define DID_F18C_VAL_2		0x02

/*
 * --------------------------------------------------------------------------
 * FUNCTION_NAME:
 *  RBAPLCUST_F18C_ModeSelector_WriteData
 * FUNCTION_NAME_END:
 * --------------------------------------------------------------------------
 * FUNCTION_DESCRIPTION:
 *  Write the ModeSelector Information
 * FUNCTION_DESCRIPTION_END:
 * --------------------------------------------------------------------------
 * FUNCTION_PARAMETER:
 *  Data --- information requested for updating ModeSelector information
 *  ErrorCode -- information about the error caused
 * FUNCTION_PARAMETER_END:
 * --------------------------------------------------------------------------
 * FUNCTION_RETURN:
 *  E_OK -- means the function is executed successfully
 *  E_NOT_OK -- means the function is not completed / error code
 * FUNCTION_RETURN_END:
 * --------------------------------------------------------------------------
 */

Std_ReturnType RBAPLCUST_F18C_ModeSelector_WriteData (const uint8 * Data, Dcm_NegativeResponseCodeType * ErrorCode)
{
	/* Return value initialization */
	Std_ReturnType retVal = E_NOT_OK;
#if(RBFS_DCOM_ModeSelector == RBFS_DCOM_ModeSelector_ON)
	/* DID: 0xF18C - ModeSelector
	 * Operation: Write data to NVM (EEPROM) with enum value validation
	 * Valid values: 0x00, 0x01, 0x02
	 * Size: 1 bytes
	 * NVM Block: NVM_ID_DCOM_ModeSelector */
	if((Data[0] == DID_F18C_VAL_0) || (Data[0] == DID_F18C_VAL_1) || (Data[0] == DID_F18C_VAL_2))
	{
		/* Valid enum value - perform NVM write operation */
		retVal = DCOM_WriteDataByNVMId(NvMConf_NvMBlockDescriptor_NVM_ID_DCOM_ModeSelector, Data, ErrorCode);
	}
	else
	{
		/* Invalid enum value - return request out of range */
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
