import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';
import { PermissionsEnum } from '@gauzy/contracts';
import { InviteGuard, PermissionsGuard } from '@gauzy/ui-core/core';
import { DateRangePickerResolver } from '@gauzy/ui-core/shared';
import { EmployeesComponent } from './employees.component';
import { ManageEmployeeInviteComponent } from './manage-employee-invite/manage-employee-invite.component';
import { EditEmployeeComponent } from './edit-employee/edit-employee.component';
import {
	EditEmployeeContactComponent,
	EditEmployeeEmploymentComponent,
	EditEmployeeHiringComponent,
	EditEmployeeLocationComponent,
	EditEmployeeMainComponent,
	EditEmployeeNetworksComponent,
	EditEmployeeOtherSettingsComponent,
	EditEmployeeProjectsComponent,
	EditEmployeeRatesComponent
} from './edit-employee/edit-employee-profile';
import { EmployeeResolver, EmployeeViewResolver } from './employee.resolver';
import { ViewEmployeeComponent } from './view-employee/view-employee.component';

const selectors = {
	team: false,
	project: false,
	employee: false,
	date: false,
	organization: false
};

const routes: Routes = [
	{
		path: '',
		component: EmployeesComponent,
		canActivate: [PermissionsGuard],
		data: {
			// The data table identifier for the route
			dataTableId: 'employee-manage-page',
			// The permission required to access the route
			permissions: {
				only: [PermissionsEnum.ORG_EMPLOYEES_VIEW],
				redirectTo: '/pages/dashboard'
			},
			// The selectors for the route
			selectors: {
				team: false,
				project: false,
				employee: false,
				date: false
			}
		}
	},
	{
		// Read-only View. An employee is a large record, so it gets a page rather
		// than a drawer; the guard is the same one that gates the Manage Employees
		// list it is opened from, so it shows nothing new.
		path: 'view/:id',
		component: ViewEmployeeComponent,
		canActivate: [PermissionsGuard],
		data: {
			permissions: {
				only: [PermissionsEnum.ORG_EMPLOYEES_VIEW],
				redirectTo: '/pages/dashboard'
			},
			selectors
		},
		resolve: { employee: EmployeeViewResolver }
	},
	{
		path: 'edit/:id',
		component: EditEmployeeComponent,
		canActivate: [PermissionsGuard],
		data: {
			// The tabset identifier for the route
			tabsetId: 'employee-edit-page',
			// The permission required to access the route
			permissions: {
				only: [PermissionsEnum.ORG_EMPLOYEES_EDIT, PermissionsEnum.PROFILE_EDIT],
				redirectTo: '/pages/dashboard'
			},
			// The selectors for the route
			selectors
		},
		resolve: { employee: EmployeeResolver },
		children: [
			{
				path: '',
				redirectTo: 'account',
				pathMatch: 'full'
			},
			{
				path: 'account',
				component: EditEmployeeMainComponent,
				data: { selectors }
			},
			{
				path: 'networks',
				component: EditEmployeeNetworksComponent,
				data: { selectors }
			},
			{
				path: 'rates',
				component: EditEmployeeRatesComponent,
				data: { selectors }
			},
			{
				path: 'projects',
				component: EditEmployeeProjectsComponent,
				canActivate: [PermissionsGuard],
				data: {
					// The selectors for the route
					selectors,
					// The permission required to access the route
					permissions: {
						only: [PermissionsEnum.ALL_ORG_VIEW, PermissionsEnum.ORG_PROJECT_VIEW],
						redirectTo: '/pages/dashboard'
					}
				}
			},
			{
				path: 'contacts',
				component: EditEmployeeContactComponent,
				data: { selectors }
			},
			{
				path: 'location',
				component: EditEmployeeLocationComponent,
				data: { selectors }
			},
			{
				path: 'hiring',
				component: EditEmployeeHiringComponent,
				data: { selectors }
			},
			{
				path: 'employment',
				component: EditEmployeeEmploymentComponent,
				data: { selectors }
			},
			{
				path: 'settings',
				component: EditEmployeeOtherSettingsComponent,
				data: { selectors }
			}
		]
	},
	{
		path: 'invites',
		component: ManageEmployeeInviteComponent,
		canActivate: [InviteGuard],
		data: {
			expectedPermissions: [PermissionsEnum.ORG_INVITE_EDIT, PermissionsEnum.ORG_INVITE_VIEW],
			selectors: {
				project: false,
				employee: false,
				date: false
			}
		}
	},
	{
		path: 'timesheets',
		loadChildren: () => import('./timesheet/timesheet.module').then((m) => m.TimesheetModule)
	},
	{
		path: 'activity',
		loadChildren: () => import('./activity/activity.module').then((m) => m.ActivityModule)
	},
	{
		// "My work" — the employee-facing page. Gathers the three reads an
		// employee is allowed into one tabset so they have a single destination
		// rather than three sidebar entries. Admins and managers can open it too;
		// the API decides whose data comes back.
		path: 'my-work',
		loadChildren: () => import('./my-work/my-work.module').then((m) => m.MyWorkModule)
	},
	{
		// Hourly productivity chart. Its own page rather than a settings tab —
		// it is a report read regularly, not a setting changed occasionally.
		path: 'productivity',
		loadChildren: () => import('./productivity/productivity.module').then((m) => m.ProductivityModule),
		data: {
			// Use the dashboard's own header selectors rather than adding a second
			// employee dropdown and date field inside the page. The date picker is
			// locked to a single day because the chart is an hour-by-hour view —
			// a week range has no meaning on a 24-bar axis.
			selectors: {
				project: false,
				employee: true,
				date: true,
				organization: true
			},
			datePicker: {
				unitOfTime: 'day',
				isLockDatePicker: true,
				// NOT saved between visits. A daily report should open on today;
				// persisting the picker meant inheriting whatever range was last
				// used elsewhere — a week range collapsed to its start date, so the
				// page opened four days in the past and looked empty.
				isSaveDatePicker: false,
				isSingleDatePicker: true,
				isDisableFutureDate: true
			}
		},
		resolve: { dates: DateRangePickerResolver }
	}
];

@NgModule({
	imports: [RouterModule.forChild(routes)],
	exports: [RouterModule]
})
export class EmployeesRoutingModule {}
