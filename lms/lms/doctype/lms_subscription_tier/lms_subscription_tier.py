# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class LMSSubscriptionTier(Document):
	def validate(self):
		if cint(self.rank) <= 0:
			frappe.throw(_("Subscription tier rank must be greater than zero."))
