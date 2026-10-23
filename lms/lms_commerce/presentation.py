"""Enrich native LMS responses; never fetch or replace the native course list."""

import frappe
from frappe import _
from frappe.utils import fmt_money

from lms.lms_commerce.integrations.lms import MAX_REQUESTS, decide_many
from lms.lms_commerce.utils import validate_safe_url


def decorate_courses(courses: list) -> list:
	if not courses or not frappe.db.get_single_value("Commerce Settings", "enabled"):
		return courses
	for start in range(0, len(courses), MAX_REQUESTS):
		_decorate_page(courses[start : start + MAX_REQUESTS])
	return courses


def _decorate_page(courses):
	from lms.lms.permissions import can_author_course

	names = list(dict.fromkeys(course.name for course in courses))
	decisions = decide_many(
		user=frappe.session.user,
		requests=[
			{"key": name, "resource_type": "course", "resource_name": name, "action": "catalog"}
			for name in names
		],
	)
	prices = {
		row.target_name: row
		for row in frappe.get_all(
			"Commerce Offering",
			filters={"enabled": 1, "target_doctype": "LMS Course", "target_name": ["in", names]},
			fields=["target_name", "access_policy", "required_tier", "amount", "currency"],
		)
	}
	for course in courses:
		decision = decisions[course.name]
		if not decision["handled"]:
			continue
		access = {key: decision.get(key) for key in ("handled", "allowed", "reason", "badge")}
		access["offers"] = [
			{**offer, "url": validate_safe_url(offer["url"], required=True)}
			for offer in decision.get("offers", [])
		]
		if not access["allowed"] and can_author_course(course.name, user=frappe.session.user):
			access.update(allowed=True, reason="staff_access", offers=[])
		price = prices.get(course.name)
		access["price_label"] = _price_label(price) if price else _("Access managed by Commerce")
		course["commerce"] = access


def _price_label(offering):
	if offering.access_policy == "Free":
		return _("Free")
	if offering.access_policy == "Tier":
		return _("Included in {0}").format(offering.required_tier)
	price = fmt_money(offering.amount, currency=offering.currency)
	if offering.access_policy == "Tier or Purchase":
		return _("Included in {0}, or {1}").format(offering.required_tier, price)
	return price


def settings_flags() -> dict:
	return {
		"commerce_enabled": bool(frappe.db.get_single_value("Commerce Settings", "enabled")),
		"can_manage_commerce": frappe.session.user != "Guest"
		and bool(frappe.has_permission("Commerce Settings", "read")),
	}
