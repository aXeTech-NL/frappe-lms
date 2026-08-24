<template>
	<PageHeader :breadcrumbs="breadcrumbs" />
	<PageBody :title="__('Subscriptions')">
		<div class="px-5 pb-10 max-w-6xl mx-auto w-full">
			<div v-if="!user.data?.name" class="rounded-md border p-6 text-center">
				<p class="text-ink-gray-7 mb-4">
					{{ __('Please log in to view subscription plans.') }}
				</p>
				<Button variant="solid" @click="login">{{ __('Log in') }}</Button>
			</div>
			<div v-else-if="catalog.loading && !catalog.data" class="text-ink-gray-6">
				{{ __('Loading subscription plans...') }}
			</div>
			<div
				v-else-if="catalog.data && !catalog.data.enabled"
				class="rounded-md border p-6"
			>
				{{ __('Subscriptions are not enabled on this site.') }}
			</div>
			<template v-else-if="catalog.data?.enabled">
				<div
					v-if="readOnlyMode"
					class="rounded-md bg-surface-amber-2 p-3 text-ink-amber-6 mb-5"
				>
					{{
						__(
							'This site is in read-only mode. Subscription changes are unavailable.',
						)
					}}
				</div>
				<section
					v-if="catalog.data.current_subscription"
					data-testid="current-subscription"
					class="rounded-lg border border-outline-gray-2 bg-surface-gray-1 p-5 mb-8"
				>
					<div
						class="flex flex-col md:flex-row md:items-start md:justify-between gap-4"
					>
						<div>
							<div class="flex items-center gap-2 mb-2">
								<h2 class="text-xl-semibold text-ink-gray-9">
									{{ catalog.data.current_subscription.tier }}
								</h2>
								<Badge :theme="statusTheme">{{
									catalog.data.current_subscription.status
								}}</Badge>
							</div>
							<p class="text-ink-gray-6">
								{{ periodLabel }}
							</p>
							<p
								v-if="catalog.data.current_subscription.cancel_at_period_end"
								class="text-ink-amber-6 mt-2"
							>
								{{
									__(
										'Cancellation is scheduled for the end of the current period.',
									)
								}}
							</p>
						</div>
						<div
							v-if="
								!readOnlyMode &&
								canCancel &&
								!catalog.data.current_subscription.cancel_at_period_end
							"
							class="flex flex-wrap gap-2"
						>
							<Button
								data-testid="cancel-at-period-end"
								:loading="cancellation.loading"
								@click="cancel(true)"
							>
								{{ __('Cancel at period end') }}
							</Button>
							<Button
								data-testid="cancel-immediately"
								theme="red"
								variant="outline"
								:loading="cancellation.loading"
								@click="cancel(false)"
							>
								{{ __('Cancel immediately') }}
							</Button>
						</div>
					</div>
				</section>

				<div class="mb-5">
					<h2 class="text-2xl-semibold text-ink-gray-9">
						{{ __('Available plans') }}
					</h2>
					<p class="text-ink-gray-6 mt-1">
						{{ __('Higher tiers include all content from lower tiers.') }}
					</p>
				</div>
				<div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
					<article
						v-for="tier in catalog.data.tiers"
						:key="tier.name"
						class="rounded-lg border border-outline-gray-2 p-5 flex flex-col"
					>
						<div class="flex items-start justify-between gap-3">
							<div>
								<h3 class="text-xl-semibold text-ink-gray-9">
									{{ tier.tier_name }}
								</h3>
								<p v-if="tier.description" class="text-ink-gray-6 mt-1">
									{{ tier.description }}
								</p>
							</div>
							<Badge theme="gray">{{ __('Tier {0}').format(tier.rank) }}</Badge>
						</div>
						<div class="mt-5 space-y-3 flex-1">
							<div
								v-for="plan in plansForTier(tier.name)"
								:key="plan.name"
								class="rounded-md bg-surface-gray-1 p-3"
							>
								<div class="flex items-center justify-between gap-3">
									<div>
										<div class="font-medium text-ink-gray-9">
											{{ plan.plan_name }}
										</div>
										<div class="text-sm text-ink-gray-6">
											{{ plan.price }} / {{ intervalLabel(plan) }}
										</div>
									</div>
									<Button
										:data-testid="`select-plan-${plan.name}`"
										:disabled="planUnavailable(plan)"
										:variant="planUnavailable(plan) ? 'subtle' : 'solid'"
										@click="selectPlan(plan)"
									>
										{{ planLabel(plan) }}
									</Button>
								</div>
							</div>
							<p
								v-if="!plansForTier(tier.name).length"
								class="text-sm text-ink-gray-5"
							>
								{{ __('No active plans for this tier.') }}
							</p>
						</div>
					</article>
				</div>
			</template>
		</div>
	</PageBody>
</template>

<script setup lang="ts">
import { Badge, Button, createResource, toast, usePageMeta } from 'frappe-ui'
import { computed, inject, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/Layouts/PageHeader.vue'
import PageBody from '@/components/Layouts/PageBody.vue'
import { sessionStore } from '@/stores/session'
import type { SessionUser } from '@/types'

interface SubscriptionPlan {
	name: string
	plan_name: string
	tier: string
	tier_rank: number
	price: string
	billing_interval: 'Month' | 'Year'
	interval_count: number
}

const user = inject<SessionUser>('$user')!
const router = useRouter()
const { brand } = sessionStore()
const breadcrumbs = [
	{ label: __('Subscriptions'), route: { name: 'Subscriptions' } },
]

const catalog = createResource({
	url: 'lms.lms.subscriptions.get_subscription_catalog',
	auto: false,
})

onMounted(() => {
	if (user.data?.name) catalog.fetch()
})

const readOnlyMode = Boolean(
	(window as Window & { read_only_mode?: boolean }).read_only_mode,
)
const currentRank = computed(() => {
	const current = catalog.data?.current_subscription
	if (!current || !['Trial', 'Active', 'Past Due'].includes(current.status))
		return 0
	return (
		catalog.data?.tiers.find((tier) => tier.name === current.tier)?.rank || 0
	)
})
const statusTheme = computed(() => {
	const status = catalog.data?.current_subscription?.status
	if (status === 'Active' || status === 'Trial') return 'green'
	if (status === 'Past Due') return 'orange'
	return 'gray'
})
const periodLabel = computed(() => {
	const current = catalog.data?.current_subscription
	if (!current?.current_period_end) return __('Waiting for the first payment.')
	return __('Current access runs through {0}.').format(
		current.current_period_end,
	)
})
const canCancel = computed(() =>
	['Trial', 'Active', 'Past Due'].includes(
		catalog.data?.current_subscription?.status,
	),
)

const plansForTier = (tier: string): SubscriptionPlan[] =>
	(catalog.data?.plans || []).filter(
		(plan: SubscriptionPlan) => plan.tier === tier,
	)
const intervalLabel = (plan: SubscriptionPlan) => {
	const unit = plan.billing_interval === 'Year' ? __('year') : __('month')
	return plan.interval_count === 1 ? unit : `${plan.interval_count} ${unit}s`
}
const planIncluded = (plan: SubscriptionPlan) => {
	const status = catalog.data?.current_subscription?.status || ''
	return (
		['Trial', 'Active'].includes(status) && currentRank.value >= plan.tier_rank
	)
}
const pastDueUnavailable = (plan: SubscriptionPlan) => {
	const current = catalog.data?.current_subscription
	if (current?.status !== 'Past Due') return false
	return (
		plan.tier_rank < currentRank.value ||
		(plan.tier_rank === currentRank.value && plan.name !== current.plan)
	)
}
const planUnavailable = (plan: SubscriptionPlan) =>
	readOnlyMode || planIncluded(plan) || pastDueUnavailable(plan)
const planLabel = (plan: SubscriptionPlan) => {
	if (readOnlyMode) return __('Unavailable')
	if (planIncluded(plan)) return __('Included')
	if (pastDueUnavailable(plan)) return __('Higher tier required')
	const current = catalog.data?.current_subscription
	if (current?.status === 'Past Due' && plan.name === current.plan)
		return __('Retry payment')
	return currentRank.value ? __('Upgrade') : __('Choose plan')
}
const selectPlan = (plan: SubscriptionPlan) => {
	if (planUnavailable(plan)) return
	router.push({
		name: 'Billing',
		params: { type: 'subscription', name: plan.name },
	})
}

const cancellation = createResource({
	url: 'lms.lms.subscriptions.cancel_subscription',
})
const cancel = (atPeriodEnd: boolean) => {
	if (readOnlyMode) return
	const subscription = catalog.data?.current_subscription?.name
	if (!subscription) return
	const message = atPeriodEnd
		? __('Cancel this subscription at the end of the current period?')
		: __('Cancel this subscription immediately? Access may end now.')
	if (!window.confirm(message)) return
	cancellation.submit(
		{ subscription, at_period_end: atPeriodEnd },
		{
			onSuccess() {
				toast.success(__('Subscription updated.'))
				catalog.reload()
			},
			onError(error: any) {
				toast.error(error.messages?.[0] || error.message || error)
			},
		},
	)
}

const login = () => {
	window.location.href = `/login?redirect-to=${window.location.pathname}`
}

usePageMeta(() => ({ title: __('Subscriptions'), icon: brand.favicon }))
</script>
