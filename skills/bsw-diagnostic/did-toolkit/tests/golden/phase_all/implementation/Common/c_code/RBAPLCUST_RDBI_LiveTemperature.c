/**
 * @ingroup 'RBAPLCust'
 * @{
 *
 * RBAPLCUST_RDBI_LiveTemperature.c
 * Contains function to read Information.
 *
 * RBAPLCUST_F1A0_LiveTemperature_ReadData -- Read the LiveTemperature Information
 *
 * \copyright
 * Robert Bosch GmbH reserves all rights even in the event of industrial property rights.
 * We reserve all rights of disposal such as copying and passing on to third parties.
 */


/* used interfaces */

#include "RBAPLCUST_Global.h"

/* realized interfaces */

/* Assert supported configurations: switches, parameters, constants, ... */
RB_ASSERT_SWITCH_SETTINGS(RBFS_DCOM_LiveTemperature,
						  RBFS_DCOM_LiveTemperature_ON,
						  RBFS_DCOM_LiveTemperature_OFF);


/*
 * --------------------------------------------------------------------------
 * FUNCTION_NAME:
 *  RBAPLCUST_F1A0_LiveTemperature_ReadData
 * FUNCTION_NAME_END:
 * --------------------------------------------------------------------------
 * FUNCTION_DESCRIPTION:
 *  Read the LiveTemperature Information
 * FUNCTION_DESCRIPTION_END:
 * --------------------------------------------------------------------------
 * FUNCTION_PARAMETER:
 *  Data --- corresponding buffer for updating LiveTemperature information
 * FUNCTION_PARAMETER_END:
 * --------------------------------------------------------------------------
 * FUNCTION_RETURN:
 *  E_OK -- means the function is executed successfully
 *  E_NOT_OK -- means the function is not completed / error code
 * FUNCTION_RETURN_END:
 * --------------------------------------------------------------------------
 */

Std_ReturnType RBAPLCUST_F1A0_LiveTemperature_ReadData (uint8 * Data)
{
	/* Return value initialization */
	Std_ReturnType retVal = E_NOT_OK;
#if(RBFS_DCOM_LiveTemperature == RBFS_DCOM_LiveTemperature_ON)
	/* DID: 0xF1A0 - LiveTemperature
	 * Operation: Read data (RAM storage)
	 * Size: 1 bytes
	 *
	 * TODO(agent): replace this stub with the real RAM read body.
	 *   Brief:     outputs/implementation/c_code/_briefs/0xF1A0_r.md
	 *   Playbook:  reference/implementation-storage-positions.md
	 *   On completion: flip retVal = E_NOT_OK -> E_OK and remove
	 *                  this TODO(agent) line. */
#endif
	return retVal;
}

/** @}
 * End ingroup 'RBAPLCust'
 */
