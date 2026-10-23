import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { commerceDenied, safeActionUrl } from '@/commerce/access'
import { commerceLinks, commerceRoutes } from '@/commerce/navigation'

vi.mock('frappe-ui', () => ({
	Badge: { template: '<span><slot /></span>' },
	Tooltip: { template: '<span><slot /></span>' },
	Button: { template: '<button><slot /></button>' },
}))
vi.mock('@/stores/session', () => ({ sessionStore: () => ({ user: null }) }))
vi.mock('@/utils', () => ({ formatAmount: String, formatRating: String }))
vi.mock('@/components/UserAvatar.vue', () => ({ default: { template: '<span />' } }))
vi.mock('@/components/CourseInstructors.vue', () => ({ default: { template: '<span />' } }))
import CourseCard from '@/components/CourseCard.vue'
import CommerceNotice from '@/commerce/CommerceNotice.vue'

const denied = { handled: true, allowed: false, reason: 'tier_required', badge: { label: 'Max' }, price_label: 'Included in Max', offers: [] }

describe('internal Commerce UI', () => {
	it('keeps unmanaged and disabled data native, and fails closed on malformed managed decisions', () => {
		expect(commerceDenied(undefined)).toBe(false)
		expect(commerceDenied({ handled: false, allowed: false })).toBe(false)
		expect(commerceDenied(denied)).toBe(true)
		expect(commerceDenied({ handled: true } as never)).toBe(true)
		expect(commerceDenied({ ...denied, allowed: true })).toBe(false)
	})
	it.each(['javascript:alert(1)', '//evil.test', '/\\evil.test', 'http://evil.test', 'https://user:pass@example.com', '/bad\nurl'])('rejects unsafe action URLs: %s', url => {
		expect(safeActionUrl(url)).toBeNull()
	})
	it('allows local paths and HTTPS', () => {
		expect(safeActionUrl('/lms/access')).toBe('/lms/access')
		expect(safeActionUrl('https://example.com/plans')).toBe('https://example.com/plans')
	})
	it('adds access and management navigation conditionally, without replacing course routes', () => {
		expect(commerceLinks({}, {}).items).toEqual([])
		expect(commerceLinks({ commerce_enabled: true }, null).items).toEqual([])
		expect(commerceLinks({ commerce_enabled: true }, {}).items[0].to).toBe('CommerceAccess')
		expect(commerceLinks({ can_manage_commerce: true }, {}).items[0].to).toBe('desk/commerce')
		expect(commerceRoutes.map(route => route.path)).toEqual(['/access'])
	})
	it('enriches the actual native CourseCard rather than a replacement card', () => {
		const wrapper = mount(CourseCard, {
			props: { course: { name: 'course', title: 'Original course', instructors: [], lessons: 4, short_introduction: 'Original description', commerce: denied } },
			global: { mocks: { __: globalThis.__ } },
		})
		expect(wrapper.text()).toContain('Original course')
		expect(wrapper.text()).toContain('Original description')
		expect(wrapper.text()).toContain('Included in Max')
	})
	it('shows unavailable instead of inventing a checkout, and ignores unsafe links', () => {
		const wrapper = mount(CommerceNotice, {
			props: { access: { ...denied, offers: [{ kind: 'purchase', label: 'Bad', url: 'javascript:alert(1)' }] } },
			global: { mocks: { __: globalThis.__ } },
		})
		expect(wrapper.text()).toContain('Currently unavailable')
		expect(wrapper.findAll('button')).toHaveLength(0)
	})
	it('does not show a commerce warning for allowed or unmanaged courses', () => {
		for (const access of [undefined, { ...denied, allowed: true }]) {
			const wrapper = mount(CommerceNotice, { props: { access }, global: { mocks: { __: globalThis.__ } } })
			expect(wrapper.find('[data-testid="commerce-notice"]').exists()).toBe(false)
		}
	})
})
