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
 * Rows are one per WINDOW TITLE per category — the tab, not the browser. A row
 * reading "chrome, 3 windows" hides the one thing this page exists to show, so
 * each page keeps its own line and the owning application follows it as a
 * footnote. A browser therefore appears under every category it earned time in,
 * because its individual tabs land in different ones.
 *
 * Categories are per DEPARTMENT: the same application can be one team's job and
 * another's distraction.
 */
interface CategoryRow {
	/** The window or tab title — what the person was actually looking at. */
	title: string;
	/** The application that showed it, e.g. "chrome". Empty when the two are the same. */
	app: string;
	seconds: number;
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
			// and keep the title as the row.
			const acc: Record<string, number> = {};
			for (const hb of Object.values(hours) as any[]) {
				// Days recorded before the tracker published `focus` fall back to
				// that hour's per-process apps: coarse, but honest.
				const classifiable = Object.keys(hb?.focus || {}).length ? hb.focus : hb?.apps || {};
				for (const [title, secs] of Object.entries(classifiable) as [string, any][]) {
					const n = Number(secs || 0);
					if (n <= 0) continue;
					const category = this.classify(title, processNames, browser) || 'Unclassified';
					const app = this.owningApp(title, processNames, browser);
					// One row per TITLE, not per application: "chrome — 3 windows"
					// hides the very thing the page is for. The owning app is kept
					// alongside so a tab is still attributable to its browser.
					// NUL separates the parts because neither a category nor a title
					// can contain one, unlike a space.
					const key = `${category}\u0000${title}\u0000${app === title ? '' : app}`;
					acc[key] = (acc[key] || 0) + n;
				}
			}

			const names = ['Productive', 'Neutral', 'Unproductive', 'Unclassified'] as const;
			this.groups = names.map((name) => {
				const rows: CategoryRow[] = Object.entries(acc)
					.filter(([k]) => k.startsWith(`${name}\u0000`))
					.map(([k, seconds]) => {
						const [, title, app] = k.split('\u0000');
						return { title, app, seconds };
					})
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
	/**
	 * The bucket a stored category counts towards. "Chrome Neutral" is Neutral;
	 * the prefix scopes where the rule applies, not what it counts as.
	 */
	private bucketOf(value: string): string {
		return (value || '').replace(/^Chrome /, '') || 'Neutral';
	}

	public classify(title: string, processNames?: Set<string>, browser?: string): string | null {
		const name = (title || '').toLowerCase();
		if (!name) return null;
		// A "Chrome …" category is scoped to browser tabs, so it must not classify
		// a desktop process of the same name — `spotify → Chrome Unproductive`
		// marks Spotify in a tab and leaves the Spotify application alone.
		const isTab = !processNames?.has(name);
		const applies = (value: string) => isTab || !value.startsWith('Chrome ');
		if (this.categories[name] && applies(this.categories[name])) {
			return this.bucketOf(this.categories[name]);
		}
		let best = '';
		for (const key of Object.keys(this.categories)) {
			if (!key || !applies(this.categories[key])) continue;
			if (name.includes(key) && key.length > best.length) best = key;
		}
		if (best) return this.bucketOf(this.categories[best]);

		// Unmatched BROWSER TABS inherit the browser's own category, matching the
		// Productivity page. The mapping is written against process names, but a
		// browser's time arrives keyed by tab title and a title rarely contains
		// the word "chrome" — so "chrome: Productive" would otherwise classify
		// nothing it was meant to. Name the exceptions; the rest take the
		// browser's category.
		if (browser && !processNames?.has(name)) {
			const browserCategory = this.categories[browser.toLowerCase()];
			if (browserCategory) return this.bucketOf(browserCategory);
		}
		// A genuinely unknown application — not a browser tab — stays
		// unclassified, so gaps in the mapping remain visible.
		return null;
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
