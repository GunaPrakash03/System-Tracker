import { ISidebarConfig } from '@gauzy/ui-core/core';
import { ThemeSettingsComponent } from './theme-settings/theme-settings.component';

// The changelog sidebar — the gift icon in the header, opening a "What's new?"
// panel — is not registered. It served Ever's seeded release notes to our staff,
// and with those rows removed it opened as an empty titled card, which reads as
// a broken feature rather than an absent one. Nothing here announces releases.
// The component itself is left in the tree so re-registering is a one-line
// change if that ever becomes wanted.
export const DEFAULT_SIDEBARS: { [id: string]: ISidebarConfig } = {
	settings_sidebar: {
		loadComponent: () => ThemeSettingsComponent,
		class: 'settings-sidebar',
		actionItem: {
			id: 'settings_sidebar',
			label: 'settings sidebar',
			icon: 'settings-2-outline',
			class: 'toggle-layout'
		}
	}
};
