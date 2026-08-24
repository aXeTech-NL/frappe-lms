import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import CourseCardOverlay from '@/components/CourseCardOverlay.vue'

vi.stubGlobal('__', (text: string) => text)
String.prototype.format = function (this: string, ...args: unknown[]) {
	return this.replace(/{(\d+)}/g, (_, index) =>
		String(args[Number(index)] ?? ''),
	)
}

const { callMock } = vi.hoisted(() => ({
	callMock: vi.fn(() => Promise.resolve()),
}))
vi.mock('frappe-ui', () => ({
	Badge: { template: '<span><slot /></span>' },
	Button: {
		inheritAttrs: false,
		template:
			'<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>',
	},
	call: callMock,
	createResource: () => ({ submit: vi.fn() }),
	toast: { success: vi.fn(), warning: vi.fn() },
}))
vi.mock('frappe-ui/frappe', () => ({
	useTelemetry: () => ({ capture: vi.fn() }),
}))
vi.mock('@/components/VideoPreview.vue', () => ({
	default: { template: '<div />' },
}))
vi.mock('@/components/CertificationLinks.vue', () => ({
	default: { template: '<div />' },
}))
vi.mock('@/utils/openExternal', () => ({ openExternal: vi.fn() }))

const router = createRouter({
	history: createMemoryHistory(),
	routes: [
		{
			path: '/lesson/:courseName',
			name: 'Lesson',
			component: { template: '<div />' },
		},
		{
			path: '/billing/:type/:name',
			name: 'Billing',
			component: { template: '<div />' },
		},
		{
			path: '/subscriptions',
			name: 'Subscriptions',
			component: { template: '<div />' },
		},
	],
})

const base = {
	name: 'max-course',
	title: 'Max Course',
	instructors: [],
	paid_course: 1,
	price: '€ 99',
	enable_certification: 0,
}

const render = (
	course: Record<string, any>,
	user: Record<string, any> | null = { name: 'student@test.com' },
) =>
	mount(CourseCardOverlay, {
		props: { course: { data: course } as any },
		global: {
			plugins: [router],
			provide: { $user: { data: user } },
			mocks: { __: (text: string) => text },
		},
	})

describe('Course subscription access CTA precedence', () => {
	beforeEach(() => {
		vi.clearAllMocks()
		;(window as any).read_only_mode = false
	})

	it('preserves feature-off paid course purchase behavior and hides persisted tiers', () => {
		const wrapper = render({ ...base, required_subscription_tier: 'Max' })
		expect(wrapper.find('[data-testid="course-purchase"]').exists()).toBe(true)
		expect(wrapper.find('[data-testid="course-enroll"]').exists()).toBe(false)
		expect(wrapper.text()).not.toContain('Included in Max')
		expect(wrapper.find('[data-testid="course-subscribe"]').exists()).toBe(
			false,
		)
	})

	it('does not continue an expired membership and offers both purchase and upgrade', () => {
		const wrapper = render({
			...base,
			required_subscription_tier: 'Max',
			membership: { progress: 40 },
			access: {
				allowed: false,
				reason: 'purchase_or_subscription_required',
				can_purchase: true,
			},
		})
		expect(wrapper.text()).not.toContain('Continue Learning')
		expect(wrapper.find('[data-testid="course-purchase"]').exists()).toBe(true)
		expect(wrapper.find('[data-testid="course-subscribe"]').exists()).toBe(true)
	})

	it('does not advertise direct purchase for a tier-only course', () => {
		const wrapper = render({
			...base,
			paid_course: 0,
			required_subscription_tier: 'Max',
			access: { allowed: false, reason: 'subscription_required' },
		})
		expect(wrapper.text()).toContain('Requires the Max tier.')
		expect(wrapper.text()).not.toContain('direct purchase')
		expect(wrapper.find('[data-testid="course-purchase"]').exists()).toBe(false)
	})

	it('lets a current tier entitlement enroll before learning', () => {
		const wrapper = render({
			...base,
			paid_course: 0,
			required_subscription_tier: 'Basic',
			access: { allowed: true, source: 'Subscription' },
		})
		expect(wrapper.find('[data-testid="course-enroll"]').exists()).toBe(true)
		expect(wrapper.find('[data-testid="course-subscribe"]').exists()).toBe(
			false,
		)
	})

	it('continues only when membership and current entitlement both exist', () => {
		const wrapper = render({
			...base,
			membership: { progress: 10 },
			access: { allowed: true, source: 'Purchase' },
		})
		expect(wrapper.text()).toContain('Continue Learning')
	})
})
