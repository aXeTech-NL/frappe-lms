from unittest.mock import patch

import frappe

from lms.lms.utils import get_course_details, get_courses
from lms.lms_commerce.api import get_my_access
from lms.lms_commerce.install import DOCTYPES, MODULE, before_migrate
from lms.lms_commerce.presentation import settings_flags
from lms.lms_commerce.services.entitlements import grant_manual_entitlement
from lms.lms_commerce.tests.test_helpers import CommerceIntegrationTestCase


class TestNativeCommerceIntegration(CommerceIntegrationTestCase):
	def grant(self, member, course):
		frappe.set_user("Administrator")
		name = grant_manual_entitlement(
			member, "Target", target_doctype="LMS Course", target_name=course.name
		)
		self.cleanup_items.append(("Commerce Entitlement", name))
		return name

	def test_native_list_and_detail_are_enriched_without_replacing_native_data(self):
		course = self.create_course()
		self.create_offering(course, "Purchase")
		student = self.create_user()
		frappe.set_user(student.name)
		rows = get_courses(filters={"title": course.title})
		self.assertEqual([row.name for row in rows], [course.name])
		self.assertTrue(rows[0].instructors)
		self.assertFalse(rows[0].commerce["allowed"])
		detail = get_course_details(course.name)
		self.assertEqual(detail.title, course.title)
		self.assertFalse(detail.paid_course)
		self.assertTrue(detail.commerce["price_label"])
		self.assertEqual(detail.commerce["offers"], [])
		self.grant(student.name, course)
		frappe.set_user(student.name)
		detail = get_course_details(course.name)
		self.assertTrue(detail.commerce["allowed"])
		self.assertFalse(detail.membership)

	def test_disabled_or_unmanaged_courses_keep_native_dtos(self):
		course = self.create_course()
		self.assertNotIn("commerce", get_course_details(course.name))
		self.create_offering(course, "Purchase")
		frappe.db.set_single_value("Commerce Settings", "enabled", 0)
		self.assertNotIn("commerce", get_course_details(course.name))
		self.assertFalse(settings_flags()["commerce_enabled"])
		self.assertTrue(settings_flags()["can_manage_commerce"])

	def test_staff_presentation_matches_native_author_access(self):
		course = self.create_course()
		self.create_offering(course, "Purchase")
		access = get_course_details(course.name).commerce
		self.assertTrue(access["allowed"])
		self.assertEqual(access["reason"], "staff_access")
		self.assertEqual(frappe.db.count("Commerce Entitlement", {"target_name": course.name}), 0)

	def test_my_access_never_returns_another_members_grants(self):
		course = self.create_course()
		student, other = self.create_user(), self.create_user()
		own = self.grant(student.name, course)
		self.grant(other.name, course)
		frappe.set_user(student.name)
		result = get_my_access()
		self.assertEqual([row.name for row in result["grants"]], [own])
		self.assertFalse(result["can_manage_commerce"])
		self.assertFalse(result["has_more"])
		with self.assertRaises(frappe.ValidationError):
			get_my_access(start=True)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_my_access()

	def test_legacy_app_cannot_coexist_with_internal_module(self):
		with patch("frappe.get_installed_apps", return_value=["frappe", "lms", "frappe_lms_commerce"]):
			with self.assertRaises(frappe.ValidationError):
				before_migrate()

	def test_internal_ownership_without_a_standalone_app(self):
		self.assertNotIn("frappe_lms_commerce", frappe.get_installed_apps())
		before_migrate()
		for doctype in DOCTYPES:
			self.assertEqual(frappe.db.get_value("DocType", doctype, "module"), MODULE)
		self.assertEqual(frappe.db.get_value("Module Def", MODULE, "app_name"), "lms")
