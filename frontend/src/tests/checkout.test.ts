import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({ resources: {} as Record<string, any>, replace: vi.fn() }))
vi.mock('vue-router', () => ({
	useRoute: () => ({ params: { offering: 'COF-1', order: 'order-1' }, query: { status: 'paid' } }),
	useRouter: () => ({ replace: mocks.replace }),
}))
vi.mock('frappe-ui', () => ({
	Button: { props: ['disabled', 'route'], template: '<button :disabled="disabled"><slot /></button>' },
	Checkbox: { props: ['modelValue', 'label'], emits: ['update:modelValue'], template: '<label><input type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" />{{ label }}</label>' },
	usePageMeta: vi.fn(),
	createResource: (options: any) => {
		const key = options.url.split('.').pop()
		const resource = mocks.resources[key]
		resource.onSuccess = options.onSuccess
		if (options.auto && resource.data && options.onSuccess) options.onSuccess(resource.data)
		return resource
	},
}))
vi.mock('@/components/Layouts/PageHeader.vue', () => ({ default: { template: '<header />' } }))
vi.mock('@/components/Layouts/PageBody.vue', () => ({ default: { template: '<main><slot /></main>' } }))
import Checkout from '@/commerce/Checkout.vue'
import CheckoutReturn from '@/commerce/CheckoutReturn.vue'

const globals = { mocks: { __: (value: string) => value } }
beforeEach(() => {
	mocks.replace.mockReset().mockResolvedValue(undefined)
	for (const key of ['get_quote', 'start_checkout', 'get_order', 'refresh_order']) {
		mocks.resources[key] = { data: null, loading: false, error: null, submit: vi.fn().mockResolvedValue({ name: 'order-1', checkout_url: null }) }
	}
	mocks.resources.get_quote.data = {
		title: 'Native course', offering: 'COF-1', course: 'course-1', amount: '25.00', currency: 'EUR',
		mode: 'test', terms_url: '/terms/v1', quote_token: 'server-quote',
	}
	mocks.resources.get_order.data = { name: 'order-1', title: 'Native course', course: 'course-1', status: 'open', access_granted: false, mode: 'test' }
})

describe('native Commerce checkout', () => {
	it('shows total, one-time scope and explicit test-mode warning', () => {
		const wrapper = mount(Checkout, { global: globals })
		expect(wrapper.text()).toContain('EUR 25.00')
		expect(wrapper.text()).toContain('No real money')
		expect(wrapper.text()).toContain('does not start a subscription')
		expect(wrapper.findAll('button')[0].attributes('disabled')).toBeDefined()
	})
	it('submits only offering, quote version and consent, not client money or member', async () => {
		const wrapper = mount(Checkout, { global: globals })
		await wrapper.find('input').setValue(true)
		await wrapper.findAll('button')[0].trigger('click')
		await flushPromises()
		expect(mocks.resources.start_checkout.submit).toHaveBeenCalledWith({ offering: 'COF-1', quote_token: 'server-quote', accept_terms: true })
		expect(mocks.replace).toHaveBeenCalledWith({ name: 'CommerceCheckoutReturn', params: { order: 'order-1' } })
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
		expect(mocks.resources.refresh_order.submit).toHaveBeenCalledWith({ order: 'order-1' })
	})
	it('shows confirmed access only from the order API', () => {
		mocks.resources.get_order.data = { ...mocks.resources.get_order.data, status: 'paid', access_granted: true }
		const wrapper = mount(CheckoutReturn, { global: globals })
		expect(wrapper.text()).toContain('Open the course to enroll')
	})
	it('does not automatically retry uncertain payment creation on a page view', () => {
		mocks.resources.get_order.data.status = 'creating'
		mount(CheckoutReturn, { global: globals })
		expect(mocks.resources.refresh_order.submit).not.toHaveBeenCalled()
	})
	it.each(['failed', 'canceled', 'expired'])('does not claim access after %s', status => {
		mocks.resources.get_order.data.status = status
		const wrapper = mount(CheckoutReturn, { global: globals })
		expect(wrapper.text()).toContain('Payment was not completed')
	})
})
