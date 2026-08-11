import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { NbCardModule, NbSpinnerModule } from '@nebular/theme';
import { TranslateModule } from '@ngx-translate/core';
import { SharedModule } from '@gauzy/ui-core/shared';
import { AppCategoriesComponent } from './app-categories.component';

/**
 * Wraps AppCategoriesComponent so more than one page can host it — the same
 * reason AppUsageModule exists. An Angular component may only be declared once,
 * and this tab is wanted from My work today and likely from Employees →
 * Activity later.
 */
@NgModule({
	imports: [CommonModule, NbCardModule, NbSpinnerModule, TranslateModule.forChild(), SharedModule],
	declarations: [AppCategoriesComponent],
	exports: [AppCategoriesComponent]
})
export class AppCategoriesModule {}
