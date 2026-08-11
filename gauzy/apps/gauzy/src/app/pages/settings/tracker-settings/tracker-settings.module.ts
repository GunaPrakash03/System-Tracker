import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import {
	NbButtonModule,
	NbButtonGroupModule,
	NbCardModule,
	NbInputModule,
	NbSelectModule,
	NbSpinnerModule,
	NbToggleModule
} from '@nebular/theme';
import { TranslateModule } from '@ngx-translate/core';
import { TrackerSettingsComponent } from './tracker-settings.component';

const NB_MODULES = [
	NbButtonModule,
	NbButtonGroupModule,
	NbCardModule,
	NbInputModule,
	NbSelectModule,
	NbSpinnerModule,
	NbToggleModule
];

/**
 * System-Tracker settings page.
 *
 * Routing is declared here rather than in a separate routing module: the page is
 * a single component with no children, so a second file would carry one route
 * and nothing else.
 */
@NgModule({
	imports: [
		CommonModule,
		FormsModule,
		RouterModule.forChild([{ path: '', component: TrackerSettingsComponent }]),
		TranslateModule.forChild(),
		...NB_MODULES
	],
	declarations: [TrackerSettingsComponent]
})
export class TrackerSettingsModule {}
