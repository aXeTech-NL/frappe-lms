export interface LMSSubscriptionTier {
	creation: string
	name: string
	modified: string
	owner: string
	modified_by: string
	docstatus: 0 | 1 | 2
	idx?: number
	/** Tier Name : Data */
	tier_name: string
	/** Enabled : Check */
	enabled?: 0 | 1
	/** Rank : Int */
	rank: number
	/** Description : Small Text */
	description?: string
}
