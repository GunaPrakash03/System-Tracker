import { Component, OnInit, ChangeDetectorRef, AfterViewInit } from '@angular/core';
import { ActivatedRoute, QueryParamsHandling } from '@angular/router';
import { tap } from 'rxjs';
import { UntilDestroy, untilDestroyed } from '@ngneat/until-destroy';
import { PermissionsEnum } from '@gauzy/contracts';
import { PageTabRegistryService, PageTabsetPageId, RouteUtil } from '@gauzy/ui-core/core';

/**
 * "My Work" — the page an employee lands on.
 *
 * The reads are gathered here as tabs rather than sitting as separate sidebar
 * entries: Productivity for the employee themselves, and App categories, Apps &
 * URLs and App usage for admins and managers. An employee has one place to go;
 * an admin or manager reaching the same page sees whichever employee the header
 * selector is pointing at, with the API deciding whether that selection is
 * permitted.
 */
@UntilDestroy({ checkProperties: true })
@Component({
	selector: 'ngx-my-work-layout',
	templateUrl: './my-work-layout.component.html',
	providers: [RouteUtil],
	standalone: false
})
export class MyWorkLayoutComponent implements OnInit, AfterViewInit {
	public title: string;
	public tabsetId: PageTabsetPageId = this._route.snapshot.data.tabsetId;

	constructor(
		private readonly _route: ActivatedRoute,
		private readonly _cdr: ChangeDetectorRef,
		private readonly _routeUtil: RouteUtil,
		private readonly _pageTabRegistryService: PageTabRegistryService
	) {}

	ngOnInit(): void {
		this.registerPageTabs();

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
	 * Registers the page's tabs.
	 *
	 * TIME_TRACKER gates Productivity: every role that may see this page at all
	 * holds it, and which *employee's* data comes back is settled by the API,
	 * not by hiding a tab. The rest need ORG_EMPLOYEES_VIEW.
	 *
	 * @returns {void}
	 */
	registerPageTabs(): void {
		this._pageTabRegistryService.registerPageTab({
			tabsetId: this.tabsetId,
			tabId: 'productivity',
			tabsetType: 'route',
			tabTitle: () => 'Productivity',
			responsive: true,
			route: '/pages/employees/my-work/productivity',
			queryParamsHandling: 'merge' as QueryParamsHandling,
			activeLinkOptions: { exact: false },
			order: 1,
			permissions: [PermissionsEnum.TIME_TRACKER]
		});

		// The remaining tabs are for admins and managers, not for the employee
		// themselves — an employee's self-service view is Productivity alone.
		// ORG_EMPLOYEES_VIEW is the separator: employees do not hold it, managers
		// and admins do. Hiding the tab is only half of it; the routes carry the
		// same guard (see my-work.module.ts) so a typed URL is refused rather
		// than rendering.
		//
		// Registering the tab is NOT optional and is easy to forget: a route
		// added to my-work.module.ts without a matching entry here is reachable
		// by URL but invisible, which reads as "the feature did not ship".
		this._pageTabRegistryService.registerPageTab({
			tabsetId: this.tabsetId,
			tabId: 'app-categories',
			tabsetType: 'route',
			tabTitle: () => 'App categories',
			responsive: true,
			route: '/pages/employees/my-work/app-categories',
			queryParamsHandling: 'merge' as QueryParamsHandling,
			activeLinkOptions: { exact: false },
			// Next to Productivity, whose numbers it explains.
			order: 2,
			permissions: [PermissionsEnum.ORG_EMPLOYEES_VIEW]
		});

		this._pageTabRegistryService.registerPageTab({
			tabsetId: this.tabsetId,
			tabId: 'apps-urls',
			tabsetType: 'route',
			tabTitle: () => 'Apps & URLs',
			responsive: true,
			route: '/pages/employees/my-work/apps-urls',
			queryParamsHandling: 'merge' as QueryParamsHandling,
			activeLinkOptions: { exact: false },
			order: 3,
			permissions: [PermissionsEnum.ORG_EMPLOYEES_VIEW]
		});

		this._pageTabRegistryService.registerPageTab({
			tabsetId: this.tabsetId,
			tabId: 'app-usage',
			tabsetType: 'route',
			tabTitle: () => 'App usage',
			responsive: true,
			route: '/pages/employees/my-work/app-usage',
			queryParamsHandling: 'merge' as QueryParamsHandling,
			activeLinkOptions: { exact: false },
			order: 4,
			permissions: [PermissionsEnum.ORG_EMPLOYEES_VIEW]
		});
	}
}
