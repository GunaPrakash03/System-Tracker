import { Component, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Store } from '@gauzy/ui-core/core';
import { firstValueFrom } from 'rxjs';

/**
 * System-Tracker settings.
 *
 * Everything here is stored in GAUZY ITSELF — in the generic `employee_setting`
 * table, a per-employee row with a jsonb `data` column — and reached through
 * Gauzy's own API with the session the dashboard already holds. There is no
 * separate settings service, no second port and no extra process to keep alive.
 *
 * Gauzy has no field of its own for any of these: `screenshotFrequency` is
 * organisation-wide rather than per employee, there is no notion of media
 * counting as idle, and none of an app being productive within a department.
 * The generic settings row is what lets all three live here without forking
 * Gauzy's backend to add tables.
 */
interface EmployeeRow {
	id: string;
	label: string;
	interval: string;
	mediaIdle: boolean;
	blur: boolean;
	idleAfter: string;
	departmentId: string;
	settingId?: string;
	/** The row's full data object, so a save preserves keys this page does not own. */
	raw?: any;
}

@Component({
	selector: 'ga-tracker-settings',
	templateUrl: './tracker-settings.component.html',
	styleUrls: ['./tracker-settings.component.scss'],
	standalone: false
})
export class TrackerSettingsComponent implements OnInit {
	public tab: 'employees' | 'apps' = 'employees';

	public loading = true;
	public error = '';
	public saved = '';

	public employees: EmployeeRow[] = [];
	public departments: { id: string; name: string }[] = [];

	/**
	 * The first five mirror what Gauzy itself offers, so the two agree. The
	 * longer ones are ours: a shot every few minutes is intrusive for roles that
	 * need only occasional evidence of presence, and the tracker snaps any value
	 * to a whole number of slot intervals, so a longer one costs it nothing.
	 */
	public readonly intervals = [
		{ value: '', label: 'Default' },
		{ value: '60', label: '1 min' },
		{ value: '180', label: '3 min' },
		{ value: '300', label: '5 min' },
		{ value: '600', label: '10 min' },
		{ value: '900', label: '15 min' },
		{ value: '1800', label: '30 min' },
		{ value: '2700', label: '45 min' },
		{ value: '3600', label: '1 hr' }
	];
	/**
	 * The three plain categories apply wherever the name matches — a process, or
	 * a browser tab's title.
	 *
	 * The two "Chrome …" categories apply ONLY when the match is a browser tab.
	 * That is the difference between the Spotify desktop application and Spotify
	 * open in a tab: `spotify → Unproductive` covers both, `spotify → Chrome
	 * Unproductive` covers only the tab and leaves the desktop app to whatever
	 * else classifies it. They count towards Neutral and Unproductive in the
	 * totals; the prefix scopes *where* the rule applies, it is not a fourth and
	 * fifth category.
	 */
	public readonly categories = ['Productive', 'Neutral', 'Unproductive', 'Chrome Neutral', 'Chrome Unproductive'];

	/**
	 * How long without keyboard or mouse before a moment counts as idle. The
	 * employee stays "active" for this long after their last keystroke, so short
	 * pauses for reading or thinking do not register — which is why the default
	 * is generous. Tighten it for roles whose work is continuous input.
	 */
	public readonly idleAfters = [
		{ value: '', label: 'Default (3 min)' },
		{ value: '60', label: '1 min' },
		{ value: '120', label: '2 min' },
		{ value: '180', label: '3 min' },
		{ value: '300', label: '5 min' },
		{ value: '600', label: '10 min' }
	];

	public appDept = '';
	public apps: { name: string; category: string }[] = [];
	public newApp = '';
	public newAppCategory = 'Productive';

	/**
	 * departmentId -> { processName: category }.
	 *
	 * Held on every employee's settings row rather than on the department,
	 * because `organization_department` has no free-text or JSON column and
	 * `tenant_setting` rejects keys other than its own. Writing the same map to
	 * each employee is the price of not forking Gauzy's backend to add a table;
	 * the map is small and this page is its only writer.
	 */
	private appCategories: Record<string, Record<string, string>> = {};

	constructor(private readonly http: HttpClient, private readonly store: Store) {}

	private get scope(): string {
		return `where[tenantId]=${this.store.user?.tenantId}&where[organizationId]=${this.store.selectedOrganization?.id}`;
	}

	async ngOnInit(): Promise<void> {
		await this.load();
	}

	private async load(): Promise<void> {
		this.loading = true;
		this.error = '';
		try {
			const orgId = this.store.selectedOrganization?.id;
			const tenantId = this.store.user?.tenantId;

			const [emps, depts, settings]: any[] = await Promise.all([
				firstValueFrom(
					this.http.get(`/api/employee?${this.scope}&relations[0]=user`)
				),
				firstValueFrom(this.http.get(`/api/organization-department?${this.scope}`)),
				firstValueFrom(this.http.get(`/api/employee-settings?${this.scope}`))
			]);

			this.departments = (depts?.items || depts || []).map((d: any) => ({
				id: d.id,
				name: d.name || '(unnamed)'
			}));

			// Newest row wins: saving writes a fresh row rather than mutating the
			// old one, so an employee accumulates history and only the last entry
			// reflects what the admin currently intends.
			const byEmployee: Record<string, any> = {};
			for (const s of settings?.items || settings || []) {
				if (s?.employeeId) byEmployee[s.employeeId] = s;
			}

			this.employees = (emps?.items || emps || []).map((e: any) => {
				const user = e.user || {};
				const data = byEmployee[e.id]?.data || {};
				if (data.app_categories) this.appCategories = data.app_categories;
				return {
					id: e.id,
					label:
						user.name ||
						[user.firstName, user.lastName].filter(Boolean).join(' ') ||
						user.email ||
						e.id.slice(0, 8),
					interval: data.screenshot_interval_seconds ? String(data.screenshot_interval_seconds) : '',
					mediaIdle: data.count_audio_as_active === false,
					blur: data.blur_screenshots === true,
					idleAfter: data.idle_threshold_seconds ? String(data.idle_threshold_seconds) : '',
					departmentId: data.department_id || '',
					settingId: byEmployee[e.id]?.id,
					raw: data
				};
			});

			if (!this.appDept && this.departments.length) this.appDept = this.departments[0].id;
			this.refreshApps();
			if (!orgId || !tenantId) {
				this.error = 'No organization selected — pick one in the header first.';
			}
		} catch (e: any) {
			this.error = `Could not load settings from Gauzy (HTTP ${e?.status || '?'}).`;
		} finally {
			this.loading = false;
		}
	}

	public refreshApps(): void {
		const map = this.appCategories[this.appDept] || {};
		this.apps = Object.entries(map).map(([name, category]) => ({ name, category }));
	}

	/** Write one employee's settings row. */
	private async persist(row: EmployeeRow): Promise<void> {
		await firstValueFrom(
			this.http.post('/api/employee-settings', {
				employeeId: row.id,
				organizationId: this.store.selectedOrganization?.id,
				tenantId: this.store.user?.tenantId,
				entity: 'Employee',
				entityId: row.id,
				settingType: 'Custom',
				// MERGE, never replace. POST to this endpoint is an upsert keyed on
				// the employee and it overwrites `data` wholesale — there is one row
				// per person, shared with the tracker, which publishes its daily
				// usage summary under `usage`. Writing a bare object here would
				// silently delete that summary, exactly as the tracker writing a
				// bare object used to delete these settings.
				data: {
					...(row.raw || {}),
					screenshot_interval_seconds: row.interval ? Number(row.interval) : null,
					// false means "media is idle for this person"; null means "no
					// opinion", leaving the workstation's own config to decide.
					// Sending true would overrule a machine that deliberately set
					// it false locally.
					count_audio_as_active: row.mediaIdle ? false : null,
					// Unlike media-as-idle, true is meaningful here: blurring is a
					// promise to the employee, so an admin turning it on must
					// override a workstation config that left it off.
					blur_screenshots: row.blur ? true : null,
					idle_threshold_seconds: row.idleAfter ? Number(row.idleAfter) : null,
					department_id: row.departmentId || null,
					app_categories: this.appCategories
				}
			})
		);
	}

	public async saveEmployee(row: EmployeeRow): Promise<void> {
		this.saved = '';
		this.error = '';
		try {
			await this.persist(row);
			this.saved = `Saved ${row.label}. The tracker applies it within 60 seconds.`;
		} catch (e: any) {
			this.error = `Could not save (HTTP ${e?.status || '?'}).`;
		}
	}

	/**
	 * App categories belong to a department, but are stored per employee, so a
	 * change has to be written to everyone. Small N and this page is the only
	 * writer, so a straightforward loop is enough.
	 */
	private async persistCategories(): Promise<void> {
		this.saved = '';
		this.error = '';
		try {
			for (const row of this.employees) {
				await this.persist(row);
			}
			this.saved = 'Saved. The tracker applies it within 60 seconds.';
		} catch (e: any) {
			this.error = `Could not save (HTTP ${e?.status || '?'}).`;
		}
	}

	public async saveApp(name: string, category: string): Promise<void> {
		const app = (name || '').trim().toLowerCase();
		if (!app || !this.appDept) return;
		this.appCategories[this.appDept] = { ...(this.appCategories[this.appDept] || {}), [app]: category };
		this.newApp = '';
		this.refreshApps();
		await this.persistCategories();
	}

	public async removeApp(name: string): Promise<void> {
		if (!this.appCategories[this.appDept]) return;
		delete this.appCategories[this.appDept][name];
		this.refreshApps();
		await this.persistCategories();
	}


}
