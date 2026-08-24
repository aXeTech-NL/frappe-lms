# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from lms.lms.utils import PRIVILEGED_ROLES


class LMSLessonNote(Document):
	def validate(self):
		if PRIVILEGED_ROLES & set(frappe.get_roles()):
			return

		from lms.lms.access import subscriptions_enabled

		if not subscriptions_enabled():
			return

		if self.member and self.member != frappe.session.user:
			frappe.throw(_("You can only manage notes for your own account."), frappe.PermissionError)
		self.member = frappe.session.user

		from lms.lms.permissions import can_access_lesson

		if not can_access_lesson(self.lesson):
			frappe.throw(_("You do not have access to this lesson."), frappe.PermissionError)
