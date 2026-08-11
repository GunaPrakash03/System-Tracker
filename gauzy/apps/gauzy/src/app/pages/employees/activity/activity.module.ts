import { Inject, NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ROUTES, RouterModule } from '@angular/router';
import { NbButtonModule, NbCardModule, NbInputModule, NbSelectModule, NbSpinnerModule } from '@nebular/theme';
import { TranslateModule } from '@ngx-translate/core';
import { PermissionsEnum } from '@gauzy/contracts';
import { BookmarkQueryParamsResolver, PageRouteRegistryService, PermissionsGuard } from '@gauzy/ui-core/core';
import {
	ActivityItemModule,
	DateRangePickerResolver,
	DynamicTabsModule,
	GauzyFiltersModule,
	NoDataMessageModule,
	SharedModule
} from '@gauzy/ui-core/shared';
import { createActivityRoutes } from './activity.routes';
import { ActivityLayoutComponent } from './layout/layout.component';
import { AppUrlActivityComponent } from './app-url-activity/app-url-activity.component';
import { AppUsageComponent } from './app-usage/app-usage.component';
import { AppUsageModule } from './app-usage/app-usage.module';
import { AppCategoriesComponent } from '../app-categories/app-categories.component';
import { AppCategoriesModule } from '../app-categories/app-categories.module';

@NgModule({
	imports: [
		CommonModule,
		FormsModule,
		RouterModule.forChild([]),
		NbButtonModule,
		NbCardModule,
		NbInputModule,
		NbSelectModule,
		NbSpinnerModule,
		TranslateModule.forChild(),
		ActivityItemModule,
		AppUsageModule,
		AppCategoriesModule,
		DynamicTabsModule,
		GauzyFiltersModule,
		NoDataMessageModule,
		SharedModule
	],
	declarations: [ActivityLayoutComponent, AppUrlActivityComponent],
	providers: [
		{
			provide: ROUTES,
			useFactory: (service: PageRouteRegistryService) => createActivityRoutes(service),
			deps: [PageRouteRegistryService],
			multi: true
		}
	]
})
export class ActivityModule {
	private static hasRegisteredPageRoutes = false; // Flag to check if routes have been registered

	constructor(@Inject(PageRouteRegistryService) readonly _pageRouteRegistryService: PageRouteRegistryService) {
		// Register the routes
		this.registerPageRoutes();
	}

	/**
	 * Registers page routes for the activity module.
	 * Ensures that routes are registered only once.
	 *
	 * @returns {void}
	 */
	registerPageRoutes(): void {
		if (ActivityModule.hasRegisteredPageRoutes) {
			return;
		}

		// Register Time & Activity Page Routes
		this._pageRouteRegistryService.registerPageRoute({
			location: 'time-activity-sections',
			path: 'time-activities',
			loadChildren: () =>
				import('./time-activities/time-activities.module').then((m) => m.TimeAndActivitiesModule)
		});

		// Register Screenshot Page Routes.
		//
		// Guarded by ORG_EMPLOYEES_VIEW, which admins and managers hold and plain
		// employees do not — screenshots are not part of an employee's own
		// self-service view. Without the guard the page is still reachable by
		// typing the URL, and would render that employee's own screenshots.
		// The three views that also appear under My work, registered here so the
		// per-employee page can show them. Same components, same date-picker
		// config — only the way in differs.
		this._pageRouteRegistryService.registerPageRoute({
			location: 'time-activity-sections',
			path: 'productivity',
			canActivate: [PermissionsGuard],
			data: {
				permissions: {
					only: [PermissionsEnum.ORG_EMPLOYEES_VIEW],
					redirectTo: '/pages/employees'
				},
				datePicker: {
					unitOfTime: 'day',
					isLockDatePicker: true,
					isSaveDatePicker: false,
					isSingleDatePicker: true,
					isDisableFutureDate: true
				}
			},
			resolve: { dates: DateRangePickerResolver },
			loadChildren: () => import('../productivity/productivity.module').then((m) => m.ProductivityModule)
		});

		this._pageRouteRegistryService.registerPageRoute({
			location: 'time-activity-sections',
			path: 'app-categories',
			component: AppCategoriesComponent,
			canActivate: [PermissionsGuard],
			data: {
				permissions: {
					only: [PermissionsEnum.ORG_EMPLOYEES_VIEW],
					redirectTo: '/pages/employees'
				},
				datePicker: {
					unitOfTime: 'day',
					isLockDatePicker: true,
					isSaveDatePicker: false,
					isSingleDatePicker: true,
					isDisableFutureDate: true
				},
				title: 'App categories',
				type: 'app-categories'
			},
			resolve: { dates: DateRangePickerResolver, bookmarkParams: BookmarkQueryParamsResolver }
		});

		this._pageRouteRegistryService.registerPageRoute({
			location: 'time-activity-sections',
			path: 'apps-urls',
			canActivate: [PermissionsGuard],
			data: {
				permissions: {
					only: [PermissionsEnum.ORG_EMPLOYEES_VIEW],
					redirectTo: '/pages/employees'
				}
			},
			loadChildren: () =>
				import('../../reports/apps-urls-report/apps-urls-report.module').then((m) => m.AppsUrlsReportModule)
		});

		this._pageRouteRegistryService.registerPageRoute({
			location: 'time-activity-sections',
			path: 'screenshots',
			canActivate: [PermissionsGuard],
			data: {
				permissions: {
					only: [PermissionsEnum.ORG_EMPLOYEES_VIEW],
					redirectTo: '/pages/employees/my-work'
				},
				// Single-day, matching every other activity tab. Without this the
				// route declares no range at all, and the date picker is *shared*
				// global state (DateRangePickerBuilderService) — so arriving from
				// Timesheets → Weekly or Calendar ('week') or Approvals ('month')
				// left that wider range in place and the gallery showed yesterday's
				// screenshots next to today's. The API was filtering correctly the
				// whole time; the page was asking for the wrong window.
				datePicker: {
					unitOfTime: 'day',
					isLockDatePicker: true,
					isSaveDatePicker: false,
					isSingleDatePicker: true,
					isDisableFutureDate: true
				}
			},
			resolve: {
				dates: DateRangePickerResolver,
				bookmarkParams: BookmarkQueryParamsResolver
			},
			loadChildren: () => import('./screenshot/screenshot.module').then((m) => m.ScreenshotModule)
		});

		// Register Videos Page Routes
		this._pageRouteRegistryService.registerPageRoute({
			location: 'time-activity-sections',
			path: 'videos',
			loadChildren: () => import('@gauzy/plugin-videos-ui').then((m) => m.VideoUiModule)
		});

		// Register App Usage Page Routes — running time vs on-screen time.
		this._pageRouteRegistryService.registerPageRoute({
			location: 'time-activity-sections',
			path: 'app-usage',
			component: AppUsageComponent,
			data: {
				// Single-day, like the other activity tabs: this is a per-day
				// report, and the page reads the header selectors rather than
				// carrying an employee dropdown and date field of its own.
				datePicker: {
					unitOfTime: 'day',
					isLockDatePicker: true,
					isSaveDatePicker: false,
					isSingleDatePicker: true,
					isDisableFutureDate: true
				},
				title: 'App usage',
				type: 'app-usage'
			},
			resolve: {
				dates: DateRangePickerResolver,
				bookmarkParams: BookmarkQueryParamsResolver
			}
		});

		// Register App Activity Page Routes
		this._pageRouteRegistryService.registerPageRoute({
			location: 'time-activity-sections',
			path: 'apps',
			component: AppUrlActivityComponent,
			data: {
				datePicker: {
					unitOfTime: 'day',
					isLockDatePicker: true,
					isSaveDatePicker: true,
					isSingleDatePicker: true,
					isDisableFutureDate: true
				},
				title: 'ACTIVITY.APPS', // Register the title for the page
				type: 'apps' // Register the type for the page
			},
			resolve: {
				dates: DateRangePickerResolver,
				bookmarkParams: BookmarkQueryParamsResolver
			}
		});

		// Register URL Activity Page Routes
		this._pageRouteRegistryService.registerPageRoute({
			location: 'time-activity-sections',
			path: 'urls',
			component: AppUrlActivityComponent,
			data: {
				datePicker: {
					unitOfTime: 'day',
					isLockDatePicker: true,
					isSaveDatePicker: true,
					isSingleDatePicker: true,
					isDisableFutureDate: true
				},
				title: 'ACTIVITY.VISITED_SITES', // Register the title for the page
				type: 'urls' // Register the type for the page
			},
			resolve: {
				dates: DateRangePickerResolver,
				bookmarkParams: BookmarkQueryParamsResolver
			}
		});

		// Set the flag to true
		ActivityModule.hasRegisteredPageRoutes = true;
	}
}
