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
 * exposes the *classification* behind that number, which is what a manager needs
 * when a figure is questioned.
 *
 * Restricted to ADMIN / SUPER_ADMIN / MANAGER by the route guard in
 * my-work.module.ts, using the same ORG_EMPLOYEES_VIEW permission that gates the
 * Apps & URLs and App usage tabs.
 *
 * Rows are one per APPLICATION per category, so a browser appears under each
 * category it earned time in — productive for the ticket system, neutral for a
 * video — rather than as one row with a single verdict. Classification is still
 * per window title, because that is the only level at which a browser can be
 * split at all; the titles are then rolled up into the owning application.
 *
 * Categories are per DEPARTMENT: the same application can be one team's job and
 * another's distraction.
 */
interface CategoryRow {
	/** The owning application, e.g. "chrome" — not the window title. */
	app: string;
	seconds: number;
	/** Distinct window titles rolled into this row, for the tooltip. */
	titles: string[];
}

interface CategoryGroup {
	name: 'Productive' | 'Neutral' | 'Unproductive' | 'Unclassified';
	cssClass: string;
	rows: CategoryRow[];
	totalSeconds: number;
}

/**
 * Browsers, for attributing a tab title back to the application that showed it.
 * Mirrors the tracker's own default `browsers` list; a title that is not itself
 * a process name came from one of these.
 */
const BROWSERS = ['chrome', 'chromium', 'firefox', 'edge', 'brave', 'opera', 'safari', 'vivaldi'];

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
			const sameDay = usage?.date === this.date;
			const hours = sameDay ? usage.hours || {} : {};
			const apps = sameDay ? usage.apps || {} : {};

			// Process names, for telling an application apart from a tab title.
			// `usage.apps` is keyed by process; `hours[h].focus` mixes the two —
			// "gnome-terminal-server" is a process, "HR Portal - Young Globes" is a
			// tab inside a browser.
			const processNames = new Set(Object.keys(apps).map((a) => a.toLowerCase()));
			const browser = Object.keys(apps).find((a) => BROWSERS.includes(a.toLowerCase()));

			// Classify per TITLE — the only level at which a browser splits at all —
			// then roll the titles up into the owning application.
			const acc: Record<string, { seconds: number; titles: Set<string> }> = {};
			for (const hb of Object.values(hours) as any[]) {
				// Days recorded before the tracker published `focus` fall back to
				// that hour's per-process apps: coarse, but honest.
				const classifiable = Object.keys(hb?.focus || {}).length ? hb.focus : hb?.apps || {};
				for (const [title, secs] of Object.entries(classifiable) as [string, any][]) {
					const n = Number(secs || 0);
					if (n <= 0) continue;
					const category = this.classify(title) || 'Unclassified';
					const app = this.owningApp(title, processNames, browser);
					const key = `${category} ${app}`;
					const bucket = (acc[key] ||= { seconds: 0, titles: new Set<string>() });
					bucket.seconds += n;
					bucket.titles.add(title);
				}
			}

			const names = ['Productive', 'Neutral', 'Unproductive', 'Unclassified'] as const;
			this.groups = names.map((name) => {
				const rows: CategoryRow[] = Object.entries(acc)
					.filter(([k]) => k.startsWith(`${name} `))
					.map(([k, v]) => ({
						// slice, not split: an app name can contain spaces, which happens
					// when no browser was running and the title is kept as-is.
						app: k.slice(name.length + 1),
						seconds: v.seconds,
						titles: [...v.titles].sort()
					}))
					.sort((a, b) => b.seconds - a.seconds);
				return {
					name,
					cssClass: name.toLowerCase(),
					rows,
					totalSeconds: rows.reduce((s, r) => s + r.seconds, 0)
				};
			});
		} catch (e: any) {
			this.error = e?.message || 'Could not load app categories.';
		} finally {
			this.loading = false;
		}
	}

	/**
	 * Which application showed this window.
	 *
	 * A focus key that is itself a process name IS the application. Anything else
	 * is a tab title, and a tab can only have come from a browser — so it is
	 * attributed to whichever browser was running. With no browser in the day's
	 * process list the title is left as-is rather than invented.
	 */
	private owningApp(title: string, processNames: Set<string>, browser: string | undefined): string {
		if (processNames.has((title || '').toLowerCase())) return title;
		return browser || title;
	}

	/**
	 * Longest-substring match against the department's mapping, matching the
	 * Productivity page's rule so the two pages agree.
	 *
	 * Returns null when nothing matches, rather than defaulting to Neutral. The
	 * default is what made Neutral a dumping ground: genuinely-neutral apps and
	 * never-classified ones summed into one figure, so the mapping's gaps were
	 * invisible. They surface as "Unclassified" instead.
	 */
	public classify(title: string): string | null {
		const name = (title || '').toLowerCase();
		if (!name) return null;
		if (this.categories[name]) return this.categories[name];
		let best = '';
		for (const key of Object.keys(this.categories)) {
			if (key && name.includes(key) && key.length > best.length) best = key;
		}
		return best ? this.categories[best] : null;
	}

	/** Share of the day's on-screen time across every group, Unclassified included. */
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
