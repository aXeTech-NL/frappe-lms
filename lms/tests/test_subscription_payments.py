# Copyright (c) 2026, Frappe and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, add_months, getdate, nowdate

from lms.lms.access import get_course_access
from lms.lms.subscriptions import (
	cancel_subscription,
	expire_subscriptions,
	get_or_create_pending_subscription,
	get_provider_event_key,
	get_subscription_catalog,
	record_subscription_event,
)
from lms.lms.test_helpers import BaseTestUtils
from lms.lms.utils import complete_enrollment, get_order_summary


class TestSubscriptionPayments(BaseTestUtils):
	def setUp(self):
		super().setUp()
		self.original_user = frappe.session.user
		self.original_enabled = frappe.db.get_single_value("LMS Settings", "enable_subscriptions")
		frappe.db.set_single_value("LMS Settings", "enable_subscriptions", 1)
		frappe.clear_document_cache("LMS Settings", "LMS Settings")
		hash = frappe.generate_hash(length=8)
		self.student = self._create_user(
			f"subscription-payment-{hash}@example.com", "Payment", "Member", ["LMS Student"]
		)
		rank = int(hash[:4], 36) + 1000
		self.tier = frappe.get_doc(
			{
				"doctype": "LMS Subscription Tier",
				"tier_name": f"Payment Tier {hash}",
				"rank": rank,
				"enabled": 1,
			}
		).insert()
		self.cleanup_items.append((self.tier.doctype, self.tier.name))
		self.plan = frappe.get_doc(
			{
				"doctype": "LMS Subscription Plan",
				"plan_name": f"Payment Plan {hash}",
				"tier": self.tier.name,
				"billing_interval": "Month",
				"interval_count": 1,
				"amount": 25,
				"currency": "USD",
				"enabled": 1,
			}
		).insert()
		self.cleanup_items.append((self.plan.doctype, self.plan.name))
		self.address = self._create_address()
		self.source = self._create_source()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("LMS Settings", "enable_subscriptions", self.original_enabled or 0)
		frappe.clear_document_cache("LMS Settings", "LMS Settings")
		super().tearDown()
		frappe.set_user(self.original_user)

	def _create_address(self):
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"Subscription Payment {frappe.generate_hash(length=6)}",
				"address_type": "Billing",
				"address_line1": "1 Test Street",
				"city": "Amsterdam",
				"country": "Netherlands",
				"email_id": self.student.name,
			}
		).insert(ignore_permissions=True)
		self.cleanup_items.append((address.doctype, address.name))
		return address

	def _create_source(self):
		name = f"Subscription Test {frappe.generate_hash(length=6)}"
		source = frappe.get_doc({"doctype": "LMS Source", "source": name}).insert(ignore_permissions=True)
		self.cleanup_items.append((source.doctype, source.name))
		return source

	def _create_subscription(self, plan=None):
		subscription = frappe.get_doc(
			{
				"doctype": "LMS Subscription",
				"member": self.student.name,
				"plan": (plan or self.plan).name,
				"status": "Pending",
				"payment_gateway": "Test Gateway",
			}
		).insert(ignore_permissions=True)
		self.cleanup_items.append((subscription.doctype, subscription.name))
		return subscription

	def _create_payment(self, doctype, docname, *, subscription=None, payment_id=None):
		payment = frappe.get_doc(
			{
				"doctype": "LMS Payment",
				"member": self.student.name,
				"billing_name": self.student.full_name,
				"address": self.address.name,
				"source": self.source.name,
				"amount": 25,
				"original_amount": 25,
				"currency": "USD",
				"payment_for_document_type": doctype,
				"payment_for_document": docname,
				"payment_received": 1,
				"payment_status": "Paid",
				"payment_id": payment_id,
				"payment_gateway": "Test Gateway",
				"subscription": subscription,
				"member_consent": 1,
			}
		).insert(ignore_permissions=True)
		self.cleanup_items.append((payment.doctype, payment.name))
		return payment

	def test_subscription_catalog_returns_safe_enabled_plans_and_current_member_state(self):
		subscription = self._create_subscription()
		subscription.db_set(
			{
				"status": "Active",
				"current_period_start": nowdate(),
				"current_period_end": add_days(nowdate(), 30),
				"gateway_customer_id": "secret-customer",
				"gateway_subscription_id": f"secret-{frappe.generate_hash(length=6)}",
			},
			update_modified=False,
		)
		frappe.set_user(self.student.name)
		catalog = get_subscription_catalog()

		# The catalog is the learner-safe projection. Generic document reads must
		# not expose provider customer/subscription identifiers from the source row.
		self.assertFalse(frappe.has_permission("LMS Subscription", "read", doc=subscription))
		frappe.set_user("Administrator")

		self.assertTrue(catalog.enabled)
		self.assertEqual(catalog.current_subscription.name, subscription.name)
		self.assertEqual(catalog.current_subscription.tier, self.tier.name)
		self.assertNotIn("gateway_customer_id", catalog.current_subscription)
		self.assertTrue(any(plan.name == self.plan.name and plan.price for plan in catalog.plans))

	def test_subscription_plan_order_summary_uses_plan_price(self):
		summary = get_order_summary("LMS Subscription Plan", self.plan.name)
		self.assertEqual(summary.title, self.plan.plan_name)
		self.assertEqual(summary.original_amount, self.plan.amount)
		self.assertEqual(summary.currency, self.plan.currency)

	def test_subscription_snapshots_plan_terms_at_creation(self):
		subscription = self._create_subscription()
		self.plan.db_set(
			{
				"billing_interval": "Year",
				"interval_count": 2,
				"amount": 99,
				"currency": "EUR",
			},
			update_modified=False,
		)
		subscription.reload()
		self.assertEqual(subscription.billing_interval, "Month")
		self.assertEqual(subscription.interval_count, 1)
		self.assertEqual(subscription.billing_amount, 25)
		self.assertEqual(subscription.billing_currency, "USD")

		payment = self._create_payment(
			"LMS Subscription",
			subscription.name,
			subscription=subscription.name,
			payment_id="pay-snapshot",
		)
		complete_enrollment(payment.name)
		subscription.reload()
		expected_end = add_days(add_months(subscription.current_period_start, 1), -1)
		self.assertEqual(getdate(subscription.current_period_end), getdate(expected_end))

	def test_initial_checkout_activates_stored_member_from_guest_callback(self):
		subscription = self._create_subscription()
		payment = self._create_payment(
			"LMS Subscription", subscription.name, subscription=subscription.name, payment_id="pay-initial"
		)

		frappe.set_user("Guest")
		complete_enrollment(payment.name, "LMS Subscription", subscription.name)
		frappe.set_user("Administrator")

		subscription.reload()
		self.assertEqual(subscription.member, self.student.name)
		self.assertEqual(subscription.status, "Active")
		self.assertEqual(subscription.latest_payment, payment.name)
		self.assertTrue(subscription.current_period_start)
		self.assertTrue(subscription.current_period_end)
		self.assertEqual(
			frappe.db.get_value("LMS Payment", payment.name, "provider_event_id"),
			"checkout:pay-initial",
		)

	def test_course_fulfillment_uses_stored_member_not_callback_session(self):
		course = self._create_course(f"Stored Member Course {frappe.generate_hash(length=6)}")
		course.update({"paid_course": 1, "course_price": 25, "currency": "USD"})
		course.save()
		payment = self._create_payment("LMS Course", course.name, payment_id="pay-stored-member")

		frappe.set_user("Guest")
		complete_enrollment(payment.name, "LMS Course", course.name)
		frappe.set_user("Administrator")

		self.assertTrue(
			frappe.db.exists("LMS Enrollment", {"course": course.name, "member": self.student.name})
		)
		self.assertFalse(frappe.db.exists("LMS Enrollment", {"course": course.name, "member": "Guest"}))

	def test_paid_renewal_extends_once_and_failed_or_refunded_events_do_not(self):
		subscription = self._create_subscription()
		initial = self._create_payment(
			"LMS Subscription", subscription.name, subscription=subscription.name, payment_id="pay-first"
		)
		complete_enrollment(initial.name)
		subscription.reload()
		first_end = getdate(subscription.current_period_end)

		result = record_subscription_event(
			subscription.name,
			"Paid",
			"event-renewal",
			provider_payment_id="pay-renewal",
			payment_gateway="Test Gateway",
		)
		self.cleanup_items.append(("LMS Payment", result.payment))
		subscription.reload()
		renewed_end = getdate(subscription.current_period_end)
		self.assertGreater(renewed_end, first_end)
		self.assertFalse(result.replayed)

		replay = record_subscription_event(
			subscription.name,
			"Paid",
			"event-renewal",
			provider_payment_id="pay-renewal",
		)
		subscription.reload()
		self.assertTrue(replay.replayed)
		self.assertEqual(getdate(subscription.current_period_end), renewed_end)

		duplicate_event = record_subscription_event(
			subscription.name,
			"Paid",
			"event-renewal-delivered-again",
			provider_payment_id="pay-renewal",
			payment_gateway="Test Gateway",
		)
		self.cleanup_items.append(("LMS Payment", duplicate_event.payment))
		subscription.reload()
		self.assertFalse(duplicate_event.replayed)
		self.assertFalse(duplicate_event.applied)
		self.assertNotEqual(duplicate_event.payment, result.payment)
		self.assertEqual(
			frappe.db.get_value("LMS Payment", duplicate_event.payment, "related_payment"),
			result.payment,
		)
		self.assertEqual(getdate(subscription.current_period_end), renewed_end)

		failed = record_subscription_event(
			subscription.name,
			"Failed",
			"event-failed",
			provider_payment_id="pay-failed",
			failure_reason="insufficient funds",
		)
		self.cleanup_items.append(("LMS Payment", failed.payment))
		subscription.reload()
		self.assertEqual(getdate(subscription.current_period_end), renewed_end)

		refunded = record_subscription_event(
			subscription.name,
			"Refunded",
			"event-refund",
			provider_payment_id="pay-renewal",
			payment_name=result.payment,
		)
		self.cleanup_items.append(("LMS Payment", refunded.payment))
		subscription.reload()
		self.assertEqual(getdate(subscription.current_period_end), renewed_end)
		self.assertEqual(
			frappe.db.get_value("LMS Payment", {"provider_event_id": "event-refund"}, "payment_status"),
			"Refunded",
		)

	def test_initial_failed_event_can_later_become_paid_before_latest_payment_exists(self):
		subscription = self._create_subscription()
		initial = self._create_payment(
			"LMS Subscription",
			subscription.name,
			subscription=subscription.name,
			payment_id=None,
		)
		initial.db_set(
			{"payment_received": 0, "payment_status": "Pending"},
			update_modified=False,
		)

		failed = record_subscription_event(
			subscription.name,
			"Failed",
			"event-initial-failed",
			provider_payment_id="pay-initial-retry",
			payment_name=initial.name,
			payment_gateway="Test Gateway",
			failure_reason="temporary failure",
		)
		paid = record_subscription_event(
			subscription.name,
			"Paid",
			"event-initial-paid",
			provider_payment_id="pay-initial-retry",
			payment_gateway="Test Gateway",
		)
		self.cleanup_items.append(("LMS Payment", paid.payment))
		subscription.reload()

		self.assertEqual(failed.payment, initial.name)
		self.assertTrue(paid.applied)
		self.assertEqual(subscription.status, "Active")
		self.assertEqual(subscription.latest_payment, paid.payment)
		self.assertEqual(frappe.db.get_value("LMS Payment", initial.name, "payment_status"), "Failed")
		self.assertEqual(
			frappe.db.get_value("LMS Payment", paid.payment, "related_payment"),
			initial.name,
		)

	def test_failed_event_can_later_become_paid_for_same_provider_payment(self):
		subscription = self._create_subscription()
		initial = self._create_payment(
			"LMS Subscription", subscription.name, subscription=subscription.name, payment_id="pay-base"
		)
		complete_enrollment(initial.name)
		subscription.reload()
		first_end = getdate(subscription.current_period_end)

		failed = record_subscription_event(
			subscription.name,
			"Failed",
			"event-retry-failed",
			provider_payment_id="pay-retry",
			payment_gateway="Test Gateway",
			failure_reason="temporary failure",
		)
		self.cleanup_items.append(("LMS Payment", failed.payment))
		paid = record_subscription_event(
			subscription.name,
			"Paid",
			"event-retry-paid",
			provider_payment_id="pay-retry",
			payment_gateway="Test Gateway",
		)
		self.cleanup_items.append(("LMS Payment", paid.payment))
		subscription.reload()

		self.assertTrue(paid.applied)
		self.assertGreater(getdate(subscription.current_period_end), first_end)
		self.assertEqual(
			frappe.db.get_value("LMS Payment", failed.payment, "provider_payment_reference"),
			"pay-retry",
		)
		self.assertEqual(frappe.db.get_value("LMS Payment", failed.payment, "payment_status"), "Failed")
		paid_row = frappe.db.get_value(
			"LMS Payment",
			paid.payment,
			["payment_status", "payment_id", "related_payment"],
			as_dict=True,
		)
		self.assertEqual(paid_row.payment_status, "Paid")
		self.assertEqual(paid_row.payment_id, "pay-retry")
		self.assertEqual(paid_row.related_payment, failed.payment)

	def test_paid_events_preserve_immediate_and_period_end_cancellation(self):
		subscription = self._create_subscription()
		initial = self._create_payment(
			"LMS Subscription", subscription.name, subscription=subscription.name, payment_id="pay-cancel"
		)
		complete_enrollment(initial.name)
		subscription.reload()
		period_end = subscription.current_period_end

		frappe.set_user(self.student.name)
		cancel_subscription(subscription.name, at_period_end=False)
		frappe.set_user("Administrator")
		late = record_subscription_event(
			subscription.name,
			"Paid",
			"event-after-cancel",
			provider_payment_id="pay-after-cancel",
			payment_gateway="Test Gateway",
		)
		self.cleanup_items.append(("LMS Payment", late.payment))
		subscription.reload()
		self.assertFalse(late.applied)
		self.assertEqual(subscription.status, "Cancelled")
		self.assertEqual(subscription.current_period_end, period_end)
		self.assertEqual(frappe.db.get_value("LMS Payment", late.payment, "payment_status"), "Paid")

		second = self._create_subscription()
		second_payment = self._create_payment(
			"LMS Subscription", second.name, subscription=second.name, payment_id="pay-period-end"
		)
		complete_enrollment(second_payment.name)
		second.reload()
		second_end = second.current_period_end
		frappe.set_user(self.student.name)
		cancel_subscription(second.name, at_period_end=True)
		frappe.set_user("Administrator")
		late_renewal = record_subscription_event(
			second.name,
			"Paid",
			"event-after-period-cancel",
			provider_payment_id="pay-after-period-cancel",
			payment_gateway="Test Gateway",
		)
		self.cleanup_items.append(("LMS Payment", late_renewal.payment))
		second.reload()
		self.assertFalse(late_renewal.applied)
		self.assertEqual(second.status, "Active")
		self.assertTrue(second.cancel_at_period_end)
		self.assertEqual(second.current_period_end, second_end)

	def test_higher_tier_upgrade_cancels_old_subscription_and_blocks_lower_checkout(self):
		basic = self._create_subscription()
		basic_payment = self._create_payment(
			"LMS Subscription", basic.name, subscription=basic.name, payment_id="pay-basic"
		)
		complete_enrollment(basic_payment.name)

		higher_tier = frappe.get_doc(
			{
				"doctype": "LMS Subscription Tier",
				"tier_name": f"Higher {frappe.generate_hash(length=6)}",
				"rank": self.tier.rank + 1,
				"enabled": 1,
			}
		).insert()
		self.cleanup_items.append((higher_tier.doctype, higher_tier.name))
		higher_plan = frappe.get_doc(
			{
				"doctype": "LMS Subscription Plan",
				"plan_name": f"Higher Plan {frappe.generate_hash(length=6)}",
				"tier": higher_tier.name,
				"billing_interval": "Month",
				"interval_count": 1,
				"amount": 50,
				"currency": "USD",
				"enabled": 1,
			}
		).insert()
		self.cleanup_items.append((higher_plan.doctype, higher_plan.name))

		upgrade = get_or_create_pending_subscription(higher_plan.name, self.student.name, "Test Gateway")
		self.cleanup_items.append((upgrade.doctype, upgrade.name))
		upgrade_payment = self._create_payment(
			"LMS Subscription", upgrade.name, subscription=upgrade.name, payment_id="pay-upgrade"
		)
		complete_enrollment(upgrade_payment.name)
		basic.reload()
		upgrade.reload()
		self.assertEqual(basic.status, "Cancelled")
		self.assertEqual(upgrade.status, "Active")

		with self.assertRaises(frappe.ValidationError):
			get_or_create_pending_subscription(self.plan.name, self.student.name, "Test Gateway")

	def test_past_due_member_can_retry_same_plan(self):
		subscription = self._create_subscription()
		subscription.db_set(
			{
				"status": "Past Due",
				"current_period_start": add_days(nowdate(), -40),
				"current_period_end": add_days(nowdate(), -10),
			},
			update_modified=False,
		)
		retry = get_or_create_pending_subscription(self.plan.name, self.student.name, "Test Gateway")
		self.assertEqual(retry.name, subscription.name)
		self.assertEqual(retry.status, "Pending")

	def test_provider_event_idempotency_is_scoped_by_gateway(self):
		self.assertNotEqual(
			get_provider_event_key("Gateway A", "event-1"),
			get_provider_event_key("Gateway B", "event-1"),
		)
		self.assertEqual(
			get_provider_event_key(" Gateway A ", "event-1"),
			get_provider_event_key("gateway a", "event-1"),
		)

	def test_expiry_preserves_subscription_record(self):
		subscription = self._create_subscription()
		subscription.db_set(
			{
				"status": "Active",
				"current_period_start": add_days(nowdate(), -32),
				"current_period_end": add_days(nowdate(), -2),
			},
			update_modified=False,
		)
		self.assertGreaterEqual(expire_subscriptions(), 1)
		subscription.reload()
		self.assertEqual(subscription.status, "Expired")

	def test_cancellation_requires_owner_and_cancellable_status(self):
		subscription = self._create_subscription()
		other = self._create_user(
			f"subscription-other-{frappe.generate_hash(length=6)}@example.com",
			"Other",
			"Member",
			["LMS Student"],
		)
		subscription.db_set(
			{
				"status": "Active",
				"current_period_start": nowdate(),
				"current_period_end": add_days(nowdate(), 30),
			},
			update_modified=False,
		)

		frappe.set_user(other.name)
		with self.assertRaises(frappe.PermissionError):
			cancel_subscription(subscription.name, at_period_end=True)

		frappe.set_user(self.student.name)
		subscription.db_set("status", "Expired", update_modified=False)
		with self.assertRaises(frappe.ValidationError):
			cancel_subscription(subscription.name, at_period_end=True)
		frappe.set_user("Administrator")

	def test_cancel_at_period_end_becomes_cancelled_on_expiry(self):
		subscription = self._create_subscription()
		subscription.db_set(
			{
				"status": "Active",
				"cancel_at_period_end": 1,
				"current_period_start": add_days(nowdate(), -32),
				"current_period_end": add_days(nowdate(), -2),
			},
			update_modified=False,
		)
		self.assertGreaterEqual(expire_subscriptions(), 1)
		subscription.reload()
		self.assertEqual(subscription.status, "Cancelled")
		self.assertTrue(subscription.cancelled_on)

	def test_program_sync_recomputes_progress_for_reused_and_removed_courses(self):
		complete_course = self._create_course(f"Complete Program Course {frappe.generate_hash(length=6)}")
		incomplete_course = self._create_course(f"Incomplete Program Course {frappe.generate_hash(length=6)}")
		complete_enrollment_row = self._create_enrollment(self.student.name, complete_course.name)
		self._create_enrollment(self.student.name, incomplete_course.name)
		frappe.db.set_value(
			"LMS Enrollment", complete_enrollment_row.name, "progress", 100, update_modified=False
		)
		program = frappe.get_doc(
			{
				"doctype": "LMS Program",
				"title": f"Progress Program {frappe.generate_hash(length=6)}",
				"published": 1,
				"paid_program": 1,
				"program_price": 25,
				"currency": "USD",
				"program_courses": [
					{"course": complete_course.name},
					{"course": incomplete_course.name},
				],
			}
		).insert()
		self.cleanup_items.append((program.doctype, program.name))
		payment = self._create_payment("LMS Program", program.name, payment_id="pay-progress-program")
		complete_enrollment(payment.name)
		self.assertEqual(
			frappe.db.get_value(
				"LMS Program Member",
				{"parent": program.name, "member": self.student.name},
				"progress",
			),
			50,
		)

		program.reload()
		program.set(
			"program_courses",
			[row for row in program.program_courses if row.course != incomplete_course.name],
		)
		program.save()
		self.assertEqual(
			frappe.db.get_value(
				"LMS Program Member",
				{"parent": program.name, "member": self.student.name},
				"progress",
			),
			100,
		)

		program.reload()
		program.set("program_courses", [])
		program.save()
		self.assertEqual(
			frappe.db.get_value(
				"LMS Program Member",
				{"parent": program.name, "member": self.student.name},
				"progress",
			),
			0,
		)

	def test_program_purchase_uses_stored_member_and_syncs_dynamic_course_bundle(self):
		first_course = self._create_course(f"Purchased Program Course {frappe.generate_hash(length=6)}")
		first_course.update({"paid_course": 1, "course_price": 40, "currency": "USD"})
		first_course.save()
		program = frappe.get_doc(
			{
				"doctype": "LMS Program",
				"title": f"Purchased Program {frappe.generate_hash(length=6)}",
				"published": 1,
				"paid_program": 1,
				"program_price": 25,
				"currency": "USD",
				"program_courses": [{"course": first_course.name}],
			}
		).insert()
		self.cleanup_items.append((program.doctype, program.name))
		payment = self._create_payment("LMS Program", program.name, payment_id="pay-program")

		frappe.set_user("Guest")
		complete_enrollment(payment.name, "LMS Program", program.name)
		frappe.set_user("Administrator")

		membership = frappe.db.get_value(
			"LMS Program Member",
			{"parent": program.name, "member": self.student.name},
			["name", "access_source", "permanent_access", "payment"],
			as_dict=True,
		)
		self.assertEqual(membership.access_source, "Purchase")
		self.assertTrue(membership.permanent_access)
		self.assertEqual(membership.payment, payment.name)
		first_enrollment = frappe.db.get_value(
			"LMS Enrollment",
			{"course": first_course.name, "member": self.student.name},
			["name", "access_source", "enrollment_from_program"],
			as_dict=True,
		)
		self.assertEqual(first_enrollment.access_source, "Program")
		self.assertEqual(first_enrollment.enrollment_from_program, program.name)
		self.assertTrue(get_course_access(first_course.name, self.student.name).allowed)

		future_course = self._create_course(f"Future Program Course {frappe.generate_hash(length=6)}")
		future_course.update({"paid_course": 1, "course_price": 50, "currency": "USD"})
		future_course.save()
		program.reload()
		program.append("program_courses", {"course": future_course.name})
		program.save()
		self.assertTrue(
			frappe.db.exists("LMS Enrollment", {"course": future_course.name, "member": self.student.name})
		)

		program.reload()
		program.set(
			"program_courses",
			[row for row in program.program_courses if row.course != first_course.name],
		)
		program.save()
		self.assertFalse(get_course_access(first_course.name, self.student.name).allowed)
		self.assertTrue(frappe.db.exists("LMS Enrollment", first_enrollment.name))
