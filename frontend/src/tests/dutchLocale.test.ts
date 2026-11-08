import { afterEach, describe, expect, it, vi } from 'vitest'

const browser = window as Window & { lang?: string; timezone?: { system: string } }
const originalLang = browser.lang
const originalTimezone = browser.timezone
const originalDirection = document.documentElement.dir

afterEach(async () => {
	const { default: dayjs } = await import('@/utils/dayjs')
	dayjs.locale('en')
	browser.lang = originalLang
	browser.timezone = originalTimezone
	document.documentElement.dir = originalDirection
	vi.useRealTimers()
})

describe('Dutch dates and relative times', () => {
	it.each(['nl', 'nl-NL', 'nl_NL', 'nl-BE'])('supports %s in the left-to-right LMS', async (language) => {
		browser.lang = language
		document.documentElement.dir = 'ltr'
		vi.resetModules()
		const { default: dayjs } = await import('@/utils/dayjs')
		expect(dayjs.locale()).toBe('nl')
		expect(dayjs('2026-11-09').format('dddd D MMMM YYYY')).toBe('maandag 9 november 2026')
		expect(dayjs('2026-11-09 14:30').format('LT')).toBe('14:30')
	})

	it('uses Dutch relative time in both notification and discussion formatting', async () => {
		browser.lang = 'nl'
		browser.timezone = { system: 'Europe/Amsterdam' }
		vi.useFakeTimers()
		vi.setSystemTime(new Date('2026-11-09T12:00:00Z'))
		vi.resetModules()
		const { serverTime } = await import('@/utils/dayjs')
		const { timeAgo } = await import('@/utils/format')
		expect(serverTime('2026-11-09 12:59:00').fromNow()).toBe('een minuut geleden')
		expect(timeAgo('2026-11-09 12:59:00')).toBe('een minuut geleden')
		expect(timeAgo('2026-11-09 13:05:00')).toBe('over 5 minuten')
	})

	it('formats Dutch times, amounts and ratings without changing English defaults', async () => {
		browser.lang = 'nl'
		vi.resetModules()
		const { default: dayjs } = await import('@/utils/dayjs')
		const {
			formatTime, formatNumber, formatNumberIntoCurrency, formatAmount, formatRating,
		} = await import('@/utils/format')
		expect(formatTime('14:30:00')).toBe('14:30')
		expect(formatNumber(1234567)).toBe('1.234.567')
		expect(formatNumberIntoCurrency(1234, 'EUR')).toBe('€\u00a01.234')
		expect(formatAmount(1250)).toBe('1,3k')
		expect(formatRating(4.5)).toBe('4,5')
		dayjs.locale('en')
		expect(formatTime('14:30:00')).toBe('2:30 PM')
		expect(formatNumber(1234567)).toBe('12,34,567')
		expect(formatAmount(1250)).toBe('1.3k')
		expect(formatRating(4.5)).toBe('4.5')
	})

	it('retains English fallback and the existing RTL locale support', async () => {
		browser.lang = 'en'
		vi.resetModules()
		let { default: dayjs } = await import('@/utils/dayjs')
		expect(dayjs('2026-11-09').format('MMMM')).toBe('November')
		browser.lang = 'ar'
		document.documentElement.dir = 'rtl'
		vi.resetModules()
		;({ default: dayjs } = await import('@/utils/dayjs'))
		expect(dayjs.locale()).toBe('ar')
	})
})
