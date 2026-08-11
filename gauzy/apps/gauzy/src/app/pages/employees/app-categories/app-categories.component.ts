import { Component, OnDestroy, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { UntilDestroy, untilDestroyed } from '@ngneat/until-destroy';
import { DateRangePickerBuilderService, Store } from '@gauzy/ui-core/core';
import { combineLatest, firstValueFrom } from 'rxjs';
import { debounceTime, tap } from 'rxjs/operators';

/**
 * App categories — which applications counted as productive, neutral or
 * unproductive, and for how long.
 *
 * Separate from the Productivity page on purpose. That page answers "how much of
 * the day was productive" and is shown to the employee themselves; this one
 * exposes the *classification* behind that number — the list of applications and
 * the verdict attached to each. That is management information: it is the rule
 * being applied to someone, not a fact about their day, and it is the thing a
 * manager needs when a figure is questioned.
 *
 * Restricted to ADMIN / SUPER_ADMIN / MANAGER by the route guard in
 * my-work.module.ts, using the same ORG_EMPLOYEES_VIEW permission that already
 * gates the Apps & URLs and App usage tabs. Which employees a manager may open
 * is enforced server-side and is a separate question from this one.
 *
 * The categories themselves are per DEPARTMENT, not global: the same application
 * can be someone's job and someone else's distraction, so a browser is
 * productive for support and neutral for accounts. The mapping lives in the
 * tracker settings, keyed by the employee's department.
 */
interface CategoryRow {
	title: string;
	onScreenSeconds: number;
}

interface CategoryGroup {
	name: 'Productive' | 'Neutral' | 'Unproductive';
	cssClass: string;
	rows: CategoryRow[];
	totalSeconds: number;
}

@UntilDestroy({ checkProperties: true })
@Component({
	selector: 'ga-app-categories',
	templateUrl: './app-categories.component.html',
	styleUrls: ['./app-categories.component.scss'],
	standalone: false
})
export class AppCategoriesComponent implements OnInit, OnDestroy {
	public groups: CategoryGroup[] = [];
	public loading = true;
	public error = '';
	public date = '';
	public employeeId = '';
	public departmentSet = true;
	/** app name (lowercased) -> "Productive" | "Neutral" | "Unproductive" */
	private categories: Record<string, string> = {};

	constructor(
		private readonly http: HttpClient,
		private readonly store: Store,
		private readonly dateRangePickerBuilderService: DateRangePickerBuilderService
	) {}

	/**
	 * Driven by the dashboard's own header selectors, like every other tab here.
	 * A second employee dropdown inside the page can disagree with the header
	 * one, which produces an empty report that reads as a fault rather than a
	 * mismatch.
	 */
	ngOnInit(): void {
		combineLatest([this.store.selectedEmployee$, this.dateRangePickerBuilderService.selectedDateRange$])
			.pipe(
				debounceTime(300),
				tap(([employee, range]) => {
					const user: any = this.store.user;
					this.employeeId = employee?.id || user?.employeeId || user?.employee?.id || '';
					const start = range?.startDate ? new Date(range.startDate) : new Date();
					this.date = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(
						start.getDate()
					).padStart(2, '0')}`;
					this.load();
				}),
				untilDestroyed(this)
			)
			.subscribe();
	}

	ngOnDestroy(): void {}

	public async load(): Promise<void> {
		this.loading = true;
		this.error = '';
		this.groups = [];
		try {
			const res: any = await firstValueFrom(
				this.http.get(
					`/api/employee-settings?where[employeeId]=${this.employeeId}` +
						`&where[tenantId]=${this.store.user?.tenantId}` +
						`&where[organizationId]=${this.store.selectedOrganization?.id}`
				)
			);
			const items = Array.isArray(res) ? res : res?.items || [];
			const data = items[items.length - 1]?.data || {};
			const dept = data.department_id;
			// No department means no mapping, which is not the same as "everything
			// is neutral" — say so rather than presenting an all-neutral list as a
			// finding.
			this.departmentSet = !!dept;
			this.categories = (dept && data.app_categories?.[dept]) || {};

			const usage = data.usage;
			const apps = usage?.date === this.date ? usage.apps || {} : {};

			const buckets: Record<string, CategoryRow[]> = { Productive: [], Neutral: [], Unproductive: [] };
			for (const [title, v] of Object.entries(apps) as [string, any][]) {
				// On-screen seconds only. Running time would list every headless
				// service as "neutral for 8 hours", which says nothing about how
				// anybody spent their day — see the App usage tab for why the two
				// measurements must not share a column.
				const onScreenSeconds = Number(v?.s || 0);
				if (onScreenSeconds <= 0) continue;
				const cat = this.categorise(title);
				(buckets[cat] || buckets['Neutral']).push({ title, onScreenSeconds });
			}

			this.groups = (['Productive', 'Neutral', 'Unproductive'] as const).map((name) => {
				const rows = (buckets[name] || []).sort((a, b) => b.onScreenSeconds - a.onScreenSeconds);
				return {
					name,
					cssClass: name.toLowerCase(),
					rows,
					totalSeconds: rows.reduce((s, r) => s + r.onScreenSeconds, 0)
				};
			});
		} catch (e: any) {
			this.error = e?.message || 'Could not load app categories.';
		} finally {
			this.loading = false;
		}
	}

	/**
	 * Longest-substring match, matching the Productivity page exactly.
	 *
	 * The mapping holds fragments rather than exact process names, so "chrome"
	 * can classify "Google Chrome" and a tab title alike. Longest wins, so a
	 * specific rule ("youtube") beats a general one ("chrome") regardless of the
	 * order keys happen to be stored in. Anything unmatched is Neutral: an
	 * unclassified application is not evidence of anything.
	 */
	public categorise(title: string): string {
		const name = (title || '').toLowerCase();
		if (!name) return 'Neutral';
		if (this.categories[name]) return this.categories[name];
		let best = '';
		for (const key of Object.keys(this.categories)) {
			if (key && name.includes(key) && key.length > best.length) best = key;
		}
		return best ? this.categories[best] : 'Neutral';
	}

	/** Share of the day's on-screen time across all three categories. */
	public sharePct(seconds: number): number {
		const total = this.groups.reduce((s, g) => s + g.totalSeconds, 0);
		return total ? (seconds / total) * 100 : 0;
	}

	public get hasAnything(): boolean {
		return this.groups.some((g) => g.rows.length > 0);
	}

	/** "2h 14m", or "18m" under the hour. Seconds are noise at this scale. */
	public fmt(seconds: number): string {
		const s = Math.max(0, Math.round(seconds));
		const h = Math.floor(s / 3600);
		const m = Math.round((s % 3600) / 60);
		return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`;
	}
}
