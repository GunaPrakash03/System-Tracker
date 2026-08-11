import { Component, OnInit, OnDestroy, ChangeDetectorRef } from '@angular/core';
import { ActivatedRoute, QueryParamsHandling } from '@angular/router';
import { tap } from 'rxjs';
import { UntilDestroy, untilDestroyed } from '@ngneat/until-destroy';
import { PermissionsEnum } from '@gauzy/contracts';
import { EmployeesService, PageTabRegistryService, PageTabsetPageId, RouteUtil, Store } from '@gauzy/ui-core/core';
import { firstValueFrom } from 'rxjs';

@UntilDestroy({ checkProperties: true })
@Component({
	selector: 'ngx-time-activities-layout',
	templateUrl: './layout.component.html',
	styleUrls: ['./layout.component.scss'],
	providers: [RouteUtil],
	standalone: false
})
export class ActivityLayoutComponent implements OnInit, OnDestroy {
	public title: string;
	public tabsetId: PageTabsetPageId = this._route.snapshot.data.tabsetId; // The identifier for the tabset

	constructor(
		private readonly _route: ActivatedRoute,
		private readonly _cdr: ChangeDetectorRef,
		private readonly _routeUtil: RouteUtil,
		private readonly _pageTabRegistryService: PageTabRegistryService,
		private readonly _employeesService: EmployeesService,
		private readonly _store: Store
	) {}

	ngOnInit(): void {
		// Register the page tabs
		this.registerPageTabs();
		this.selectEmployeeFromUrl();

		this._routeUtil.data$
			.pipe(
				tap((data) => (this.title = data.title)),
				untilDestroyed(this)
			)
			.subscribe();
	}

	ngAfterViewInit(): void {
		this._cdr.detectChanges();
	}

	/**
	 * Puts the employee named in the URL into the shared selector.
	 *
	 * This is what makes a per-employee view linkable. Every tab under here reads
	 * `store.selectedEmployee$` — the header dropdown is its only other writer —
	 * so setting it from the URL leaves all seven components untouched while
	 * making the address the source of truth. Repointing each component at a
	 * route parameter instead would have meant editing the data-loading path of
	 * seven pages, which is precisely where this project's defects have come
	 * from.
	 *
	 * A QUERY parameter, not a path segment: the tabs already declare
	 * `queryParamsHandling: 'merge'`, so ?employeeId carries across a tab switch
	 * for free, and /pages/employees/activity/screenshots keeps working without
	 * an employee for the sidebar link. docs/employee-activity-pages.md describes
	 * a /:employeeId/ path; this is the same guarantee with no route surgery.
	 *
	 * Silent on failure by design. A stale or deleted id should leave whatever
	 * the header already had rather than blanking the page — an empty report is
	 * indistinguishable from a broken one, which this codebase has learned twice.
	 */
	private async selectEmployeeFromUrl(): Promise<void> {
		const employeeId = this._route.snapshot.queryParamMap.get('employeeId');
		if (!employeeId || this._store.selectedEmployee?.id === employeeId) {
			return;
		}
		try {
			const employee: any = await firstValueFrom(
				this._employeesService.getEmployeeById(employeeId, ['user'])
			);
			if (!employee) return;
			this._store.selectedEmployee = {
				id: employee.id,
				firstName: employee.user?.firstName,
				lastName: employee.user?.lastName,
				fullName: employee.user?.name,
				imageUrl: employee.user?.imageUrl,
				tags: employee.tags || []
			} as any;
		} catch {
			// See the note above: leave the existing selection alone.
		}
	}

	/**
	 * Registers page tabs for the timesheet module.
	 * Ensures that tabs are registered only once.
	 *
	 * @returns {void}
	 */
	registerPageTabs(): void {
		// The three views that used to live only under My work. Registered first
		// so an employee opens on Productivity — the summary — rather than on a raw
		// activity list.
		this._pageTabRegistryService.registerPageTab({
			tabsetId: this.tabsetId,
			tabId: 'productivity',
			tabsetType: 'route',
			tabTitle: () => 'Productivity',
			responsive: true,
			route: '/pages/employees/activity/productivity',
			queryParamsHandling: 'merge' as QueryParamsHandling,
			activeLinkOptions: { exact: false },
			order: -3,
			permissions: [PermissionsEnum.ORG_EMPLOYEES_VIEW]
		});
		this._pageTabRegistryService.registerPageTab({
			tabsetId: this.tabsetId,
			tabId: 'app-categories',
			tabsetType: 'route',
			tabTitle: () => 'App categories',
			responsive: true,
			route: '/pages/employees/activity/app-categories',
			queryParamsHandling: 'merge' as QueryParamsHandling,
			activeLinkOptions: { exact: false },
			order: -2,
			permissions: [PermissionsEnum.ORG_EMPLOYEES_VIEW]
		});
		this._pageTabRegistryService.registerPageTab({
			tabsetId: this.tabsetId,
			tabId: 'apps-urls',
			tabsetType: 'route',
			tabTitle: () => 'Apps & URLs',
			responsive: true,
			route: '/pages/employees/activity/apps-urls',
			queryParamsHandling: 'merge' as QueryParamsHandling,
			activeLinkOptions: { exact: false },
			order: -1,
			permissions: [PermissionsEnum.ORG_EMPLOYEES_VIEW]
		});

		// Register the time-activity tab
		this._pageTabRegistryService.registerPageTab({
			tabsetId: this.tabsetId, // The identifier for the tabset
			tabId: 'time-activities', // The identifier for the tab
			tabsetType: 'route', // The type of tabset to use
			tabTitle: (_i18n) => _i18n.getTranslation('ACTIVITY.TIME_AND_ACTIVITIES'), // The title for the tab
			responsive: true, // Whether the tab is responsive
			route: '/pages/employees/activity/time-activities', // The route for the tab
			queryParamsHandling: 'merge' as QueryParamsHandling,
			activeLinkOptions: { exact: false }, // The options for the active link
			order: 1, // The order of the tab
			permissions: [PermissionsEnum.TIME_TRACKER, PermissionsEnum.TIME_TRACKING_DASHBOARD] // The permissions required to display the tab
		});

		// Register the screenshots tab
		this._pageTabRegistryService.registerPageTab({
			tabsetId: this.tabsetId, // The identifier for the tabset
			tabId: 'screenshots', // The identifier for the tab
			tabsetType: 'route', // The type of tabset to use
			tabTitle: (_i18n) => _i18n.getTranslation('ACTIVITY.SCREENSHOTS'), // The title for the tab
			responsive: true, // Whether the tab is responsive
			route: '/pages/employees/activity/screenshots', // The route for the tab
			queryParamsHandling: 'merge' as QueryParamsHandling,
			activeLinkOptions: { exact: false }, // The options for the active link
			order: 2, // The order of the tab
			permissions: [PermissionsEnum.TIME_TRACKER, PermissionsEnum.TIME_TRACKING_DASHBOARD] // The permissions required to display the tab
		});

		this._pageTabRegistryService.registerPageTab({
			tabsetId: this.tabsetId, // The identifier for the tabset
			tabId: 'videos', // The identifier for the tab
			tabsetType: 'route', // The type of tabset to use
			tabTitle: (_i18n) => _i18n.getTranslation('PLUGIN.VIDEO.PLURAL'), // The title for the tab
			responsive: true, // Whether the tab is responsive
			route: '/pages/employees/activity/videos', // The route for the tab
			queryParamsHandling: 'merge' as QueryParamsHandling,
			activeLinkOptions: { exact: false }, // The options for the active link
			hide: !this._route.snapshot.data.videoAvailability,
			order: 3, // The order of the tab
			permissions: [PermissionsEnum.TIME_TRACKER, PermissionsEnum.TIME_TRACKING_DASHBOARD] // The permissions required to display the tab
		});

		// Register the app usage tab — running time vs on-screen time.
		//
		// Sits before the built-in Apps tab because it answers the question that
		// tab appears to answer. Gauzy's Apps percentage is an app's share of the
		// summed durations of every tracked process, and this tracker records
		// headless services too, so every app converges on 1/(number of apps)
		// regardless of use. Screen time is the honest measure.
		this._pageTabRegistryService.registerPageTab({
			tabsetId: this.tabsetId,
			tabId: 'app-usage',
			tabsetType: 'route',
			tabTitle: () => 'App usage',
			responsive: true,
			route: '/pages/employees/activity/app-usage',
			queryParamsHandling: 'merge' as QueryParamsHandling,
			activeLinkOptions: { exact: false },
			order: 4,
			permissions: [PermissionsEnum.TIME_TRACKER, PermissionsEnum.TIME_TRACKING_DASHBOARD]
		});

		// Register the app activity tab
		this._pageTabRegistryService.registerPageTab({
			tabsetId: this.tabsetId, // The identifier for the tabset
			tabId: 'app-activity', // The identifier for the tab
			tabsetType: 'route', // The type of tabset to use
			tabTitle: (_i18n) => _i18n.getTranslation('ACTIVITY.APPS'), // The title for the tab
			responsive: true, // Whether the tab is responsive
			route: '/pages/employees/activity/apps', // The route for the tab
			queryParamsHandling: 'merge' as QueryParamsHandling,
			activeLinkOptions: { exact: false }, // The options for the active link
			order: 5, // The order of the tab
			permissions: [PermissionsEnum.TIME_TRACKER, PermissionsEnum.TIME_TRACKING_DASHBOARD] // The permissions required to display the tab
		});

		// Register the visited sites tab
		this._pageTabRegistryService.registerPageTab({
			tabsetId: this.tabsetId, // The identifier for the tabset
			tabId: 'urls-activity', // The identifier for the tab
			tabsetType: 'route', // The type of tabset to use
			tabTitle: (_i18n) => _i18n.getTranslation('ACTIVITY.VISITED_SITES'), // The title for the tab
			responsive: true, // Whether the tab is responsive
			route: '/pages/employees/activity/urls', // The route for the tab
			queryParamsHandling: 'merge' as QueryParamsHandling,
			activeLinkOptions: { exact: false }, // The options for the active link
			order: 6, // The order of the tab
			permissions: [PermissionsEnum.TIME_TRACKER, PermissionsEnum.TIME_TRACKING_DASHBOARD] // The permissions required to display the tab
		});
	}

	ngOnDestroy(): void {}
}
