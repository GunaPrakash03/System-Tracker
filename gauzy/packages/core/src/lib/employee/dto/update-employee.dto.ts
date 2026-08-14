import { IEmployeeUpdateInput } from '@gauzy/contracts';
import { IntersectionType } from '@nestjs/mapped-types';
import { PickType } from '@nestjs/swagger';
import { UpdateProfileDTO } from './update-profile.dto';
import { Employee } from '../employee.entity';

/**
 * Only SUPER_ADMIN/ADMIN updates these fields
 * Private fields DTO
 */
export class UpdateEmployeeDTO
	extends IntersectionType(
		UpdateProfileDTO,

		PickType(Employee, [
			'show_anonymous_bonus',
			'show_average_bonus',
			'show_average_expenses',
			'show_average_income',
			'show_billrate',
			'show_payperiod',
			'show_start_work_on'
		] as const),

		PickType(Employee, [
			'isActive',
			'isArchived',
			'isVerified',
			'isVetted',
			'isOnline',
			'isTrackingEnabled',
			'isTrackingTime',
			'isJobSearchActive',
			'allowScreenshotCapture',
			'allowManualTime',
			'allowModifyTime',
			'allowDeleteTime',
			'allowAgentAppExit',
			'allowLogoutFromAgentApp',
			'trackKeyboardMouseActivity',
			'trackAllDisplays'
		] as const),

		// This DTO is an explicit allow-list, so a field absent from every PickType
		// is dropped on update without an error — the request succeeds and the value
		// simply does not change. `employeeCode` has to be named here or it would be
		// settable at creation and permanently uneditable afterwards.
		PickType(Employee, ['employeeCode'] as const)
	)
	implements IEmployeeUpdateInput {}
