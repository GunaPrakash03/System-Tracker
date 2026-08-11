import { Component, OnDestroy, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { UntilDestroy, untilDestroyed } from '@ngneat/until-destroy';
import { DateRangePickerBuilderService, Store } from '@gauzy/ui-core/core';
import { combineLatest, firstValueFrom } from 'rxjs';
import { debounceTime, tap } from 'rxjs/operators';

/**
 * App usage — running time versus on-screen time.
 *
 * Exists because Gauzy's own Apps tab answers a different question than it
 * appears to. The tracker records every RUNNING process, headless services
 * included, and each one is posted with the full slot duration. So `containerd`,
 * `postgres` and `node` all accumulate exactly as much duration as the browser
 * somebody actually used, and the percentage on that tab — an app's share of the
 * summed durations — collapses towards 1/(number of apps) for everything. With
 * 21 apps running, every app reads about 4.8% no matter how the day was spent.
 *
 * That is not a defect in the capture. Recording background processes is the
 * reason this tracker exists; neither ActivityShow nor Gauzy's own agent sees
 * them. But "was running" and "was being used" are different measurements and
 * should not share a column.
 *
 * This tab separates them. Running time comes from the activity duration;
 * on-screen time comes from `foregroundSeconds`, sampled while the window held
 * focus. Only one window has focus at a time, so on-screen seconds are
 * non-overlapping — which is what makes them comparable between apps and safe
 * to express as a share of the day.
 */
interface AppRow {
	title: string;
	runningSeconds: number;
	onScreenSeconds: number;
}

@UntilDestroy({ checkProperties: true })
@Component({
	selector: 'ga-app-usage',
	templateUrl: './app-usage.component.html',
	styleUrls: ['./app-usage.component.scss'],
	standalone: false
})
export class AppUsageComponent implements OnInit, OnDestroy {
	public rows: AppRow[] = [];
	public backgroundRows: AppRow[] = [];
	public loading = true;
	public error = '';
	public date = '';
	public employeeId = '';
	/** Collapse the never-on-screen services into one line by default. */
	public showBackground = false;

	constructor(
		private readonly http: HttpClient,
		private readonly store: Store,
		private readonly dateRangePickerBuilderService: DateRangePickerBuilderService
	) {}

	/**
	 * Driven by the dashboard's OWN header selectors.
	 *
	 * A second employee dropdown inside the page did not merely duplicate the
	 * header one — the two could disagree, and did: the header said one employee
	 * while the page queried another, producing an empty report that looked like
	 * a fault rather than a mismatch.
	 */
	ngOnInit(): void {
		combineLatest([this.store.selectedEmployee$, this.dateRangePickerBuilderService.selectedDateRange$])
			.pipe(
				// Both selectors settle independently on load; without this the
				// page fires a request per emission, the first with a stale value.
				debounceTime(300),
				tap(([employee, range]) => {
					this.employeeId = employee?.id || this.store.user?.employeeId || '';
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
		this.rows = [];
		this.backgroundRows = [];
		try {
			// Read the tracker's own published daily summary, NOT the activity
			// list. Gauzy's activity endpoint is hard-capped at 30 rows in its
			// controller and strips any limit you pass, so a day of per-app
			// activity cannot be read through it — it returns 30 rows out of
			// several thousand and reports minutes where there were hours. The
			// aggregating /activity/daily endpoint is complete but drops
			// metaData, where foreground seconds live. So the tracker publishes
			// the totals it already has into the employee's own record.
			const res: any = await firstValueFrom(
				this.http.get(
					`/api/employee-settings?where[employeeId]=${this.employeeId}` +
						`&where[tenantId]=${this.store.user?.tenantId}` +
						`&where[organizationId]=${this.store.selectedOrganization?.id}`
				)
			);
			const items = Array.isArray(res) ? res : res?.items || [];
			// One settings row per employee; the tracker publishes its daily
			// summary under `usage` on that same row.
			const usage = items[items.length - 1]?.data?.usage;
			const apps = usage?.date === this.date ? usage.apps || {} : {};
			const all: AppRow[] = Object.entries(apps).map(([title, v]: [string, any]) => ({
				title,
				runningSeconds: Number(v?.r || 0),
				onScreenSeconds: Number(v?.s || 0)
			}));
			this.rows = all.filter((r) => r.onScreenSeconds > 0).sort((a, b) => b.onScreenSeconds - a.onScreenSeconds);
			this.backgroundRows = all
				.filter((r) => r.onScreenSeconds === 0)
				.sort((a, b) => b.runningSeconds - a.runningSeconds);
			if (!all.length) {
				// Name the date: an empty report beside a header date the user did
				// not choose reads as a fault rather than a wrong-day selection.
				this.error =
					`No usage recorded for this employee on ${this.date}. Totals are published by the ` +
					'tracker itself, so a machine not running it that day has none. Check the date in the header.';
			}
		} catch (e: any) {
			this.error = `Could not load usage (HTTP ${e?.status || '?'}).`;
		} finally {
			this.loading = false;
		}
	}

	/** "3h 30m" / "57m" / "0" — compact, and never a bare number of seconds. */
	public fmt(secs: number): string {
		if (!secs) return '0';
		const h = Math.floor(secs / 3600);
		const m = Math.round((secs % 3600) / 60);
		if (h && m) return `${h}h ${m}m`;
		if (h) return `${h}h`;
		return `${m}m`;
	}

	public get backgroundNames(): string {
		const names = this.backgroundRows.map((r) => r.title);
		return names.length > 4 ? `${names.slice(0, 4).join(', ')}, +${names.length - 4} more` : names.join(', ');
	}

	public get backgroundRunning(): number {
		return this.backgroundRows.reduce((t, r) => Math.max(t, r.runningSeconds), 0);
	}

	public get totalOnScreen(): number {
		return this.rows.reduce((t, r) => t + r.onScreenSeconds, 0);
	}

	public sharePct(row: AppRow): number {
		const total = this.totalOnScreen;
		return total ? (row.onScreenSeconds / total) * 100 : 0;
	}
}
