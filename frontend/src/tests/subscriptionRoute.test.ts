import { describe, expect, it } from 'vitest'
import { routes } from '@/routes'

describe('subscription routes', () => {
	it('registers the learner subscription page and generic billing route', () => {
		expect(routes).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					name: 'Subscriptions',
					path: '/subscriptions',
				}),
				expect.objectContaining({
					name: 'Billing',
					path: '/billing/:type/:name',
				}),
			]),
		)
	})
})
