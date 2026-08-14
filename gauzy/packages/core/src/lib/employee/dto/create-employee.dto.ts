import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { Type } from 'class-transformer';
import {
	IsEnum,
	IsNotEmpty,
	IsObject,
	IsOptional,
	IsString,
	IsUUID,
	MaxLength,
	ValidateIf,
	ValidateNested
} from 'class-validator';
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

	/**
	 * Operator-chosen employee identifier. Optional: leaving it blank keeps the
	 * generated UUID as the only identifier, which is how every employee created
	 * before this field existed still works. Unique per organisation when set —
	 * a duplicate is refused by the database index, not by this DTO.
	 */
	@ApiPropertyOptional({ type: () => String, maxLength: 64 })
	@IsOptional()
	@IsString()
	@MaxLength(64)
	readonly employeeCode?: string;

	readonly members?: IEmployee[];
	public originalUrl?: string;
}
