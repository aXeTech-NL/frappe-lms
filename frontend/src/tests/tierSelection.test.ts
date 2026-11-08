import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive, nextTick } from 'vue'

const mocks = vi.hoisted(() => ({
	resources: {} as Record<string, any>,
	route: null as any,
}))
vi.mock('vue-router', () => ({ useRoute: () => mocks.route }))
vi.mock('frappe-ui', () => ({
	Button: {
		props: ['route', 'disabled'],
		template: '<button :disabled="disabled"><slot /></button>',
	},
	Badge: { template: '<span><slot /></span>' },
	usePageMeta: vi.fn(),
	createResource: (options: any) => {
		const resource = mocks.resources[options.url.split('.').pop()]
		resource.onSuccess = options.onSuccess
		return resource
	},
}))
vi.mock('@/components/Layouts/PageHeader.vue', () => ({
	default: { template: '<header><slot name="actions" /></header>' },
}))
vi.mock('@/components/Layouts/PageBody.vue', () => ({
	default: { template: '<main><slot /></main>' },
}))
import TierSelection from '@/commerce/TierSelection.vue'
import MyAccess from '@/commerce/MyAccess.vue'

const globals = (user: any = { name: 'student@example.test' }) => ({
	mocks: { __: globalThis.__ },
	provide: { $user: { data: user } },
})
function resource(data: any) {
	const result = reactive({
		data,
		error: null as any,
		loading: false,
		onSuccess: undefined as any,
		abort: vi.fn(),
		submit: vi.fn(() => {
			if (result.error) return Promise.reject(result.error)
			result.onSuccess?.(result.data)
			return Promise.resolve(result.data)
		}),
		fetch: vi.fn(() => result.submit()),
	})
	return result
}
beforeEach(() => {
	mocks.route = reactive({ query: {} })
	mocks.resources.get_tier_options = resource({
		commerce_enabled: true,
		current_tier: 'Basic',
		course: null,
		subscription_checkout_available: false,
		tiers: [
			{
				name: 'Basic',
				rank: 10,
				current: true,
				description: '<img src=x onerror=alert(1)>',
				meets_course_tier: null,
			},
			{ name: 'Max', rank: 20, current: false, meets_course_tier: null },
		],
	})
	mocks.resources.get_my_access = resource({
		commerce_enabled: true,
		grants: [],
		has_more: false,
	})
})

describe('tier choices in the native LMS', () => {
	it('links My access to tier selection even without a grant', async () => {
		const wrapper = mount(MyAccess, { global: globals() })
		await flushPromises()
		expect(wrapper.find('[data-testid="tier-upgrade-button"]').exists()).toBe(
			true,
		)
		expect(
			wrapper
				.findComponent('[data-testid="tier-upgrade-button"]')
				.props('route'),
		).toEqual({ name: 'CommerceTiers' })
	})
	it.each([false, true])(
		'hides the upgrade entry when disabled or anonymous: %s',
		(anonymous) => {
			if (!anonymous)
				mocks.resources.get_my_access.data.commerce_enabled = false
			const wrapper = mount(MyAccess, {
				global: globals(anonymous ? null : {}),
			})
			expect(wrapper.find('[data-testid="tier-upgrade-button"]').exists()).toBe(
				false,
			)
		},
	)
	it('shows effective access without calling a manual grant a subscription; escapes descriptions', () => {
		const wrapper = mount(TierSelection, { global: globals() })
		expect(wrapper.text()).toContain('Current tier access: Basic')
		expect(wrapper.find('img').exists()).toBe(false)
		expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')
		expect(wrapper.text()).toContain(
			'Paid tier upgrades are not available yet.',
		)
		expect(wrapper.text()).not.toContain('€')
	})
	it('selects another tier locally, but never creates a payment or changes access', async () => {
		const wrapper = mount(TierSelection, { global: globals() })
		const button = wrapper
			.findAll('button')
			.find((button) => button.text() === 'Select Max')!
		await button.trigger('click')
		expect(button.attributes('aria-pressed')).toBe('true')
		expect(wrapper.text()).toContain('Your selection: Max')
		expect(wrapper.text()).toContain('Current tier access: Basic')
		const payment = wrapper
			.findAll('button')
			.find((button) => button.text() === 'Payment is not available yet')!
		expect(payment.attributes('disabled')).toBeDefined()
		expect(
			mocks.resources.get_tier_options.submit,
		).toHaveBeenCalledExactlyOnceWith({})
		expect(mocks.resources.get_my_access.submit).not.toHaveBeenCalled()
	})
	it('checks course requirements from the server, not URL claims', async () => {
		mocks.route.query = {
			course: 'safety',
			required_tier: 'Basic',
			tier: 'Max',
			status: 'paid',
		}
		Object.assign(mocks.resources.get_tier_options.data, {
			course: { name: 'safety', title: 'Safety', required_tier: 'Max' },
		})
		mocks.resources.get_tier_options.data.tiers[0].meets_course_tier = false
		mocks.resources.get_tier_options.data.tiers[1].meets_course_tier = true
		const wrapper = mount(TierSelection, { global: globals() })
		expect(wrapper.text()).toContain('Required tier: Max or higher')
		expect(
			wrapper
				.findAll('button')
				.find((button) => button.text() === 'Select Basic')!
				.attributes('disabled'),
		).toBeDefined()
		expect(wrapper.findAll('[aria-pressed="true"]')).toHaveLength(0)
		expect(
			mocks.resources.get_tier_options.submit,
		).toHaveBeenCalledExactlyOnceWith({ course: 'safety' })
		await wrapper
			.findAll('button')
			.find((button) => button.text() === 'Select Max')!
			.trigger('click')
		mocks.route.query = {}
		await nextTick()
		expect(wrapper.findAll('[aria-pressed="true"]')).toHaveLength(0)
		expect(mocks.resources.get_tier_options.submit).toHaveBeenLastCalledWith({})
	})
	it('does not query or expose tiers to anonymous viewers', () => {
		const wrapper = mount(TierSelection, { global: globals(null) })
		expect(wrapper.text()).toContain('Please log in')
		expect(wrapper.findAll('article')).toHaveLength(0)
		expect(mocks.resources.get_tier_options.submit).not.toHaveBeenCalled()
	})
	it('keeps native fallback when Commerce is disabled', () => {
		mocks.resources.get_tier_options.data.commerce_enabled = false
		const wrapper = mount(TierSelection, { global: globals() })
		expect(wrapper.text()).toContain('Native LMS access applies')
		expect(wrapper.findAll('article')).toHaveLength(0)
	})
	it('shows loading instead of stale choices', () => {
		mocks.resources.get_tier_options.loading = true
		const wrapper = mount(TierSelection, { global: globals() })
		expect(wrapper.text()).toContain('Loading tiers...')
		expect(wrapper.findAll('article')).toHaveLength(0)
	})
	it('handles an empty enabled tier list', () => {
		mocks.resources.get_tier_options.data.tiers = []
		const wrapper = mount(TierSelection, { global: globals() })
		expect(wrapper.text()).toContain('No tiers are available')
		expect(wrapper.findAll('article')).toHaveLength(0)
	})
	it('catches initial fetch and retry rejection and hides stale choices', async () => {
		mocks.resources.get_tier_options.error = new Error('unavailable')
		const wrapper = mount(TierSelection, { global: globals() })
		await flushPromises()
		expect(wrapper.find('[role="alert"]').text()).toContain(
			'Unable to load tiers',
		)
		await wrapper
			.findAll('button')
			.find((button) => button.text() === 'Try again')!
			.trigger('click')
		await flushPromises()
		expect(wrapper.findAll('article')).toHaveLength(0)
	})
	it('catches My access initial load and refresh rejection', async () => {
		mocks.resources.get_my_access.error = new Error('unavailable')
		const wrapper = mount(MyAccess, { global: globals() })
		await flushPromises()
		expect(wrapper.find('[role="alert"]').text()).toContain(
			'Unable to load your access',
		)
		await wrapper
			.findAll('button')
			.find((button) => button.text() === 'Refresh')!
			.trigger('click')
		await flushPromises()
	})
})
