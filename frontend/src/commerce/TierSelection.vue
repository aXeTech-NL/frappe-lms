<template>
	<PageHeader
		:breadcrumbs="[
			{ label: __('My access'), route: { name: 'CommerceAccess' } },
			{ label: __('Choose a tier'), route: { name: 'CommerceTiers' } },
		]"
	/>
	<PageBody>
		<div class="commerce-checkout space-y-6">
			<header class="commerce-checkout__intro">
				<p class="commerce-checkout__eyebrow">{{ __('My access') }}</p>
				<h1>{{ __('Choose a tier') }}</h1>
				<p class="commerce-checkout__lead">
					{{
						__(
							'Compare the available tiers and select the access level that suits you.',
						)
					}}
				</p>
			</header>
			<p v-if="!user?.data" role="status">
				{{ __('Please log in to view your access.') }}
			</p>
			<p v-else-if="options.loading" role="status">
				{{ __('Loading tiers...') }}
			</p>
			<div
				v-else-if="options.error"
				role="alert"
				class="commerce-checkout__stack"
			>
				<p>{{ __('Unable to load tiers. Please try again.') }}</p>
				<Button @click="load">{{ __('Try again') }}</Button>
			</div>
			<p
				v-else-if="options.data && !options.data.commerce_enabled"
				role="status"
			>
				{{ __('Commerce is disabled. Native LMS access applies.') }}
			</p>
			<template v-else-if="options.data?.commerce_enabled">
				<div class="commerce-checkout__test" role="status">
					<Info :size="18" aria-hidden="true" />
					<div>
						<p class="font-semibold">
							{{ __('Paid tier upgrades are not available yet.') }}
						</p>
						<p>
							{{
								__(
									'Selecting a tier here does not start a subscription, charge a payment or change your access.',
								)
							}}
						</p>
					</div>
				</div>
				<p>
					{{ __('Current tier access') }}:
					<strong>{{
						options.data.current_tier || __('No active tier')
					}}</strong>
				</p>
				<div v-if="options.data.course" class="commerce-checkout__stack">
					<h2>{{ options.data.course.title }}</h2>
					<p>
						{{
							__('Required tier: {0} or higher').format(
								options.data.course.required_tier,
							)
						}}
					</p>
					<p class="commerce-checkout__muted">
						{{
							__(
								'A tier does not replace course enrolment or other course requirements.',
							)
						}}
					</p>
				</div>
				<p v-if="!options.data.tiers.length" role="status">
					{{ __('No tiers are available at the moment.') }}
				</p>
				<ul
					v-else
					class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5"
					:aria-label="__('Available tiers')"
				>
					<li
						v-for="tier in options.data.tiers"
						:key="tier.name"
						class="flex min-w-0"
					>
						<article
							class="commerce-checkout__content commerce-checkout__stack w-full break-words"
						>
							<h2>{{ tier.name }}</h2>
							<Badge v-if="tier.current" theme="gray">{{
								__('Current tier access')
							}}</Badge>
							<p v-if="tier.description">{{ tier.description }}</p>
							<p
								v-if="tier.meets_course_tier === false"
								class="commerce-checkout__muted"
							>
								{{ __('This tier is below the required course tier.') }}
							</p>
							<p
								v-else-if="tier.meets_course_tier === true"
								class="commerce-checkout__muted"
							>
								{{ __('This tier meets the course tier requirement.') }}
							</p>
							<Button
								:variant="selected === tier.name ? 'solid' : 'outline'"
								:aria-pressed="selected === tier.name"
								:disabled="tier.meets_course_tier === false"
								:class="{
									'commerce-checkout__primary': selected === tier.name,
								}"
								@click="selected = tier.name"
							>
								{{
									selected === tier.name
										? __('Selected: {0}').format(tier.name)
										: __('Select {0}').format(tier.name)
								}}
							</Button>
						</article>
					</li>
				</ul>
				<section
					v-if="selected"
					class="commerce-checkout__content commerce-checkout__stack"
					aria-live="polite"
				>
					<h2>{{ __('Your selection') }}: {{ selected }}</h2>
					<p>
						{{
							__(
								'Prices, billing periods and recurring payment consent will be shown here once subscription checkout is available.',
							)
						}}
					</p>
					<Button disabled>{{ __('Payment is not available yet') }}</Button>
				</section>
			</template>
			<div class="flex flex-wrap gap-3">
				<Button :route="{ name: 'CommerceAccess' }">{{
					__('Back to my access')
				}}</Button>
				<Button
					v-if="options.data?.course && !options.error && !options.loading"
					:route="{
						name: 'CourseDetail',
						params: { courseName: options.data.course.name },
					}"
				>
					{{ __('Back to course') }}
				</Button>
			</div>
		</div>
	</PageBody>
</template>

<script setup>
import { computed, inject, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Badge, Button, createResource, usePageMeta } from 'frappe-ui'
import { Info } from 'lucide-vue-next'
import PageHeader from '@/components/Layouts/PageHeader.vue'
import PageBody from '@/components/Layouts/PageBody.vue'
import './checkout.css'

const user = inject('$user')
const route = useRoute()
const selected = ref(null)
const course = computed(() =>
	typeof route.query.course === 'string' ? route.query.course : undefined,
)
const options = createResource({ url: 'lms.lms_commerce.api.get_tier_options' })
function load() {
	selected.value = null
	if (!user?.data) return
	options.abort()
	options.submit(course.value ? { course: course.value } : {}).catch(() => {})
}
watch(course, load, { immediate: true })
usePageMeta(() => ({ title: __('Choose a tier') }))
</script>
