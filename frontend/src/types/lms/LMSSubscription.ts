export interface LMSSubscription {
	creation: string
	name: string
	modified: string
	owner: string
	modified_by: string
	docstatus: 0 | 1 | 2
	idx?: number
	/** Member : Link - User */
	member: string
	/** Subscription Plan : Link - LMS Subscription Plan */
	plan: string
	/** Subscription Tier : Link - LMS Subscription Tier */
	tier: string
	/** Status : Select */
	status: 'Pending' | 'Trial' | 'Active' | 'Past Due' | 'Cancelled' | 'Expired'
	/** Cancel at Period End : Check */
	cancel_at_period_end?: 0 | 1
	/** Starts On : Date */
	starts_on?: string
	/** Current Period Start : Date */
	current_period_start?: string
	/** Current Period End : Date */
	current_period_end?: string
	/** Cancelled On : Datetime */
	cancelled_on?: string
	/** Billing Interval : Select */
	billing_interval: 'Month' | 'Year'
	/** Interval Count : Int */
	interval_count: number
	/** Billing Amount : Currency */
	billing_amount: number
	/** Billing Currency : Link - Currency */
	billing_currency: string
	/** Payment Gateway : Data */
	payment_gateway?: string
	/** Gateway Customer ID : Data */
	gateway_customer_id?: string
	/** Gateway Subscription ID : Data */
	gateway_subscription_id?: string
	/** Latest Payment : Link - LMS Payment */
	latest_payment?: string
}
