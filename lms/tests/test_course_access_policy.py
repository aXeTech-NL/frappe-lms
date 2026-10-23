import json
from contextlib import contextmanager
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from lms.lms import access_policy
from lms.lms.access_policy import course_access_policy_allows, course_access_policy_decision
from lms.lms.api import track_video_watch_duration
from lms.lms.doctype.course_lesson.course_lesson import save_progress
from lms.lms.doctype.lms_quiz.lms_quiz import check_answer, save_progress_after_quiz
from lms.lms.permissions import can_access_quiz, resolve_lesson_access
from lms.lms.test_helpers import BaseTestUtils
from lms.page_renderers import SCORMRenderer


@contextmanager
def without_policy_providers():
	real_get_hooks = frappe.get_hooks

	def get_hooks(hook=None, *args, **kwargs):
		if hook == access_policy.POLICY_HOOK:
			return []
		return real_get_hooks(hook, *args, **kwargs)

	setattr(frappe.local, access_policy._CACHE_ATTRIBUTE, {})
	try:
		with patch.object(frappe, "get_hooks", side_effect=get_hooks):
			yield
	finally:
		setattr(frappe.local, access_policy._CACHE_ATTRIBUTE, {})


@contextmanager
def configured_policy(provider):
	real_get_hooks = frappe.get_hooks
	real_get_attr = frappe.get_attr

	def get_hooks(hook=None, *args, **kwargs):
		if hook == access_policy.POLICY_HOOK:
			return ["test_app.course_access_policy"]
		return real_get_hooks(hook, *args, **kwargs)

	def get_attr(path, *args, **kwargs):
		if path == "test_app.course_access_policy":
			return provider
		return real_get_attr(path, *args, **kwargs)

	setattr(frappe.local, access_policy._CACHE_ATTRIBUTE, {})
	try:
		with (
			patch.object(frappe, "get_hooks", side_effect=get_hooks),
			patch.object(frappe, "get_attr", side_effect=get_attr),
		):
			yield
	finally:
		setattr(frappe.local, access_policy._CACHE_ATTRIBUTE, {})


class TestCourseAccessPolicyContract(FrappeTestCase):
	def setUp(self):
		setattr(frappe.local, access_policy._CACHE_ATTRIBUTE, {})

	def call_policy(self, **overrides):
		arguments = {
			"user": "student@example.com",
			"course": "course-1",
			"action": "consume",
			"context": {"lesson": "lesson-1"},
		}
		arguments.update(overrides)
		return course_access_policy_allows(**arguments)

	def test_no_provider_preserves_native_processing(self):
		with without_policy_providers():
			self.assertTrue(self.call_policy())

	def test_all_none_means_unmanaged(self):
		with configured_policy(Mock(return_value=None)):
			self.assertIsNone(
				course_access_policy_decision(
					user="student@example.com",
					course="course-1",
					action="consume",
					context={"lesson": "lesson-1"},
				)
			)

	def test_none_and_true_do_not_deny(self):
		for result in (None, True):
			provider = Mock(return_value=result)
			with self.subTest(result=result), configured_policy(provider):
				self.assertTrue(self.call_policy())
				provider.assert_called_once_with(
					user="student@example.com",
					course="course-1",
					action="consume",
					context={"lesson": "lesson-1", "quiz": None, "is_preview": None},
				)

	def test_false_denies(self):
		with configured_policy(Mock(return_value=False)):
			self.assertFalse(self.call_policy())

	def test_non_boolean_falsey_result_denies(self):
		with configured_policy(Mock(return_value=0)):
			self.assertFalse(self.call_policy())

	def test_provider_exception_is_logged_and_denies(self):
		logger = Mock()
		with (
			configured_policy(Mock(side_effect=RuntimeError("provider detail"))),
			patch.object(frappe, "logger", return_value=logger),
		):
			self.assertFalse(self.call_policy())
		logger.exception.assert_called_once()

	def test_request_local_cache_includes_user_and_canonical_context(self):
		provider = Mock(return_value=True)
		with configured_policy(provider):
			self.assertTrue(self.call_policy())
			self.assertTrue(
				self.call_policy(context={"is_preview": None, "quiz": None, "lesson": "lesson-1"})
			)
			self.assertTrue(self.call_policy(context={"lesson": "lesson-2"}))
			self.assertTrue(self.call_policy(user="other@example.com"))
		self.assertEqual(provider.call_count, 3)

	def test_unknown_or_overlong_context_is_rejected_before_provider_call(self):
		provider = Mock(return_value=True)
		with configured_policy(provider):
			self.assertFalse(self.call_policy(context={"offering": "x"}))
			self.assertFalse(self.call_policy(context={"lesson": "x" * 141}))
		provider.assert_not_called()

	def test_multiple_providers_compose_deny_only(self):
		providers = {
			"test.first": Mock(return_value=True),
			"test.second": Mock(return_value=False),
			"test.third": Mock(return_value=True),
		}
		with (
			patch.object(frappe, "get_hooks", return_value=list(providers)),
			patch.object(frappe, "get_attr", side_effect=providers.__getitem__),
		):
			self.assertFalse(self.call_policy())
		providers["test.first"].assert_called_once()
		providers["test.second"].assert_called_once()
		providers["test.third"].assert_not_called()


class TestCourseAccessPolicyIntegration(BaseTestUtils):
	def setUp(self):
		super().setUp()
		setattr(frappe.local, access_policy._CACHE_ATTRIBUTE, {})
		capture = patch("lms.lms.doctype.course_lesson.course_lesson.capture", return_value=None)
		capture.start()
		self.addCleanup(capture.stop)
		hash = frappe.generate_hash(length=6)
		self.instructor = self._create_user(
			f"policy-instructor-{hash}@example.com", "Policy", "Instructor", ["Course Creator"]
		)
		self.student = self._create_user(
			f"policy-student-{hash}@example.com", "Policy", "Student", ["LMS Student"]
		)
		self.outsider = self._create_user(
			f"policy-outsider-{hash}@example.com", "Policy", "Outsider", ["LMS Student"]
		)
		self.course = self._create_course(title=f"Policy Course {hash}", instructor=self.instructor.email)
		self.chapter = self._create_chapter(f"Policy Chapter {hash}", self.course.name)
		self._create_chapter_reference(self.course.name, self.chapter.name)
		self.questions = self._create_quiz_questions()
		self.quiz = self._create_quiz(self.questions, title=f"Policy Quiz {hash}")
		self.lesson = self._create_lesson(f"Policy Lesson {hash}", self.chapter.name, self.course.name)
		self._create_lesson_reference(self.chapter.name, self.lesson.name)
		# Current LMS requires a real lesson placement, not just the legacy quiz stamp.
		# quiz_id places it without adding a completion requirement to lesson content.
		frappe.db.set_value("Course Lesson", self.lesson.name, "quiz_id", self.quiz.name)
		frappe.db.set_value(
			"LMS Quiz",
			self.quiz.name,
			{"course": self.course.name, "lesson": self.lesson.name},
		)
		self._create_enrollment(self.student.email, self.course.name)

	def tearDown(self):
		frappe.set_user("Administrator")
		setattr(frappe.local, access_policy._CACHE_ATTRIBUTE, {})
		super().tearDown()

	def test_no_provider_preserves_native_lesson_and_quiz_access(self):
		frappe.set_user(self.student.email)
		with without_policy_providers():
			self.assertEqual(resolve_lesson_access(self.lesson.name), (False, True))
			self.assertTrue(can_access_quiz(self.quiz.name))

	def test_policy_never_grants_around_native_lesson_access(self):
		frappe.set_user(self.outsider.email)
		with configured_policy(Mock(return_value=True)):
			self.assertEqual(resolve_lesson_access(self.lesson.name), (False, False))

	def test_preview_calls_consume_policy_with_preview_context(self):
		frappe.db.set_value("Course Lesson", self.lesson.name, "include_in_preview", 1)
		frappe.set_user(self.outsider.email)
		provider = Mock(return_value=False)
		with configured_policy(provider):
			self.assertEqual(resolve_lesson_access(self.lesson.name), (False, False))
		provider.assert_called_once_with(
			user=self.outsider.email,
			course=self.course.name,
			action="consume",
			context={"lesson": self.lesson.name, "quiz": None, "is_preview": True},
		)

	def test_consume_denial_blocks_enrolled_lesson_and_course_quiz(self):
		frappe.set_user(self.student.email)
		with configured_policy(Mock(return_value=False)):
			self.assertEqual(resolve_lesson_access(self.lesson.name), (False, False))
			self.assertFalse(can_access_quiz(self.quiz.name))

	def test_instructor_bypasses_policy_at_native_lesson_and_quiz_boundaries(self):
		frappe.set_user(self.instructor.email)
		provider = Mock(return_value=False)
		with configured_policy(provider):
			self.assertEqual(resolve_lesson_access(self.lesson.name), (True, True))
			self.assertTrue(can_access_quiz(self.quiz.name))
		provider.assert_not_called()

	def test_scorm_renderer_uses_lesson_consume_policy(self):
		frappe.db.set_value("Course Chapter", self.chapter.name, "is_scorm_package", 1)
		frappe.set_user(self.student.email)
		renderer = SCORMRenderer(path=f"scorm/{self.course.name}/{self.chapter.title}/index.html")
		with configured_policy(Mock(return_value=False)), self.assertRaises(frappe.PermissionError):
			renderer._check_permission()

	def test_enrolled_instructor_bypasses_progress_policy(self):
		self._create_enrollment(self.instructor.email, self.course.name)
		frappe.set_user(self.instructor.email)
		provider = Mock(return_value=False)
		with configured_policy(provider):
			save_progress(self.lesson.name, self.course.name)
		provider.assert_not_called()
		self.assertTrue(
			frappe.db.exists(
				"LMS Course Progress", {"lesson": self.lesson.name, "member": self.instructor.email}
			)
		)

	def test_progress_denial_prevents_direct_write(self):
		frappe.set_user(self.student.email)
		provider = Mock(side_effect=lambda **kwargs: kwargs["action"] != "progress")
		with configured_policy(provider), self.assertRaises(frappe.PermissionError):
			save_progress(self.lesson.name, self.course.name)
		self.assertFalse(
			frappe.db.exists(
				"LMS Course Progress", {"lesson": self.lesson.name, "member": self.student.email}
			)
		)

	def test_video_watch_requires_progress_policy(self):
		frappe.set_user(self.student.email)
		provider = Mock(side_effect=lambda **kwargs: kwargs["action"] != "progress")
		videos = [{"source": "https://example.com/policy.mp4", "watch_time": 10}]
		with configured_policy(provider), self.assertRaises(frappe.PermissionError):
			track_video_watch_duration(self.lesson.name, videos)
		self.assertFalse(
			frappe.db.exists(
				"LMS Video Watch Duration",
				{"lesson": self.lesson.name, "member": self.student.email},
			)
		)

	def test_progress_binds_lesson_to_its_authoritative_course(self):
		other_course = self._create_course(
			title=f"Other Policy Course {frappe.generate_hash(length=6)}",
			instructor=self.instructor.email,
		)
		self._create_enrollment(self.student.email, other_course.name)
		frappe.set_user(self.student.email)
		with self.assertRaises(frappe.ValidationError):
			save_progress(self.lesson.name, other_course.name)

	def test_no_provider_preserves_native_progress(self):
		frappe.set_user(self.student.email)
		with without_policy_providers():
			save_progress(self.lesson.name, self.course.name)
		self.assertTrue(
			frappe.db.exists(
				"LMS Course Progress", {"lesson": self.lesson.name, "member": self.student.email}
			)
		)

	def test_quiz_follow_up_skips_policy_denied_progress(self):
		frappe.set_user(self.student.email)
		provider = Mock(side_effect=lambda **kwargs: kwargs["action"] != "progress")
		quiz_details = frappe.db.get_value(
			"LMS Quiz", self.quiz.name, ["lesson", "course", "passing_percentage"], as_dict=True
		)
		with configured_policy(provider):
			save_progress_after_quiz(quiz_details, 100)
		self.assertFalse(
			frappe.db.exists(
				"LMS Course Progress", {"lesson": self.lesson.name, "member": self.student.email}
			)
		)

	def test_no_provider_preserves_native_answer_oracle_denial(self):
		frappe.db.set_value("LMS Quiz", self.quiz.name, "show_answers", 1)
		frappe.set_user(self.outsider.email)
		with without_policy_providers(), self.assertRaises(frappe.PermissionError):
			check_answer(self.quiz.name, self.questions[0].name, "Choices", json.dumps(["Option 1"]))

	def test_managed_answer_oracle_requires_native_quiz_access(self):
		frappe.db.set_value("LMS Quiz", self.quiz.name, "show_answers", 1)
		frappe.set_user(self.outsider.email)
		with configured_policy(Mock(return_value=True)), self.assertRaises(frappe.PermissionError):
			check_answer(self.quiz.name, self.questions[0].name, "Choices", json.dumps(["Option 1"]))
