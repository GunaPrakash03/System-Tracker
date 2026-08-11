import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { Type } from 'class-transformer';
import { IsEnum, IsNotEmpty, IsObject, IsOptional, IsUUID, ValidateIf, ValidateNested } from 'class-validator';
import { IntersectionType } from '@nestjs/mapped-types';
import { ID, IEmployee, IEmployeeCreateInput, RolesEnum } from '@gauzy/contracts';
import { EmploymentDTO } from './employment.dto';
import { UserInputDTO } from './user-input-dto';
import { RelationalTagDTO } from './../../tags/dto';

/**
 * Employee Create DTO
 *
 */
export class CreateEmployeeDTO
	extends IntersectionType(EmploymentDTO, RelationalTagDTO)
	implements IEmployeeCreateInput
{
	/**
	 * Create user to the employee
	 */
	@ApiPropertyOptional({ type: () => UserInputDTO })
	@ValidateIf((it) => !it.userId)
	@IsObject()
	@ValidateNested()
	@Type(() => UserInputDTO)
	readonly user: UserInputDTO;

	/**
	 * Sync user to the employee
	 */
	@ApiPropertyOptional({ type: () => String })
	@ValidateIf((it) => !it.user)
	@IsNotEmpty()
	@IsUUID()
	readonly userId: ID;

	@ApiProperty({ type: () => String, required: true })
	@ValidateIf((it) => !it.userId)
	@IsNotEmpty()
	readonly password: string;

	/**
	 * Role to give the new user. Only EMPLOYEE, MANAGER and ADMIN reach the
	 * handler; it decides separately whether this caller may actually grant the
	 * one requested, falling back to EMPLOYEE when they may not.
	 */
	@ApiPropertyOptional({ enum: [RolesEnum.EMPLOYEE, RolesEnum.MANAGER, RolesEnum.ADMIN] })
	@IsOptional()
	@IsEnum(RolesEnum)
	readonly roleName?: RolesEnum;

	readonly members?: IEmployee[];
	public originalUrl?: string;
}
