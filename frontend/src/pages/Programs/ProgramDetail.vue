<template>
	<PageHeader :breadcrumbs="breadcrumbs" />
	<PageBody>
		<template #name>
			<span class="flex items-center gap-x-2">
				{{ program.data?.name }}

				<Badge
					v-if="program.data"
					:theme="program.data.progress < 100 ? 'orange' : 'green'"
				>
					{{ program.data.progress }}% {{ __('completed') }}
				</Badge>

				<Tooltip
					v-if="program.data?.enforce_course_order"
					placement="right"
					:text="
						__(
							'Courses must be completed in order. You can only start the next course after completing the previous one.',
						)
					"
				>
					<span class="lucide-info size-3 cursor-pointer" />
				</Tooltip>
			</span>
		</template>

		<div v-if="program.data" class="px-5 pb-10">
			<div
				v-if="!entitled"
				data-testid="program-access-expired"
				class="rounded-md border border-outline-amber-2 bg-surface-amber-2 p-5 mb-5"
			>
				<h2 class="text-lg-semibold text-ink-gray-9">
					{{ __('Access required') }}
				</h2>
				<p class="text-ink-gray-7 mt-1 mb-4">
					{{ recoveryMessage }}
				</p>
				<div class="flex flex-wrap gap-2">
					<router-link v-if="program.data.paid_program" :to="purchaseRoute">
						<Button variant="solid">{{ __('Buy program') }}</Button>
					</router-link>
					<router-link
						v-if="program.data.required_subscription_tier"
						:to="{ name: 'Subscriptions' }"
					>
						<Button variant="outline">
							{{ __('View subscription plans') }}
						</Button>
					</router-link>
				</div>
			</div>
			<div
				v-else
				class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 mb-5"
			>
				<div
					v-for="course in program.data.courses"
					:key="course.name"
					class="relative group"
					:class="
						(course.eligible && program.data.enforce_course_order) ||
						!program.data.enforce_course_order
							? 'cursor-pointer'
							: 'cursor-default'
					"
				>
					<CourseCard
						:course="course"
						@click="openCourse(course, program.data.enforce_course_order)"
					/>
					<div
						v-if="!course.eligible && program.data.enforce_course_order"
						class="absolute inset-0 flex flex-col items-center justify-center space-y-2 text-ink-base rounded-md invisible group-hover:visible"
						:style="{
							background:
								'radial-gradient(circle, darkgray 0%, lightgray 100%)',
						}"
					>
						<span class="lucide-lock-keyhole size-5" />
						<span class="font-medium text-center leading-5 px-10">
							{{
								__('Please complete the previous course to unlock this one.')
							}}
						</span>
					</div>
				</div>
			</div>
		</div>
	</PageBody>
</template>
<script setup lang="ts">
import { computed, inject, onMounted } from 'vue'
import PageHeader from '@/components/Layouts/PageHeader.vue'
import PageBody from '@/components/Layouts/PageBody.vue'
import {
	Badge,
	Button,
	call,
	createResource,
	Tooltip,
	usePageMeta,
} from 'frappe-ui'
import { sessionStore } from '@/stores/session'

import { useRouter } from 'vue-router'
import CourseCard from '@/components/CourseCard.vue'

const { brand } = sessionStore()
const router = useRouter()
const user = inject<any>('$user')

const props = defineProps<{
	programName: string
}>()

onMounted(() => {
	checkIfEnrolled()
})

const checkIfEnrolled = () => {
	call('frappe.client.get_value', {
		doctype: 'LMS Program Member',
		filters: {
			member: user.data.name,
			parent: props.programName,
		},
		parent: 'LMS Program',
		fieldname: 'name',
	}).then((data: { name: string }) => {
		if (data.name) {
			program.reload()
		} else {
			router.push({ name: 'Programs' })
		}
	})
}

const program = createResource({
	url: 'lms.lms.utils.get_program_details',
	params: {
		program_name: props.programName,
	},
})

const entitled = computed(() =>
	program.data?.access ? Boolean(program.data.access.allowed) : true,
)
const purchaseRoute = computed(() => ({
	name: 'Billing',
	params: { type: 'program', name: props.programName },
}))
const recoveryMessage = computed(() => {
	const canPurchase = Boolean(program.data?.paid_program)
	const tier = program.data?.required_subscription_tier
	if (canPurchase && tier)
		return __(
			'Your progress is saved. Purchase this program or renew the required subscription to continue.',
		)
	if (canPurchase)
		return __('Your progress is saved. Purchase this program to continue.')
	return __(
		'Your progress is saved. Renew the required subscription to continue.',
	)
})

const openCourse = (course: any, enforceCourseOrder: boolean) => {
	if (!course.eligible && enforceCourseOrder) return
	router.push({
		name: 'CourseDetail',
		params: { courseName: course.name },
	})
}

const breadcrumbs = computed(() => {
	return [
		{ label: __('Programs'), route: { name: 'Programs' } },
		{
			label: props.programName,
			route: {
				name: 'ProgramDetail',
				params: { programName: props.programName },
			},
		},
	]
})

usePageMeta(() => {
	return {
		title: props.programName,
		icon: brand.favicon,
	}
})
</script>
