<template>
	<CheckoutLayout
		:label="__('Checkout')"
		:title="__('Your next step starts here.')"
		:description="
			__(
				'Review your course and complete payment. You can then continue learning here.',
			)
		"
		:breadcrumb-route="{ name: 'CommerceCheckout', params: { offering } }"
	>
		<div
			v-if="quotation.loading"
			role="status"
			class="commerce-checkout__stack"
		>
			<p>{{ __('Loading checkout...') }}</p>
		</div>
		<div
			v-else-if="quotation.error || !quotation.data"
			class="commerce-checkout__stack"
		>
			<p role="alert" class="commerce-checkout__error">
				{{
					__(
						'Checkout is unavailable. Please return to the course or contact the administrator.',
					)
				}}
			</p>
			<Button :route="{ name: 'Courses' }">{{ __('Back to courses') }}</Button>
		</div>
		<div v-else class="commerce-checkout__stack">
			<h2>{{ __('Review your purchase') }}</h2>
			<p class="commerce-checkout__muted">
				{{
					__(
						'One-time course access. This does not start a subscription or automatic debit.',
					)
				}}
			</p>
			<div
				v-if="quotation.data.mode === 'test'"
				role="status"
				class="commerce-checkout__test"
			>
				<FlaskConical class="size-4" aria-hidden="true" />
				<span>{{ __('Test payment. No real money will be charged.') }}</span>
			</div>
			<template v-if="quotation.data.pending_order">
				<p>
					{{
						__(
							'You already have an open checkout for this course. Continue that checkout to avoid paying twice.',
						)
					}}
				</p>
				<Button
					variant="solid"
					class="commerce-checkout__primary"
					:route="{
						name: 'CommerceCheckoutReturn',
						params: { order: quotation.data.pending_order },
					}"
				>
					{{ __('Continue existing checkout') }}
				</Button>
			</template>
			<template v-else>
				<div class="commerce-checkout__consent">
					<Checkbox
						v-model="accepted"
						:disabled="starting"
						:label="__('I accept the terms and request access after payment.')"
					/>
					<a
						v-if="termsUrl"
						v-external
						:href="safeUrl(termsUrl)"
						class="underline"
						>{{ __('Read the terms') }}</a
					>
				</div>
				<Button
					variant="solid"
					class="commerce-checkout__primary"
					:disabled="!accepted || !termsUrl || starting"
					:loading="starting"
					@click="pay"
				>
					{{ __('Continue to payment') }}
					<template #suffix
						><ArrowRight class="size-4" aria-hidden="true"
					/></template>
				</Button>
			</template>
			<p v-if="error" role="alert" class="commerce-checkout__error">
				{{
					__(
						'Payment could not be opened. Refresh this page to recover your existing checkout; do not start a separate payment.',
					)
				}}
			</p>
			<Button
				variant="ghost"
				:route="{
					name: 'CourseDetail',
					params: { courseName: quotation.data.course },
				}"
			>
				<template #prefix
					><ArrowLeft class="size-4" aria-hidden="true"
				/></template>
				{{ __('Back to course') }}
			</Button>
		</div>
		<template
			v-if="quotation.data && !quotation.loading && !quotation.error"
			#summary
		>
			<CheckoutSummary
				:title="quotation.data.title"
				:amount="quotation.data.amount"
				:currency="quotation.data.currency"
			/>
		</template>
	</CheckoutLayout>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button, Checkbox, createResource, usePageMeta } from 'frappe-ui'
import { ArrowLeft, ArrowRight, FlaskConical } from 'lucide-vue-next'
import { vExternal } from '@/directives/external'
import { safeUrl } from '@/utils/safeUrl'
import CheckoutLayout from './CheckoutLayout.vue'
import CheckoutSummary from './CheckoutSummary.vue'
import { safeActionUrl } from './access'

const route = useRoute()
const router = useRouter()
const offering = computed(() => String(route.params.offering))
const accepted = ref(false)
const starting = ref(false)
const error = ref(false)
const quotation = createResource({
	url: 'lms.lms_commerce.services.checkout.get_quote',
	params: { offering: offering.value },
})
// An unavailable checkout is rendered inline, not an unhandled auto-fetch rejection.
quotation.fetch().catch(() => {})
const start = createResource({
	url: 'lms.lms_commerce.services.checkout.start_checkout',
})
const termsUrl = computed(() => safeActionUrl(quotation.data?.terms_url || ''))
async function pay() {
	if (!accepted.value || !termsUrl.value || starting.value || !quotation.data)
		return
	starting.value = true
	error.value = false
	try {
		const order = await start.submit({
			offering: offering.value,
			quote_token: quotation.data.quote_token,
			accept_terms: true,
		})
		// Save the return route before leaving: a closed provider tab is recoverable.
		await router.replace({
			name: 'CommerceCheckoutReturn',
			params: { order: order.name },
		})
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
