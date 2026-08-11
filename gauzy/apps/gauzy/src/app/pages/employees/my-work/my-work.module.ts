import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Routes } from '@angular/router';
import { NbCardModule } from '@nebular/theme';
import { TranslateModule } from '@ngx-translate/core';
import { PermissionsEnum } from '@gauzy/contracts';
import { BookmarkQueryParamsResolver, PermissionsGuard } from '@gauzy/ui-core/core';
import { DateRangePickerResolver, DynamicTabsModule, SharedModule } from '@gauzy/ui-core/shared';
import { MyWorkLayoutComponent } from './my-work-layout.component';
import { AppUsageComponent } from '../activity/app-usage/app-usage.component';
import { AppUsageModule } from '../activity/app-usage/app-usage.module';
import { AppCategoriesComponent } from '../app-categories/app-categories.component';
import { AppCategoriesModule } from '../app-categories/app-categories.module';

/**
 * Each tab keeps the date-picker configuration its page already had when it
 * stood alone — productivity, app categories and app usage are single-day
 * reads, apps & URLs is a week. Changing that here would silently alter what
 * the pages show.
 *
 * Productivity is open to everyone: an employee may see how their own day was
 * spent. The other three carry ORG_EMPLOYEES_VIEW, so only admins, super admins
 * and managers reach them — the classification, the raw app list and the URL
 * report are all management views of someone else's work.
 */
const routes: Routes = [
	{
		path: '',
		component: MyWorkLayoutComponent,
		data: { tabsetId: 'my-work-page', title: 'My work' },
		children: [
			{
				path: '',
				redirectTo: 'productivity',
				pathMatch: 'full'
			},
			{
				path: 'productivity',
				loadChildren: () => import('../productivity/productivity.module').then((m) => m.ProductivityModule),
				data: {
					selectors: { project: false, employee: true, date: true, organization: true },
					datePicker: {
						unitOfTime: 'day',
						isLockDatePicker: true,
						isSaveDatePicker: false,
						isSingleDatePicker: true,
						isDisableFutureDate: true
					}
				},
				resolve: { dates: DateRangePickerResolver }
			},
			{
				// Admin/manager only. Hiding the tab is presentation; this is the
				// part that refuses a typed URL. The API scopes which employee's
				// data comes back regardless — see docs/manager-role-and-visibility.md.
				path: 'apps-urls',
				canActivate: [PermissionsGuard],
				data: {
					permissions: {
						only: [PermissionsEnum.ORG_EMPLOYEES_VIEW],
						redirectTo: '/pages/employees/my-work/productivity'
					}
				},
				loadChildren: () =>
					import('../../reports/apps-urls-report/apps-urls-report.module').then((m) => m.AppsUrlsReportModule)
			},
			{
				// The app CLASSIFICATION — which applications counted as
				// productive, neutral or unproductive — rather than the totals.
				// Deliberately its own tab and not part of the Productivity page:
				// that page is read by the employee themselves and answers "how
				// much of my day was productive", while this exposes the rule
				// being applied to them, which is what a manager needs when a
				// figure is challenged.
				//
				// Same guard as the two tabs below. Hiding a tab is presentation;
				// this is the part that refuses a typed URL.
				path: 'app-categories',
				component: AppCategoriesComponent,
				canActivate: [PermissionsGuard],
				data: {
					permissions: {
						only: [PermissionsEnum.ORG_EMPLOYEES_VIEW],
						redirectTo: '/pages/employees/my-work/productivity'
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
				resolve: {
					dates: DateRangePickerResolver,
					bookmarkParams: BookmarkQueryParamsResolver
				}
			},
			{
				// The three Time & Activity views, so My work carries the same set as
				// the per-employee page. Same guard as the rest: an employee sees
				// Productivity and nothing else.
				path: 'apps',
				canActivate: [PermissionsGuard],
				data: {
					permissions: {
						only: [PermissionsEnum.ORG_EMPLOYEES_VIEW],
						redirectTo: '/pages/employees/my-work/productivity'
					}
				},
				loadChildren: () =>
					import('../../reports/apps-urls-report/apps-urls-report.module').then((m) => m.AppsUrlsReportModule)
			},
			{
				path: 'urls',
				canActivate: [PermissionsGuard],
				data: {
					permissions: {
						only: [PermissionsEnum.ORG_EMPLOYEES_VIEW],
						redirectTo: '/pages/employees/my-work/productivity'
					}
				},
				loadChildren: () =>
					import('../../reports/apps-urls-report/apps-urls-report.module').then((m) => m.AppsUrlsReportModule)
			},
			{
				path: 'screenshots',
				canActivate: [PermissionsGuard],
				data: {
					permissions: {
						only: [PermissionsEnum.ORG_EMPLOYEES_VIEW],
						redirectTo: '/pages/employees/my-work/productivity'
					},
					datePicker: {
						unitOfTime: 'day',
						isLockDatePicker: true,
						isSaveDatePicker: false,
						isSingleDatePicker: true,
						isDisableFutureDate: true
					}
				},
				resolve: { dates: DateRangePickerResolver, bookmarkParams: BookmarkQueryParamsResolver },
				loadChildren: () =>
					import('../activity/screenshot/screenshot.module').then((m) => m.ScreenshotModule)
			},
			{
				path: 'app-usage',
				component: AppUsageComponent,
				canActivate: [PermissionsGuard],
				data: {
					permissions: {
						only: [PermissionsEnum.ORG_EMPLOYEES_VIEW],
						redirectTo: '/pages/employees/my-work/productivity'
					},
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
			}
		]
	}
];

@NgModule({
	imports: [
		CommonModule,
		RouterModule.forChild(routes),
		NbCardModule,
		TranslateModule.forChild(),
		AppUsageModule,
		AppCategoriesModule,
		DynamicTabsModule,
		SharedModule
	],
	declarations: [MyWorkLayoutComponent]
})
export class MyWorkModule {}
