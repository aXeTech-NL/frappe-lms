from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import frappe
from frappe.utils import add_days, now_datetime

from lms.lms.utils import get_course_details
from lms.lms_commerce.api import get_tier_options
from lms.lms_commerce.services.entitlements import grant_manual_entitlement, revoke_manual_entitlement
from lms.lms_commerce.tests.test_helpers import CommerceIntegrationTestCase


class TestTierOptions(CommerceIntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.student = self.create_user()
		self.basic = self.create_tier(rank=10)
		self.maximum = self.create_tier(rank=20)

	def grant(self, user, tier, **kwargs):
		frappe.set_user("Administrator")
		name = grant_manual_entitlement(user.name, "Tier", tier=tier.name, **kwargs)
		self.cleanup_items.append(("Commerce Entitlement", name))
		return name

	def test_own_effective_access_is_not_a_subscription_or_a_price(self):
		other = self.create_user()
		self.grant(self.student, self.basic)
		self.grant(other, self.maximum)
		frappe.set_user(self.student.name)
		result = get_tier_options()
		self.assertEqual(result["current_tier"], self.basic.name)
		self.assertFalse(result["subscription_checkout_available"])
		self.assertIsNone(result["course"])
		by_name = {tier.name: tier for tier in result["tiers"]}
		self.assertTrue(by_name[self.basic.name].current)
		self.assertFalse(by_name[self.maximum.name].included_in_current_access)
		self.assertNotIn("amount", by_name[self.basic.name])
		self.assertNotIn("member", by_name[self.basic.name])
		self.assertNotIn("subscription", result)

	def test_current_tier_uses_highest_active_rank(self):
		self.grant(self.student, self.basic)
		self.grant(self.student, self.maximum)
		frappe.set_user(self.student.name)
		result = get_tier_options()
		self.assertEqual(result["current_tier"], self.maximum.name)
		self.assertTrue(
			next(row for row in result["tiers"] if row.name == self.basic.name).included_in_current_access
		)

	def test_future_expired_revoked_and_disabled_tiers_do_not_become_current(self):
		for condition in ("future", "expired", "revoked", "disabled"):
			with self.subTest(condition=condition):
				frappe.set_user("Administrator")
				student = self.create_user()
				tier = self.create_tier(rank=30 + len(self.cleanup_items))
				period = {"starts_on": add_days(now_datetime(), 2)} if condition == "future" else {}
				if condition == "expired":
					period = {
						"starts_on": add_days(now_datetime(), -3),
						"ends_on": add_days(now_datetime(), -1),
					}
				grant = self.grant(student, tier, **period)
				if condition == "revoked":
					revoke_manual_entitlement(grant)
				if condition == "disabled":
					tier.enabled = 0
					tier.save()
				frappe.set_user(student.name)
				result = get_tier_options()
				self.assertIsNone(result["current_tier"])
				if condition == "disabled":
					self.assertNotIn(tier.name, [row.name for row in result["tiers"]])

	def test_published_course_requirement_is_resolved_by_server(self):
		course = self.create_course()
		self.create_offering(course, "Tier", self.maximum)
		frappe.set_user(self.student.name)
		result = get_tier_options(course.name)
		self.assertEqual(result["course"]["required_tier"], self.maximum.name)
		by_name = {tier.name: tier for tier in result["tiers"]}
		self.assertFalse(by_name[self.basic.name].meets_course_tier)
		self.assertTrue(by_name[self.maximum.name].meets_course_tier)
		self.assertFalse(get_course_details(course.name).commerce["allowed"])
		self.assertFalse(frappe.db.exists("Commerce Entitlement", {"member": self.student.name}))
		self.assertFalse(
			frappe.db.exists("LMS Enrollment", {"member": self.student.name, "course": course.name})
		)

	def test_private_course_and_native_permission_denial_are_not_exposed(self):
		course = self.create_course()
		course.published = 0
		course.save()
		frappe.set_user(self.student.name)
		with self.assertRaises(frappe.PermissionError):
			get_tier_options(course.name)
		frappe.set_user("Administrator")
		course.published = 1
		course.save()
		frappe.set_user(self.student.name)
		with (
			patch("lms.lms.permissions.can_access_course", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			get_tier_options(course.name)

	def test_guest_disabled_user_and_disabled_commerce_do_not_expose_choices(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_tier_options()
		frappe.set_user("Administrator")
		frappe.db.set_value("User", self.student.name, "enabled", 0)
		frappe.set_user(self.student.name)
		with self.assertRaises(frappe.PermissionError):
			get_tier_options()
		frappe.set_user("Administrator")
		frappe.db.set_single_value("Commerce Settings", "enabled", 0)
		result = get_tier_options()
		self.assertFalse(result["commerce_enabled"])
		self.assertEqual(result["tiers"], [])
		self.assertIsNone(result["current_tier"])

	def test_selection_does_not_take_member_rank_or_price_from_browser(self):
		frappe.set_user(self.student.name)
		for kwargs in (
			{"member": "Administrator"},
			{"rank": 20},
			{"amount": "0.01"},
			{"tier": self.maximum.name},
		):
			with self.assertRaises(TypeError):
				get_tier_options(**kwargs)
		for course in ("", "x" * 141):
			with self.assertRaises(frappe.ValidationError):
				get_tier_options(course)

	def test_course_entry_uses_native_base_path_even_with_checkout_off(self):
		course = self.create_course()
		self.create_offering(course, "Tier", self.basic)
		frappe.set_user(self.student.name)
		with patch("lms.hooks.get_lms_path", return_value="academy"):
			access = get_course_details(course.name).commerce
		self.assertFalse(access["allowed"])
		upgrade = next(offer for offer in access["offers"] if offer["kind"] == "upgrade")
		url = urlsplit(upgrade["url"])
		self.assertEqual(url.path, "/academy/access/tiers")
		self.assertEqual(parse_qs(url.query), {"course": [course.name]})
		frappe.set_user("Guest")
		self.assertEqual(
			[offer["kind"] for offer in get_course_details(course.name).commerce["offers"]], ["login"]
		)
		frappe.set_user("Administrator")
		self.assertEqual(get_course_details(course.name).commerce["offers"], [])

	def test_explicit_upgrade_url_is_not_duplicated_or_overwritten(self):
		course = self.create_course()
		self.create_offering(course, "Tier", self.basic, upgrade_url="https://example.test/configured")
		frappe.set_user(self.student.name)
		offers = get_course_details(course.name).commerce["offers"]
		self.assertEqual(len(offers), 1)
		self.assertEqual(offers[0]["url"], "https://example.test/configured")

	def test_unmanaged_and_purchase_only_courses_have_no_tier_requirement(self):
		course = self.create_course()
		frappe.set_user(self.student.name)
		self.assertIsNone(get_tier_options(course.name)["course"])
		frappe.set_user("Administrator")
		self.create_offering(course, "Purchase")
		frappe.set_user(self.student.name)
		self.assertIsNone(get_tier_options(course.name)["course"])
		self.assertFalse(
			any(offer["kind"] == "upgrade" for offer in get_course_details(course.name).commerce["offers"])
		)
