<template>
	<div class="commerce-checkout__summary-top">
		<BookOpen class="size-6" aria-hidden="true" />
		<span>{{ __('One-time purchase') }}</span>
	</div>
	<h2>{{ title }}</h2>
	<dl class="commerce-checkout__total">
		<dt>{{ __('Total') }}</dt>
		<dd>{{ formattedAmount }}</dd>
	</dl>
	<ul class="commerce-checkout__benefits">
		<li>
			<Check class="size-4" aria-hidden="true" /><span>{{
				__('No subscription or automatic debit')
			}}</span>
		</li>
		<li>
			<Check class="size-4" aria-hidden="true" /><span>{{
				__('Access after payment confirmation')
			}}</span>
		</li>
		<li>
			<Check class="size-4" aria-hidden="true" /><span>{{
				__('Continue learning in this environment')
			}}</span>
		</li>
	</ul>
	<p class="commerce-checkout__provider-note">
		<LockKeyhole class="size-4" aria-hidden="true" />
		<span>{{
			__('You complete payment with our payment provider, then return here.')
		}}</span>
	</p>
</template>

<script setup>
import { computed } from 'vue'
import { BookOpen, Check, LockKeyhole } from 'lucide-vue-next'

const props = defineProps({
	title: { type: String, required: true },
	amount: { type: String, required: true },
	currency: { type: String, required: true },
})
const formattedAmount = computed(() => {
	// Display only. The browser never calculates or submits a price.
	const locale =
		window.frappe?.boot?.lang || document.documentElement.lang || 'en'
	try {
		return new Intl.NumberFormat(locale, {
			style: 'currency',
			currency: props.currency,
		}).format(Number(props.amount))
	} catch {
		return `${props.currency} ${props.amount}`
	}
})
</script>
