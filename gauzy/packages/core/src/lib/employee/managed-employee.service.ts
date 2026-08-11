import { Injectable } from '@nestjs/common';
import { In } from 'typeorm';
import { ID, PermissionsEnum, RolesEnum } from '@gauzy/contracts';
import { isNotEmpty } from '@gauzy/utils';
import { RequestContext } from '../core/context';
import { TypeOrmOrganizationTeamEmployeeRepository } from '../organization-team-employee/repository/type-orm-organization-team-employee.repository';
import { TypeOrmOrganizationProjectEmployeeRepository } from '../organization-project/repository/type-orm-organization-project-employee.repository';

/**
 * Stands in for "this caller may see nobody".
 *
 * Every consumer of these ids guards its WHERE clause with isNotEmpty(), so an
 * empty array reads downstream as "apply no employee filter" — i.e. the whole
 * organisation. Returning [] for a denied caller would therefore widen access
 * rather than deny it: a manager asking for an employee outside their team would
 * receive everyone. A uuid that matches no row denies it safely instead.
 */
const NO_ACCESSIBLE_EMPLOYEES: ID = '00000000-0000-0000-0000-000000000000';

/**
 * Service to handle manager access control and filter accessible employeeIds
 * based on team/project membership and manager status.
 *
 * This service centralizes the logic for determining which employees a user can access,
 * taking into account:
 * - Global permissions (CHANGE_SELECTED_EMPLOYEE)
 * - Team manager status (isManager in OrganizationTeamEmployee)
 * - Project manager status (isManager in OrganizationProjectEmployee)
 */
@Injectable()
export class ManagedEmployeeService {
	constructor(
		private readonly typeOrmTeamEmployeeRepository: TypeOrmOrganizationTeamEmployeeRepository,
		private readonly typeOrmProjectEmployeeRepository: TypeOrmOrganizationProjectEmployeeRepository
	) {}

	/**
	 * Guards a scoped caller's id list against the empty-means-everything trap
	 * described on NO_ACCESSIBLE_EMPLOYEES. Only ever use for callers who are
	 * restricted — an admin's empty list legitimately means "no filter".
	 *
	 * @param employeeIds - The ids a restricted caller resolved to
	 * @returns The same ids, or a non-matching sentinel when there are none
	 */
	private denyIfEmpty(employeeIds: ID[]): ID[] {
		return isNotEmpty(employeeIds) ? employeeIds : [NO_ACCESSIBLE_EMPLOYEES];
	}

	/**
	 * Filters the requested employeeIds based on the current user's permissions and manager status.
	 *
	 * Logic:
	 * 1. If user has CHANGE_SELECTED_EMPLOYEE permission → Return requested employeeIds as-is
	 * 2. If user explicitly requests "onlyMe" → Return only current user's employeeId
	 * 3. If teamIds or projectIds are provided → Check if user is manager and filter accordingly
	 * 4. Otherwise → Return only current user's employeeId
	 *
	 * @param requestedEmployeeIds - The employeeIds requested by the client
	 * @param teamIds - The teamIds provided in the request (optional)
	 * @param projectIds - The projectIds provided in the request (optional)
	 * @param onlyMe - If the user explicitly requests their own data only
	 * @returns The filtered list of accessible employeeIds
	 */
	async filterAccessibleEmployeeIds(
		requestedEmployeeIds: ID[] = [],
		teamIds: ID[] = [],
		projectIds: ID[] = [],
		onlyMe: boolean = false
	): Promise<ID[]> {
		const user = RequestContext.currentUser();
		const currentEmployeeId = user?.employeeId;

		// Case 1: Admins are unrestricted.
		//
		// Note this is a ROLE check, not a permission check. A team manager is
		// granted CHANGE_SELECTED_EMPLOYEE so the employee selector works for them
		// in the UI, but for a manager that permission must mean "choose among the
		// people I manage", not "choose anyone". Keying unrestricted access off the
		// permission would hand every manager the whole organisation.
		if (RequestContext.hasRoles([RolesEnum.SUPER_ADMIN, RolesEnum.ADMIN])) {
			return requestedEmployeeIds;
		}

		// Case 2: User explicitly requests "onlyMe"
		if (onlyMe && currentEmployeeId) {
			return [currentEmployeeId];
		}

		// Case 3: No employeeId (user not logged in as employee). Anyone holding
		// the blanket permission keeps their previous unrestricted behaviour.
		if (!currentEmployeeId) {
			return RequestContext.hasPermission(PermissionsEnum.CHANGE_SELECTED_EMPLOYEE)
				? requestedEmployeeIds
				: this.denyIfEmpty([]);
		}

		// Case 4: Check if user is manager of the specified teams/projects
		if (isNotEmpty(teamIds) || isNotEmpty(projectIds)) {
			const isManager = await this.isManagerOfTeamsOrProjects(currentEmployeeId, teamIds, projectIds);

			if (isManager) {
				// User is manager → Get all members of the specified teams/projects
				const managedEmployeeIds = await this.getMembersOfTeamsAndProjects(teamIds, projectIds);

				// Filter requested employeeIds to only include managed employees
				if (isNotEmpty(requestedEmployeeIds)) {
					return this.denyIfEmpty(requestedEmployeeIds.filter((id) => managedEmployeeIds.includes(id)));
				}

				// No specific employeeIds requested → Return all managed employees
				return this.denyIfEmpty(managedEmployeeIds);
			}
		}

		// Case 5: No team or project was named in the request, but the user may
		// still manage people. This is the path every tracking page takes — they
		// filter by employee and date, never by team — so without this branch a
		// manager silently sees only their own data on those pages.
		const managedEmployeeIds = await this.getManagedEmployeeIdsInAnyTeam(currentEmployeeId);

		if (isNotEmpty(managedEmployeeIds)) {
			// Asking for an employee outside the managed set yields an empty result
			// rather than an error, so the response shape is the same for callers
			// who are allowed and callers who are not.
			return this.denyIfEmpty(
				isNotEmpty(requestedEmployeeIds)
					? requestedEmployeeIds.filter((id) => managedEmployeeIds.includes(id))
					: managedEmployeeIds
			);
		}

		// Case 6: Manages nobody, but holds the blanket permission — a non-admin
		// role configured for wide access. Left unrestricted so this change does
		// not quietly narrow any role other than a team manager.
		if (RequestContext.hasPermission(PermissionsEnum.CHANGE_SELECTED_EMPLOYEE)) {
			return requestedEmployeeIds;
		}

		// Case 7: Plain employee → access only to themselves
		return [currentEmployeeId];
	}

	/**
	 * Gets every employeeId the current user manages, across all teams in which
	 * they hold manager status — without the caller having to name a team.
	 *
	 * The manager's own id is included: they are themselves a member row of the
	 * teams they manage, so it is picked up along with everyone else's.
	 *
	 * @param currentEmployeeId - The employeeId of the (possible) manager
	 * @returns employeeIds of all members of the teams this employee manages; empty if they manage none
	 */
	async getManagedEmployeeIdsInAnyTeam(currentEmployeeId: ID): Promise<ID[]> {
		const tenantId = RequestContext.currentTenantId();

		if (!currentEmployeeId || !tenantId) {
			return [];
		}

		// Teams in which this employee is a manager
		const managedTeams = await this.typeOrmTeamEmployeeRepository.find({
			where: {
				employeeId: currentEmployeeId,
				isManager: true,
				isActive: true,
				isArchived: false,
				tenantId
			},
			select: {
				organizationTeamId: true
			}
		});

		if (!isNotEmpty(managedTeams)) {
			return [];
		}

		return this.getMembersOfTeamsAndProjects(managedTeams.map((team) => team.organizationTeamId));
	}

	/**
	 * Checks if the current employee is a manager of at least one of the specified teams or projects.
	 *
	 * @param currentEmployeeId - The employeeId to check
	 * @param teamIds - The teamIds to check against
	 * @param projectIds - The projectIds to check against
	 * @returns True if the employee is a manager of at least one team or project
	 */
	async isManagerOfTeamsOrProjects(
		currentEmployeeId: ID,
		teamIds: ID[] = [],
		projectIds: ID[] = []
	): Promise<boolean> {
		const tenantId = RequestContext.currentTenantId();

		if (!tenantId) {
			return false;
		}

		// Check if manager of any specified team
		if (isNotEmpty(teamIds)) {
			const isTeamManager = await this.typeOrmTeamEmployeeRepository.existsBy({
				employeeId: currentEmployeeId,
				organizationTeamId: In(teamIds),
				isManager: true,
				isActive: true,
				isArchived: false,
				tenantId
			});

			if (isTeamManager) {
				return true;
			}
		}

		// Check if manager of any specified project
		if (isNotEmpty(projectIds)) {
			const isProjectManager = await this.typeOrmProjectEmployeeRepository.existsBy({
				employeeId: currentEmployeeId,
				organizationProjectId: In(projectIds),
				isManager: true,
				isActive: true,
				isArchived: false,
				tenantId
			});

			if (isProjectManager) {
				return true;
			}
		}

		return false;
	}

	/**
	 * Checks if the current employee can manage a specific target employee.
	 *
	 * This method verifies access based on:
	 * 1. Global permissions (CHANGE_SELECTED_EMPLOYEE)
	 * 2. Self-access (currentEmployeeId === targetEmployeeId)
	 * 3. Manager status in the specified team (if organizationTeamId provided)
	 *
	 * @param targetEmployeeId - The employee ID to check access for
	 * @param organizationTeamId - Optional team ID to check manager status
	 * @returns true if the current employee can manage the target employee
	 */
	async canManageEmployee(targetEmployeeId: ID, organizationTeamId?: ID): Promise<boolean> {
		const user = RequestContext.currentUser();
		const currentEmployeeId = user?.employeeId;

		// Case 1: Admins may manage anyone. A role check, not a permission check —
		// see the note in filterAccessibleEmployeeIds for why a manager holding
		// CHANGE_SELECTED_EMPLOYEE must not fall through here.
		if (RequestContext.hasRoles([RolesEnum.SUPER_ADMIN, RolesEnum.ADMIN])) {
			return true;
		}

		// Case 2: No employeeId (user not logged in as employee)
		if (!currentEmployeeId) {
			return RequestContext.hasPermission(PermissionsEnum.CHANGE_SELECTED_EMPLOYEE);
		}

		// Case 3: User is accessing their own data
		if (currentEmployeeId === targetEmployeeId) {
			return true;
		}

		// Case 4: Check if user is manager of the target employee in the specified team
		if (organizationTeamId) {
			const tenantId = RequestContext.currentTenantId();

			if (!tenantId) {
				return false;
			}

			// Check if current user is manager of this team
			const isManagerOfTeam = await this.typeOrmTeamEmployeeRepository.existsBy({
				employeeId: currentEmployeeId,
				organizationTeamId: organizationTeamId,
				isManager: true,
				isActive: true,
				isArchived: false,
				tenantId
			});

			if (!isManagerOfTeam) {
				return false;
			}

			// Check if target employee is member of this team
			const isTargetMemberOfTeam = await this.typeOrmTeamEmployeeRepository.existsBy({
				employeeId: targetEmployeeId,
				organizationTeamId: organizationTeamId,
				isActive: true,
				isArchived: false,
				tenantId
			});

			return isTargetMemberOfTeam;
		}

		// Case 5: No team named. Fall back to "do I manage this person in any of my
		// teams?" so callers that carry no team context still resolve correctly.
		if (await this.canManageEmployeeInAnyTeam(targetEmployeeId)) {
			return true;
		}

		// Case 6: Not a manager of this person, but holds the blanket permission —
		// preserved so no existing non-admin role is narrowed by this change.
		return RequestContext.hasPermission(PermissionsEnum.CHANGE_SELECTED_EMPLOYEE);
	}

	/**
	 * Checks if the current employee can manage ALL specified employees.
	 *
	 * This method verifies that the current user can manage every employee in the provided list.
	 * It checks against the specified teams (if provided).
	 *
	 * @param targetEmployeeIds - Array of employee IDs to check access for
	 * @param organizationTeamIds - Optional array of team IDs to check manager status
	 * @returns true if the current employee can manage ALL target employees
	 */
	async canManageEmployees(targetEmployeeIds: ID[], organizationTeamIds?: ID[]): Promise<boolean> {
		// No employees to check → return true
		if (!isNotEmpty(targetEmployeeIds)) {
			return true;
		}

		// Check each employee
		for (const targetEmployeeId of targetEmployeeIds) {
			// Check if user can manage this employee in at least one of the specified teams
			let canManageThisEmployee = false;

			if (isNotEmpty(organizationTeamIds)) {
				// Check against specified teams
				for (const teamId of organizationTeamIds) {
					if (await this.canManageEmployee(targetEmployeeId, teamId)) {
						canManageThisEmployee = true;
						break;
					}
				}
			} else {
				// No teams specified → Check if user manages this employee in ANY team
				canManageThisEmployee = await this.canManageEmployeeInAnyTeam(targetEmployeeId);
			}

			if (!canManageThisEmployee) {
				return false; // At least one employee cannot be managed
			}
		}

		return true; // All employees can be managed
	}

	/**
	 * Checks if the current employee can manage a target employee in ANY team.
	 *
	 * @param targetEmployeeId - The employee ID to check access for
	 * @returns true if the current employee manages the target employee in at least one team
	 */
	private async canManageEmployeeInAnyTeam(targetEmployeeId: ID): Promise<boolean> {
		// Read employeeId off the user rather than RequestContext.currentEmployeeId(),
		// which deliberately returns null for anyone holding CHANGE_SELECTED_EMPLOYEE
		// — that is precisely the manager we need to identify here.
		const currentEmployeeId = RequestContext.currentUser()?.employeeId;
		const tenantId = RequestContext.currentTenantId();

		if (!currentEmployeeId || !tenantId) {
			return false;
		}

		// Get all teams where current user is manager
		const managedTeams = await this.typeOrmTeamEmployeeRepository.find({
			where: {
				employeeId: currentEmployeeId,
				isManager: true,
				isActive: true,
				isArchived: false,
				tenantId
			},
			select: {
                organizationTeamId: true
            }
		});

		if (!isNotEmpty(managedTeams)) {
			return false;
		}

		const managedTeamIds = managedTeams.map((t) => t.organizationTeamId);

		// Check if target employee is member of any of these teams
		const isTargetMember = await this.typeOrmTeamEmployeeRepository.existsBy({
			employeeId: targetEmployeeId,
			organizationTeamId: In(managedTeamIds),
			isActive: true,
			isArchived: false,
			tenantId
		});

		return isTargetMember;
	}

	/**
	 * Gets all employeeIds who are members of the specified teams and/or projects.
	 *
	 * @param teamIds - The teamIds to get members from
	 * @param projectIds - The projectIds to get members from
	 * @returns Array of employeeIds who are members of the specified teams/projects
	 */
	private async getMembersOfTeamsAndProjects(teamIds: ID[] = [], projectIds: ID[] = []): Promise<ID[]> {
		const tenantId = RequestContext.currentTenantId();
		const employeeIds = new Set<ID>();

		if (!tenantId) {
			return [];
		}

		// Get members of specified teams
		if (isNotEmpty(teamIds)) {
			const teamMembers = await this.typeOrmTeamEmployeeRepository.find({
				where: {
					organizationTeamId: In(teamIds),
					isActive: true,
					isArchived: false,
					tenantId
				},
				select: {
                    employeeId: true
                }
			});

			teamMembers.forEach((member) => employeeIds.add(member.employeeId));
		}

		// Get members of specified projects
		if (isNotEmpty(projectIds)) {
			const projectMembers = await this.typeOrmProjectEmployeeRepository.find({
				where: {
					organizationProjectId: In(projectIds),
					isActive: true,
					isArchived: false,
					tenantId
				},
				select: {
                    employeeId: true
                }
			});

			projectMembers.forEach((member) => employeeIds.add(member.employeeId));
		}

		return Array.from(employeeIds);
	}
}
