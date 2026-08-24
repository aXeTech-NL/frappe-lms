export interface LMSSubscriptionPlan {
	creation: string
	name: string
	modified: string
	owner: string
	modified_by: string
	docstatus: 0 | 1 | 2
	idx?: number
	/** Plan Name : Data */
	plan_name: string
	/** Subscription Tier : Link - LMS Subscription Tier */
	tier: string
	/** Enabled : Check */
	enabled?: 0 | 1
	/** Billing Interval : Select */
	billing_interval: 'Month' | 'Year'
	/** Interval Count : Int */
	interval_count: number
	/** Amount : Currency */
	amount: number
	/** Currency : Link - Currency */
	currency: string
	/** Amount (USD) : Currency */
	amount_usd?: number
}
