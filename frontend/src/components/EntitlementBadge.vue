<template>
	<Badge
		v-if="decision?.handled && badge"
		:data-testid="decision.allowed ? 'entitlement-badge' : 'entitlement-lock'"
		:theme="badge.theme"
		size="lg"
		class="inline-flex items-center gap-1"
	>
		<span :class="`lucide-${badge.icon} size-3.5`" />
		{{ badge.label }}
	</Badge>
</template>

<script setup lang="ts">
import { Badge } from 'frappe-ui'
import { computed } from 'vue'
import type { EntitlementDecision } from '@/types'

const props = defineProps<{
	decision?: EntitlementDecision | null
}>()

const badge = computed(() => {
	if (props.decision?.badge) return props.decision.badge
	if (props.decision?.handled && !props.decision.allowed)
		return { label: __('Locked'), theme: 'gray' as const, icon: 'lock' as const }
	return null
})
</script>
