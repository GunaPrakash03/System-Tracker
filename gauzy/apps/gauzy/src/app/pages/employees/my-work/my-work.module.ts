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

/**
 * The three tabs keep the date-picker configuration each page already had when
 * it stood alone — productivity and app usage are single-day reads, apps & URLs
 * is a week. Changing that here would silently alter what the pages show.
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
		DynamicTabsModule,
		SharedModule
	],
	declarations: [MyWorkLayoutComponent]
})
export class MyWorkModule {}
