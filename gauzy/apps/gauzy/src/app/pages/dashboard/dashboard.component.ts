import { Component, OnDestroy, OnInit, Signal, ViewChild, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, NavigationEnd, Router } from '@angular/router';
import { filter, map, tap } from 'rxjs/operators';
import { TranslateService } from '@ngx-translate/core';
import { UntilDestroy, untilDestroyed } from '@ngneat/until-destroy';
import { ISelectedEmployee } from '@gauzy/contracts';
import { PageTabRegistryService, Store, PageTabsetPageId } from '@gauzy/ui-core/core';
import { TranslationBaseComponent } from '@gauzy/ui-core/i18n';
import { DynamicTabsComponent } from '@gauzy/ui-core/shared';

@UntilDestroy()
@Component({
	selector: 'ga-dashboard-layout',
	templateUrl: './dashboard.component.html',
	styleUrls: ['./dashboard.component.scss'],
	standalone: false
})
export class DashboardComponent extends TranslationBaseComponent implements OnInit, OnDestroy {
	private readonly _route = inject(ActivatedRoute);
	private readonly _store = inject(Store);
	private readonly _pageTabRegistryService = inject(PageTabRegistryService);

	public tabsetId: PageTabsetPageId = this._route.snapshot.data.tabsetId; // The identifier for the tabset
	public selectedEmployee: ISelectedEmployee;

	/**
	 * True while a user-built custom dashboard is open (`/pages/dashboard/custom/:id`).
	 *
	 * Drives hiding the standard tabset: those tabs (Teams, Project Management,
	 * Time Tracking, Accounting) are the Standard dashboard's own sections and
	 * are meaningless on a canvas that carries its own tabs.
	 */
	public readonly isCustomDashboard: Signal<boolean> = toSignal(
		inject(Router).events.pipe(
			filter((event): event is NavigationEnd => event instanceof NavigationEnd),
			map((event: NavigationEnd) => event.urlAfterRedirects.includes('/dashboard/custom/'))
		),
		{ initialValue: inject(Router).url.includes('/dashboard/custom/') }
	);

	@ViewChild('dynamicTabs', { static: true }) dynamicTabsComponent!: DynamicTabsComponent;

	constructor(public readonly translateService: TranslateService) {
		super(translateService);
	}

	ngOnInit(): void {
		// Register the page tabs
		this.registerPageTabs();

		// Subscribe to the store employee observable
		const storeEmployee$ = this._store.selectedEmployee$.pipe(
			filter((employee: ISelectedEmployee) => !!employee),
			tap((employee: ISelectedEmployee) => (this.selectedEmployee = employee)),
			tap(() => this.registerAccountingTabs()),
			untilDestroyed(this)
		);

		// Subscribe to the store employee observable
		storeEmployee$.subscribe();
	}

	/**
	 * Registers page tabs for the dashboard module.
	 * Ensures that tabs are registered only once.
	 *
	 * @returns {void}
	 */
	registerPageTabs(): void {
		// Teams and Project Management are deliberately not registered. Neither
		// shows tracking data, which is the only thing this deployment reports on.
		// Their routes remain, so a bookmarked URL still resolves; only the tabs
		// are gone. Accounting is dropped in registerAccountingTabs() below, which
		// owns the tabs that depend on the header's employee selection.
	}

	/**
	 * Registers accounting tabs for the dashboard module.
	 * Ensures that tabs are registered only once.
	 */
	registerAccountingTabs(): void {
		// Remove the specified page tabs for the current tenant
		this._pageTabRegistryService.removePageTab(this.tabsetId, 'accounting');
		this._pageTabRegistryService.removePageTab(this.tabsetId, 'hr');

		// Both tabs upstream registers here are deliberately gone. Accounting
		// reports on invoicing and expenses; Human Resources reports on headcount,
		// recruitment and salaries. Neither shows tracking data, which is the only
		// thing this deployment reports on, so this tabset is now always empty and
		// the dashboard renders its single default view.
		//
		// The /pages/dashboard/hr route still resolves, so an existing bookmark is
		// not broken — only the tab is gone. That matches how Teams and Project
		// Management are handled in registerPageTabs() above.

		// Reload the dynamic tabs component
		this.dynamicTabsComponent.reload$.next(true);
	}

	/**
	 * Clears the registry when the component is destroyed.
	 */
	ngOnDestroy() {}
}
