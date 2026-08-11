import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { NbMenuService } from '@nebular/theme';
import { UntilDestroy, untilDestroyed } from '@ngneat/until-destroy';
import { filter, map, tap } from 'rxjs/operators';
import { IEmployee } from '@gauzy/contracts';

/**
 * Row actions for the employee list — a vertical 3-dot button opening Edit and
 * Delete.
 *
 * A menu rather than two buttons in the row: Delete should not sit permanently
 * next to Edit where it can be hit by accident, and the menu absorbs later
 * actions without costing another column.
 *
 * The context-menu TAG is the employee id, which matters more than it looks.
 * Nebular routes menu clicks by tag through one shared NbMenuService, so every
 * row sharing a tag would open together and a click would fire on all of them.
 * The id is unique per row by definition.
 */
@UntilDestroy({ checkProperties: true })
@Component({
	selector: 'gauzy-employee-row-actions',
	templateUrl: './employee-row-actions.component.html',
	styleUrls: ['./employee-row-actions.component.scss'],
	standalone: false
})
export class EmployeeRowActionsComponent implements OnInit {
	@Input() rowData: IEmployee;
	@Output() edit: EventEmitter<IEmployee> = new EventEmitter();
	@Output() delete: EventEmitter<IEmployee> = new EventEmitter();

	public items = [
		{ title: 'Edit', icon: 'edit-outline', data: { action: 'edit' } },
		{ title: 'Delete', icon: 'trash-2-outline', data: { action: 'delete' } }
	];

	constructor(private readonly _nbMenuService: NbMenuService) {}

	/** Unique per row — see the class comment on why this cannot be a constant. */
	public get tag(): string {
		return `employee-actions-${this.rowData?.id}`;
	}

	ngOnInit(): void {
		this._nbMenuService
			.onItemClick()
			.pipe(
				filter(({ tag }) => tag === this.tag),
				map(({ item }) => (item as any)?.data?.action),
				tap((action: string) => {
					if (action === 'edit') this.edit.emit(this.rowData);
					if (action === 'delete') this.delete.emit(this.rowData);
				}),
				untilDestroyed(this)
			)
			.subscribe();
	}
}
