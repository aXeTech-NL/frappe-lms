import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import Subscriptions from '@/pages/Subscriptions.vue'

vi.stubGlobal('__', (text: string) => text)
String.prototype.format = function (this: string, ...args: unknown[]) {
	return this.replace(/{(\d+)}/g, (_, index) =>
		String(args[Number(index)] ?? ''),
	)
}

const { catalog, cancelSubmit } = vi.hoisted(() => ({
	catalog: {
		data: null as any,
		loading: false,
		fetch: vi.fn(),
		reload: vi.fn(),
	},
	cancelSubmit: vi.fn(),
}))

vi.mock('frappe-ui', () => ({
	Badge: { template: '<span><slot /></span>' },
	Button: {
		inheritAttrs: false,
		props: ['disabled', 'loading'],
		template:
			'<button v-bind="$attrs" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
	},
	createResource: (options: { url: string }) => {
		if (options.url.includes('get_subscription_catalog')) return catalog
		return { loading: false, submit: cancelSubmit }
	},
	toast: { success: vi.fn(), error: vi.fn() },
	usePageMeta: vi.fn(),
}))
vi.mock('@/stores/session', () => ({
	sessionStore: () => ({ brand: { favicon: '' } }),
}))

const router = createRouter({
	history: createMemoryHistory(),
	routes: [
		{ path: '/subscriptions', name: 'Subscriptions', component: Subscriptions },
		{
			path: '/billing/:type/:name',
			name: 'Billing',
			component: { template: '<div>billing</div>' },
		},
	],
})

const data = {
	enabled: true,
	tiers: [
		{
			name: 'Basic',
			tier_name: 'Basic',
			rank: 1,
			description: 'Core catalogue',
		},
		{ name: 'Max', tier_name: 'Max', rank: 2, description: 'Everything' },
	],
	plans: [
		{
			name: 'BASIC-M',
			plan_name: 'Basic Monthly',
			tier: 'Basic',
			tier_rank: 1,
			price: '€ 10',
			billing_interval: 'Month',
			interval_count: 1,
		},
		{
			name: 'MAX-M',
			plan_name: 'Max Monthly',
			tier: 'Max',
			tier_rank: 2,
			price: '€ 20',
			billing_interval: 'Month',
			interval_count: 1,
		},
	],
	current_subscription: {
		name: 'SUB-1',
		tier: 'Basic',
		status: 'Active',
		current_period_end: '2026-09-30',
		cancel_at_period_end: 0,
	},
}

const render = async () => {
	catalog.data = data
	const wrapper = mount(Subscriptions, {
		global: {
			plugins: [router],
			provide: { $user: { data: { name: 'student@test.com' } } },
			stubs: {
				PageHeader: { template: '<div />' },
				PageBody: { template: '<main><slot /></main>' },
			},
			mocks: { __: (text: string) => text },
		},
	})
	await flushPromises()
	return wrapper
}

describe('Subscriptions page', () => {
	beforeEach(async () => {
		vi.clearAllMocks()
		window.confirm = vi.fn(() => true)
		;(window as Window & { read_only_mode?: boolean }).read_only_mode = false
		data.current_subscription = {
			name: 'SUB-1',
			plan: 'BASIC-M',
			tier: 'Basic',
			status: 'Active',
			current_period_end: '2026-09-30',
			cancel_at_period_end: 0,
		}
		await router.push('/subscriptions')
	})

	it('shows current access, includes lower tiers, and routes upgrades to checkout', async () => {
		const wrapper = await render()
		expect(wrapper.find('[data-testid="current-subscription"]').exists()).toBe(
			true,
		)
		expect(
			wrapper
				.find('[data-testid="select-plan-BASIC-M"]')
				.attributes('disabled'),
		).toBeDefined()
		await wrapper.find('[data-testid="select-plan-MAX-M"]').trigger('click')
		await flushPromises()
		expect(router.currentRoute.value.name).toBe('Billing')
		expect(router.currentRoute.value.params).toMatchObject({
			type: 'subscription',
			name: 'MAX-M',
		})
	})

	it('requests cancellation at period end through the authorized endpoint', async () => {
		const wrapper = await render()
		await wrapper.find('[data-testid="cancel-at-period-end"]').trigger('click')
		expect(cancelSubmit).toHaveBeenCalledWith(
			{ subscription: 'SUB-1', at_period_end: true },
			expect.any(Object),
		)
	})

	it('lets a past-due member retry only the same plan or upgrade', async () => {
		data.current_subscription = {
			...data.current_subscription,
			plan: 'BASIC-M',
			status: 'Past Due',
		}
		const wrapper = await render()
		expect(
			wrapper.find('[data-testid="select-plan-BASIC-M"]').text(),
		).toContain('Retry payment')
		expect(
			wrapper
				.find('[data-testid="select-plan-BASIC-M"]')
				.attributes('disabled'),
		).toBeUndefined()
		expect(
			wrapper.find('[data-testid="select-plan-MAX-M"]').attributes('disabled'),
		).toBeUndefined()
	})

	it('suppresses cancellation and checkout in read-only mode', async () => {
		;(window as Window & { read_only_mode?: boolean }).read_only_mode = true
		const wrapper = await render()
		expect(wrapper.find('[data-testid="cancel-at-period-end"]').exists()).toBe(
			false,
		)
		expect(
			wrapper.find('[data-testid="select-plan-MAX-M"]').attributes('disabled'),
		).toBeDefined()
	})
})
