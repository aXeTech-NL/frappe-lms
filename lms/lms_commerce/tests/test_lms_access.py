from unittest.mock import patch

import frappe
from frappe.utils import add_days, now_datetime

from lms.lms.api import track_video_watch_duration
from lms.lms.doctype.course_lesson.course_lesson import save_progress
from lms.lms.permissions import can_access_lesson, can_access_quiz
from lms.lms.test_helpers import BaseTestUtils
from lms.lms.utils import get_courses, get_lesson
from lms.lms_commerce.services.entitlements import (
	grant_manual_entitlement,
	revoke_manual_entitlement,
)
from lms.page_renderers import SCORMRenderer


class TestLiveLMSCommerceAccess(BaseTestUtils):
	"""Real installed hooks, real LMS boundaries, isolated DB savepoint per test."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		capture = patch("lms.lms.doctype.course_lesson.course_lesson.capture")
		capture.start()
		self.addCleanup(capture.stop)
		self.token = frappe.generate_hash(length=8)
		self.student = self._create_user(
			f"commerce-gate-{self.token}@example.com", "Commerce", "Student", ["LMS Student"]
		)
		self.outsider = self._create_user(
			f"commerce-other-{self.token}@example.com", "Commerce", "Other", ["LMS Student"]
		)
		self.instructor = self._create_user(
			f"commerce-author-{self.token}@example.com", "Commerce", "Author", ["Course Creator"]
		)
		self.course = self._create_course(f"Commerce gate {self.token}", self.instructor.name)
		self.chapter = self._create_chapter(f"Gate {self.token}", self.course.name)
		self._create_chapter_reference(self.course.name, self.chapter.name)
		self.lesson = self._create_lesson(f"Gate lesson {self.token}", self.chapter.name, self.course.name)
		self._create_lesson_reference(self.chapter.name, self.lesson.name)
		self.quiz = self._create_quiz(self._create_quiz_questions(), title=f"Gate quiz {self.token}")
		frappe.db.set_value("Course Lesson", self.lesson.name, "quiz_id", self.quiz.name)
		self._create_enrollment(self.student.name, self.course.name)
		self.offering = frappe.get_doc(
			{
				"doctype": "Commerce Offering",
				"title": self.course.title,
				"target_doctype": "LMS Course",
				"target_name": self.course.name,
				"access_policy": "Purchase",
				"amount": 25,
				"currency": "USD",
				"enabled": 1,
			}
		).insert()
		frappe.db.set_single_value("Commerce Settings", "enabled", 1)
		self.as_user(self.student.name)

	def tearDown(self):
		self.as_user("Administrator")
		super().tearDown()

	def as_user(self, user):
		# Each switch models the next HTTP request, not a long-lived cached decision.
		frappe.set_user(user)
		frappe.local.lms_course_access_policy_cache = {}

	def grant(self, member=None, **kwargs):
		self.as_user("Administrator")
		return grant_manual_entitlement(
			member or self.student.name,
			"Target",
			target_doctype="LMS Course",
			target_name=self.course.name,
			**kwargs,
		)

	def test_enabled_denies_lesson_payload_quiz_list_progress_and_video(self):
		self.assertFalse(can_access_lesson(self.lesson.name))
		self.assertFalse(can_access_quiz(self.quiz.name))
		self.assertEqual(frappe.get_list("LMS Quiz", filters={"name": self.quiz.name}, pluck="name"), [])
		payload = get_lesson(self.course.name, 1, 1)
		self.assertEqual(payload.get("no_preview"), 1)
		self.assertNotIn("content", payload)
		self.assertNotIn("body", payload)
		with self.assertRaises(frappe.PermissionError):
			save_progress(self.lesson.name, self.course.name)
		with self.assertRaises(frappe.PermissionError):
			track_video_watch_duration(self.lesson.name, [{"source": "test-video", "watch_time": 10}])
		self.assertFalse(
			frappe.db.exists("LMS Course Progress", {"lesson": self.lesson.name, "member": self.student.name})
		)

	def test_disabling_commerce_or_offering_restores_native_access(self):
		for switch in ("commerce", "offering"):
			self.as_user("Administrator")
			frappe.db.set_single_value("Commerce Settings", "enabled", int(switch != "commerce"))
			frappe.db.set_value("Commerce Offering", self.offering.name, "enabled", int(switch != "offering"))
			self.as_user(self.student.name)
			self.assertTrue(can_access_lesson(self.lesson.name))
			self.assertTrue(can_access_quiz(self.quiz.name))
			self.assertEqual(
				frappe.get_list("LMS Quiz", filters={"name": self.quiz.name}, pluck="name"), [self.quiz.name]
			)

	def test_target_grant_allows_and_revocation_denies_on_next_request(self):
		grant = self.grant()
		self.as_user(self.student.name)
		self.assertTrue(can_access_lesson(self.lesson.name))
		self.assertTrue(can_access_quiz(self.quiz.name))
		self.assertEqual(
			frappe.get_list("LMS Quiz", filters={"name": self.quiz.name}, pluck="name"), [self.quiz.name]
		)
		save_progress(self.lesson.name, self.course.name)
		self.as_user("Administrator")
		revoke_manual_entitlement(grant)
		self.as_user(self.student.name)
		self.assertFalse(can_access_lesson(self.lesson.name))
		self.assertFalse(can_access_quiz(self.quiz.name))

	def test_future_and_expired_grants_do_not_unlock(self):
		grant = self.grant(starts_on=add_days(now_datetime(), 1))
		self.as_user(self.student.name)
		self.assertFalse(can_access_lesson(self.lesson.name))
		self.as_user("Administrator")
		revoke_manual_entitlement(grant)
		self.grant(ends_on=add_days(now_datetime(), -1))
		self.as_user(self.student.name)
		self.assertFalse(can_access_lesson(self.lesson.name))

	def test_elapsed_grant_expires_without_a_scheduler_or_status_update(self):
		grant = self.grant(ends_on=add_days(now_datetime(), 1))
		self.as_user(self.student.name)
		self.assertTrue(can_access_lesson(self.lesson.name))
		self.as_user("Administrator")
		frappe.db.set_value("Commerce Entitlement", grant, "ends_on", add_days(now_datetime(), -1))
		self.assertEqual(frappe.db.get_value("Commerce Entitlement", grant, "status"), "Active")
		self.as_user(self.student.name)
		self.assertFalse(can_access_lesson(self.lesson.name))

	def test_entitlement_cannot_bypass_native_payment_eligibility(self):
		self.grant(member=self.outsider.name)
		frappe.db.set_value("LMS Course", self.course.name, "paid_course", 1)
		self.as_user(self.outsider.name)
		with self.assertRaisesRegex(frappe.ValidationError, "payment"):
			self._create_enrollment(self.outsider.name, self.course.name)

	def test_entitlement_cannot_bypass_native_enrollment(self):
		self.grant(member=self.outsider.name)
		self.as_user(self.outsider.name)
		self.assertFalse(can_access_lesson(self.lesson.name))
		self.assertFalse(can_access_quiz(self.quiz.name))

	def test_course_staff_keep_native_access_without_grants(self):
		self.as_user(self.instructor.name)
		self.assertTrue(can_access_lesson(self.lesson.name))
		self.assertTrue(can_access_quiz(self.quiz.name))

	def test_stale_course_mirror_does_not_bypass_commerce(self):
		self.as_user("Administrator")
		other = self._create_course(f"Unmanaged {self.token}", self.instructor.name)
		self._create_enrollment(self.student.name, other.name)
		frappe.db.set_value("Course Lesson", self.lesson.name, "course", other.name)
		self.as_user(self.student.name)
		self.assertFalse(can_access_lesson(self.lesson.name))

	def test_learner_with_author_role_cannot_list_managed_lesson_content(self):
		self.as_user("Administrator")
		self.student.add_roles("Course Creator")
		# A former course author may still own the lesson and retain its role-level
		# read grant, while no longer being an instructor of this managed course.
		frappe.db.set_value("Course Lesson", self.lesson.name, "owner", self.student.name)
		self.as_user(self.student.name)
		self.assertEqual(
			frappe.get_list("Course Lesson", filters={"name": self.lesson.name}, fields=["name", "content"]),
			[],
		)
		self.grant()
		self.as_user(self.student.name)
		rows = frappe.get_list(
			"Course Lesson", filters={"name": self.lesson.name}, fields=["name", "content"]
		)
		self.assertEqual([row.name for row in rows], [self.lesson.name])

	def test_private_scorm_uses_commerce_policy(self):
		frappe.db.set_value("Course Chapter", self.chapter.name, "is_scorm_package", 1)
		renderer = SCORMRenderer(path=f"scorm/{self.course.name}/{self.chapter.title}/index.html")
		with self.assertRaises(frappe.PermissionError):
			renderer._check_permission()
		self.grant()
		self.as_user(self.student.name)
		renderer._check_permission()

	def test_native_catalog_uses_same_access_decision(self):
		row = get_courses(filters={"title": self.course.title})[0]
		self.assertEqual(row["name"], self.course.name)
		self.assertTrue(row["commerce"]["handled"])
		self.assertFalse(row["commerce"]["allowed"])
		self.assertEqual(row["commerce"]["offers"], [])
		self.grant()
		self.as_user(self.student.name)
		row = get_courses(filters={"title": self.course.title})[0]
		self.assertTrue(row["commerce"]["allowed"])
		self.assertEqual(row["commerce"]["offers"], [])

	def test_new_enrollment_requires_access_without_changing_lms(self):
		self.as_user(self.outsider.name)
		with self.assertRaises(frappe.PermissionError):
			self._create_enrollment(self.outsider.name, self.course.name)
		self.grant(member=self.outsider.name)
		self.as_user(self.outsider.name)
		self._create_enrollment(self.outsider.name, self.course.name)
		self.assertTrue(can_access_lesson(self.lesson.name))

	def test_disabled_commerce_keeps_native_self_enrollment(self):
		self.as_user("Administrator")
		frappe.db.set_single_value("Commerce Settings", "enabled", 0)
		self.as_user(self.outsider.name)
		self._create_enrollment(self.outsider.name, self.course.name)
		self.assertTrue(can_access_lesson(self.lesson.name))

	def test_higher_tier_unlocks_lower_tier_but_not_native_enrollment(self):
		self.as_user("Administrator")
		basic = frappe.get_doc(
			{"doctype": "Commerce Tier", "tier_name": f"Basic {self.token}", "rank": 10, "enabled": 1}
		).insert()
		maximum = frappe.get_doc(
			{"doctype": "Commerce Tier", "tier_name": f"Max {self.token}", "rank": 20, "enabled": 1}
		).insert()
		self.offering.access_policy = "Tier"
		self.offering.required_tier = basic.name
		self.offering.save()
		grant_manual_entitlement(self.student.name, "Tier", tier=maximum.name)
		self.as_user(self.student.name)
		self.assertTrue(can_access_lesson(self.lesson.name))
		self.assertTrue(can_access_quiz(self.quiz.name))
