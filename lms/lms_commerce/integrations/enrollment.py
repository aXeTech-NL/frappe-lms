import frappe
from frappe import _
from frappe.model.document import Document

from lms.lms_commerce.integrations.lms import decide_many


def validate_enrollment(doc: Document, method: str | None = None):
	"""Deny a new managed-course enrollment without replacing LMS eligibility checks.

	Frappe runs the native before_insert method before this doc-event hook. Native
	course staff may still enroll learners manually; that never grants Commerce
	access to the learner's lesson/assessment requests.
	"""
	from lms.lms.permissions import can_author_course

	if can_author_course(doc.course):
		return
	decision = decide_many(
		user=doc.member,
		requests=[
			{
				"key": "enrollment",
				"resource_type": "course",
				"resource_name": doc.course,
				"action": "enroll",
			}
		],
	)["enrollment"]
	if decision.get("handled") is False:
		return
	if decision.get("handled") is not True or decision.get("allowed") is not True:
		frappe.throw(
			_("You need Commerce access to this course before enrolling."),
			frappe.PermissionError,
		)
