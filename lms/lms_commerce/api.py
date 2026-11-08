import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import get_datetime, now_datetime

from lms.lms_commerce.presentation import settings_flags


@frappe.whitelist(methods=["GET", "POST"])
@rate_limit(limit=300, seconds=3600)
def get_tier_options(course: str | None = None) -> dict:
	"""Own effective tier and enabled choices, not an order or billing quote.

	Never infer a paid subscription from a manual grant, invent a price, or
	change access because the member selected a tier in the browser.
	"""
	from lms.lms.permissions import can_access_course
	from lms.lms_commerce.integrations.lms import TIER_POLICIES, _load_identity

	user = frappe.session.user
	if user == "Guest" or not frappe.db.get_value("User", user, "enabled"):
		frappe.throw(_("Please log in to view your access."), frappe.PermissionError)
	if course is not None and (not isinstance(course, str) or not course or len(course) > 140):
		frappe.throw(_("Invalid course."))
	result = {
		"commerce_enabled": settings_flags()["commerce_enabled"],
		"tiers": [],
		"current_tier": None,
		"course": None,
		"subscription_checkout_available": False,
	}
	if not result["commerce_enabled"]:
		return result

	if course:
		document = frappe.get_doc("LMS Course", course)
		# Use the LMS learner/catalog policy, not Desk DocPerm (Website Users
		# need not have Desk read permission to browse a published course).
		if not document.published or not can_access_course(course, user=user):
			frappe.throw(_("This course is not available."), frappe.PermissionError)
		offering = frappe.db.get_value(
			"Commerce Offering",
			{"target_doctype": "LMS Course", "target_name": course, "enabled": 1},
			["access_policy", "required_tier"],
			as_dict=True,
		)
		if offering and offering.access_policy in TIER_POLICIES:
			result["course"] = {
				"name": course,
				"title": document.title,
				"required_tier": offering.required_tier,
			}

	tiers = frappe.get_all(
		"Commerce Tier",
		filters={"enabled": 1},
		fields=["name", "rank", "description"],
		order_by="rank asc, name asc",
		limit=101,
	)
	if len(tiers) > 100:
		frappe.throw(_("Tier selection is temporarily unavailable. Please contact the administrator."))
	identity = _load_identity(user, [])
	required = next(
		(tier for tier in tiers if result["course"] and tier.name == result["course"]["required_tier"]), None
	)
	for tier in tiers:
		tier["current"] = tier.rank == identity.max_tier_rank
		tier["included_in_current_access"] = bool(
			identity.max_tier_rank and tier.rank <= identity.max_tier_rank
		)
		tier["meets_course_tier"] = (
			None if not result["course"] else bool(required and tier.rank >= required.rank)
		)
		if tier["current"]:
			result["current_tier"] = tier.name
	result["tiers"] = tiers
	return result


@frappe.whitelist()
@rate_limit(limit=300, seconds=3600)
def get_my_access(start: int | bool = 0) -> dict:
	"""Own grants only, including expiry, with bounded pagination. Not billing."""
	if frappe.session.user == "Guest":
		frappe.throw("Please log in", frappe.PermissionError)
	if type(start) is not int or not 0 <= start <= 10000:
		frappe.throw("Invalid page offset")
	status = settings_flags()
	if not status["commerce_enabled"]:
		return {**status, "grants": [], "has_more": False, "next_start": start}
	rows = frappe.get_all(
		"Commerce Entitlement",
		filters={"member": frappe.session.user},
		fields=["name", "scope", "tier", "target_doctype", "target_name", "status", "starts_on", "ends_on"],
		order_by="creation desc, name desc",
		start=start,
		page_length=51,
	)
	now = now_datetime()
	for row in rows:
		if row.status == "Active":
			if row.ends_on and get_datetime(row.ends_on) <= now:
				row.status = "Expired"
			elif row.starts_on and get_datetime(row.starts_on) > now:
				row.status = "Scheduled"
	return {
		**status,
		"grants": rows[:50],
		"has_more": len(rows) > 50,
		"next_start": start + min(50, len(rows)),
	}
