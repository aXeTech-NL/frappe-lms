<template>
	<PageHeader
		:breadcrumbs="[
			{ label: __('My access'), route: { name: 'CommerceAccess' } },
		]"
	>
		<template #actions
			><Button :loading="access.loading" @click="reload">{{
				__('Refresh')
			}}</Button></template
		>
	</PageHeader>
	<PageBody :title="__('My access')">
		<div class="px-5 pb-5 space-y-5">
			<p class="text-p-sm text-ink-gray-6">
				{{
					__(
						'Your tiers and course access are shown here. Automatic subscriptions and billing are not connected yet.',
					)
				}}
			</p>
			<Button
				v-if="user?.data && access.data?.commerce_enabled"
				variant="solid"
				:route="{ name: 'CommerceTiers' }"
				data-testid="tier-upgrade-button"
			>
				{{ __('Upgrade or change tier') }}
			</Button>
			<p v-if="!user?.data" role="status">
				{{ __('Please log in to view your access.') }}
			</p>
			<p v-else-if="access.error" role="alert">
				{{ __('Unable to load your access. Please try again.') }}
			</p>
			<p v-else-if="access.data && !access.data.commerce_enabled" role="status">
				{{ __('Commerce is disabled. Native LMS access applies.') }}
			</p>
			<p v-else-if="access.data && !grants.length" role="status">
				{{ __('No tier or course grants have been assigned to you.') }}
			</p>
			<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
				<div
					v-for="grant in grants"
					:key="grant.name"
					class="border border-outline-gray-1 rounded-5 p-5 space-y-3 bg-surface-elevation-1"
				>
					<div class="font-semibold text-ink-gray-9">
						{{ grant.tier || grant.target_name }}
					</div>
					<Badge :theme="grant.status === 'Active' ? 'green' : 'gray'">{{
						__(grant.status)
					}}</Badge>
					<p v-if="grant.starts_on" class="text-p-sm text-ink-gray-6">
						{{ __('From') }}: {{ grant.starts_on }}
					</p>
					<p v-if="grant.ends_on" class="text-p-sm text-ink-gray-6">
						{{ __('Until') }}: {{ grant.ends_on }}
					</p>
					<Button
						v-if="grant.target_doctype === 'LMS Course'"
						:route="{
							name: 'CourseDetail',
							params: { courseName: grant.target_name },
						}"
						>{{ __('View course') }}</Button
					>
				</div>
			</div>
			<Button
				v-if="access.data?.has_more"
				:loading="access.loading"
				@click="loadMore"
				>{{ __('Load More') }}</Button
			>
		</div>
	</PageBody>
</template>

<script setup>
import { inject, ref } from 'vue'
import { Badge, Button, createResource, usePageMeta } from 'frappe-ui'
import PageHeader from '@/components/Layouts/PageHeader.vue'
import PageBody from '@/components/Layouts/PageBody.vue'

const user = inject('$user')
const grants = ref([])
const access = createResource({
	url: 'lms.lms_commerce.api.get_my_access',
	params: { start: 0 },
	onSuccess(data) {
		grants.value.push(...data.grants)
	},
})
if (user?.data) access.fetch().catch(() => {})
function reload() {
	if (!user?.data) return
	access.abort()
	grants.value = []
	access.submit({ start: 0 }).catch(() => {})
}
function loadMore() {
	if (access.loading || !access.data?.has_more) return
	access.submit({ start: access.data.next_start }).catch(() => {})
}
usePageMeta(() => ({ title: __('My access') }))
</script>
