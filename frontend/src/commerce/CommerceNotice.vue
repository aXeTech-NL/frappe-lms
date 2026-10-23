<template>
	<div v-if="commerceDenied(access)" class="space-y-3 mb-4" data-testid="commerce-notice">
		<CommerceBadge :access="access" />
		<p class="text-p-sm text-ink-gray-7">
			{{ access?.reason === 'login_required' ? __('Log in to check your access.') : __('This course requires additional access. Your learning progress is preserved.') }}
		</p>
		<Button v-for="offer in offers" :key="offer.url" variant="solid" class="w-full" @click="follow(offer.url)">
			{{ offer.label }}
		</Button>
		<p v-if="!offers.length" class="text-p-sm text-ink-gray-6">
			{{ __('Currently unavailable. Please contact the administrator for access.') }}
		</p>
	</div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Button } from 'frappe-ui'
import CommerceBadge from './CommerceBadge.vue'
import { commerceDenied, safeActionUrl, type CommerceAccess } from './access'

const props = defineProps<{ access?: CommerceAccess | null }>()
const offers = computed(() => (props.access?.offers || []).flatMap(offer => {
	const url = safeActionUrl(offer.url)
	return url ? [{ ...offer, url }] : []
}))
function follow(value: string) {
	const url = safeActionUrl(value)
	if (!url) return
	if (url === '/login') {
		window.location.assign(`/login?redirect-to=${encodeURIComponent(window.location.pathname)}`)
	} else {
		window.location.assign(url)
	}
}
</script>
