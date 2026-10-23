export interface CommerceAccess {
	handled: boolean
	allowed: boolean
	reason?: string
	badge?: { label: string; theme?: string; icon?: string }
	price_label?: string
	offers?: { kind: string; label: string; url: string; variant?: string }[]
}

export function commerceDenied(access?: CommerceAccess | null): boolean {
	return access?.handled === true && access.allowed !== true
}

export function safeActionUrl(value: unknown): string | null {
	if (typeof value !== 'string' || !value || /[\s\\\u0000-\u001f\u007f]/.test(value)) return null
	if (value.startsWith('/') && !value.startsWith('//')) return value
	try {
		const url = new URL(value)
		return url.protocol === 'https:' && !url.username && !url.password ? url.href : null
	} catch {
		return null
	}
}
