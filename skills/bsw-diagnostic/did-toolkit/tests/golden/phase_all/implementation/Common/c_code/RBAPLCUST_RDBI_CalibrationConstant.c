/**
 * @ingroup 'RBAPLCust'
 * @{
 *
 * RBAPLCUST_RDBI_CalibrationConstant.c
 * Contains function to read Information.
 *
 * RBAPLCUST_F1A1_CalibrationConstant_ReadData -- Read the CalibrationConstant Information
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


/*
 * --------------------------------------------------------------------------
 * FUNCTION_NAME:
 *  RBAPLCUST_F1A1_CalibrationConstant_ReadData
 * FUNCTION_NAME_END:
 * --------------------------------------------------------------------------
 * FUNCTION_DESCRIPTION:
 *  Read the CalibrationConstant Information
 * FUNCTION_DESCRIPTION_END:
 * --------------------------------------------------------------------------
 * FUNCTION_PARAMETER:
 *  Data --- corresponding buffer for updating CalibrationConstant information
 * FUNCTION_PARAMETER_END:
 * --------------------------------------------------------------------------
 * FUNCTION_RETURN:
 *  E_OK -- means the function is executed successfully
 *  E_NOT_OK -- means the function is not completed / error code
 * FUNCTION_RETURN_END:
 * --------------------------------------------------------------------------
 */

Std_ReturnType RBAPLCUST_F1A1_CalibrationConstant_ReadData (uint8 * Data)
{
	/* Return value initialization */
	Std_ReturnType retVal = E_NOT_OK;
#if(RBFS_DCOM_CalibrationConstant == RBFS_DCOM_CalibrationConstant_ON)
	/* DID: 0xF1A1 - CalibrationConstant
	 * Operation: Read data from NVM (EEPROM)
	 * NVM Block: NVM_ID_DCOM_CalibrationConstant
	 * Size: 1 bytes
	 * Default value: 0xFF */
	retVal = DCOM_ReadDataByNVMId(NvMConf_NvMBlockDescriptor_NVM_ID_DCOM_CalibrationConstant, Data, NVM_CFG_NV_BLOCK_LENGTH_NVM_ID_DCOM_CalibrationConstant, 0xFF);
#endif
	return retVal;
}

/** @}
 * End ingroup 'RBAPLCust'
 */
