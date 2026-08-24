<template>
	<div class="p-5 space-y-8">
		<div>
			<h2 class="text-xl-semibold text-ink-gray-9">
				{{ __('Subscription tiers') }}
			</h2>
			<p class="text-ink-gray-6 mt-1">
				{{
					__('Higher ranks include access granted to every lower-ranked tier.')
				}}
			</p>
			<div class="mt-4 space-y-2">
				<div
					v-for="tier in tiers.data || []"
					:key="tier.name"
					class="flex items-center justify-between rounded-md border p-3"
				>
					<div>
						<div class="font-medium text-ink-gray-9">{{ tier.tier_name }}</div>
						<div class="text-sm text-ink-gray-6">
							{{ __('Rank {0}').format(tier.rank) }} ·
							{{ tier.enabled ? __('Enabled') : __('Disabled') }}
						</div>
					</div>
					<div class="flex gap-2">
						<Button @click="editTier(tier)">{{ __('Edit') }}</Button>
						<Button
							theme="red"
							variant="ghost"
							@click="removeTier(tier.name)"
							>{{ __('Delete') }}</Button
						>
					</div>
				</div>
			</div>
			<Button class="mt-3" variant="solid" @click="newTier">{{
				__('New tier')
			}}</Button>
		</div>

		<div>
			<h2 class="text-xl-semibold text-ink-gray-9">
				{{ __('Subscription plans') }}
			</h2>
			<p class="text-ink-gray-6 mt-1">
				{{
					__('Plans define the first and recurring billing period for a tier.')
				}}
			</p>
			<div class="mt-4 space-y-2">
				<div
					v-for="plan in plans.data || []"
					:key="plan.name"
					class="flex items-center justify-between rounded-md border p-3"
				>
					<div>
						<div class="font-medium text-ink-gray-9">{{ plan.plan_name }}</div>
						<div class="text-sm text-ink-gray-6">
							{{ plan.tier }} · {{ plan.currency }} {{ plan.amount }} ·
							{{ interval(plan) }}
						</div>
					</div>
					<div class="flex gap-2">
						<Button @click="editPlan(plan)">{{ __('Edit') }}</Button>
						<Button
							theme="red"
							variant="ghost"
							@click="removePlan(plan.name)"
							>{{ __('Delete') }}</Button
						>
					</div>
				</div>
			</div>
			<Button class="mt-3" variant="solid" @click="newPlan">{{
				__('New plan')
			}}</Button>
		</div>
	</div>

	<Dialog
		v-model:open="tierDialog"
		:title="tierForm.name ? __('Edit tier') : __('New tier')"
	>
		<div class="space-y-4">
			<FormControl
				v-model="tierForm.tier_name"
				:label="__('Tier name')"
				:required="true"
			/>
			<FormControl
				v-model="tierForm.rank"
				type="number"
				min="1"
				:label="__('Rank')"
				:required="true"
			/>
			<FormControl
				v-model="tierForm.description"
				type="textarea"
				:label="__('Description')"
			/>
			<FormControl
				v-model="tierForm.enabled"
				type="checkbox"
				:label="__('Enabled')"
			/>
		</div>
		<template #actions>
			<Button variant="solid" :loading="saving" @click="saveTier">{{
				__('Save')
			}}</Button>
		</template>
	</Dialog>

	<Dialog
		v-model:open="planDialog"
		:title="planForm.name ? __('Edit plan') : __('New plan')"
	>
		<div class="space-y-4">
			<FormControl
				v-model="planForm.plan_name"
				:label="__('Plan name')"
				:required="true"
			/>
			<Link
				v-model="planForm.tier"
				doctype="LMS Subscription Tier"
				:filters="{ enabled: 1 }"
				:label="__('Tier')"
				:required="true"
			/>
			<FormControl
				v-model="planForm.billing_interval"
				type="select"
				:options="['Month', 'Year']"
				:label="__('Billing interval')"
			/>
			<FormControl
				v-model="planForm.interval_count"
				type="number"
				min="1"
				:label="__('Interval count')"
				:required="true"
			/>
			<Link
				v-model="planForm.currency"
				doctype="Currency"
				:filters="{ enabled: 1 }"
				:label="__('Currency')"
				:required="true"
			/>
			<FormControl
				v-model="planForm.amount"
				type="number"
				min="0.01"
				:label="__('Amount')"
				:required="true"
			/>
			<FormControl
				v-model="planForm.amount_usd"
				type="number"
				min="0"
				:label="__('Amount (USD)')"
			/>
			<FormControl
				v-model="planForm.enabled"
				type="checkbox"
				:label="__('Enabled')"
			/>
		</div>
		<template #actions>
			<Button variant="solid" :loading="saving" @click="savePlan">{{
				__('Save')
			}}</Button>
		</template>
	</Dialog>
</template>

<script setup lang="ts">
import {
	Button,
	Dialog,
	FormControl,
	createListResource,
	toast,
} from 'frappe-ui'
import { reactive, ref } from 'vue'
import Link from '@/components/Controls/Link.vue'

const tiers = createListResource({
	doctype: 'LMS Subscription Tier',
	fields: ['name', 'tier_name', 'rank', 'description', 'enabled'],
	orderBy: 'rank asc',
	pageLength: 100,
	auto: true,
})
const plans = createListResource({
	doctype: 'LMS Subscription Plan',
	fields: [
		'name',
		'plan_name',
		'tier',
		'billing_interval',
		'interval_count',
		'amount',
		'currency',
		'amount_usd',
		'enabled',
	],
	orderBy: 'creation asc',
	pageLength: 100,
	auto: true,
})

const tierDialog = ref(false)
const planDialog = ref(false)
const saving = ref(false)
const blankTier = () => ({
	name: '',
	tier_name: '',
	rank: 1,
	description: '',
	enabled: true,
})
const blankPlan = () => ({
	name: '',
	plan_name: '',
	tier: '',
	billing_interval: 'Month',
	interval_count: 1,
	amount: 0,
	currency: '',
	amount_usd: 0,
	enabled: true,
})
const tierForm = reactive(blankTier())
const planForm = reactive(blankPlan())
const assign = (target: Record<string, any>, value: Record<string, any>) => {
	Object.keys(target).forEach((key) => delete target[key])
	Object.assign(target, value)
}

const newTier = () => {
	assign(tierForm, blankTier())
	tierDialog.value = true
}
const editTier = (tier: any) => {
	assign(tierForm, { ...blankTier(), ...tier, enabled: Boolean(tier.enabled) })
	tierDialog.value = true
}
const newPlan = () => {
	assign(planForm, blankPlan())
	planDialog.value = true
}
const editPlan = (plan: any) => {
	assign(planForm, { ...blankPlan(), ...plan, enabled: Boolean(plan.enabled) })
	planDialog.value = true
}
const interval = (plan: any) =>
	`${plan.interval_count} ${plan.billing_interval.toLowerCase()}${plan.interval_count === 1 ? '' : 's'}`

const validateTier = () => {
	if (!tierForm.tier_name.trim()) return __('Tier name is required.')
	if (Number(tierForm.rank) <= 0) return __('Rank must be greater than zero.')
	return ''
}
const validatePlan = () => {
	if (!planForm.plan_name.trim()) return __('Plan name is required.')
	if (!planForm.tier) return __('Tier is required.')
	if (!planForm.currency) return __('Currency is required.')
	if (Number(planForm.interval_count) <= 0)
		return __('Interval count must be greater than zero.')
	if (Number(planForm.amount) <= 0)
		return __('Amount must be greater than zero.')
	return ''
}
const save = (
	resource: any,
	form: Record<string, any>,
	dialog: { value: boolean },
	validationError: string,
) => {
	if (saving.value) return
	if (validationError) {
		toast.error(validationError)
		return
	}
	saving.value = true
	const payload = { ...form, enabled: form.enabled ? 1 : 0 }
	if (!payload.name) delete payload.name
	const operation = form.name ? resource.setValue : resource.insert
	let request
	try {
		request = operation.submit(payload, {
			onSuccess() {
				dialog.value = false
				toast.success(__('Saved successfully'))
				resource.reload()
			},
			onError(error: any) {
				toast.error(error.messages?.[0] || error.message || error)
			},
		})
	} catch (error: any) {
		toast.error(error.messages?.[0] || error.message || error)
		saving.value = false
		return
	}
	Promise.resolve(request)
		.catch(() => undefined)
		.finally(() => {
			saving.value = false
		})
}
const saveTier = () => save(tiers, tierForm, tierDialog, validateTier())
const savePlan = () => save(plans, planForm, planDialog, validatePlan())
const remove = (resource: any, name: string) => {
	if (!window.confirm(__('Delete {0}?').format(name))) return
	resource.delete.submit(name, {
		onSuccess() {
			resource.reload()
			toast.success(__('Deleted successfully'))
		},
		onError(error: any) {
			toast.error(error.messages?.[0] || error.message || error)
		},
	})
}
const removeTier = (name: string) => remove(tiers, name)
const removePlan = (name: string) => remove(plans, name)
</script>
