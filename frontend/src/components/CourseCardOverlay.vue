<template>
	<div class="border-2 rounded-md min-w-80 max-w-sm">
		<VideoPreview
			:video-link="course.data?.video_link"
			:fallback-image="course.data?.image"
		/>
		<div class="p-5">
			<div class="text-3xl-semibold text-ink-gray-9 mb-4">
				{{ priceLabel }}
			</div>
			<div v-if="!readOnlyMode">
				<div v-if="canContinue" class="space-y-2 mb-8">
					<router-link :to="lessonRoute">
						<Button variant="solid" size="md" class="w-full">
							<template #prefix
								><span class="lucide-book-text size-4"
							/></template>
							{{ __('Continue Learning') }}
						</Button>
					</router-link>
					<CertificationLinks :courseName="course.data.name" class="w-full" />
				</div>
				<div v-else-if="!isAdmin" class="space-y-2 mb-8">
					<Button
						v-if="needsLogin"
						data-testid="course-login"
						variant="solid"
						class="w-full"
						@click="login"
					>
						{{ __('Log in to enroll') }}
					</Button>
					<Badge
						v-else-if="course.data?.disable_self_learning && canEnroll"
						theme="blue"
						size="lg"
						class="mb-4"
					>
						{{ __('Contact the Administrator to enroll for this course') }}
					</Badge>
					<Button
						v-else-if="canEnroll"
						data-testid="course-enroll"
						@click="enrollStudent()"
						variant="solid"
						class="w-full"
						size="md"
					>
						<template #prefix
							><span class="lucide-book-text size-4"
						/></template>
						{{ __('Enroll Now') }}
					</Button>
					<router-link v-if="canPurchase" :to="purchaseRoute">
						<Button
							data-testid="course-purchase"
							variant="solid"
							size="md"
							class="w-full"
						>
							<template #prefix
								><span class="lucide-credit-card size-4"
							/></template>
							{{ __('Buy this course') }}
						</Button>
					</router-link>
					<router-link v-if="canSubscribe" :to="{ name: 'Subscriptions' }">
						<Button
							data-testid="course-subscribe"
							variant="outline"
							size="md"
							class="w-full"
						>
							<template #prefix><span class="lucide-layers size-4" /></template>
							{{ subscriptionLabel }}
						</Button>
					</router-link>
					<p v-if="accessMessage" class="text-sm text-ink-gray-6">
						{{ accessMessage }}
					</p>
				</div>
				<Button
					v-if="canGetCertificate"
					@click="fetchCertificate()"
					variant="subtle"
					class="w-full mt-2"
					size="md"
				>
					<template #prefix>
						<span class="lucide-graduation-cap size-4" />
					</template>
					{{ __('Get Certificate') }}
				</Button>
			</div>
			<section v-if="hasCourseStats" class="space-y-3">
				<div class="text-base text-ink-gray-9 mb-1">
					{{ __('This course includes:') }}
				</div>
				<div
					v-if="enrolledLabel"
					class="flex items-center gap-3 text-ink-gray-8"
				>
					<span class="lucide-users size-4 shrink-0 text-ink-gray-7" />
					<span>{{ enrolledLabel }} {{ __('enrolled') }}</span>
				</div>
				<div
					v-if="course.data?.video_link"
					class="flex items-center gap-3 text-ink-gray-8"
				>
					<span class="lucide-monitor-play size-4 shrink-0 text-ink-gray-7" />
					<span>{{ __('On demand course video') }}</span>
				</div>
				<div
					v-if="course.data?.lessons"
					class="flex items-center gap-3 text-ink-gray-8"
				>
					<span class="lucide-book-open size-4 shrink-0 text-ink-gray-7" />
					<span>
						{{ course.data?.lessons }}
						{{ course.data?.lessons === 1 ? __('Lesson') : __('Lessons') }}
					</span>
				</div>
				<div
					v-if="(course.data?.quiz_count || 0) > 0"
					class="flex items-center gap-3 text-ink-gray-8"
				>
					<span class="lucide-help-circle size-4 shrink-0 text-ink-gray-7" />
					<span>
						{{ course.data?.quiz_count }}
						{{
							course.data?.quiz_count === 1
								? __('Quiz topic')
								: __('Quiz topics')
						}}
					</span>
				</div>
				<div
					v-if="course.data?.enable_certification"
					class="flex items-center gap-3 text-ink-gray-8"
				>
					<span class="lucide-award size-4 shrink-0 text-ink-gray-7" />
					<span>{{ __('Certificate of completion') }}</span>
				</div>
			</section>
		</div>
	</div>
</template>
<script setup lang="ts">
import { computed, inject } from 'vue'
import { Badge, Button, call, createResource, toast } from 'frappe-ui'
import { useRouter } from 'vue-router'
import CertificationLinks from '@/components/CertificationLinks.vue'
import VideoPreview from '@/components/VideoPreview.vue'
import { useTelemetry } from 'frappe-ui/frappe'
import { openExternal } from '@/utils/openExternal'
import type {
	CourseDetails,
	CourseInstructorInfo,
	Resource,
	SessionUser,
} from '@/types'

const router = useRouter()
const user = inject<SessionUser>('$user')!
const readOnlyMode = (window as Window & { read_only_mode?: boolean })
	.read_only_mode
const { capture } = useTelemetry()

const props = withDefaults(
	defineProps<{
		course: Resource<CourseDetails | null>
	}>(),
	{},
)

function enrollStudent() {
	if (!user.data) {
		toast.warning(__('You need to login first to enroll for this course'))
		setTimeout(() => {
			window.location.href = `/login?redirect-to=${window.location.pathname}`
		}, 500)
		return
	}
	const courseName = props.course.data?.name
	if (!courseName) return
	call('frappe.client.insert', {
		doc: {
			doctype: 'LMS Enrollment',
			course: courseName,
			member: user.data.name,
		},
	})
		.then(() => {
			capture('enrolled_in_course', { course: courseName })
			toast.success(__('You have been enrolled in this course'))
			setTimeout(() => {
				router.push({
					name: 'Lesson',
					params: {
						courseName,
						chapterNumber: 1,
						lessonNumber: 1,
					},
				})
			}, 1000)
		})
		.catch((err: { messages?: string[] } | string) => {
			const msg = typeof err === 'string' ? err : (err.messages?.[0] ?? 'Error')
			toast.warning(__(msg))
			console.error(err)
		})
}

const is_instructor = (): boolean => {
	let user_is_instructor = false
	props.course.data?.instructors.forEach((instructor: CourseInstructorInfo) => {
		if (!user_is_instructor && instructor.name == user.data?.name) {
			user_is_instructor = true
		}
	})
	return user_is_instructor
}

const access = computed(() => props.course.data?.access)
const subscriptionMode = computed(() => Boolean(access.value))
const entitled = computed(
	() => !subscriptionMode.value || Boolean(access.value?.allowed),
)
const canContinue = computed(() =>
	Boolean(props.course.data?.membership && entitled.value),
)
const canEnroll = computed(() =>
	Boolean(
		!props.course.data?.membership &&
		entitled.value &&
		(Boolean(user.data) || !subscriptionMode.value) &&
		(subscriptionMode.value || !props.course.data?.paid_course),
	),
)
const needsLogin = computed(() =>
	Boolean(subscriptionMode.value && access.value?.reason === 'login_required'),
)
const canPurchase = computed(() =>
	Boolean(
		props.course.data?.paid_course &&
		(!subscriptionMode.value || !entitled.value) &&
		!needsLogin.value,
	),
)
const canSubscribe = computed(() =>
	Boolean(
		props.course.data?.required_subscription_tier &&
		!entitled.value &&
		!needsLogin.value,
	),
)
const subscriptionLabel = computed(() =>
	__('Subscribe or upgrade to {0}').format(
		props.course.data?.required_subscription_tier || '',
	),
)
const accessMessage = computed(() => {
	if (!subscriptionMode.value || entitled.value || needsLogin.value) return ''
	const tier = props.course.data?.required_subscription_tier
	if (!tier) return ''
	return props.course.data?.paid_course
		? __('Requires the {0} tier or a direct purchase.').format(tier)
		: __('Requires the {0} tier.').format(tier)
})
const lessonRoute = computed(() => ({
	name: 'Lesson',
	params: {
		courseName: props.course.data?.name,
		chapterNumber: props.course.data?.current_lesson
			? props.course.data.current_lesson.split('-')[0]
			: 1,
		lessonNumber: props.course.data?.current_lesson
			? props.course.data.current_lesson.split('-')[1]
			: 1,
	},
}))
const purchaseRoute = computed(() => ({
	name: 'Billing',
	params: { type: 'course', name: props.course.data?.name },
}))
const login = () => {
	window.location.href = `/login?redirect-to=${window.location.pathname}`
}

const priceLabel = computed<string>(() => {
	const price = props.course.data?.paid_course
		? props.course.data?.price || ''
		: ''
	const tier = subscriptionMode.value
		? props.course.data?.required_subscription_tier
		: ''
	if (tier && price) return __('{0} or included in {1}').format(price, tier)
	if (tier) return __('Included in {0}').format(tier)
	return price || __('Free')
})

const enrolledLabel = computed<string>(() => {
	const n = props.course.data?.enrollments ?? 0
	if (!n) return ''
	if (n < 50) return String(n)
	const tier = n < 1000 ? 50 : 100
	return `${Math.floor(n / tier) * tier}+`
})

const hasCourseStats = computed<boolean>(() =>
	Boolean(
		enrolledLabel.value ||
		props.course.data?.video_link ||
		props.course.data?.lessons ||
		(props.course.data?.quiz_count ?? 0) > 0 ||
		props.course.data?.enable_certification,
	),
)

const canGetCertificate = computed<boolean>(() => {
	return Boolean(
		canContinue.value &&
		props.course.data?.enable_certification &&
		(props.course.data?.membership?.progress ?? 0) >= 100,
	)
})

const certificate = createResource({
	url: 'lms.lms.doctype.lms_certificate.lms_certificate.create_certificate',
	makeParams(values: { course?: string }) {
		return {
			course: values.course,
		}
	},
	onSuccess(data: { name: string; template: string }) {
		openExternal(
			`/api/method/frappe.utils.print_format.download_pdf?doctype=LMS+Certificate&name=${
				data.name
			}&format=${encodeURIComponent(data.template)}`,
		)
	},
}) as Resource<{ name: string; template: string } | null>

const fetchCertificate = () => {
	certificate.submit({
		course: props.course.data?.name,
		member: user.data?.name,
	})
}

const isAdmin = computed<boolean>(() => {
	return Boolean(user.data?.is_moderator) || is_instructor()
})
</script>
