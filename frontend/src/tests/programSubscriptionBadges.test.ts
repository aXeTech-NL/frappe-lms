import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { reactive } from 'vue'

vi.stubGlobal('__', (text: string) => text)
window.matchMedia ??= (() => ({
	matches: false,
	addEventListener: () => {},
	removeEventListener: () => {},
})) as unknown as typeof window.matchMedia
String.prototype.format = function (this: string, ...args: unknown[]) {
	return this.replace(/{(\d+)}/g, (_, index) =>
		String(args[Number(index)] ?? ''),
	)
}

const programs = {
	enrolled: [
		{
			name: 'paid-program',
			course_count: 2,
			member_count: 1,
			progress: 0,
			paid_program: 1,
			required_subscription_tier: 'Max',
		},
	],
	published: [],
}

vi.mock('frappe-ui', () => ({
	Badge: { template: '<span><slot /></span>' },
	createResource: () => reactive({ data: programs }),
	TabButtons: {
		props: ['modelValue', 'options'],
		template: '<div />',
	},
}))
vi.mock('@/stores/settings', () => ({
	useSettings: () => ({
		settings: reactive({ data: { enable_subscriptions: 0 } }),
	}),
}))
vi.mock('@/components/ProgressBar.vue', () => ({
	default: { template: '<div />' },
}))
vi.mock('@/components/Layouts/EmptyStateLayout.vue', () => ({
	default: { template: '<div />' },
}))
vi.mock('@/composables/useFormRoute', () => ({ openFormRoute: vi.fn() }))

const router = {
	push: vi.fn(),
}

vi.mock('vue-router', async (importOriginal) => {
	const actual = await importOriginal<typeof import('vue-router')>()
	return { ...actual, useRouter: () => router }
})

const { default: StudentPrograms } =
	await import('@/pages/Programs/StudentPrograms.vue')

describe('Program subscription badges', () => {
	it('hides persisted commerce metadata while subscriptions are disabled', () => {
		const wrapper = mount(StudentPrograms, {
			global: { mocks: { __: (text: string) => text } },
		})
		expect(wrapper.text()).not.toContain('Included in Max')
		expect(wrapper.text()).not.toContain('Available for purchase')
	})
})
