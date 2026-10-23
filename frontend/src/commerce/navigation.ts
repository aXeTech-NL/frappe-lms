export function commerceLinks(settings: Record<string, unknown> | null | undefined, user: unknown) {
	const items = []
	if (settings?.commerce_enabled && user) {
		items.push({ label: 'My access', icon: 'KeyRound', to: 'CommerceAccess', activeFor: ['CommerceAccess'] })
	}
	if (settings?.can_manage_commerce && user) {
		items.push({ label: 'Commerce management', icon: 'CreditCard', to: 'desk/commerce', activeFor: [] })
	}
	return { label: 'Commerce', hideLabel: true, items }
}

export const commerceRoutes = [{
	path: '/access',
	name: 'CommerceAccess',
	component: () => import('./MyAccess.vue'),
}]
