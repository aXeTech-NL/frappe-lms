# Copyright (c) 2024, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from lms.lms.utils import guest_access_allowed


class LMSProgram(Document):
	def validate(self):
		self.validate_program_courses()
		self.validate_program_members()
		self.validate_pricing()
		self.validate_subscription_tier()
		self.update_count()

	def validate_program_courses(self):
		courses = [row.course for row in self.program_courses]
		duplicates = {course for course in courses if courses.count(course) > 1}
		if len(duplicates):
			frappe.throw(
				_("Course {0} has already been added to this program.").format(
					frappe.bold(next(iter(duplicates)))
				)
			)

	def validate_program_members(self):
		members = [row.member for row in self.program_members]
		duplicates = {member for member in members if members.count(member) > 1}
		if len(duplicates):
			frappe.throw(
				_("Member {0} has already been added to this program.").format(
					frappe.bold(next(iter(duplicates)))
				)
			)

	def validate_pricing(self):
		# Pricing fields are ignored by commerce while subscriptions are disabled,
		# but must remain editable so an existing Program can still be maintained
		# without silently clearing its future configuration.
		if self.paid_program and "payments" not in frappe.get_installed_apps():
			frappe.throw(_("Please install the Payments App to create a paid program."))
		if self.paid_program and (flt(self.program_price) <= 0 or not self.currency):
			frappe.throw(_("Amount and currency are required for paid programs."))

	def validate_subscription_tier(self):
		from lms.lms.access import subscriptions_enabled

		if not subscriptions_enabled() or not self.required_subscription_tier:
			return

		program_rank = frappe.db.get_value("LMS Subscription Tier", self.required_subscription_tier, "rank")
		if not program_rank or not frappe.db.get_value(
			"LMS Subscription Tier", self.required_subscription_tier, "enabled"
		):
			frappe.throw(_("The selected subscription tier is not enabled."))

		course_names = [row.course for row in self.program_courses]
		if not course_names:
			return
		course_tiers = frappe.get_all(
			"LMS Course",
			filters={"name": ["in", course_names], "required_subscription_tier": ["is", "set"]},
			pluck="required_subscription_tier",
		)
		if not course_tiers:
			return
		max_course_rank = max(
			frappe.get_all("LMS Subscription Tier", filters={"name": ["in", course_tiers]}, pluck="rank")
			or [0]
		)
		if program_rank < max_course_rank:
			frappe.throw(
				_("Program tier must be at least as high as every subscription course in the program.")
			)

	def update_count(self):
		course_count = len(self.program_courses)
		member_count = len(self.program_members)

		if self.course_count != course_count:
			self.course_count = course_count

		if self.member_count != member_count:
			self.member_count = member_count

	def on_update(self):
		from lms.lms.access import subscriptions_enabled

		if subscriptions_enabled():
			from lms.lms.subscriptions import sync_program_course_enrollments

			sync_program_course_enrollments(program=self.name)

	def on_payment_authorized(self, payment_status):
		if payment_status in ("Authorized", "Completed"):
			from lms.lms.utils import update_payment_record

			update_payment_record("LMS Program", self.name)

	def on_trash(self):
		# Retain course progress while removing the now-invalid Program source link.
		frappe.db.set_value(
			"LMS Enrollment",
			{"enrollment_from_program": self.name},
			"enrollment_from_program",
			None,
			update_modified=False,
		)


def has_permission(doc, ptype="read", user=None):
	user = user or frappe.session.user

	if user == "Guest" and not guest_access_allowed():
		return False

	roles = frappe.get_roles(user)
	if "Moderator" in roles or "Course Creator" in roles:
		return True

	if ptype not in ("read", "select", "print"):
		return False

	is_enrolled = frappe.db.exists("LMS Program Member", {"parent": doc.name, "member": user})
	if is_enrolled:
		return True

	is_program_published = frappe.db.get_value("LMS Program", doc.name, "published")
	if is_program_published:
		return True

	return False


def get_permission_query_conditions(user=None):
	"""List-read counterpart of has_permission above: published, or a member."""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""

	if user == "Guest" and not guest_access_allowed():
		return "1 = 0"

	roles = frappe.get_roles(user)
	if "Moderator" in roles or "Course Creator" in roles:
		return ""

	escaped = frappe.db.escape(user)
	return f"""(`tabLMS Program`.published = 1 or `tabLMS Program`.name in (
		select parent from `tabLMS Program Member` where member = {escaped}
	))"""
