import { Component, OnInit, OnDestroy, ChangeDetectorRef, ViewChild } from '@angular/core';
import { FormBuilder, FormGroup, NgForm } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { filter, firstValueFrom, tap } from 'rxjs';
import { NbAccordionComponent, NbAccordionItemComponent } from '@nebular/theme';
import { UntilDestroy, untilDestroyed } from '@ngneat/until-destroy';
import * as moment from 'moment';
import { DEFAULT_TIME_FORMATS } from '@gauzy/constants';
import { IEmployee } from '@gauzy/contracts';
import { EmployeeStore, Store } from '@gauzy/ui-core/core';

@UntilDestroy({ checkProperties: true })
@Component({
	selector: 'ga-edit-employee-settings',
	templateUrl: './edit-employee-other-settings.component.html',
	styleUrls: ['./edit-employee-other-settings.component.scss'],
	standalone: false
})
export class EditEmployeeOtherSettingsComponent implements OnInit, OnDestroy {
	listOfTimeFormats = DEFAULT_TIME_FORMATS;
	selectedEmployee: IEmployee;
	/**
	 * Nebular Accordion Main Component
	 */
	accordion: NbAccordionComponent;
	@ViewChild('accordion') set content(content: NbAccordionComponent) {
		if (content) {
			this.accordion = content;
			this.cdr.detectChanges();
		}
	}

	/**
	 * Nebular Accordion Item Components
	 */
	@ViewChild('general') general: NbAccordionItemComponent;
	@ViewChild('integrations') integrations: NbAccordionItemComponent;
	@ViewChild('timer') timer: NbAccordionItemComponent;
	@ViewChild('agent') agent: NbAccordionItemComponent;

	/**
	 * Employee other settings settings
	 */
	public form: FormGroup = EditEmployeeOtherSettingsComponent.buildForm(this.fb);
	static buildForm(fb: FormBuilder): FormGroup {
		return fb.group({
			timeZone: [],
			timeFormat: [],
			upworkId: [],
			linkedInId: [],
			allowManualTime: [false],
			allowModifyTime: [false],
			allowDeleteTime: [false],
			allowScreenshotCapture: [true],
			allowAgentAppExit: [true],
			allowLogoutFromAgentApp: [true],
			trackKeyboardMouseActivity: [false],
			trackAllDisplays: [true]
		});
	}

	/**
	 * Tracker department. Not the same field as the Department column on the
	 * employee list, which shows Gauzy's own organizationDepartments relation and
	 * can hold several at once.
	 *
	 * App productivity rules are stored per department and looked up by exactly
	 * one id, so the tracker keeps its own single-valued field rather than
	 * guessing which of an employee's departments should govern. Leave it unset
	 * and nothing classifies: Productivity shows the whole day as Neutral.
	 */
	public departments: { id: string; name: string }[] = [];
	public departmentId = '';
	public departmentSaving = false;
	public departmentNote = '';
	/** The rest of the settings row, kept so a save cannot discard it. */
	private settingsData: any = {};
	private settingId: string | undefined;

	constructor(
		private readonly cdr: ChangeDetectorRef,
		private readonly fb: FormBuilder,
		private readonly employeeStore: EmployeeStore,
		private readonly http: HttpClient,
		private readonly store: Store
	) {}

	/**
	 *
	 */
	ngOnInit(): void {
		this.employeeStore.selectedEmployee$
			.pipe(
				filter((employee: IEmployee) => !!employee),
				tap((employee: IEmployee) => {
					this.selectedEmployee = employee;
					this._patchFormValue(employee);
					this._loadDepartment(employee);
				}),
				untilDestroyed(this)
			)
			.subscribe();
	}

	/** Departments to choose from, and whichever one is already recorded. */
	private async _loadDepartment(employee: IEmployee): Promise<void> {
		this.departmentNote = '';
		const scope =
			`where[tenantId]=${this.store.user?.tenantId}` +
			`&where[organizationId]=${this.store.selectedOrganization?.id}`;
		try {
			const [depts, settings]: any[] = await Promise.all([
				firstValueFrom(this.http.get(`/api/organization-department?${scope}`)),
				firstValueFrom(this.http.get(`/api/employee-settings?where[employeeId]=${employee.id}&${scope}`))
			]);
			this.departments = (depts?.items || depts || []).map((d: any) => ({ id: d.id, name: d.name }));
			const items = Array.isArray(settings) ? settings : settings?.items || [];
			const row = items[items.length - 1];
			this.settingsData = row?.data || {};
			this.settingId = row?.id;
			this.departmentId = this.settingsData.department_id || '';
			this.cdr.detectChanges();
		} catch (e: any) {
			this.departmentNote = `Could not load departments (HTTP ${e?.status || '?'}).`;
		}
	}

	/**
	 * Save the tracker department.
	 *
	 * MERGE, never replace: this endpoint upserts and overwrites `data` wholesale,
	 * and the row is shared with the tracker, which publishes its daily usage
	 * summary into the same object. A bare write here would delete that summary
	 * along with the screenshot interval and blur setting.
	 */
	public async saveDepartment(): Promise<void> {
		if (!this.selectedEmployee) return;
		this.departmentSaving = true;
		this.departmentNote = '';
		try {
			await firstValueFrom(
				this.http.post('/api/employee-settings', {
					employeeId: this.selectedEmployee.id,
					organizationId: this.store.selectedOrganization?.id,
					tenantId: this.store.user?.tenantId,
					entity: 'Employee',
					entityId: this.selectedEmployee.id,
					settingType: 'Custom',
					data: { ...this.settingsData, department_id: this.departmentId || null }
				})
			);
			this.settingsData = { ...this.settingsData, department_id: this.departmentId || null };
			this.departmentNote = this.departmentId
				? 'Saved. App productivity rules for that department now apply to this employee.'
				: 'Cleared. With no department, Productivity reports every app as Neutral.';
		} catch (e: any) {
			this.departmentNote = `Could not save (HTTP ${e?.status || '?'}).`;
		} finally {
			this.departmentSaving = false;
			this.cdr.detectChanges();
		}
	}

	/**
	 * Patches the form with employee data or default values if data is unavailable.
	 *
	 * @param {IEmployee} employee - The employee object containing user data.
	 * @returns {void}
	 */
	private _patchFormValue(employee: IEmployee): void {
		if (!employee) return;

		const {
			user,
			upworkId,
			linkedInId,
			allowManualTime,
			allowDeleteTime,
			allowModifyTime,
			allowScreenshotCapture,
			allowAgentAppExit,
			allowLogoutFromAgentApp,
			trackKeyboardMouseActivity,
			trackAllDisplays
		} = employee;
		this.form.patchValue({
			timeZone: user?.timeZone ?? moment.tz.guess(),
			timeFormat: user?.timeFormat,
			upworkId,
			linkedInId,
			allowManualTime,
			allowDeleteTime,
			allowModifyTime,
			allowScreenshotCapture,
			allowAgentAppExit: allowAgentAppExit ?? true,
			allowLogoutFromAgentApp: allowLogoutFromAgentApp ?? true,
			trackKeyboardMouseActivity: trackKeyboardMouseActivity ?? false,
			trackAllDisplays: trackAllDisplays ?? true
		});
		this.form.updateValueAndValidity();
	}

	/**
	 * Handles the form submission, updating employee and user settings if valid.
	 *
	 * @param {NgForm} form - The form reference for submission.
	 * @returns {void}
	 */
	onSubmit(form: NgForm): void {
		if (form.invalid) return;

		const { organizationId, tenantId } = this.selectedEmployee;
		const {
			timeZone,
			timeFormat,
			upworkId,
			linkedInId,
			allowManualTime,
			allowDeleteTime,
			allowModifyTime,
			allowScreenshotCapture,
			allowAgentAppExit,
			allowLogoutFromAgentApp,
			trackKeyboardMouseActivity,
			trackAllDisplays
		} = this.form.value;

		this.employeeStore.updateUserForm({ timeZone, timeFormat });
		this.employeeStore.updateEmployeeForm({
			upworkId,
			linkedInId,
			organizationId,
			tenantId,
			allowManualTime,
			allowDeleteTime,
			allowModifyTime,
			allowScreenshotCapture,
			allowAgentAppExit,
			allowLogoutFromAgentApp,
			trackKeyboardMouseActivity,
			trackAllDisplays
		});
	}

	/**
	 *
	 */
	ngOnDestroy(): void {}
}
