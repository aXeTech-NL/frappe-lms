# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from lms.lms.utils import PRIVILEGED_ROLES


class LMSLessonNote(Document):
	def validate(self):
		if not self.lesson or PRIVILEGED_ROLES & set(frappe.get_roles()):
			return
		course = frappe.db.get_value("Course Lesson", self.lesson, "course")
		if not course:
			return
		from lms.lms.permissions import get_course_entitlement

		entitlement = get_course_entitlement(
			course,
			"consume",
			user=frappe.session.user,
			context={"lesson": self.lesson, "is_preview": False},
		)
		if not entitlement.handled:
			return
		if not frappe.db.exists("LMS Enrollment", {"course": course, "member": frappe.session.user}):
			frappe.throw(_("You must be enrolled before saving lesson notes."), frappe.PermissionError)
		if not entitlement.allowed:
			frappe.throw(_("You do not currently have access to this lesson."), frappe.PermissionError)
