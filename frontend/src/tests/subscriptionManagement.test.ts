import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import SubscriptionManagement from '@/components/Settings/SubscriptionManagement.vue'

vi.stubGlobal('__', (text: string) => text)
String.prototype.format = function (this: string, ...args: unknown[]) {
	return this.replace(/{(\d+)}/g, (_, index) =>
		String(args[Number(index)] ?? ''),
	)
}

const { resources, toast } = vi.hoisted(() => ({
	resources: [] as any[],
	toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('frappe-ui', () => ({
	Button: {
		inheritAttrs: false,
		props: ['loading'],
		template:
			'<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>',
	},
	Dialog: {
		props: ['open', 'title'],
		emits: ['update:open'],
		template: '<div v-if="open"><slot /><slot name="actions" /></div>',
	},
	FormControl: {
		props: ['modelValue', 'label', 'type'],
		emits: ['update:modelValue'],
		template: '<input />',
	},
	createListResource: (options: any) => {
		const resource = {
			options,
			data: [],
			reload: vi.fn(() => Promise.resolve()),
			insert: {
				submit: vi.fn((_payload, handlers) => {
					handlers?.onSuccess?.()
					return Promise.resolve()
				}),
			},
			setValue: {
				submit: vi.fn((_payload, handlers) => {
					handlers?.onSuccess?.()
					return Promise.resolve()
				}),
			},
			delete: { submit: vi.fn() },
		}
		resources.push(resource)
		return resource
	},
	toast,
}))
vi.mock('@/components/Controls/Link.vue', () => ({
	default: { template: '<div />' },
}))

const render = () =>
	mount(SubscriptionManagement, {
		global: { mocks: { __: (text: string) => text } },
	})

beforeEach(() => {
	resources.length = 0
	vi.clearAllMocks()
})

describe('SubscriptionManagement', () => {
	it('rejects invalid tier and plan values before resource submission', async () => {
		const wrapper = render()
		const vm = wrapper.vm as any
		vm.newTier()
		vm.tierForm.tier_name = ''
		vm.tierForm.rank = 0
		vm.saveTier()
		vm.newPlan()
		vm.planForm.plan_name = 'Monthly'
		vm.planForm.tier = 'Basic'
		vm.planForm.currency = 'EUR'
		vm.planForm.interval_count = 1
		vm.planForm.amount = 0
		vm.savePlan()
		await flushPromises()

		expect(resources[0].insert.submit).not.toHaveBeenCalled()
		expect(resources[1].insert.submit).not.toHaveBeenCalled()
		expect(toast.error).toHaveBeenCalledWith('Tier name is required.')
		expect(toast.error).toHaveBeenCalledWith(
			'Amount must be greater than zero.',
		)
	})

	it('normalizes valid create payloads and resets loading after success', async () => {
		const wrapper = render()
		const vm = wrapper.vm as any
		vm.newTier()
		vm.tierForm.tier_name = 'Basic'
		vm.tierForm.rank = 1
		vm.tierForm.enabled = true
		vm.saveTier()
		await flushPromises()

		expect(resources[0].insert.submit).toHaveBeenCalledWith(
			expect.objectContaining({
				tier_name: 'Basic',
				rank: 1,
				enabled: 1,
			}),
			expect.any(Object),
		)
		expect(resources[0].insert.submit.mock.calls[0][0]).not.toHaveProperty(
			'name',
		)
		expect(vm.saving).toBe(false)
	})
})
