import { Component, OnDestroy, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { UntilDestroy, untilDestroyed } from '@ngneat/until-destroy';
import { DateRangePickerBuilderService, Store } from '@gauzy/ui-core/core';
import { RolesEnum } from '@gauzy/contracts';
import { combineLatest, firstValueFrom } from 'rxjs';
import { debounceTime, tap } from 'rxjs/operators';

/**
 * Hourly productivity — a stacked bar per hour of the day.
 *
 * Its own page in the sidebar rather than a tab under Settings, because it is a
 * report an admin reads regularly, not a setting they change occasionally.
 *
 * Two sources, because neither alone can answer the question:
 *
 *   time slots -> `duration` and `overall` per bucket. The ONLY honest source of
 *                 idle time: `overall` is the seconds actually active, so idle is
 *                 the remainder.
 *   activities -> per-app `metaData.foregroundSeconds`, which splits the active
 *                 time by productivity category.
 *
 * An activity's own `duration` is NOT a usable weight: the tracker posts every
 * running process with the full slot duration, so on a machine running twenty
 * processes they sum to twenty times the wall clock. Foreground seconds are
 * non-overlapping — only one window holds focus — which is what makes a
 * percentage meaningful.
 */
interface HourBar {
	hour: number;
	label: string;
	productive: number;
	neutral: number;
	unproductive: number;
	idle: number;
	/** Minutes of the hour with no tracking at all — logged out, or machine off. */
	untracked: number;
	trackedMinutes: number;
}

/**
 * One block of the day timeline: what was happening, and when.
 *
 * `x` and `w` are percentages of the drawn span, so the strip scales with the
 * container and needs no viewBox arithmetic.
 */
interface Block {
	x: number;
	w: number;
	kind: 'productive' | 'neutral' | 'unproductive' | 'idle';
	label: string;
}

/** An hour tick on the timeline's x axis. */
interface Tick {
	x: number;
	label: string;
}

/**
 * The day as one set of figures.
 *
 * Seconds, not averaged percentages. Averaging the per-hour percentages — which
 * is what this page used to show as "day average" — weights a two-minute hour
 * the same as a full one, so a single early check of email could outweigh a
 * whole afternoon. Summing the seconds and dividing once is the honest form.
 */
interface DaySummary {
	productive: number;
	neutral: number;
	unproductive: number;
	idle: number;
	/** Seconds inside the working span with no tracking at all. */
	unmonitored: number;
	/** Seconds actually tracked. The denominator for the four shares above. */
	tracked: number;
	/** First tracked hour to last, inclusive — the span the day covers. */
	span: number;
	startedAt: string | null;
	lastIdleStartedAt: string | null;
	lastActiveResumedAt: string | null;
}

@UntilDestroy({ checkProperties: true })
@Component({
	selector: 'ga-productivity',
	templateUrl: './productivity.component.html',
	styleUrls: ['./productivity.component.scss'],
	standalone: false
})
export class ProductivityComponent implements OnInit, OnDestroy {
	public loading = false;
	public note = '';
	/**
	 * Today in LOCAL time. `toISOString()` is UTC, so before 05:30 IST it names
	 * yesterday and the page opens on an empty day.
	 */
	public date = (() => {
		const d = new Date();
		return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
	})();
	public employeeId = '';
	public bars: HourBar[] = [];
	public summary: DaySummary | null = null;
	public blocks: Block[] = [];
	/**
	 * Whether to draw the app categorisation and the unmonitored figure.
	 *
	 * False for an EMPLOYEE looking at their own day: they see how long they
	 * worked, not this deployment's verdict on which of their applications was
	 * productive. Defaults to false so a role that fails to resolve shows less
	 * rather than more.
	 *
	 * This is presentation, NOT access control — /api/employee-settings still
	 * serves the same payload to the same token. Restricting the data itself
	 * needs a server-side filter; see docs/manager-role-and-visibility.md.
	 */
	public canSeeCategories = false;
	public ticks: Tick[] = [];
	/** Explains the ribbon's resolution, or why it is empty. */
	public timelineNote = '';

	private categories: Record<string, string> = {};
	/**
	 * Dominant category per hour, from the tracker's per-hour app mix.
	 *
	 * Time slots carry how long was active but not which app, so the ribbon takes
	 * the colour of an active block from the hour it falls in.
	 */
	private hourKind: Record<number, 'productive' | 'neutral' | 'unproductive'> = {};

	constructor(
		private readonly http: HttpClient,
		private readonly store: Store,
		private readonly dateRangePickerBuilderService: DateRangePickerBuilderService
	) {}

	/**
	 * Driven by Gauzy's OWN header selectors, not by pickers of its own.
	 *
	 * The page previously carried a second employee dropdown and date field,
	 * which meant choosing the employee twice — once in the header, once in the
	 * page — and the two could disagree. Reading the shared selectors means this
	 * page behaves like every other report in the dashboard, and the header's
	 * date picker is configured to single-day mode for this route.
	 */
	ngOnInit(): void {
		combineLatest([this.store.selectedEmployee$, this.dateRangePickerBuilderService.selectedDateRange$])
			.pipe(
				// The two selectors settle independently on load; without this the
				// page would fire a request for each, the first with a stale value.
				debounceTime(300),
				tap(([employee, range]) => {
					// "All employees" clears the selection — fall back to the
					// signed-in user rather than showing nothing.
					//
					// Both shapes are checked: `user.employeeId` is only populated
					// when /user/me was asked for it, and on a fresh session it is
					// frequently null while `user.employee.id` is present. Relying on
					// the first alone left the page blank and silent for anyone who
					// had not touched the header selector.
					const user: any = this.store.user;
					// Who may see the app categorisation and the unmonitored figure.
					// An employee sees how long they worked; they do not see this
					// deployment's judgement of which of their applications counted
					// as productive, nor how much of their day went unobserved.
					// That is management information and it reads very differently
					// to the person being measured.
					//
					// A manager's *scope* — which employees they may look at — is
					// enforced server-side; this only decides whether the breakdown
					// is drawn at all for whoever is looking.
					this.canSeeCategories = [
						RolesEnum.SUPER_ADMIN,
						RolesEnum.ADMIN,
						RolesEnum.MANAGER
					].includes(user?.role?.name);
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
		// Never fail silently. Returning without a word here rendered an empty
		// card that looked identical to a broken page — which is exactly how it
		// was reported. If there is no employee to report on, say so.
		if (!this.employeeId) {
			this.summary = null;
			this.blocks = [];
			this.ticks = [];
			this.bars = [];
			this.note =
				'No employee selected. Choose one from the employee selector in the header to see their ' +
				'productivity for the day.';
			return;
		}
		if (!this.date) return;
		this.loading = true;
		this.note = '';
		this.bars = [];
		try {
			// Everything comes from the tracker's own published summary.
			//
			// The obvious sources cannot serve this. Gauzy's activity endpoint is
			// hard-capped at 30 rows in its controller and strips any limit you
			// pass; of the 30 it returns, almost none carry foreground seconds,
			// so every hour collapsed to Neutral and the whole chart rendered
			// blue. The time-slot endpoint is capped the same way — 33 of 303
			// slots — so even idle was computed from a tenth of the day. The
			// tracker has both numbers already and publishes them per hour.
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
			this.categories = (dept && data.app_categories?.[dept]) || {};

			const usage = data.usage;
			const hours = usage?.date === this.date ? usage.hours || {} : {};
			const marks = (usage?.date === this.date ? usage.marks : null) || {};
			const segments = (usage?.date === this.date ? usage.segments : null) || [];

			// Day totals in seconds, accumulated alongside the hour buckets.
			const day = { productive: 0, neutral: 0, unproductive: 0, idle: 0, tracked: 0 };
			let firstHour = -1;
			let lastHour = -1;

			const bars: HourBar[] = [];
			for (let h = 0; h < 24; h++) {
				const key = String(h).padStart(2, '0');
				const hb = hours[key];
				if (!hb || !hb.wall) continue;
				// An hour cannot hold more than 3600 seconds. Gauzy stores both
				// per-post time slots AND aggregated 10-minute buckets, so summing
				// slot durations double-counts — a backfilled hour could read 112
				// tracked minutes. The tracker's own accounting is correct; this
				// cap keeps historical or externally-written data honest too.
				const wall = Math.min(hb.wall, 3600);
				const active = Math.min(hb.active || 0, wall);
				// Every segment is a share of the WHOLE hour, not of the tracked
				// part. Otherwise an hour with four minutes of work reads exactly
				// like a full one, and logging out looks identical to being busy.
				const coverage = wall / 3600;
				const untrackedPct = Math.max(0, 100 - coverage * 100);
				const idle = Math.max(0, ((wall - active) / 3600) * 100);
				const activePct = Math.max(0, coverage * 100 - idle);
				const fg: Record<string, number> = { Productive: 0, Neutral: 0, Unproductive: 0 };
				// `focus` keys browser time by TAB TITLE rather than by process, so
				// "youtube" can be classified apart from the dashboard even though
				// both are chrome. Days recorded before the tracker published it
				// fall back to `apps`, where every tab is simply "chrome".
				const classifiable = Object.keys(hb.focus || {}).length ? hb.focus : hb.apps || {};
				for (const [app, secs] of Object.entries(classifiable)) {
					const cat = this.categorise(app);
					if (fg[cat] !== undefined) fg[cat] += Number(secs || 0);
				}
				const total = fg.Productive + fg.Neutral + fg.Unproductive;
				// No focused window all hour — a headless build, or a locked screen
				// still registering input — leaves nothing to split the active time
				// by, so it falls to Neutral rather than inflating Productive.
				const share = (c: string) =>
					total ? (fg[c] / total) * activePct : c === 'Neutral' ? activePct : 0;
				bars.push({
					hour: h,
					label: `${key}:00`,
					productive: share('Productive'),
					neutral: share('Neutral'),
					unproductive: share('Unproductive'),
					idle,
					untracked: untrackedPct,
					trackedMinutes: Math.round(wall / 60)
				});

				// Day totals, in seconds. The active seconds are split by the same
				// foreground ratio used for the hour, so the two views agree.
				const activeSecs = Math.max(0, active);
				day.idle += Math.max(0, wall - active);
				day.tracked += wall;
				if (total) {
					day.productive += (fg.Productive / total) * activeSecs;
					day.neutral += (fg.Neutral / total) * activeSecs;
					day.unproductive += (fg.Unproductive / total) * activeSecs;
				} else {
					day.neutral += activeSecs;
				}
				// Which category dominated this hour, for colouring the ribbon.
				const winner = (['Productive', 'Unproductive', 'Neutral'] as const).reduce((a, b) =>
					fg[a] >= fg[b] ? a : b
				);
				this.hourKind[h] = (total ? winner.toLowerCase() : 'neutral') as
					| 'productive'
					| 'neutral'
					| 'unproductive';

				if (firstHour < 0) firstHour = h;
				lastHour = h;
			}
			this.bars = bars;

			// Unmonitored is measured across the working span — not across 24
			// hours. A whole day would put 15 hours of "unmonitored" against a
			// normal shift and drown every other figure; the useful number is the
			// gaps *within* the day someone worked.
			//
			// The span has to be the REAL one. Hour buckets round it up at both
			// ends, and inside a single hour that is ruinous: a morning that
			// started at 10:22 and is 25 minutes old sits entirely in hour 10, so
			// the span came out as a full 3600s and the page reported 40 minutes
			// unmonitored — 20 of them before tracking began and 12 that had not
			// happened yet. It was counting the future.
			//
			// So use the minute-accurate wall clock the tracker already publishes:
			// start at the reconciled start mark, end at the last segment's end,
			// and never run past now on the day in progress.
			const startedAtMark = this.reconcileStart(marks.started_at, firstHour);
			const startSecs = this.hhmmToSeconds(startedAtMark);
			const lastSegmentEnd = segments.reduce((latest: number | null, seg: any) => {
				const e = this.hhmmToSeconds(seg?.e);
				return e === null || (latest !== null && e < latest) ? latest : e;
			}, null as number | null);
			// Buckets remain the fallback for days recorded before segments
			// shipped. They are only hour-accurate, which is why they are second
			// choice rather than first.
			const bucketEnd = lastHour >= 0 ? (lastHour + 1) * 3600 : 0;
			let endSecs = lastSegmentEnd ?? bucketEnd;
			if (this.date === this.todayKey()) {
				const now = new Date();
				endSecs = Math.min(endSecs, now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds());
			}
			const span = firstHour < 0 || startSecs === null ? 0 : Math.max(0, endSecs - startSecs);
			this.summary = bars.length
				? {
						productive: day.productive,
						neutral: day.neutral,
						unproductive: day.unproductive,
						idle: day.idle,
						unmonitored: Math.max(0, span - day.tracked),
						tracked: day.tracked,
						span,
						// The mark is minute-accurate and preferred — but only when it
						// is consistent with the buckets. A tracker deployed or first
						// started mid-day marks its own start time while earlier hours
						// already hold tracked time, which would report someone who
						// began at 09:00 as arriving at 14:34. When the buckets show
						// tracking before the mark, the first tracked hour is the
						// truthful answer even though it is only hour-accurate.
						startedAt: startedAtMark,
						lastIdleStartedAt: marks.last_idle_started_at || null,
						lastActiveResumedAt: marks.last_active_resumed_at || null
				  }
				: null;

			// The ribbon is built from time slots, not from the tracker's segment
			// list. Slots have covered every tracked day since the beginning, and
			// they are what the screenshots hang off — so a morning visible in the
			// screenshots is visible here too. Segments only exist from the day
			// that feature shipped, which left the morning of an otherwise normal
			// day looking untracked.
			//
			// The cost is resolution: slots are ten-minute buckets, so the ribbon
			// is accurate to ten minutes rather than to the minute. The wall-clock
			// marks above are minute-accurate and come from the tracker directly.
			let slots: any[] = [];
			try {
				const sres: any = await firstValueFrom(
					this.http.get(
						`/api/timesheet/time-slot?organizationId=${this.store.selectedOrganization?.id}` +
							`&startDate=${this.date} 00:00:00&endDate=${this.date} 23:59:59` +
							`&employeeIds[]=${this.employeeId}`
					)
				);
				slots = Array.isArray(sres) ? sres : sres?.items || [];
			} catch {
				// A failed slot fetch costs the ribbon, not the page: the summary
				// above comes from a different source and is still valid.
				slots = [];
			}
			this.buildTimeline(slots, segments, this.summary?.startedAt || null);
			if (!bars.length) {
				// Name the date. "No tracked time on this date" beside a header
				// showing a date the user did not choose reads as a fault; naming
				// it makes the actual cause — wrong day selected — obvious.
				this.note =
					`No tracked time for this employee on ${this.date}. Hourly totals are published by ` +
					'the tracker, so a machine not running it that day has none. Check the date in the header.';
			} else if (!Object.keys(this.categories).length) {
				this.note =
					'No apps classified for this employee\u2019s department, so active time shows as Neutral. ' +
					'Classify apps under Settings \u2192 Tracker Settings \u2192 App productivity.';
			}
		} catch (e: any) {
			this.note = `Could not load usage (HTTP ${e?.status || '?'}).`;
		} finally {
			this.loading = false;
		}
	}

	/**
	 * Category for a process name.
	 *
	 * Exact match first, then the LONGEST classified name contained in the
	 * process name. Exact-only matching looked correct and quietly failed in
	 * practice: an admin classifies "terminal", the tracker reports
	 * "gnome-terminal-server", nothing matches and the time silently lands in
	 * Neutral — indistinguishable from not having classified it at all.
	 *
	 * Longest-wins matters because short names are substrings of unrelated ones:
	 * "code" appears inside "codex". Preferring the longest match, and letting an
	 * exact entry beat any partial, means classifying "codex" explicitly always
	 * overrides the accidental "code" hit.
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

	/**
	 * Turns the day's time slots into a positioned timeline.
	 *
	 * Position carries the meaning here, not proportion: a block sits where it
	 * happened and is as wide as it lasted. Gaps between blocks are left empty —
	 * that is the tracker not running, and the strip background shows through as
	 * unmonitored.
	 *
	 * Each slot is a ten-minute bucket holding `duration` seconds tracked and
	 * `overall` seconds active. It becomes up to two blocks: the active part,
	 * coloured by the category that dominated that hour, then the idle remainder.
	 * Their order inside the bucket is not recorded, so active is drawn first —
	 * which is why the ribbon is described as ten-minute resolution rather than
	 * being presented as an exact account of the minute.
	 *
	 * The axis runs from the hour the day started — login, in practice — through
	 * to midnight, NOT merely across the blocks that exist. Fitting the axis to
	 * the blocks makes an hour of tracking fill the width and read like a full
	 * day; anchoring it to the working day shows the empty stretch for what it is.
	 *
	 * @param slots - time slots for the day, as returned by the API
	 * @param startedAt - "HH:MM" the day's tracking began, if known
	 */
	private buildTimeline(slots: any[], segments: any[], startedAt: string | null): void {
		this.blocks = [];
		this.ticks = [];
		// Cleared first: switching to a day that has data must not leave the
		// previous day's "nothing to draw" message on screen.
		//
		// Silent when the ribbon is fine. The resolution caveat used to be stated
		// on every render, which is noise on a page read daily — it only earns
		// space when there is nothing to draw.
		this.timelineNote = '';
		if (!slots.length) {
			this.timelineNote = 'No tracked slots for this day, so there is nothing to place on a timeline.';
			return;
		}

		// Slot times arrive as UTC; the ribbon is a wall-clock view, so they are
		// read in the browser's local zone — the same zone the hour buckets and the
		// tracker's marks are already keyed to.
		const localMins = (iso: string) => {
			const d = new Date(iso);
			return d.getHours() * 60 + d.getMinutes();
		};

		const ordered = [...slots].sort((a, b) => String(a.startedAt).localeCompare(String(b.startedAt)));
		const from = Math.floor(
			(startedAt
				? Number(startedAt.slice(0, 2)) * 60 + Number(startedAt.slice(3, 5))
				: localMins(ordered[0].startedAt)) / 60
		) * 60;
		const to = 24 * 60; // midnight closes the day
		const span = Math.max(1, to - from);
		const pct = (m: number) => ((m - from) / span) * 100;
		const hhmm = (m: number) =>
			`${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(Math.round(m % 60)).padStart(2, '0')}`;
		// Sub-minute spells are real; rounding them to "0m" reads as a fault, so
		// anything under a minute is named in seconds.
		const spell = (m: number) => (m < 1 ? `${Math.round(m * 60)}s` : `${Math.round(m)}m`);

		// Segments first: they name the app, so a two-minute spell of something
		// classified differently from the rest of the hour keeps its own colour.
		// Slots cannot do this — they record how long was active, never in what —
		// so a short unproductive burst inside a productive hour disappears.
		const segMins = (hm: string) => Number(hm.slice(0, 2)) * 60 + Number(hm.slice(3, 5));
		let segFrom = Infinity;
		for (const sg of segments) {
			const a = segMins(sg.s);
			const b = Math.max(a, segMins(sg.e));
			segFrom = Math.min(segFrom, a);
			const len = Math.max(b - a, 0);
			if (!len) continue;
			const kind =
				sg.k === 'idle'
					? 'idle'
					: (this.categorise(sg.a || '').toLowerCase() as 'productive' | 'neutral' | 'unproductive');
			this.blocks.push({
				x: pct(a),
				w: (Math.max(1, len) / span) * 100,
				kind,
				label: `${sg.s}–${sg.e} · ${sg.k === 'idle' ? 'idle' : sg.a || 'no window'} ${spell(len)}`
			});
		}

		for (const slot of ordered) {
			const begin = localMins(slot.startedAt);
			const tracked = Math.max(0, Number(slot.duration || 0)) / 60;
			if (!tracked) continue;
			// Where segments exist they are strictly better; drawing both would
			// stack a coarse block over a fine one and hide it.
			if (begin + tracked > segFrom) continue;
			const active = Math.min(tracked, Math.max(0, Number(slot.overall || 0)) / 60);
			const idle = Math.max(0, tracked - active);
			const kind = this.hourKind[Math.floor(begin / 60)] || 'neutral';

			if (active > 0) {
				this.blocks.push({
					x: pct(begin),
					// A floor of one minute keeps a brief burst visible on a 15-hour axis.
					w: (Math.max(1, active) / span) * 100,
					kind,
					label: `${hhmm(begin)}–${hhmm(begin + active)} · active ${spell(active)}`
				});
			}
			if (idle > 0) {
				this.blocks.push({
					x: pct(begin + active),
					w: (Math.max(1, idle) / span) * 100,
					kind: 'idle',
					label: `${hhmm(begin + active)}–${hhmm(begin + tracked)} · idle ${spell(idle)}`
				});
			}
		}

		// Hourly while that stays readable; every second hour once the day is long
		// enough that the labels would collide.
		const step = span > 8 * 60 ? 120 : 60;
		for (let m = from; m <= to; m += step) {
			const hour = Math.floor(m / 60);
			this.ticks.push({
				x: pct(m),
				// 24:00 rather than 00:00 at the right edge: this is the end of the
				// day being shown, not the start of the next one.
				label: hour === 24 ? '24:00' : `${String(hour).padStart(2, '0')}:00`
			});
		}
		if (this.ticks[this.ticks.length - 1]?.x !== 100) {
			this.ticks.push({ x: 100, label: '24:00' });
		}
	}

	/**
	 * Reconciles the tracker's start mark against the hour buckets.
	 *
	 * @param mark - "HH:MM" published by the tracker, if any
	 * @param firstHour - first hour of the day holding tracked time, or -1
	 * @returns the time to show, or null when the day has nothing at all
	 */
	/**
	 * "HH:MM" as published by the tracker → seconds since local midnight.
	 * Returns null for an absent or unparseable mark, which callers treat as
	 * "no minute-accurate answer available" rather than as midnight.
	 */
	private hhmmToSeconds(mark: string | null | undefined): number | null {
		if (!mark) return null;
		const [h, m] = String(mark).split(':').map(Number);
		return Number.isFinite(h) && Number.isFinite(m) ? h * 3600 + m * 60 : null;
	}

	/**
	 * Today as "YYYY-MM-DD" in LOCAL time, matching the shape of `this.date`.
	 * Deliberately not toISOString(), which is UTC and would roll the date over
	 * five and a half hours early in IST.
	 */
	private todayKey(): string {
		const d = new Date();
		const p = (n: number) => String(n).padStart(2, '0');
		return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
	}

	private reconcileStart(mark: string | undefined, firstHour: number): string | null {
		const fallback = firstHour >= 0 ? `${String(firstHour).padStart(2, '0')}:00` : null;
		if (!mark) return fallback;
		const markHour = Number(mark.slice(0, 2));
		// Tracked time exists in an hour before the mark: the mark cannot be when
		// the day started, so prefer the buckets.
		return firstHour >= 0 && firstHour < markHour ? fallback : mark;
	}

	/**
	 * Share of TRACKED time, so productive + neutral + unproductive + idle come
	 * to 100%. Unmonitored is deliberately outside that total: it is time nobody
	 * observed, and folding it in would make an early finish look like idling.
	 */
	public pct(seconds: number): number {
		const t = this.summary?.tracked || 0;
		return t ? (seconds / t) * 100 : 0;
	}

	/** "2h 14m", or "18m" under the hour. Seconds are noise at this scale. */
	public duration(seconds: number): string {
		const s = Math.max(0, Math.round(seconds));
		const h = Math.floor(s / 3600);
		const m = Math.round((s % 3600) / 60);
		return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`;
	}

	/**
	 * Width of a bar in the single stacked strip. Uses tracked time as the
	 * denominator to match pct(), so the strip reads as the same number the
	 * figures beside it show.
	 */
	public barWidth(seconds: number): string {
		return `${this.pct(seconds)}%`;
	}
}
