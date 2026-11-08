import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h } from 'vue'

const { fetchMessages, createResource } = vi.hoisted(() => {
	const fetchMessages = vi.fn()
	return {
		fetchMessages,
		createResource: vi.fn(() => ({ fetch: fetchMessages })),
	}
})
vi.mock('frappe-ui', () => ({ createResource }))

const browser = window as Window & {
	translatedMessages?: Record<string, string>
	__?: any
}
let originalMessages: typeof browser.translatedMessages
let originalTranslate: typeof browser.__

beforeEach(() => {
	originalMessages = browser.translatedMessages
	originalTranslate = browser.__
	delete browser.translatedMessages
	vi.resetModules()
	vi.clearAllMocks()
})
afterEach(() => {
	browser.translatedMessages = originalMessages
	browser.__ = originalTranslate
})

describe('translation loading', () => {
	it('loads Dutch before setup-time labels are evaluated on the first mount', async () => {
		let resolve!: (messages: Record<string, string>) => void
		fetchMessages.mockReturnValue(new Promise((done) => { resolve = done }))
		const { default: plugin, loadTranslations } = await import('@/translation')
		const app = createApp({
			setup() {
				const label = browser.__('Courses')
				return () => h('div', label)
			},
		})
		app.use(plugin)
		const target = document.createElement('div')
		const ready = loadTranslations().then(() => app.mount(target))
		expect(target.textContent).toBe('')
		resolve({ Courses: 'Cursussen' })
		await ready
		expect(target.textContent).toBe('Cursussen')
		expect(fetchMessages).toHaveBeenCalledTimes(1)
		app.unmount()
	})

	it('shares one in-flight request across the app and editor sub-apps', async () => {
		let resolve!: (messages: Record<string, string>) => void
		fetchMessages.mockReturnValue(new Promise((done) => { resolve = done }))
		const { default: plugin, loadTranslations } = await import('@/translation')
		plugin({ config: { globalProperties: {} } })
		plugin({ config: { globalProperties: {} } })
		const first = loadTranslations()
		expect(loadTranslations()).toBe(first)
		resolve({ Save: 'Opslaan' })
		await first
		expect(await loadTranslations()).toEqual({ Save: 'Opslaan' })
		expect(fetchMessages).toHaveBeenCalledTimes(1)
	})

	it('uses preloaded messages and preserves placeholders including zero', async () => {
		browser.translatedMessages = {
			Courses: 'Cursussen',
			'{0} of {1} lessons completed': '{0} van {1} lessen afgerond',
		}
		const { default: plugin } = await import('@/translation')
		plugin({ config: { globalProperties: {} } })
		expect(browser.__('Courses')).toBe('Cursussen')
		expect(browser.__('{0} of {1} lessons completed').format(0, 5)).toBe('0 van 5 lessen afgerond')
		expect(browser.__('{0} of {1} lessons completed').format(2)).toBe('2 van {1} lessen afgerond')
		expect(browser.__('Unknown message')).toBe('Unknown message')
		expect(browser.__('Unknown {0}').format('value')).toBe('Unknown value')
		expect(createResource).not.toHaveBeenCalled()
	})

	it('keeps English fallback usable after a failure and permits a later retry', async () => {
		fetchMessages.mockRejectedValueOnce(new Error('offline'))
		const { default: plugin, loadTranslations } = await import('@/translation')
		plugin({ config: { globalProperties: {} } })
		await expect(loadTranslations()).rejects.toThrow('offline')
		expect(browser.__('Courses')).toBe('Courses')
		expect(browser.__('Question {0}').format(1)).toBe('Question 1')
		fetchMessages.mockResolvedValueOnce({ Courses: 'Cursussen' })
		await loadTranslations()
		expect(browser.__('Courses')).toBe('Cursussen')
	})
})
