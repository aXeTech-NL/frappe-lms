# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Subscription-aware LMS entitlement decisions.

Enrollment remains the durable progress record.  When subscription behavior is
on, an enrollment alone is deliberately not authorization: this module also
checks its permanent provenance, a direct purchase, an active subscription, a
batch, or a currently-entitled Program.  The disabled branch mirrors the legacy
membership behavior so migrating the schema does not change existing sites.
"""

import frappe
from frappe.utils import cint, getdate, nowdate

ACTIVE_SUBSCRIPTION_STATUSES = ("Trial", "Active")
PERMANENT_ACCESS_SOURCES = ("Legacy", "Manual", "Purchase")
STAFF_ROLES = {"Moderator", "System Manager"}


def subscriptions_enabled() -> bool:
	"""Return false on disabled and pre-migrate sites."""
	if not frappe.get_meta("LMS Settings").has_field("enable_subscriptions"):
		return False
	return bool(frappe.get_cached_value("LMS Settings", None, "enable_subscriptions"))


def decision(allowed: bool, source: str = "", reason: str = "", **values) -> frappe._dict:
	return frappe._dict(allowed=allowed, source=source, reason=reason, **values)


def is_course_staff(course: str, user: str) -> bool:
	if user == "Administrator" or STAFF_ROLES & set(frappe.get_roles(user)):
		return True
	return bool(
		frappe.db.exists(
			"Course Instructor",
			{"instructor": user, "parent": course, "parenttype": "LMS Course"},
		)
	)


def is_program_staff(user: str) -> bool:
	roles = set(frappe.get_roles(user))
	return user == "Administrator" or bool(roles & {"Moderator", "Course Creator", "System Manager"})


def get_course_access(
	course: str,
	user: str | None = None,
	*,
	require_enrollment: bool = True,
) -> frappe._dict:
	user = user or frappe.session.user
	if not course or not frappe.db.exists("LMS Course", course):
		return decision(False, reason="missing_course")
	if not subscriptions_enabled():
		enrolled = frappe.db.exists("LMS Enrollment", {"course": course, "member": user})
		return decision(bool(enrolled), source="Enrollment" if enrolled else "", reason="not_enrolled")
	if is_course_staff(course, user):
		return decision(True, source="Staff")

	enrollment = frappe.db.get_value(
		"LMS Enrollment",
		{"course": course, "member": user},
		[
			"name",
			"access_source",
			"permanent_access",
			"payment",
			"subscription",
			"enrollment_from_batch",
			"enrollment_from_program",
		],
		as_dict=True,
	)
	if user == "Guest":
		return decision(False, reason="login_required")
	if require_enrollment and not enrollment:
		return decision(False, reason="not_enrolled")

	course_row = frappe.db.get_value(
		"LMS Course",
		course,
		["paid_course", "required_subscription_tier"],
		as_dict=True,
	)

	if enrollment:
		# Empty provenance is deliberately legacy permanent access. The migration
		# fills it, but this fallback keeps access safe during rolling migrations.
		# Only permanent source kinds may use permanent_access: an older/broken Batch
		# or Program row must not turn a dynamic membership into lifetime access.
		if not enrollment.access_source or (
			enrollment.permanent_access and enrollment.access_source in PERMANENT_ACCESS_SOURCES
		):
			return decision(True, source=enrollment.access_source or "Legacy", enrollment=enrollment.name)

	payment = _received_payment("LMS Course", course, user)
	if payment:
		return decision(True, source="Purchase", payment=payment, enrollment=enrollment and enrollment.name)

	batch_grant = _course_batch_grant(course, user)
	if batch_grant.allowed:
		batch_grant.enrollment = enrollment and enrollment.name
		return batch_grant

	program_grant = _course_program_grant(course, course_row, user)
	if program_grant.allowed:
		program_grant.enrollment = enrollment and enrollment.name
		return program_grant

	if not course_row.paid_course and not course_row.required_subscription_tier:
		return decision(True, source="Free", enrollment=enrollment and enrollment.name)

	if course_row.required_subscription_tier:
		subscription = get_qualifying_subscription(user, course_row.required_subscription_tier)
		if subscription:
			return decision(
				True,
				source="Subscription",
				subscription=subscription.name,
				tier=subscription.tier,
				enrollment=enrollment and enrollment.name,
			)

	reason = "purchase_or_subscription_required" if course_row.paid_course else "subscription_required"
	return decision(
		False,
		reason=reason,
		required_tier=course_row.required_subscription_tier,
		can_purchase=bool(course_row.paid_course),
	)


def get_program_access(
	program: str,
	user: str | None = None,
	*,
	require_membership: bool = True,
) -> frappe._dict:
	user = user or frappe.session.user
	if not frappe.db.exists("LMS Program", program):
		return decision(False, reason="missing_program")
	if is_program_staff(user):
		return decision(True, source="Staff")
	if not subscriptions_enabled():
		membership = frappe.db.exists("LMS Program Member", {"parent": program, "member": user})
		published = frappe.db.get_value("LMS Program", program, "published")
		allowed = bool(membership) if require_membership else bool(published)
		return decision(allowed, source="Membership" if membership else "", reason="not_enrolled")

	program_row = frappe.db.get_value(
		"LMS Program",
		program,
		["name", "published", "paid_program", "required_subscription_tier"],
		as_dict=True,
	)
	membership = frappe.db.get_value(
		"LMS Program Member",
		{"parent": program, "member": user},
		["name", "access_source", "permanent_access", "payment", "subscription"],
		as_dict=True,
	)
	if user == "Guest":
		return decision(False, reason="login_required")
	if require_membership and not membership:
		return decision(False, reason="not_enrolled")
	if not program_row.published and not membership:
		return decision(False, reason="unpublished")

	if membership and (
		not membership.access_source
		or (membership.permanent_access and membership.access_source in PERMANENT_ACCESS_SOURCES)
	):
		return decision(True, source=membership.access_source or "Legacy", membership=membership.name)

	payment = _received_payment("LMS Program", program, user)
	if payment:
		return decision(True, source="Purchase", payment=payment, membership=membership and membership.name)

	if not program_row.paid_program and not program_row.required_subscription_tier:
		return decision(True, source="Free", membership=membership and membership.name)

	if program_row.required_subscription_tier:
		subscription = get_qualifying_subscription(user, program_row.required_subscription_tier)
		if subscription:
			return decision(
				True,
				source="Subscription",
				subscription=subscription.name,
				tier=subscription.tier,
				membership=membership and membership.name,
			)

	reason = "purchase_or_subscription_required" if program_row.paid_program else "subscription_required"
	return decision(
		False,
		reason=reason,
		required_tier=program_row.required_subscription_tier,
		can_purchase=bool(program_row.paid_program),
	)


def get_qualifying_subscription(user: str, required_tier: str) -> frappe._dict | None:
	required_rank = cint(frappe.db.get_value("LMS Subscription Tier", required_tier, "rank"))
	if not required_rank:
		return None

	today = getdate(nowdate())
	subscriptions = frappe.get_all(
		"LMS Subscription",
		filters={
			"member": user,
			"status": ["in", ACTIVE_SUBSCRIPTION_STATUSES],
			"current_period_end": [">=", today],
		},
		fields=["name", "tier", "current_period_start", "current_period_end"],
		order_by="current_period_end desc",
	)
	for subscription in subscriptions:
		if subscription.current_period_start and getdate(subscription.current_period_start) > today:
			continue
		rank = cint(frappe.db.get_value("LMS Subscription Tier", subscription.tier, "rank"))
		if rank >= required_rank:
			return subscription
	return None


def get_allowed_enrolled_courses(user: str) -> list[str]:
	if not subscriptions_enabled():
		return frappe.get_all("LMS Enrollment", {"member": user}, pluck="course")
	courses = frappe.get_all("LMS Enrollment", {"member": user}, pluck="course")
	return [course for course in courses if get_course_access(course, user).allowed]


def provenance_for_course_enrollment(
	course: str,
	user: str,
	*,
	enrollment_from_batch: str | None = None,
	enrollment_from_program: str | None = None,
) -> frappe._dict:
	if not subscriptions_enabled():
		return frappe._dict(access_source="Legacy", permanent_access=1)
	if enrollment_from_batch:
		return frappe._dict(access_source="Batch", permanent_access=0)
	if enrollment_from_program:
		program = get_program_access(enrollment_from_program, user)
		# Course access derived from a Program is always dynamic. The Program
		# membership itself may be permanent (purchase/manual/legacy), but removing
		# this Course from the Program must remove only this derived grant.
		return frappe._dict(
			access_source="Program",
			permanent_access=0,
			subscription=program.get("subscription"),
		)

	course_row = frappe.db.get_value(
		"LMS Course", course, ["paid_course", "required_subscription_tier"], as_dict=True
	)
	payment = _received_payment("LMS Course", course, user)
	if payment:
		return frappe._dict(access_source="Purchase", permanent_access=1, payment=payment)
	if not course_row.paid_course and not course_row.required_subscription_tier:
		return frappe._dict(access_source="Free", permanent_access=0)
	if course_row.required_subscription_tier:
		subscription = get_qualifying_subscription(user, course_row.required_subscription_tier)
		if subscription:
			return frappe._dict(
				access_source="Subscription",
				permanent_access=0,
				subscription=subscription.name,
			)
	return frappe._dict()


def _received_payment(doctype: str, docname: str, user: str) -> str | None:
	# payment_received is the established fulfillment flag and remains the
	# rolling-migration-safe authority. Existing paid rows can have NULL in the
	# new payment_status column until the data patch runs.
	return frappe.db.exists(
		"LMS Payment",
		{
			"payment_for_document_type": doctype,
			"payment_for_document": docname,
			"member": user,
			"payment_received": 1,
		},
	)


def _course_batch_grant(course: str, user: str) -> frappe._dict:
	"""Return a dynamic grant through any current batch/course membership pair."""
	batches = frappe.get_all("Batch Course", {"course": course}, pluck="parent")
	if not batches:
		return decision(False, reason="no_batch_entitlement")

	batch = frappe.db.exists(
		"LMS Batch Enrollment",
		{"batch": ["in", batches], "member": user},
	)
	if not batch:
		return decision(False, reason="no_batch_entitlement")

	batch_name = frappe.db.get_value("LMS Batch Enrollment", batch, "batch")
	return decision(True, source="Batch", batch=batch_name)


def _course_program_grant(course: str, course_row: frappe._dict, user: str) -> frappe._dict:
	programs = frappe.get_all("LMS Program Course", {"course": course}, pluck="parent")
	for program in programs:
		if not frappe.db.exists("LMS Program Member", {"parent": program, "member": user}):
			continue
		grant = get_program_access(program, user)
		if not grant.allowed:
			continue
		# A free Program is not a route around a paid/tiered Course. Purchased,
		# legacy/manual and subscription-backed Programs are bundle entitlements.
		if grant.source == "Free" and (course_row.paid_course or course_row.required_subscription_tier):
			continue
		if grant.source == "Subscription" and course_row.required_subscription_tier:
			program_rank = cint(frappe.db.get_value("LMS Subscription Tier", grant.tier, "rank"))
			course_rank = cint(
				frappe.db.get_value("LMS Subscription Tier", course_row.required_subscription_tier, "rank")
			)
			if program_rank < course_rank:
				continue
		return decision(
			True,
			source="Program",
			program=program,
			program_source=grant.source,
			subscription=grant.get("subscription"),
			payment=grant.get("payment"),
		)
	return decision(False, reason="no_program_entitlement")
