# Copyright (c) 2024, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

ACCESS_MANAGER_ROLES = {"Moderator", "Course Creator", "System Manager"}
PROTECTED_ACCESS_FIELDS = (
	"member",
	"access_source",
	"permanent_access",
	"payment",
	"subscription",
)


class LMSProgramMember(Document):
	def before_insert(self):
		if not self.access_source and ACCESS_MANAGER_ROLES & set(frappe.get_roles()):
			self.access_source = "Manual"
			self.permanent_access = 1
			self.flags.ignore_access_protection = True

	def validate(self):
		if self.flags.get("ignore_access_protection") or ACCESS_MANAGER_ROLES & set(frappe.get_roles()):
			return

		previous = None if self.is_new() else self.get_doc_before_save()
		for field in PROTECTED_ACCESS_FIELDS:
			self.set(field, previous.get(field) if previous else None)
