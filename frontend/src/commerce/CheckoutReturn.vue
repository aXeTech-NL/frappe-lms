<template>
	<CheckoutLayout
		:label="__('Payment status')"
		:title="view.title"
		:description="
			__(
				'Your payment status and next step, together in your learning environment.',
			)
		"
		:breadcrumb-route="{
			name: 'CommerceCheckoutReturn',
			params: { order: orderName },
		}"
		:current-step="order?.access_granted ? 3 : 2"
	>
		<div
			class="commerce-checkout__stack"
			aria-live="polite"
			:aria-busy="status.loading || refresh.loading"
		>
			<p v-if="!order && status.loading" role="status">
				{{ __('Checking payment...') }}
			</p>
			<p
				v-if="status.error || refresh.error"
				role="alert"
				class="commerce-checkout__error"
			>
				{{
					__(
						'Payment confirmation is not available yet. Please check again; do not pay twice.',
					)
				}}
			</p>
			<template v-if="order">
				<div class="commerce-checkout__status-icon" :class="view.iconClass">
					<component :is="view.icon" class="size-6" aria-hidden="true" />
				</div>
				<h2>{{ view.heading }}</h2>
				<p>{{ view.message }}</p>
				<div
					v-if="order.mode === 'test'"
					role="status"
					class="commerce-checkout__test"
				>
					<FlaskConical class="size-4" aria-hidden="true" />
					<span>{{ __('Test payment. No real money will be charged.') }}</span>
				</div>
				<p class="commerce-checkout__muted commerce-checkout__order-reference">
					{{ __('Order') }}: {{ order.name }}
				</p>
				<div class="commerce-checkout__actions">
					<Button
						v-if="order.access_granted"
						variant="solid"
						class="commerce-checkout__primary"
						:route="{
							name: 'CourseDetail',
							params: { courseName: order.course },
						}"
					>
						{{ __('Go to course') }}
						<template #suffix
							><ArrowRight class="size-4" aria-hidden="true"
						/></template>
					</Button>
					<Button
						v-if="checkoutUrl"
						variant="solid"
						class="commerce-checkout__primary"
						@click="continuePayment"
						>{{ __('Continue existing checkout') }}</Button
					>
					<Button
						:loading="refresh.loading"
						:disabled="refresh.loading"
						@click="checkStatus"
						>{{ __('Check payment status') }}</Button
					>
					<Button
						v-if="!order.access_granted"
						variant="ghost"
						:route="{
							name: 'CourseDetail',
							params: { courseName: order.course },
						}"
						>{{ __('Back to course') }}</Button
					>
				</div>
			</template>
			<Button v-else-if="!status.loading" :route="{ name: 'Courses' }">{{
				__('Back to courses')
			}}</Button>
		</div>
		<template v-if="order" #summary>
			<CheckoutSummary
				:title="order.title"
				:amount="order.amount"
				:currency="order.currency"
			/>
		</template>
	</CheckoutLayout>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Button, createResource, usePageMeta } from 'frappe-ui'
import {
	ArrowRight,
	CircleCheck,
	Clock3,
	FlaskConical,
	RotateCcw,
	CircleX,
} from 'lucide-vue-next'
import CheckoutLayout from './CheckoutLayout.vue'
import CheckoutSummary from './CheckoutSummary.vue'
import { safeActionUrl } from './access'

const orderName = String(useRoute().params.order)
const order = ref(null)
const refresh = createResource({
	url: 'lms.lms_commerce.services.checkout.refresh_order',
	onSuccess(data) {
		order.value = data
	},
})
const status = createResource({
	url: 'lms.lms_commerce.services.checkout.get_order',
	params: { order: orderName },
	auto: true,
	onSuccess(data) {
		order.value = data
		// Creating is uncertain: require an explicit retry with the same order key.
		if (['open', 'pending', 'authorized'].includes(data.status))
			refresh.submit({ order: orderName }).catch(() => {})
	},
})
const checkoutUrl = computed(() => {
	if (
		order.value?.access_granted ||
		!['open', 'pending'].includes(order.value?.status)
	)
		return null
	return safeActionUrl(order.value?.checkout_url || '')
})
const view = computed(() => {
	if (order.value?.access_granted)
		return {
			title: __('Ready to keep learning.'),
			heading: __('Payment confirmed'),
			message: __(
				'Payment confirmed. Open the course to enroll or continue learning.',
			),
			icon: CircleCheck,
			iconClass: 'commerce-checkout__status-icon--success',
		}
	if (['failed', 'canceled', 'expired'].includes(order.value?.status))
		return {
			title: __('Payment not completed.'),
			heading: __('No access granted'),
			message: __(
				'Payment was not completed. You have not received access from this order.',
			),
			icon: CircleX,
			iconClass: 'commerce-checkout__status-icon--warning',
		}
	if (
		['refunded', 'partially_charged_back', 'charged_back'].includes(
			order.value?.status,
		)
	)
		return {
			title: __('Payment reversed.'),
			heading: __('Access from this order withdrawn'),
			message: __(
				'This payment was reversed. Access from this order has been withdrawn.',
			),
			icon: RotateCcw,
			iconClass: 'commerce-checkout__status-icon--warning',
		}
	return {
		title: __('We are checking your payment.'),
		heading: __('Awaiting confirmation'),
		message: __(
			'Your payment is awaiting confirmation. Returning from the payment provider does not confirm payment.',
		),
		icon: Clock3,
		iconClass: '',
	}
})
function continuePayment() {
	if (checkoutUrl.value) window.location.assign(checkoutUrl.value)
}
function checkStatus() {
	if (!refresh.loading) refresh.submit({ order: orderName }).catch(() => {})
}
usePageMeta(() => ({ title: __('Payment status') }))
</script>
