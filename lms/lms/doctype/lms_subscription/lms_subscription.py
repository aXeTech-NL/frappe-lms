# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate

BILLABLE_STATUSES = ("Trial", "Active", "Past Due")


class LMSSubscription(Document):
	def before_insert(self):
		self.owner = self.member

	def validate(self):
		self.set_plan_snapshot()
		self.validate_period()
		self.validate_single_billable_subscription()
		self.protect_identity_fields()

	def set_plan_snapshot(self):
		if self.is_new() or self.has_value_changed("plan"):
			plan = frappe.db.get_value(
				"LMS Subscription Plan",
				self.plan,
				[
					"tier",
					"enabled",
					"billing_interval",
					"interval_count",
					"amount",
					"currency",
				],
				as_dict=True,
			)
			if not plan or not plan.enabled:
				frappe.throw(_("The subscription plan is not enabled."))
			self.tier = plan.tier
			self.billing_interval = plan.billing_interval
			self.interval_count = plan.interval_count
			self.billing_amount = plan.amount
			self.billing_currency = plan.currency
		if not self.tier:
			frappe.throw(_("The subscription plan must belong to a tier."))
		if self.billing_interval not in ("Month", "Year") or cint(self.interval_count) <= 0:
			frappe.throw(_("The subscription billing interval is invalid."))
		if flt(self.billing_amount) <= 0 or not self.billing_currency:
			frappe.throw(_("The subscription billing amount and currency are required."))

	def validate_single_billable_subscription(self):
		if self.status not in BILLABLE_STATUSES or not self.member:
			return
		frappe.db.get_value("User", self.member, "name", for_update=True)
		other = frappe.db.exists(
			"LMS Subscription",
			{
				"member": self.member,
				"status": ["in", BILLABLE_STATUSES],
				"name": ["!=", self.name],
			},
		)
		if other:
			frappe.throw(_("A member can only have one active subscription."))

	def validate_period(self):
		if self.current_period_start and self.current_period_end:
			if getdate(self.current_period_end) < getdate(self.current_period_start):
				frappe.throw(_("Subscription period end cannot be before its start."))

		if self.status in ("Trial", "Active", "Past Due") and not self.current_period_end:
			frappe.throw(_("Current period end is required for an active subscription."))

	def protect_identity_fields(self):
		if self.is_new() or {"Moderator", "System Manager"} & set(frappe.get_roles()):
			return
		previous = self.get_doc_before_save()
		for field in (
			"member",
			"plan",
			"tier",
			"billing_interval",
			"interval_count",
			"billing_amount",
			"billing_currency",
			"status",
			"starts_on",
			"current_period_start",
			"current_period_end",
			"payment_gateway",
			"gateway_customer_id",
			"gateway_subscription_id",
			"latest_payment",
		):
			self.set(field, previous.get(field))

	def on_payment_authorized(self, payment_status):
		if payment_status in ("Authorized", "Completed"):
			from lms.lms.utils import update_payment_record

			update_payment_record("LMS Subscription", self.name)
