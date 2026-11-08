<template>
	<PageHeader :breadcrumbs="[{ label, route: breadcrumbRoute }]" />
	<PageBody>
		<div class="commerce-checkout">
			<header class="commerce-checkout__intro">
				<p class="commerce-checkout__eyebrow">
					{{ __('Your learning environment') }}
				</p>
				<h1>{{ title }}</h1>
				<p class="commerce-checkout__lead">{{ description }}</p>
			</header>
			<ol
				class="commerce-checkout__steps"
				:aria-label="__('Checkout progress')"
			>
				<li
					v-for="(step, index) in steps"
					:key="step"
					:aria-current="currentStep === index + 1 ? 'step' : undefined"
					:class="{ 'is-complete': currentStep > index + 1 }"
				>
					<Check
						v-if="currentStep > index + 1"
						class="size-4"
						aria-hidden="true"
					/>
					<span v-else class="commerce-checkout__step-number" aria-hidden="true"
						>0{{ index + 1 }}</span
					>
					<span>{{ step }}</span>
				</li>
			</ol>
			<div
				class="commerce-checkout__grid"
				:class="{ 'commerce-checkout__grid--single': !$slots.summary }"
			>
				<aside
					v-if="$slots.summary"
					class="commerce-checkout__summary"
					:aria-label="__('Your order')"
				>
					<slot name="summary" />
				</aside>
				<section class="commerce-checkout__content" :aria-label="label">
					<slot />
				</section>
			</div>
		</div>
	</PageBody>
</template>

<script setup>
import { Check } from 'lucide-vue-next'
import PageHeader from '@/components/Layouts/PageHeader.vue'
import PageBody from '@/components/Layouts/PageBody.vue'
import './checkout.css'

defineProps({
	label: { type: String, required: true },
	title: { type: String, required: true },
	description: { type: String, required: true },
	breadcrumbRoute: { type: Object, required: true },
	currentStep: { type: Number, default: 1 },
})
const steps = [__('Review order'), __('Payment'), __('Access')]
</script>
