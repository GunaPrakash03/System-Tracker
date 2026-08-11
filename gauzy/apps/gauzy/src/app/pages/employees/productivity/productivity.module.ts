import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { NbButtonModule, NbCardModule, NbInputModule, NbSelectModule, NbSpinnerModule } from '@nebular/theme';
import { TranslateModule } from '@ngx-translate/core';
import { ProductivityComponent } from './productivity.component';

/**
 * Hourly productivity page.
 *
 * Routing is declared inline: one component, no children, so a separate routing
 * module would carry a single route and nothing else.
 */
@NgModule({
	imports: [
		CommonModule,
		FormsModule,
		RouterModule.forChild([{ path: '', component: ProductivityComponent }]),
		TranslateModule.forChild(),
		NbButtonModule,
		NbCardModule,
		NbInputModule,
		NbSelectModule,
		NbSpinnerModule
	],
	declarations: [ProductivityComponent]
})
export class ProductivityModule {}
