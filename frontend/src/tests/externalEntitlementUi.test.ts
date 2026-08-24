import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'

vi.stubGlobal('__', (text: string) => text)
enableAutoUnmount(afterEach)

String.prototype.format = function (this: string, ...args: unknown[]): string {
	return this.replace(/{(\d+)}/g, (match, index) =>
		args[Number(index)] === undefined ? match : String(args[Number(index)])
	)
}

const { callMock, routerPush } = vi.hoisted(() => ({
	callMock: vi.fn(() => Promise.resolve()),
	routerPush: vi.fn(),
}))

vi.mock('frappe-ui', () => ({
	Badge: {
		inheritAttrs: false,
		props: ['theme', 'size'],
		template: '<span v-bind="$attrs"><slot /></span>',
	},
	Button: {
		inheritAttrs: false,
		props: ['variant', 'size'],
		template: '<button v-bind="$attrs"><slot name="prefix"/><slot /></button>',
	},
	call: callMock,
	createResource: () => ({ submit: vi.fn() }),
	toast: { success: vi.fn(), warning: vi.fn() },
}))
vi.mock('frappe-ui/frappe', () => ({ useTelemetry: () => ({ capture: vi.fn() }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))
vi.mock('@/components/CertificationLinks.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/VideoPreview.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/utils/openExternal', () => ({ openExternal: vi.fn() }))

import EntitlementActions from '@/components/EntitlementActions.vue'
import EntitlementBadge from '@/components/EntitlementBadge.vue'
import CourseCardOverlay from '@/components/CourseCardOverlay.vue'

const denied = {
	handled: true,
	allowed: false,
	reason: 'upgrade_required',
	badge: { label: 'Max', theme: 'violet', icon: 'lock' },
	offers: [
		{
			kind: 'upgrade',
			label: 'Upgrade to Max',
			url: '/commerce/plans',
			variant: 'outline',
			icon: 'layers',
		},
	],
}

const mountOverlay = (data: Record<string, any>) =>
	mount(CourseCardOverlay, {
		props: { course: reactive({ data }) as any },
		global: {
			provide: { $user: { data: { name: 'student@example.com' } } },
			stubs: { RouterLink: { template: '<a><slot /></a>' } },
			mocks: { __: (text: string) => text },
		},
	})

describe('generic entitlement presentation', () => {
	beforeEach(() => {
		callMock.mockClear()
		routerPush.mockClear()
		;(window as Window & { read_only_mode?: boolean }).read_only_mode = false
	})

	it('renders only normalized badge data', () => {
		const wrapper = mount(EntitlementBadge, { props: { decision: denied as any } })
		expect(wrapper.find('[data-testid="entitlement-lock"]').text()).toContain('Max')
		expect(wrapper.find('.lucide-lock').exists()).toBe(true)
	})

	it('renders relative and external HTTPS provider actions safely', () => {
		const wrapper = mount(EntitlementActions, { props: { decision: denied as any } })
		const link = wrapper.get('a')
		expect(link.attributes('href')).toBe('/commerce/plans')
		expect(link.attributes('target')).toBeUndefined()
		expect(wrapper.get('[data-testid="entitlement-offer-upgrade"]').text()).toContain(
			'Upgrade to Max'
		)

		const external = mount(EntitlementActions, {
			props: {
				decision: {
					...denied,
					offers: [{ ...denied.offers[0], url: 'https://commerce.example/plans' }],
				} as any,
			},
		})
		expect(external.get('a').attributes('target')).toBe('_blank')
		expect(external.get('a').attributes('rel')).toBe('noopener noreferrer')
	})

	it('does not bind an unsafe provider URL defensively', () => {
		const wrapper = mount(EntitlementActions, {
			props: {
				decision: {
					...denied,
					offers: [{ ...denied.offers[0], url: 'javascript:alert(1)' }],
				} as any,
			},
		})
		expect(wrapper.get('a').attributes('href')).toBeUndefined()
	})

	it('replaces Continue Learning with provider offers when entitlement expired', () => {
		const wrapper = mountOverlay({
			name: 'managed-course',
			title: 'Managed',
			instructors: [],
			membership: { progress: 50 },
			entitlement: denied,
		})
		expect(wrapper.text()).not.toContain('Continue Learning')
		expect(wrapper.get('[data-testid="entitlement-offer-upgrade"]').exists()).toBe(true)
	})

	it('uses consume for Continue and enroll for enrollment actions', async () => {
		const expired = mountOverlay({
			name: 'managed-course',
			title: 'Managed',
			instructors: [],
			membership: { progress: 50 },
			entitlement: { ...denied, allowed: true, offers: [] },
			entitlements: {
				view: { ...denied, allowed: true, offers: [] },
				consume: denied,
			},
		})
		expect(expired.text()).not.toContain('Continue Learning')
		expect(expired.text()).toContain('Upgrade to Max')

		const enrollable = mountOverlay({
			name: 'managed-course',
			title: 'Managed',
			instructors: [],
			entitlement: denied,
			entitlements: {
				view: denied,
				enroll: { ...denied, allowed: true, offers: [] },
			},
		})
		await enrollable.get('[data-testid="managed-course-enroll"]').trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalled()
	})

	it('allows a learner with an external grant to choose enrollment', async () => {
		const wrapper = mountOverlay({
			name: 'managed-course',
			title: 'Managed',
			instructors: [],
			entitlement: { ...denied, allowed: true, offers: [] },
		})
		await wrapper.get('[data-testid="managed-course-enroll"]').trigger('click')
		await flushPromises()
		expect(callMock).toHaveBeenCalledWith('frappe.client.insert', {
			doc: {
				doctype: 'LMS Enrollment',
				course: 'managed-course',
				member: 'student@example.com',
			},
		})
	})

	it('preserves the native paid-course checkout when unmanaged', () => {
		const wrapper = mountOverlay({
			name: 'legacy-paid',
			title: 'Legacy paid',
			paid_course: 1,
			price: '$50',
			instructors: [],
			entitlement: { handled: false, allowed: false, offers: [] },
		})
		expect(wrapper.text()).toContain('Buy this course')
		expect(wrapper.text()).toContain('$50')
	})
})
