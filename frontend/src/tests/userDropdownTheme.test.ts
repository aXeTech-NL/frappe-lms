/**
 * The user menu's Theme row. Before this conversion it toggled light/dark only
 * — the tri-state 'system' preference `utils/theme.ts` already supports had no
 * way into the UI. It is now a submenu (Light/Dark/System), matching the
 * pattern frappe-ui's Dropdown docs show for a theme switcher in a user menu
 * (stories/UserMenu.vue) — not the full `ThemeSwitcher` component, which is
 * for a settings panel, not a menu row.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

// Only what this suite controls is replaced; the rest of frappe-ui stays real.
// Dropdown becomes a prop-capturing stub because the assertions are about the
// menu's own data (which rows exist, what they call), not popover mechanics.
vi.mock('frappe-ui', async () => {
	const actual = await vi.importActual<typeof import('frappe-ui')>('frappe-ui')
	return {
		...actual,
		call: vi.fn(),
		createResource: () => ({ data: null, loading: false, submit: vi.fn() }),
		toast: { success: vi.fn(), error: vi.fn() },
		Dropdown: {
			name: 'Dropdown',
			props: ['options'],
			template: `<div><slot :open="false" :close="() => {}" /></div>`,
		},
	}
})

vi.mock('@/stores/session', () => ({
	sessionStore: () => ({
		logout: { submit: vi.fn() },
		branding: { data: null },
		isLoggedIn: true,
	}),
}))

vi.mock('@/stores/user', () => ({
	usersStore: () => ({ userResource: { data: { is_moderator: false } } }),
}))

vi.mock('@/stores/settings', () => ({
	useSettings: () => ({ settings: { data: null } }),
}))

vi.mock('@/composables/useSettingsHash', () => ({ pushSettingsHash: vi.fn() }))
vi.mock('@/utils/openExternal', () => ({ openExternal: vi.fn() }))
vi.mock('@/utils/dialogs', () => ({ createDialog: vi.fn() }))
vi.mock('@/components/Icons/LMSLogo.vue', () => ({
	default: { template: '<div />' },
}))
vi.mock('@/components/Settings/Settings.vue', () => ({
	default: { template: '<div />' },
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/utils', () => ({ convertToTitleCase: (s: string) => s }))
vi.mock('@/utils/safeUrl', () => ({ safeUrl: (s: string) => s }))

vi.stubGlobal('__', (text: string) => text)

import UserDropdown from '@/components/Sidebar/UserDropdown.vue'
import translationPlugin from '@/translation'
import { setThemePreference, themePreference } from '@/utils/theme'

function build() {
	setActivePinia(createPinia())
	return mount(UserDropdown, { global: { mocks: { __: (t: string) => t } } })
}

function themeMenu(wrapper: ReturnType<typeof build>) {
	const options = wrapper.findComponent({ name: 'Dropdown' }).props('options')
	const group = options[0].options as any[]
	return group.find((option) => option.label === 'Theme')
}

describe('UserDropdown translations', () => {
	const dutch = {
		Learning: 'Leren',
		'My Profile': 'Mijn profiel',
		Settings: 'Instellingen',
		'Clear Demo Data': 'Demogegevens verwijderen',
		'Login to Frappe Cloud': 'Inloggen bij Frappe Cloud',
		'Log out': 'Uitloggen',
		'Log in': 'Inloggen',
		Theme: 'Thema',
		Light: 'Licht',
		Dark: 'Donker',
		System: 'Systeem',
		Configuration: 'Configuratie',
		Import: 'Importeren',
	}

	it.each([dutch, {}])('translates menu labels with native English fallback', (messages) => {
		const browser = window as Window & { translatedMessages?: Record<string, string>; __?: any }
		const previousMessages = browser.translatedMessages
		const previousTranslate = browser.__
		browser.translatedMessages = messages
		setActivePinia(createPinia())
		const wrapper = mount(UserDropdown, { global: { plugins: [translationPlugin] } })
		try {
			const translate = (text: string) => (messages as Record<string, string>)[text] || text
			const items = wrapper.findComponent({ name: 'Dropdown' }).props('options')[0].options
			const labels = items.map((item: any) => item.label)
			for (const text of ['My Profile', 'Settings', 'Clear Demo Data', 'Login to Frappe Cloud', 'Log out', 'Log in']) {
				expect(labels).toContain(translate(text))
			}
			expect(wrapper.text()).toContain(translate('Learning'))
			const theme = items.find((item: any) => item.label === translate('Theme'))
			expect(theme.submenu.map((item: any) => item.label)).toEqual(['Light', 'Dark', 'System'].map(translate))
			const configuration = items.find((item: any) => item.label === translate('Configuration'))
			expect(configuration.submenu[0].label).toBe(translate('Import'))
			// Translated labels must not change session/role gates or theme values.
			expect(items.find((item: any) => item.label === translate('My Profile')).condition()).toBe(true)
			expect(items.find((item: any) => item.label === translate('Settings')).condition()).toBe(false)
			expect(items.find((item: any) => item.label === translate('Log in')).condition()).toBe(false)
			theme.submenu.find((item: any) => item.label === translate('Dark')).onClick()
			expect(themePreference.value).toBe('dark')
		} finally {
			wrapper.unmount()
			browser.translatedMessages = previousMessages
			browser.__ = previousTranslate
			setThemePreference('system')
		}
	})
})

describe('UserDropdown theme menu', () => {
	beforeEach(() => {
		setThemePreference('system')
	})

	afterEach(() => {
		setThemePreference('system')
	})

	it('offers Light, Dark and System', () => {
		const menu = themeMenu(build())
		expect(menu.submenu.map((item: any) => item.label)).toEqual([
			'Light',
			'Dark',
			'System',
		])
	})

	it('marks the current preference selected', () => {
		setThemePreference('dark')
		const menu = themeMenu(build())
		const selected = menu.submenu.filter((item: any) => item.selected)
		expect(selected.map((item: any) => item.label)).toEqual(['Dark'])
	})

	it('sets the preference when a theme is picked', () => {
		const menu = themeMenu(build())
		menu.submenu.find((item: any) => item.label === 'Light').onClick()
		expect(themePreference.value).toBe('light')

		menu.submenu.find((item: any) => item.label === 'System').onClick()
		expect(themePreference.value).toBe('system')
	})
})
