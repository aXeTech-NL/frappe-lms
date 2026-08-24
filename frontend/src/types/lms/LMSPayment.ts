export interface LMSPayment {
	creation: string
	name: string
	modified: string
	owner: string
	modified_by: string
	docstatus: 0 | 1 | 2
	parent?: string
	parentfield?: string
	parenttype?: string
	idx?: number
	/**	Order ID : Data	*/
	order_id?: string
	/**	Payment ID : Data	*/
	payment_id?: string
	/**	Amount : Currency	*/
	amount: number
	/**	Coupon : Link - LMS Coupon	*/
	coupon?: string
	/**	Discount Amount : Currency	*/
	discount_amount?: number
	/**	Currency : Link - Currency	*/
	currency: string
	/**	GSTIN : Data	*/
	gstin?: string
	/**	PAN : Data	*/
	pan?: string
	/**	Address : Link - Address	*/
	address: string
	/**	Payment Received : Check	*/
	payment_received?: 0 | 1
	/**	Billing Name : Data	*/
	billing_name: string
	/**	Member : Link - User	*/
	member: string
	/**	Payment for Document Type : Select	*/
	payment_for_document_type:
		| ''
		| 'LMS Course'
		| 'LMS Batch'
		| 'LMS Program'
		| 'LMS Subscription'
	/**	Payment for Document : Dynamic Link - payment_for_document_type	*/
	payment_for_document: string
	/**	Source : Link - LMS Source	*/
	source: string
	/**	Payment for Certificate : Check	*/
	payment_for_certificate?: 0 | 1
	/**	Coupon Code : Data	*/
	coupon_code?: string
	/**	Amount with GST : Currency	*/
	amount_with_gst?: number
	/**	Original Amount : Currency	*/
	original_amount?: number
	/**	Member Consent : Check	*/
	member_consent?: 0 | 1
	/**	Payment Status : Select	*/
	payment_status?: 'Pending' | 'Paid' | 'Failed' | 'Refunded'
	/**	Subscription : Link - LMS Subscription	*/
	subscription?: string
	/**	Related Payment : Link - LMS Payment	*/
	related_payment?: string
	/**	Payment Gateway : Data	*/
	payment_gateway?: string
	/**	Provider Event ID : Data	*/
	provider_event_id?: string
	/**	Provider Event Key : Data	*/
	provider_event_key?: string
	/**	Provider Payment Reference : Data	*/
	provider_payment_reference?: string
	/**	Paid On : Datetime	*/
	paid_on?: string
	/**	Failure Reason : Small Text	*/
	failure_reason?: string
	/**	Billing Period Start : Date	*/
	billing_period_start?: string
	/**	Billing Period End : Date	*/
	billing_period_end?: string
}
