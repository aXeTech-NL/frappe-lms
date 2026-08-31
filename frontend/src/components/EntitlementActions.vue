<template>
	<div v-if="decision?.handled && !decision.allowed" class="space-y-2">
		<a
			v-for="offer in decision.offers || []"
			:key="`${offer.kind}:${offer.url}`"
			:href="safeUrl(offer.url)"
			:target="isExternal(offer.url) ? '_blank' : undefined"
			:rel="isExternal(offer.url) ? 'noopener noreferrer' : undefined"
			class="block"
		>
			<Button
				:data-testid="`entitlement-offer-${offer.kind}`"
				:variant="offer.variant"
				size="md"
				class="w-full"
			>
				<template v-if="offer.icon" #prefix>
					<span :class="`lucide-${offer.icon} size-4`" />
				</template>
				{{ offer.label }}
			</Button>
		</a>
		<p
			v-if="!(decision.offers || []).length"
			data-testid="entitlement-unavailable"
			class="rounded-md bg-surface-gray-2 p-3 text-sm text-ink-gray-7"
		>
			{{ __('Access to this course is currently unavailable.') }}
		</p>
	</div>
</template>

<script setup lang="ts">
import { Button } from 'frappe-ui'
import type { EntitlementDecision } from '@/types'
import { safeUrl } from '@/utils/safeUrl'

defineProps<{
	decision?: EntitlementDecision | null
}>()

const isExternal = (url: string) => url.startsWith('https://')
</script>
