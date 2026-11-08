import { createResource } from 'frappe-ui'

let translationsRequest

export default function translationPlugin(app) {
	app.config.globalProperties.__ = translate
	window.__ = translate
	// Editor sub-apps share the main app's messages and in-flight request.
	loadTranslations().catch(() => {})
}

function translate(message) {
	let translatedMessages = window.translatedMessages || {}
	let translatedMessage = translatedMessages[message] || message

	const hasPlaceholders = /{\d+}/.test(message)
	if (!hasPlaceholders) {
		return translatedMessage
	}
	return {
		format: function (...args) {
			return translatedMessage.replace(
				/{(\d+)}/g,
				function (match, number) {
					return typeof args[number] != 'undefined'
						? args[number]
						: match
				}
			)
		},
	}
}

export function loadTranslations() {
	if (window.translatedMessages) return Promise.resolve(window.translatedMessages)
	if (!translationsRequest) {
		translationsRequest = createResource({
			url: 'lms.lms.api.get_translations',
		})
			.fetch()
			.then((data) => {
				window.translatedMessages = data || {}
				return window.translatedMessages
			})
			.finally(() => {
				translationsRequest = null
			})
	}
	return translationsRequest
}
