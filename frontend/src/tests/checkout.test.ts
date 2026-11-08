import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
	resources: {} as Record<string, any>,
	replace: vi.fn(),
}))
vi.mock('vue-router', () => ({
	useRoute: () => ({
		params: { offering: 'COF-1', order: 'order-1' },
		query: { status: 'paid' },
	}),
	useRouter: () => ({ replace: mocks.replace }),
}))
vi.mock('frappe-ui', () => ({
	Button: {
		props: ['disabled', 'route'],
		template: '<button :disabled="disabled"><slot /></button>',
	},
	Checkbox: {
		props: ['modelValue', 'label'],
		emits: ['update:modelValue'],
		template:
			'<label><input type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" />{{ label }}</label>',
	},
	usePageMeta: vi.fn(),
	createResource: (options: any) => {
		const key = options.url.split('.').pop()
		const resource = mocks.resources[key]
		resource.onSuccess = options.onSuccess
		if (options.auto && resource.data && options.onSuccess)
			options.onSuccess(resource.data)
		return resource
	},
}))
vi.mock('@/components/Layouts/PageHeader.vue', () => ({
	default: { template: '<header />' },
}))
vi.mock('@/components/Layouts/PageBody.vue', () => ({
	default: { template: '<main><slot /></main>' },
}))
import Checkout from '@/commerce/Checkout.vue'
import CheckoutReturn from '@/commerce/CheckoutReturn.vue'

const globals = { mocks: { __: (value: string) => value } }
beforeEach(() => {
	mocks.replace.mockReset().mockResolvedValue(undefined)
	for (const key of [
		'get_quote',
		'start_checkout',
		'get_order',
		'refresh_order',
	]) {
		mocks.resources[key] = {
			data: null,
			loading: false,
			error: null,
			fetch: vi.fn(() => {
				const resource = mocks.resources[key]
				if (resource.error) return Promise.reject(resource.error)
				resource.onSuccess?.(resource.data)
				return Promise.resolve(resource.data)
			}),
			submit: vi
				.fn()
				.mockResolvedValue({ name: 'order-1', checkout_url: null }),
		}
	}
	mocks.resources.get_quote.data = {
		title: 'Native course',
		offering: 'COF-1',
		course: 'course-1',
		amount: '25.00',
		currency: 'EUR',
		mode: 'test',
		terms_url: '/terms/v1',
		quote_token: 'server-quote',
	}
	mocks.resources.get_order.data = {
		name: 'order-1',
		title: 'Native course',
		course: 'course-1',
		amount: '25.00',
		currency: 'EUR',
		status: 'open',
		access_granted: false,
		mode: 'test',
	}
	document.documentElement.lang = 'en'
})

describe('native Commerce checkout', () => {
	it('shows total, one-time scope and explicit test-mode warning', () => {
		const wrapper = mount(Checkout, { global: globals })
		expect(wrapper.text()).toContain('€25.00')
		expect(wrapper.text()).toContain('No real money')
		expect(wrapper.text()).toContain('does not start a subscription')
		expect(wrapper.findAll('button')[0].attributes('disabled')).toBeDefined()
	})
	it('submits only offering, quote version and consent, not client money or member', async () => {
		const wrapper = mount(Checkout, { global: globals })
		await wrapper.find('input').setValue(true)
		await wrapper.findAll('button')[0].trigger('click')
		await flushPromises()
		expect(mocks.resources.start_checkout.submit).toHaveBeenCalledWith({
			offering: 'COF-1',
			quote_token: 'server-quote',
			accept_terms: true,
		})
		expect(mocks.replace).toHaveBeenCalledWith({
			name: 'CommerceCheckoutReturn',
			params: { order: 'order-1' },
		})
	})
	it('offers recovery instead of a second checkout when an order already exists', () => {
		mocks.resources.get_quote.data.pending_order = 'order-1'
		const wrapper = mount(Checkout, { global: globals })
		expect(wrapper.text()).toContain('Continue existing checkout')
		expect(wrapper.find('input').exists()).toBe(false)
		expect(mocks.resources.start_checkout.submit).not.toHaveBeenCalled()
	})
	it('blocks unsafe terms links', () => {
		mocks.resources.get_quote.data.terms_url = 'javascript:alert(1)'
		const wrapper = mount(Checkout, { global: globals })
		expect(wrapper.find('a').exists()).toBe(false)
		expect(wrapper.findAll('button')[0].attributes('disabled')).toBeDefined()
	})
	it('does not treat a browser return or query status as paid', () => {
		const wrapper = mount(CheckoutReturn, { global: globals })
		expect(wrapper.text()).toContain('awaiting confirmation')
		expect(wrapper.text()).not.toContain('Payment confirmed.')
		expect(mocks.resources.refresh_order.submit).toHaveBeenCalledWith({
			order: 'order-1',
		})
	})
	it('shows confirmed access only from the order API', () => {
		mocks.resources.get_order.data = {
			...mocks.resources.get_order.data,
			status: 'paid',
			access_granted: true,
		}
		const wrapper = mount(CheckoutReturn, { global: globals })
		expect(wrapper.text()).toContain('Open the course to enroll')
	})
	it('uses the native shell and exposes the active checkout step', () => {
		const wrapper = mount(Checkout, { global: globals })
		expect(wrapper.find('header').exists()).toBe(true)
		expect(wrapper.find('main').exists()).toBe(true)
		expect(wrapper.find('[aria-current="step"]').text()).toContain('Review')
		expect(wrapper.find('aside').attributes('aria-label')).toBe('Your order')
	})
	it('formats Dutch prices without discarding cents', () => {
		document.documentElement.lang = 'nl'
		mocks.resources.get_quote.data.amount = '29.95'
		const wrapper = mount(Checkout, { global: globals })
		expect(wrapper.find('dd').text().replace(/\s/g, ' ')).toBe('€ 29,95')
	})
	it('places the order summary before consent in reading order', () => {
		const wrapper = mount(Checkout, { global: globals })
		expect(
			wrapper.find('.commerce-checkout__grid').element.firstElementChild
				?.tagName,
		).toBe('ASIDE')
		expect(wrapper.find('aside').attributes('aria-label')).toBe('Your order')
	})
	it('handles rejected initial quote loading without an unhandled rejection', async () => {
		mocks.resources.get_quote.error = new Error('Checkout is disabled')
		const wrapper = mount(Checkout, { global: globals })
		await flushPromises()
		expect(mocks.resources.get_quote.fetch).toHaveBeenCalledTimes(1)
		expect(wrapper.find('[role="alert"]').exists()).toBe(true)
		expect(mocks.resources.start_checkout.submit).not.toHaveBeenCalled()
	})
	it('handles rejected initial order loading without claiming access', async () => {
		mocks.resources.get_order.error = new Error('Order not accessible')
		const wrapper = mount(CheckoutReturn, { global: globals })
		await flushPromises()
		expect(mocks.resources.get_order.fetch).toHaveBeenCalledTimes(1)
		expect(wrapper.find('[role="alert"]').exists()).toBe(true)
		expect(wrapper.text()).toContain('Back to courses')
		expect(wrapper.text()).not.toContain('Payment confirmed')
		expect(mocks.resources.refresh_order.submit).not.toHaveBeenCalled()
	})
	it('provides a way back when checkout cannot be loaded', () => {
		mocks.resources.get_quote.error = new Error('Unavailable')
		const wrapper = mount(Checkout, { global: globals })
		expect(wrapper.find('[role="alert"]').text()).toContain('unavailable')
		expect(wrapper.text()).toContain('Back to courses')
		expect(wrapper.find('input').exists()).toBe(false)
		expect(wrapper.find('aside').exists()).toBe(false)
	})
	it('does not claim payment or access while the quote is loading', () => {
		mocks.resources.get_quote.loading = true
		const wrapper = mount(Checkout, { global: globals })
		expect(wrapper.find('[role="status"]').text()).toContain('Loading checkout')
		expect(wrapper.find('input').exists()).toBe(false)
		expect(wrapper.find('aside').exists()).toBe(false)
	})
	it('does not show a test warning for a live quote', () => {
		mocks.resources.get_quote.data.mode = 'live'
		const wrapper = mount(Checkout, { global: globals })
		expect(wrapper.text()).not.toContain('No real money')
	})
	it.each(['refunded', 'partially_charged_back', 'charged_back'])(
		'shows a reversal without offering another payment for %s',
		(status) => {
			mocks.resources.get_order.data = {
				...mocks.resources.get_order.data,
				status,
				checkout_url: 'https://www.mollie.com/checkout/test',
			}
			const wrapper = mount(CheckoutReturn, { global: globals })
			expect(wrapper.text()).toContain(
				'Access from this order has been withdrawn',
			)
			expect(wrapper.text()).not.toContain('Continue existing checkout')
			expect(wrapper.find('[aria-current="step"]').text()).toContain('Payment')
		},
	)
	it('offers the course, not a new charge, for confirmed access', () => {
		mocks.resources.get_order.data = {
			...mocks.resources.get_order.data,
			status: 'paid',
			access_granted: true,
		}
		const wrapper = mount(CheckoutReturn, { global: globals })
		expect(wrapper.text()).toContain('Go to course')
		expect(wrapper.text()).not.toContain('Continue existing checkout')
		expect(wrapper.find('[aria-current="step"]').text()).toContain('Access')
	})
	it('handles explicit refresh failures without an unhandled rejection', async () => {
		mocks.resources.get_order.data.status = 'creating'
		mocks.resources.refresh_order.submit.mockRejectedValue(
			new Error('Unavailable'),
		)
		const wrapper = mount(CheckoutReturn, { global: globals })
		await wrapper
			.findAll('button')
			.find((button) => button.text() === 'Check payment status')!
			.trigger('click')
		await flushPromises()
		expect(mocks.resources.refresh_order.submit).toHaveBeenCalledTimes(1)
	})
	it('does not automatically retry uncertain payment creation on a page view', () => {
		mocks.resources.get_order.data.status = 'creating'
		mount(CheckoutReturn, { global: globals })
		expect(mocks.resources.refresh_order.submit).not.toHaveBeenCalled()
	})
	it.each(['failed', 'canceled', 'expired'])(
		'does not claim access after %s',
		(status) => {
			mocks.resources.get_order.data.status = status
			const wrapper = mount(CheckoutReturn, { global: globals })
			expect(wrapper.text()).toContain('Payment was not completed')
		},
	)
})
