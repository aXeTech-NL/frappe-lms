# Copyright (c) 2026, Frappe and Contributors
# See license.txt

import base64
import json
import os
import tempfile
from unittest.mock import patch

import frappe
from frappe.tests.test_api import FrappeAPITestCase

from lms.lms.doctype.course_lesson import course_lesson
from lms.lms.doctype.course_lesson.course_lesson import save_progress, serve_resource
from lms.lms.doctype.lms_quiz.lms_quiz import check_answer
from lms.lms.permissions import can_access_lesson, can_access_quiz
from lms.lms.test_helpers import BaseTestUtils
from lms.lms.utils import get_course_details, get_courses


class TestExternalEntitlementAccess(BaseTestUtils, FrappeAPITestCase):
	def setUp(self):
		super().setUp()
		self.original_get_hooks = frappe.get_hooks
		self.original_get_attr = frappe.get_attr
		self.addCleanup(setattr, frappe, "get_hooks", self.original_get_hooks)
		self.addCleanup(setattr, frappe, "get_attr", self.original_get_attr)
		hash = frappe.generate_hash(length=6)
		self.instructor = self._create_user(
			f"ent-instr-{hash}@example.com", "Ent", "Instructor", ["Course Creator", "Moderator"]
		)
		self.student = self._create_user(f"ent-student-{hash}@example.com", "Ent", "Student", ["LMS Student"])
		self.outsider = self._create_user(f"ent-out-{hash}@example.com", "Ent", "Outsider", ["LMS Student"])
		self.course = self._create_course(
			title=f"Entitlement Course {hash}", instructor=self.instructor.email
		)
		self.chapter = self._create_chapter(f"Entitlement Chapter {hash}", self.course.name)
		self.lesson = self._create_lesson(f"Entitlement Lesson {hash}", self.chapter.name, self.course.name)
		self._create_chapter_reference(self.course.name, self.chapter.name)
		self._create_lesson_reference(self.chapter.name, self.lesson.name)
		self._create_enrollment(self.student.email, self.course.name)

		self.paid_course = self._create_course(
			title=f"Managed Paid Course {hash}", instructor=self.instructor.email
		)
		self.paid_course.db_set(
			{"paid_course": 1, "course_price": 50, "currency": "USD"},
			update_modified=False,
		)

		self.questions = self._create_quiz_questions()
		self.quiz = self._create_quiz(title=f"Entitlement Quiz {hash}")
		self.quiz.db_set("show_answers", 1)
		quiz_content = json.dumps({"blocks": [{"type": "quiz", "data": {"quiz": self.quiz.name}}]})
		self.quiz_lesson = self._create_lesson(
			f"Entitlement Quiz Lesson {hash}", self.chapter.name, self.course.name, quiz_content
		)
		self._create_lesson_reference(self.chapter.name, self.quiz_lesson.name)

		self.rules = {}
		self.provider_calls = []
		frappe.get_hooks = lambda hook=None, *args, **kwargs: (
			["lms.tests.test_external_entitlement_access.provider"]
			if hook == "lms_entitlement_provider"
			else self.original_get_hooks(hook, *args, **kwargs)
		)
		frappe.get_attr = lambda path: (
			self._provider
			if path == "lms.tests.test_external_entitlement_access.provider"
			else self.original_get_attr(path)
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def _provider(self, *, user, requests, contract_version=1):
		self.provider_calls.append((user, requests, contract_version))
		managed = {self.course.name, self.paid_course.name}
		out = {}
		for request in requests:
			if request["resource_name"] not in managed:
				out[request["key"]] = {"handled": False, "allowed": False}
				continue
			allowed = self.rules.get((user, request["resource_name"], request["action"]), True)
			out[request["key"]] = {
				"handled": True,
				"allowed": allowed,
				"reason": "upgrade_required" if not allowed else "",
				"badge": {"label": "Max", "theme": "violet", "icon": "lock"},
				"offers": []
				if allowed
				else [
					{
						"kind": "upgrade",
						"label": "Upgrade to Max",
						"url": "/commerce/plans",
						"variant": "outline",
					}
				],
			}
		return out

	def _allow(self, user, course, action, allowed):
		self.rules[(user, course, action)] = allowed
		if hasattr(frappe.local, "lms_entitlement_decisions"):
			delattr(frappe.local, "lms_entitlement_decisions")

	def test_catalog_is_decorated_in_one_bulk_provider_call(self):
		frappe.set_user(self.student.email)
		self.provider_calls.clear()
		courses = get_courses(filters={"name": ["in", [self.course.name, self.paid_course.name]]})
		matching = {course.name: course for course in courses}
		self.assertEqual(set(matching), {self.course.name, self.paid_course.name})
		self.assertTrue(matching[self.course.name].entitlement.handled)
		self.assertEqual(matching[self.course.name].entitlement.badge.label, "Max")
		self.assertEqual(len(self.provider_calls), 1)
		self.assertEqual(len(self.provider_calls[0][1]), 2)
		self.assertEqual(self.provider_calls[0][2], 1)

	def test_course_detail_carries_denied_offers_without_hiding_metadata(self):
		self._allow(self.student.email, self.course.name, "view", False)
		frappe.set_user(self.student.email)
		details = get_course_details(self.course.name)
		self.assertEqual(details.title, self.course.title)
		self.assertFalse(details.entitlement.allowed)
		self.assertEqual(details.entitlement.offers[0].url, "/commerce/plans")
		self.assertEqual(set(details.entitlements), {"view", "enroll", "consume"})
		self.assertEqual(len(self.provider_calls[-1][1]), 3)

	def test_managed_paid_course_uses_provider_instead_of_lms_payment(self):
		self._allow(self.outsider.email, self.paid_course.name, "enroll", True)
		frappe.set_user(self.outsider.email)
		enrollment = frappe.get_doc(
			{
				"doctype": "LMS Enrollment",
				"course": self.paid_course.name,
				"member": self.outsider.email,
			}
		).insert(ignore_permissions=True)
		self.cleanup_items.append(("LMS Enrollment", enrollment.name))
		self.assertFalse(
			frappe.db.exists(
				"LMS Payment",
				{"member": self.outsider.email, "payment_for_document": self.paid_course.name},
			)
		)

	def test_managed_enrollment_is_denied_and_cannot_target_another_user(self):
		self._allow(self.outsider.email, self.paid_course.name, "enroll", False)
		frappe.set_user(self.outsider.email)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "LMS Enrollment",
					"course": self.paid_course.name,
					"member": self.outsider.email,
				}
			).insert(ignore_permissions=True)

		self._allow(self.outsider.email, self.paid_course.name, "enroll", True)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "LMS Enrollment",
					"course": self.paid_course.name,
					"member": self.student.email,
				}
			).insert(ignore_permissions=True)

	def test_expired_external_access_blocks_lesson_and_progress_but_keeps_enrollment(self):
		self._allow(self.student.email, self.course.name, "consume", False)
		self._allow(self.student.email, self.course.name, "progress", False)
		frappe.set_user(self.student.email)
		self.assertFalse(can_access_lesson(self.lesson.name))
		with self.assertRaises(frappe.PermissionError):
			save_progress(self.lesson.name, self.course.name)
		self.assertTrue(
			frappe.db.exists("LMS Enrollment", {"course": self.course.name, "member": self.student.email})
		)

	def test_direct_course_progress_insert_obeys_provider(self):
		self._allow(self.student.email, self.course.name, "progress", False)
		frappe.set_user(self.student.email)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "LMS Course Progress",
					"course": self.course.name,
					"lesson": self.lesson.name,
					"member": self.student.email,
					"status": "Complete",
				}
			).insert(ignore_permissions=True)

	def test_course_progress_rejects_forged_course_for_authoritative_lesson(self):
		self._allow(self.student.email, self.course.name, "progress", False)
		self._allow(self.student.email, self.paid_course.name, "progress", True)
		frappe.set_user(self.student.email)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "LMS Course Progress",
					"course": self.paid_course.name,
					"lesson": self.lesson.name,
					"member": self.student.email,
					"status": "Complete",
				}
			).insert(ignore_permissions=True)

	def test_save_progress_rejects_forged_course_before_updating_existing_scorm(self):
		progress = frappe.get_doc(
			{
				"doctype": "LMS Course Progress",
				"lesson": self.lesson.name,
				"member": self.student.email,
				"status": "Partially Complete",
				"scorm_content": "original",
			}
		).insert(ignore_permissions=True)
		self.cleanup_items.append(("LMS Course Progress", progress.name))
		# Simulate a historical/forged partial row. The endpoint must validate the
		# lesson's own course before reaching this raw SCORM update branch.
		frappe.db.set_value(
			"LMS Course Progress", progress.name, "course", self.paid_course.name, update_modified=False
		)
		self._allow(self.student.email, self.course.name, "progress", False)
		self._allow(self.student.email, self.paid_course.name, "progress", True)
		frappe.set_user(self.student.email)

		with self.assertRaises(frappe.PermissionError):
			save_progress(
				self.lesson.name,
				self.paid_course.name,
				{"is_complete": False, "scorm_content": "forged"},
			)

		stored = frappe.db.get_value(
			"LMS Course Progress", progress.name, ["course", "scorm_content"], as_dict=True
		)
		self.assertEqual(stored.course, self.paid_course.name)
		self.assertEqual(stored.scorm_content, "original")

	def test_quiz_and_live_answer_check_obey_course_entitlement(self):
		self._allow(self.student.email, self.course.name, "consume", False)
		frappe.set_user(self.student.email)
		self.assertFalse(can_access_quiz(self.quiz.name))
		with self.assertRaises(frappe.PermissionError):
			check_answer(
				self.quiz.name,
				self.questions[0].name,
				"Choices",
				json.dumps(["Option 1"]),
			)

	def test_denied_entitlement_blocks_private_lesson_bytes(self):
		private_file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"entitlement-{frappe.generate_hash(length=6)}.txt",
				"is_private": 1,
				"attached_to_doctype": "Course Lesson",
				"attached_to_name": self.lesson.name,
				"content": base64.b64encode(b"protected").decode(),
				"decode": True,
			}
		).insert(ignore_permissions=True)
		self.cleanup_items.append(("File", private_file.name))
		self.lesson.db_set(
			"content",
			json.dumps({"blocks": [{"type": "upload", "data": {"file_url": private_file.file_url}}]}),
		)
		self._allow(self.student.email, self.course.name, "consume", False)
		frappe.set_user(self.student.email)
		original = course_lesson._serve_private_file
		course_lesson._serve_private_file = lambda *_args, **_kwargs: object()
		try:
			with self.assertRaises(frappe.PermissionError):
				serve_resource(private_file.file_url)
		finally:
			course_lesson._serve_private_file = original

	def test_scorm_renderer_denies_bytes_and_legacy_public_files_are_relocated(self):
		self.chapter.db_set("is_scorm_package", 1)
		self._allow(self.student.email, self.course.name, "consume", False)
		frappe.set_user(self.student.email)

		from lms.page_renderers import SCORMRenderer, protect_legacy_scorm_packages

		renderer = SCORMRenderer(path=f"scorm/{self.course.name}/{self.chapter.title}/index.html")
		with self.assertRaises(frappe.PermissionError):
			renderer._check_permission()

		with tempfile.TemporaryDirectory() as site_root:

			def site_path(*parts):
				return os.path.join(site_root, *parts)

			public_dir = site_path("public", "scorm", self.course.name, self.chapter.title)
			private_dir = site_path("private", "scorm", self.course.name, self.chapter.title)
			os.makedirs(public_dir, exist_ok=True)
			with open(os.path.join(public_dir, "index.html"), "w") as file:
				file.write("protected")
			with patch("lms.page_renderers.frappe.get_site_path", side_effect=site_path):
				self.assertEqual(protect_legacy_scorm_packages(), 1)
			self.assertFalse(os.path.exists(os.path.join(public_dir, "index.html")))
			self.assertTrue(os.path.exists(os.path.join(private_dir, "index.html")))

	def test_no_provider_does_not_relocate_legacy_public_scorm(self):
		frappe.get_hooks = lambda hook=None, *args, **kwargs: (
			[] if hook == "lms_entitlement_provider" else self.original_get_hooks(hook, *args, **kwargs)
		)
		from lms.page_renderers import protect_legacy_scorm_packages

		folder = f"unmanaged-{frappe.generate_hash(length=8)}"
		with tempfile.TemporaryDirectory() as site_root:

			def site_path(*parts):
				return os.path.join(site_root, *parts)

			public_dir = site_path("public", "scorm", folder)
			os.makedirs(public_dir, exist_ok=True)
			path = os.path.join(public_dir, "index.html")
			with open(path, "w") as file:
				file.write("legacy")
			with patch("lms.page_renderers.frappe.get_site_path", side_effect=site_path):
				self.assertEqual(protect_legacy_scorm_packages(), 0)
			self.assertTrue(os.path.exists(path))

	def test_no_provider_preserves_legacy_live_answer_check(self):
		frappe.get_hooks = lambda hook=None, *args, **kwargs: (
			[] if hook == "lms_entitlement_provider" else self.original_get_hooks(hook, *args, **kwargs)
		)
		frappe.set_user(self.student.email)
		result = check_answer(
			self.quiz.name,
			self.questions[0].name,
			"Choices",
			json.dumps(["Option 1"]),
		)
		self.assertIsInstance(result, list)

	def test_instructor_bypasses_provider_denial(self):
		self._allow(self.instructor.email, self.course.name, "consume", False)
		frappe.set_user(self.instructor.email)
		self.assertTrue(can_access_lesson(self.lesson.name))
