import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { NbButtonModule, NbCardModule, NbInputModule, NbSelectModule, NbSpinnerModule } from '@nebular/theme';
import { TranslateModule } from '@ngx-translate/core';
import { GauzyFiltersModule, NoDataMessageModule, SharedModule } from '@gauzy/ui-core/shared';
import { AppUsageComponent } from './app-usage.component';

/**
 * Wraps AppUsageComponent so more than one page can host it.
 *
 * It was declared directly by ActivityModule, which meant only the Time &
 * Activity tabset could show it. The employee "My Work" page needs the same
 * component, and an Angular component may only be declared once — hence this
 * module, imported by both.
 */
@NgModule({
	imports: [
		CommonModule,
		FormsModule,
		NbButtonModule,
		NbCardModule,
		NbInputModule,
		NbSelectModule,
		NbSpinnerModule,
		TranslateModule.forChild(),
		GauzyFiltersModule,
		NoDataMessageModule,
		SharedModule
	],
	declarations: [AppUsageComponent],
	exports: [AppUsageComponent]
})
export class AppUsageModule {}
