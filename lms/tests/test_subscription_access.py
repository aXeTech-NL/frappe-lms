# Copyright (c) 2026, Frappe and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, nowdate

from lms.lms.access import get_course_access
from lms.lms.payments import already_has_access
from lms.lms.permissions import can_access_lesson
from lms.lms.test_helpers import BaseTestUtils
from lms.lms.utils import enroll_in_program, get_course_outline


class TestSubscriptionAccess(BaseTestUtils):
	def setUp(self):
		super().setUp()
		self.original_user = frappe.session.user
		self.original_enabled = frappe.db.get_single_value("LMS Settings", "enable_subscriptions")
		self.original_guest_access = frappe.db.get_single_value("LMS Settings", "allow_guest_access")
		self._set_subscription_setting(1)
		frappe.db.set_single_value("LMS Settings", "allow_guest_access", 1)
		frappe.clear_document_cache("LMS Settings", "LMS Settings")

		hash = frappe.generate_hash(length=8)
		self.student = self._create_user(
			f"subscription-{hash}@example.com", "Subscription", "Student", ["LMS Student"]
		)
		base_rank = int(hash[:4], 36) * 2 + 100
		self.basic = self._create_tier(f"Basic {hash}", base_rank)
		self.maximum = self._create_tier(f"Max {hash}", base_rank + 1)
		self.basic_plan = self._create_plan(f"Basic Monthly {hash}", self.basic.name)
		self.subscription = self._create_subscription(self.basic_plan.name)
		self.course = self._create_course(f"Subscription Course {hash}")
		self.course.required_subscription_tier = self.basic.name
		self.course.save()
		self.chapter = self._create_chapter(f"Subscription Chapter {hash}", self.course.name)
		self.lesson = self._create_lesson(f"Subscription Lesson {hash}", self.chapter.name, self.course.name)
		self.lesson.db_set("include_in_preview", 1)

		frappe.set_user(self.student.name)
		self.enrollment = self._create_enrollment(self.student.name, self.course.name)
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		self._set_subscription_setting(self.original_enabled or 0)
		frappe.db.set_single_value("LMS Settings", "allow_guest_access", self.original_guest_access or 0)
		frappe.clear_document_cache("LMS Settings", "LMS Settings")
		super().tearDown()
		frappe.set_user(self.original_user)

	def _set_subscription_setting(self, value):
		frappe.db.set_single_value("LMS Settings", "enable_subscriptions", value)
		frappe.clear_document_cache("LMS Settings", "LMS Settings")

	def _create_tier(self, name, rank):
		tier = frappe.get_doc(
			{"doctype": "LMS Subscription Tier", "tier_name": name, "rank": rank, "enabled": 1}
		).insert()
		self.cleanup_items.append((tier.doctype, tier.name))
		return tier

	def _create_plan(self, name, tier):
		plan = frappe.get_doc(
			{
				"doctype": "LMS Subscription Plan",
				"plan_name": name,
				"tier": tier,
				"billing_interval": "Month",
				"interval_count": 1,
				"amount": 25,
				"currency": "USD",
				"enabled": 1,
			}
		).insert()
		self.cleanup_items.append((plan.doctype, plan.name))
		return plan

	def _create_subscription(self, plan):
		subscription = frappe.get_doc(
			{
				"doctype": "LMS Subscription",
				"member": self.student.name,
				"plan": plan,
				"status": "Active",
				"starts_on": nowdate(),
				"current_period_start": nowdate(),
				"current_period_end": add_days(nowdate(), 30),
			}
		).insert(ignore_permissions=True)
		self.cleanup_items.append((subscription.doctype, subscription.name))
		return subscription

	def _record_course_purchase(self):
		payment = frappe.new_doc("LMS Payment")
		payment.update(
			{
				"member": self.student.name,
				"billing_name": self.student.full_name,
				"source": "Subscription access test",
				"payment_for_document_type": "LMS Course",
				"payment_for_document": self.course.name,
				"payment_received": 1,
				"payment_status": "Paid",
				"amount": 50,
				"currency": "USD",
				"address": "Subscription access test",
			}
		)
		# The access resolver needs a durable transaction row; unrelated Link rows
		# belong to checkout tests and are intentionally bypassed here.
		payment.db_insert()
		self.cleanup_items.append((payment.doctype, payment.name))
		return payment

	def test_active_subscription_grants_and_expiry_revokes_without_deleting_progress(self):
		access = get_course_access(self.course.name, self.student.name)
		self.assertTrue(access.allowed)
		self.assertEqual(access.source, "Subscription")
		self.assertEqual(self.enrollment.access_source, "Subscription")
		self.assertTrue(can_access_lesson(self.lesson.name, user=self.student.name))

		self.subscription.db_set(
			{"status": "Expired", "current_period_end": add_days(nowdate(), -1)},
			update_modified=False,
		)
		access = get_course_access(self.course.name, self.student.name)
		self.assertFalse(access.allowed)
		self.assertFalse(can_access_lesson(self.lesson.name, user=self.student.name))
		self.assertTrue(frappe.db.exists("LMS Enrollment", self.enrollment.name))

	def test_authenticated_member_has_implicit_free_access(self):
		free_course = self._create_course(f"Free Course {frappe.generate_hash(length=6)}")
		frappe.set_user(self.student.name)
		enrollment = self._create_enrollment(self.student.name, free_course.name)
		frappe.set_user("Administrator")
		self.assertEqual(enrollment.access_source, "Free")
		access = get_course_access(free_course.name, self.student.name)
		self.assertTrue(access.allowed)
		self.assertEqual(access.source, "Free")

	def test_direct_purchase_overrides_expired_subscription(self):
		self.subscription.db_set(
			{"status": "Expired", "current_period_end": add_days(nowdate(), -1)},
			update_modified=False,
		)
		self.assertFalse(get_course_access(self.course.name, self.student.name).allowed)
		frappe.set_user(self.student.name)
		self.assertFalse(already_has_access("LMS Course", self.course.name, 0))
		frappe.set_user("Administrator")
		payment = self._record_course_purchase()

		access = get_course_access(self.course.name, self.student.name)
		self.assertTrue(access.allowed)
		self.assertEqual(access.source, "Purchase")
		self.assertEqual(access.payment, payment.name)

	def test_batch_grant_composes_with_subscription_enrollment_and_revokes(self):
		self.subscription.db_set(
			{"status": "Expired", "current_period_end": add_days(nowdate(), -1)},
			update_modified=False,
		)
		self.assertFalse(get_course_access(self.course.name, self.student.name).allowed)

		batch = self._create_batch(
			self.course.name,
			title=f"Subscription overlap batch {frappe.generate_hash(length=6)}",
		)
		batch_enrollment = self._create_batch_enrollment(self.student.name, batch.name)
		access = get_course_access(self.course.name, self.student.name)
		self.assertTrue(access.allowed)
		self.assertEqual(access.source, "Batch")
		self.assertEqual(access.batch, batch.name)

		frappe.delete_doc("LMS Batch Enrollment", batch_enrollment.name, force=True)
		self.assertFalse(get_course_access(self.course.name, self.student.name).allowed)
		self.assertTrue(frappe.db.exists("LMS Enrollment", self.enrollment.name))

	def test_new_batch_provenance_is_dynamic_even_when_admin_creates_it(self):
		course = self._create_course(f"Batch Max Course {frappe.generate_hash(length=6)}")
		course.required_subscription_tier = self.maximum.name
		course.save()
		batch = self._create_batch(
			course.name,
			title=f"Dynamic provenance batch {frappe.generate_hash(length=6)}",
		)

		batch_enrollment = self._create_batch_enrollment(self.student.name, batch.name)
		enrollment = frappe.db.get_value(
			"LMS Enrollment",
			{"course": course.name, "member": self.student.name},
			["name", "access_source", "permanent_access"],
			as_dict=True,
		)
		self.assertEqual(enrollment.access_source, "Batch")
		self.assertFalse(enrollment.permanent_access)
		self.assertTrue(get_course_access(course.name, self.student.name).allowed)

		frappe.delete_doc("LMS Batch Enrollment", batch_enrollment.name, force=True)
		self.assertFalse(get_course_access(course.name, self.student.name).allowed)
		self.assertTrue(frappe.db.exists("LMS Enrollment", enrollment.name))

	def test_higher_tier_includes_lower_but_lower_does_not_include_higher(self):
		max_course = self._create_course(f"Max Course {frappe.generate_hash(length=6)}")
		max_course.required_subscription_tier = self.maximum.name
		max_course.save()
		self.assertFalse(
			get_course_access(max_course.name, self.student.name, require_enrollment=False).allowed
		)

		self.subscription.db_set("status", "Expired", update_modified=False)
		max_plan = self._create_plan(f"Max Monthly {frappe.generate_hash(length=6)}", self.maximum.name)
		max_subscription = self._create_subscription(max_plan.name)
		self.assertTrue(
			get_course_access(max_course.name, self.student.name, require_enrollment=False).allowed
		)
		self.assertTrue(
			get_course_access(self.course.name, self.student.name, require_enrollment=False).allowed
		)
		max_subscription.db_set("status", "Expired", update_modified=False)

	def test_program_permanent_bit_does_not_make_subscription_source_permanent(self):
		program = frappe.get_doc(
			{
				"doctype": "LMS Program",
				"title": f"Contradictory Program {frappe.generate_hash(length=6)}",
				"published": 1,
				"required_subscription_tier": self.basic.name,
			}
		).insert()
		self.cleanup_items.append((program.doctype, program.name))
		membership = frappe.get_doc(
			{
				"doctype": "LMS Program Member",
				"parent": program.name,
				"parenttype": "LMS Program",
				"parentfield": "program_members",
				"member": self.student.name,
				"access_source": "Subscription",
				"permanent_access": 1,
				"subscription": self.subscription.name,
			}
		)
		membership.flags.ignore_access_protection = True
		membership.insert(ignore_permissions=True)
		self.cleanup_items.append((membership.doctype, membership.name))
		self.subscription.db_set("status", "Expired", update_modified=False)

		from lms.lms.access import get_program_access

		self.assertFalse(get_program_access(program.name, self.student.name).allowed)

	def test_program_tier_cannot_be_lower_than_a_course_tier(self):
		max_course = self._create_course(f"Program Max Course {frappe.generate_hash(length=6)}")
		max_course.required_subscription_tier = self.maximum.name
		max_course.save()
		program = frappe.get_doc(
			{
				"doctype": "LMS Program",
				"title": f"Invalid Basic Program {frappe.generate_hash(length=6)}",
				"published": 1,
				"required_subscription_tier": self.basic.name,
				"program_courses": [{"course": max_course.name}],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			program.insert()

	def test_program_entitlement_tracks_current_course_membership(self):
		paid_course = self._create_course(f"Program Bundle Course {frappe.generate_hash(length=6)}")
		paid_course.update({"paid_course": 1, "course_price": 50, "currency": "USD"})
		paid_course.save()
		program = frappe.get_doc(
			{
				"doctype": "LMS Program",
				"title": f"Subscription Program {frappe.generate_hash(length=6)}",
				"published": 1,
				"required_subscription_tier": self.basic.name,
				"program_courses": [
					{"course": self.course.name},
					{"course": paid_course.name},
				],
			}
		).insert()
		self.cleanup_items.append((program.doctype, program.name))

		frappe.set_user(self.student.name)
		enroll_in_program(program.name)
		program_enrollment_name = frappe.db.get_value(
			"LMS Enrollment", {"member": self.student.name, "course": paid_course.name}, "name"
		)
		program_enrollment = frappe.get_doc("LMS Enrollment", program_enrollment_name)
		self.cleanup_items.append((program_enrollment.doctype, program_enrollment.name))
		frappe.set_user("Administrator")
		self.assertEqual(program_enrollment.access_source, "Program")
		self.assertFalse(program_enrollment.permanent_access)
		access = get_course_access(paid_course.name, self.student.name)
		self.assertTrue(access.allowed)
		self.assertEqual(access.source, "Program")

		program.reload()
		program.set(
			"program_courses",
			[row for row in program.program_courses if row.course != paid_course.name],
		)
		program.save()
		self.assertFalse(get_course_access(paid_course.name, self.student.name).allowed)
		self.assertTrue(frappe.db.exists("LMS Enrollment", program_enrollment.name))

	def test_expiry_blocks_progress_and_note_writes_without_deleting_records(self):
		self.subscription.db_set(
			{"status": "Expired", "current_period_end": add_days(nowdate(), -1)},
			update_modified=False,
		)
		frappe.set_user(self.student.name)
		progress = frappe.get_doc(
			{
				"doctype": "LMS Course Progress",
				"member": self.student.name,
				"lesson": self.lesson.name,
				"course": self.course.name,
				"status": "Complete",
			}
		)
		with self.assertRaises(frappe.PermissionError):
			progress.insert(ignore_permissions=True)

		note = frappe.get_doc(
			{
				"doctype": "LMS Lesson Note",
				"member": self.student.name,
				"lesson": self.lesson.name,
				"color": "Blue",
				"note": "must not be stored",
			}
		)
		with self.assertRaises(frappe.PermissionError):
			note.insert()
		self.assertTrue(frappe.db.exists("LMS Enrollment", self.enrollment.name))

	def test_enabled_mode_requires_login_even_for_preview(self):
		self.lesson.db_set("youtube", "private-video-id", update_modified=False)
		frappe.set_user("Guest")
		self.assertFalse(can_access_lesson(self.lesson.name))
		outline = get_course_outline(self.course.name)
		lesson = outline[0].lessons[0]
		self.assertNotIn("youtube", lesson)
		self.assertNotIn("quiz_id", lesson)

	def test_disabled_mode_preserves_enrollment_and_guest_preview_behavior(self):
		self.subscription.db_set(
			{"status": "Expired", "current_period_end": add_days(nowdate(), -1)},
			update_modified=False,
		)
		self._set_subscription_setting(0)
		self.assertTrue(get_course_access(self.course.name, self.student.name).allowed)
		frappe.set_user("Guest")
		self.assertTrue(can_access_lesson(self.lesson.name))
