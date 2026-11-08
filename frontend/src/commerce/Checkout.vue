<template>
	<PageHeader :breadcrumbs="[{ label: __('Checkout'), route: { name: 'CommerceCheckout', params: { offering } } }]" />
	<PageBody :title="__('Checkout')">
		<div class="px-5 pb-5 max-w-xl space-y-5">
			<p v-if="quotation.loading" role="status">{{ __('Loading checkout...') }}</p>
			<p v-else-if="quotation.error" role="alert">{{ __('Checkout is unavailable. Please return to the course or contact the administrator.') }}</p>
			<template v-else-if="quotation.data">
				<h2 class="text-xl font-semibold text-ink-gray-9">{{ quotation.data.title }}</h2>
				<p class="text-lg">{{ __('Total') }}: {{ quotation.data.currency }} {{ quotation.data.amount }}</p>
				<p v-if="quotation.data.mode === 'test'" role="status" class="text-ink-amber-7">{{ __('Test payment. No real money will be charged.') }}</p>
				<p>{{ __('One-time course access. This does not start a subscription or automatic debit.') }}</p>
				<Button v-if="quotation.data.pending_order" variant="solid" :route="{ name: 'CommerceCheckoutReturn', params: { order: quotation.data.pending_order } }">
					{{ __('Continue existing checkout') }}
				</Button>
				<template v-else>
					<Checkbox v-model="accepted" :label="__('I accept the terms and request access after payment.')" />
					<a v-if="termsUrl" v-external :href="safeUrl(termsUrl)" class="underline">{{ __('Read the terms') }}</a>
					<Button variant="solid" :disabled="!accepted || !termsUrl || starting" :loading="starting" @click="pay">{{ __('Continue to payment') }}</Button>
				</template>
				<p v-if="error" role="alert">{{ __('Payment could not be opened. Refresh this page to recover your existing checkout; do not start a separate payment.') }}</p>
				<Button :route="{ name: 'CourseDetail', params: { courseName: quotation.data.course } }">{{ __('Back to course') }}</Button>
			</template>
		</div>
	</PageBody>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button, Checkbox, createResource, usePageMeta } from 'frappe-ui'
import { vExternal } from '@/directives/external'
import { safeUrl } from '@/utils/safeUrl'
import PageHeader from '@/components/Layouts/PageHeader.vue'
import PageBody from '@/components/Layouts/PageBody.vue'
import { safeActionUrl } from './access'

const route = useRoute()
const router = useRouter()
const offering = computed(() => String(route.params.offering))
const accepted = ref(false)
const starting = ref(false)
const error = ref(false)
const quotation = createResource({ url: 'lms.lms_commerce.services.checkout.get_quote', params: { offering: offering.value }, auto: true })
const start = createResource({ url: 'lms.lms_commerce.services.checkout.start_checkout' })
const termsUrl = computed(() => safeActionUrl(quotation.data?.terms_url || ''))
async function pay() {
	if (!accepted.value || starting.value) return
	starting.value = true
	error.value = false
	try {
		const order = await start.submit({ offering: offering.value, quote_token: quotation.data.quote_token, accept_terms: true })
		// Save the return route before leaving: a closed provider tab is recoverable.
		await router.replace({ name: 'CommerceCheckoutReturn', params: { order: order.name } })
		const url = safeActionUrl(order.checkout_url || '')
		if (url) window.location.assign(url)
	} catch {
		error.value = true
	} finally {
		starting.value = false
	}
}
usePageMeta(() => ({ title: __('Checkout') }))
</script>
