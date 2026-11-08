<template>
	<PageHeader :breadcrumbs="[{ label: __('Payment status'), route: { name: 'CommerceCheckoutReturn', params: { order: orderName } } }]" />
	<PageBody :title="__('Payment status')">
		<div class="px-5 pb-5 max-w-xl space-y-5" aria-live="polite">
			<p v-if="!order && status.loading" role="status">{{ __('Checking payment...') }}</p>
			<p v-if="status.error || refresh.error" role="alert">{{ __('Payment confirmation is not available yet. Please check again; do not pay twice.') }}</p>
			<template v-if="order">
				<h2 class="text-xl font-semibold text-ink-gray-9">{{ order.title }}</h2>
				<p v-if="order.mode === 'test'">{{ __('Test payment. No real money will be charged.') }}</p>
				<p v-if="order.access_granted">{{ __('Payment confirmed. Open the course to enroll or continue learning.') }}</p>
				<p v-else-if="['failed', 'canceled', 'expired'].includes(order.status)">{{ __('Payment was not completed. You have not received access from this order.') }}</p>
				<p v-else-if="['refunded', 'partially_charged_back', 'charged_back'].includes(order.status)">{{ __('This payment was reversed. Access from this order has been withdrawn.') }}</p>
				<p v-else>{{ __('Your payment is awaiting confirmation. Returning from the payment provider does not confirm payment.') }}</p>
				<p class="text-p-sm text-ink-gray-6">{{ __('Order') }}: {{ order.name }}</p>
				<Button v-if="checkoutUrl && !order.access_granted" variant="solid" @click="continuePayment">{{ __('Continue existing checkout') }}</Button>
				<Button :loading="refresh.loading" :disabled="refresh.loading" @click="refresh.submit({ order: orderName })">{{ __('Check payment status') }}</Button>
				<Button :route="{ name: 'CourseDetail', params: { courseName: order.course } }">{{ __('Back to course') }}</Button>
			</template>
		</div>
	</PageBody>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Button, createResource, usePageMeta } from 'frappe-ui'
import PageHeader from '@/components/Layouts/PageHeader.vue'
import PageBody from '@/components/Layouts/PageBody.vue'
import { safeActionUrl } from './access'

const orderName = String(useRoute().params.order)
const order = ref(null)
const refresh = createResource({
	url: 'lms.lms_commerce.services.checkout.refresh_order',
	onSuccess(data) { order.value = data },
})
const status = createResource({
	url: 'lms.lms_commerce.services.checkout.get_order', params: { order: orderName }, auto: true,
	onSuccess(data) {
		order.value = data
		// Creating is uncertain: require an explicit retry with the same order key.
		if (['open', 'pending', 'authorized'].includes(data.status)) refresh.submit({ order: orderName }).catch(() => {})
	},
})
const checkoutUrl = computed(() => safeActionUrl(order.value?.checkout_url || ''))
function continuePayment() {
	if (checkoutUrl.value) window.location.assign(checkoutUrl.value)
}
usePageMeta(() => ({ title: __('Payment status') }))
</script>
