import { useTimeAgo } from '@vueuse/core'
import dayjs, { serverTime } from '@/utils/dayjs'

export function timeAgo(date) {
	const value = serverTime(date)
	if (dayjs.locale() === 'nl') return value.fromNow()
	return useTimeAgo(value.toDate()).value
}

export function formatTime(timeString) {
	if (!timeString) return ''
	const [hour, minute] = timeString.split(':').map(Number)
	const dummyDate = new Date(0, 0, 0, hour, minute)
	return new Intl.DateTimeFormat(
		dayjs.locale() === 'nl' ? 'nl-NL' : 'en-US',
		{
			hour: 'numeric',
			minute: 'numeric',
			hour12: dayjs.locale() !== 'nl',
		}
	).format(dummyDate)
}

export function formatNumber(number) {
	return number.toLocaleString(dayjs.locale() === 'nl' ? 'nl-NL' : 'en-IN', {
		maximumFractionDigits: 0,
	})
}

export function formatNumberIntoCurrency(number, currency) {
	if (number) {
		return number.toLocaleString(dayjs.locale() === 'nl' ? 'nl-NL' : 'en-IN', {
			maximumFractionDigits: 0,
			style: 'currency',
			currency: currency,
		})
	}
	return ''
}

export function formatAmount(amount) {
	if (amount > 999) {
		const compact = (amount / 1000).toFixed(1)
		return (dayjs.locale() === 'nl' ? compact.replace('.', ',') : compact) + 'k'
	}
	return amount
}

export function formatRating(value) {
	const n = Number(value)
	if (!isFinite(n)) return ''
	const rating = (Math.round(n * 10) / 10).toString()
	return dayjs.locale() === 'nl' ? rating.replace('.', ',') : rating
}

// Map the site's System Settings date_format (boot data) to dayjs tokens.
const DATE_TOKENS = { yyyy: 'YYYY', yy: 'YY', mmm: 'MMM', mm: 'MM', dd: 'DD' }
export function getDateFormat() {
	const fmt = window.date_format || 'dd-mm-yyyy'
	return fmt.replace(/yyyy|yy|mmm|mm|dd/g, (t) => DATE_TOKENS[t])
}

export const formatSeconds = (time) => {
	const minutes = Math.floor(time / 60)
	const seconds = Math.floor(time % 60)
	return `${minutes}:${seconds < 10 ? '0' : ''}${seconds}`
}

// Single source of truth; decoders derive their inverse from this map.
export const HTML_ESCAPE_MAP = {
	'&': '&amp;',
	'<': '&lt;',
	'>': '&gt;',
	'"': '&quot;',
	"'": '&#39;',
	'`': '&#x60;',
	'=': '&#x3D;',
}

export const escapeHTML = (text) => {
	if (!text) return ''
	return String(text).replace(/[&<>"'`=]/g, (char) => HTML_ESCAPE_MAP[char])
}

export const formatTimestamp = (seconds) => {
	const date = new Date(seconds * 1000)
	const hours = String(date.getUTCHours()).padStart(2, '0')
	const minutes = String(date.getUTCMinutes()).padStart(2, '0')
	const secs = String(date.getUTCSeconds()).padStart(2, '0')
	return hours > 0 ? `${hours}:${minutes}:${secs}` : `${minutes}:${secs}`
}
