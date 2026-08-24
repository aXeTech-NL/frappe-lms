# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class LMSSubscriptionPlan(Document):
	def validate(self):
		if cint(self.interval_count) <= 0:
			frappe.throw(_("Subscription interval count must be greater than zero."))
		if flt(self.amount) <= 0 or not self.currency:
			frappe.throw(_("Amount and currency are required for subscription plans."))
		if not frappe.db.get_value("LMS Subscription Tier", self.tier, "enabled"):
			frappe.throw(_("The selected subscription tier is not enabled."))
