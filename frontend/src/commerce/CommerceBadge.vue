<template>
	<Badge v-if="access?.handled && access.badge" :theme="theme" size="sm">
		{{ access.badge.label }}
	</Badge>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Badge } from 'frappe-ui'
import type { CommerceAccess } from './access'

const props = defineProps<{ access?: CommerceAccess | null }>()
const theme = computed(() => props.access?.allowed ? 'green' : 'orange')
</script>
