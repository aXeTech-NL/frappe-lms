# Copyright (c) 2023, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class LMSAssignment(Document):
	pass


def has_permission(doc, ptype="read", user=None):
	from lms.lms.access import subscriptions_enabled

	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	staff = {"Moderator", "Course Creator", "Batch Evaluator", "System Manager"}
	if not subscriptions_enabled():
		return True
	if ptype not in ("read", "select", "print"):
		return user == "Administrator" or bool(roles & staff)

	from lms.lms.permissions import can_access_assessment

	return can_access_assessment(doc.doctype, doc.name, user=user)


def get_permission_query_conditions(user=None):
	from lms.lms.access import subscriptions_enabled

	if not subscriptions_enabled():
		return ""
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or roles & {
		"Moderator",
		"Course Creator",
		"Batch Evaluator",
		"System Manager",
	}:
		return ""

	from lms.lms.permissions import can_access_assessment

	allowed = [
		name
		for name in frappe.get_all("LMS Assignment", pluck="name")
		if can_access_assessment("LMS Assignment", name, user=user)
	]
	if not allowed:
		return "1 = 0"
	return f"`tabLMS Assignment`.name in ({', '.join(frappe.db.escape(name) for name in allowed)})"
