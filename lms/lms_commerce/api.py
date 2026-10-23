import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import get_datetime, now_datetime

from lms.lms_commerce.presentation import settings_flags


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
