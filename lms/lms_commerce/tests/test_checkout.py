from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from lms.lms_commerce.services import checkout
from lms.lms_commerce.services.entitlements import grant_manual_entitlement
from lms.lms_commerce.tests.test_helpers import CommerceIntegrationTestCase


class TestCheckout(CommerceIntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.saved_checkout = frappe.get_single("Commerce Settings").as_dict()
		self.old_host = frappe.conf.get("host_name")
		frappe.conf.host_name = "https://checkout.example.test"
		self.user = self.create_user()
		self.course = self.create_course()
		self.offer = self.create_offering(self.course, "Purchase", currency="EUR")
		self.gateway = "Checkout-Test-" + frappe.generate_hash(length=8)
		frappe.get_doc({"doctype": "Payment Gateway", "gateway": self.gateway}).insert(
			ignore_permissions=True
		)
		self.cleanup_items.append(("Payment Gateway", self.gateway))
		settings = frappe.get_single("Commerce Settings")
		settings.checkout_enabled = 1
		settings.payment_gateway = self.gateway
		settings.terms_url = "/terms/v1"
		settings.allow_live_payments = 0
		settings.save(ignore_permissions=True)
		self.config = patch(
			"payments.checkout.configuration",
			return_value={
				"mode": "test",
				"webhook_url": "https://checkout.example.test/hook",
				"account_fingerprint": "account-one",
			},
		)
		self.config_mock = self.config.start()
		self.addCleanup(self.config.stop)
		self.begin = patch("payments.checkout.begin", side_effect=self.provider_begin)
		self.begin_mock = self.begin.start()
		self.addCleanup(self.begin.stop)
		# Preserve IntegrationTestCase rollback isolation while testing the creation boundary.
		self.commit = patch.object(frappe.db, "commit")
		self.commit_mock = self.commit.start()
		self.addCleanup(self.commit.stop)
		frappe.set_user(self.user.name)

	def tearDown(self):
		frappe.set_user("Administrator")
		for order in frappe.get_all(
			"Commerce Order", filters={"member": self.user.name}, fields=["name", "entitlement"]
		):
			frappe.db.set_value("Commerce Order", order.name, "entitlement", None)
			if order.entitlement:
				frappe.delete_doc(
					"Commerce Entitlement", order.entitlement, force=True, ignore_permissions=True
				)
			frappe.delete_doc("Commerce Order", order.name, force=True, ignore_permissions=True)
		settings = frappe.get_single("Commerce Settings")
		for field in ("checkout_enabled", "payment_gateway", "terms_url", "allow_live_payments"):
			settings.set(field, self.saved_checkout.get(field))
		settings.save(ignore_permissions=True)
		frappe.conf.host_name = self.old_host
		super().tearDown()

	def provider_begin(self, gateway, request):
		self.assertEqual(gateway, self.gateway)
		self.assertTrue(
			frappe.db.exists("Commerce Order", request["merchant_reference"].removeprefix("lms-order:"))
		)
		self.assertTrue(self.commit_mock.called, "Order must be durable before contacting Mollie")
		self.payment = {
			"merchant_reference": request["merchant_reference"],
			"customer_reference": request["customer_reference"],
			"provider_payment_id": "tr_test" + frappe.generate_hash(length=8),
			"amount": request["amount"],
			"currency": request["currency"],
			"mode": "test",
			"status": "open",
			"checkout_url": "https://www.mollie.com/checkout/test",
		}
		return self.payment

	def start(self):
		quotation = checkout.get_quote(self.offer.name)
		return checkout.start_checkout(self.offer.name, quotation["quote_token"], True)

	def notify(self, status="paid", **fields):
		frappe.set_user("Guest")
		checkout.payment_updated(self.gateway, {**self.payment, "status": status, **fields})
		frappe.set_user(self.user.name)

	def test_start_double_click_and_return_never_grant_access(self):
		order = self.start()
		second = self.start()
		self.assertEqual(order["name"], second["name"])
		self.assertEqual(self.begin_mock.call_count, 1)
		self.assertFalse(checkout.get_order(order["name"])["access_granted"])
		self.assertFalse(frappe.db.exists("Commerce Entitlement", {"member": self.user.name}))
		self.assertEqual(frappe.db.count("Commerce Order", {"member": self.user.name}), 1)

	def test_paid_event_grants_once_without_bypassing_native_enrollment(self):
		order = self.start()
		self.notify()
		self.notify()
		self.assertTrue(checkout.get_order(order["name"])["access_granted"])
		self.assertEqual(frappe.db.count("Commerce Entitlement", {"member": self.user.name}), 1)
		self.assertFalse(
			frappe.db.exists("LMS Enrollment", {"member": self.user.name, "course": self.course.name})
		)
		with self.assertRaises(frappe.ValidationError):
			checkout.get_quote(self.offer.name)

	def test_full_refund_then_old_paid_event_cannot_restore_access(self):
		order = self.start()
		self.notify()
		self.notify("refunded", refunded_amount="25.00")
		self.notify()
		result = checkout.get_order(order["name"])
		self.assertEqual(result["status"], "refunded")
		self.assertFalse(result["access_granted"])

	def test_partial_refund_preserves_access_but_chargeback_revokes(self):
		order = self.start()
		self.notify()
		self.notify("partially_refunded", refunded_amount="5.00")
		self.assertTrue(checkout.get_order(order["name"])["access_granted"])
		self.notify("partially_charged_back", refunded_amount="5.00", charged_back_amount="1.00")
		self.assertFalse(checkout.get_order(order["name"])["access_granted"])

	def test_refund_does_not_revoke_independent_manual_access(self):
		self.start()
		frappe.set_user("Administrator")
		manual = grant_manual_entitlement(self.user.name, "Target", "LMS Course", self.course.name)
		self.cleanup_items.append(("Commerce Entitlement", manual))
		self.notify()
		self.notify("refunded", refunded_amount="25.00")
		self.assertEqual(frappe.db.get_value("Commerce Entitlement", manual, "status"), "Active")

	def test_price_currency_account_member_and_mode_must_match(self):
		order = self.start()
		for changes in (
			{"amount": "1.00"},
			{"currency": "USD"},
			{"customer_reference": "victim"},
			{"mode": "live"},
			{"provider_payment_id": "tr_other"},
		):
			with self.subTest(changes=changes), self.assertRaises(ValueError):
				checkout.payment_updated(self.gateway, {**self.payment, "status": "paid", **changes})
		with self.assertRaises(ValueError):
			checkout.payment_updated("Other-Gateway", {**self.payment, "status": "paid"})
		self.assertFalse(checkout.get_order(order["name"])["access_granted"])

	def test_guest_disabled_user_and_other_member_cannot_read_order(self):
		order = self.start()
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			checkout.get_order(order["name"])
		frappe.set_user("Administrator")
		other = self.create_user()
		frappe.set_user(other.name)
		with self.assertRaises(frappe.PermissionError):
			checkout.refresh_order(order["name"])
		frappe.db.set_value("User", self.user.name, "enabled", 0)
		frappe.set_user(self.user.name)
		with self.assertRaises(frappe.PermissionError):
			checkout.get_order(order["name"])

	def test_quote_change_and_missing_consent_never_contact_provider(self):
		quotation = checkout.get_quote(self.offer.name)
		with self.assertRaises(frappe.ValidationError):
			checkout.start_checkout(self.offer.name, quotation["quote_token"], False)
		frappe.db.set_value("Commerce Offering", self.offer.name, "amount", 30)
		with self.assertRaises(frappe.ValidationError):
			checkout.start_checkout(self.offer.name, quotation["quote_token"], True)
		self.begin_mock.assert_not_called()

	def test_native_paid_unpublished_upcoming_or_restricted_course_cannot_be_sold(self):
		for field, value in (
			("paid_course", 1),
			("published", 0),
			("upcoming", 1),
			("disable_self_learning", 1),
		):
			old = frappe.db.get_value("LMS Course", self.course.name, field)
			frappe.db.set_value("LMS Course", self.course.name, field, value)
			with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
				checkout.get_quote(self.offer.name)
			frappe.db.set_value("LMS Course", self.course.name, field, old)

	def test_disabled_checkout_and_live_key_fail_closed(self):
		frappe.db.set_single_value("Commerce Settings", "checkout_enabled", 0)
		with self.assertRaises(frappe.ValidationError):
			self.start()
		frappe.db.set_single_value("Commerce Settings", "checkout_enabled", 1)
		self.config_mock.return_value["mode"] = "live"
		with self.assertRaises(frappe.ValidationError):
			self.start()
		self.begin_mock.assert_not_called()

	def test_timeout_retries_same_saved_order(self):
		self.begin_mock.side_effect = TimeoutError("uncertain provider response")
		with self.assertRaises(TimeoutError):
			self.start()
		quotation = checkout.get_quote(self.offer.name)
		self.assertIn("pending_order", quotation)
		self.begin_mock.side_effect = self.provider_begin
		order = self.start()
		self.assertEqual(order["name"], quotation["pending_order"])
		keys = [call.args[1]["idempotency_key"] for call in self.begin_mock.call_args_list]
		self.assertEqual(keys[0], keys[1])
		self.assertEqual(frappe.db.count("Commerce Order", {"member": self.user.name}), 1)

	def test_uncertain_old_creation_is_not_recharged(self):
		self.begin_mock.side_effect = TimeoutError()
		with self.assertRaises(TimeoutError):
			self.start()
		order = checkout.get_quote(self.offer.name)["pending_order"]
		frappe.db.set_value("Commerce Order", order, "creation", add_to_date(now_datetime(), hours=-21))
		self.begin_mock.reset_mock()
		with self.assertRaises(frappe.ValidationError):
			checkout.refresh_order(order)
		self.begin_mock.assert_not_called()

	def test_failed_payment_and_late_open_do_not_grant(self):
		order = self.start()
		self.notify("failed")
		self.notify("open")
		self.assertEqual(checkout.get_order(order["name"])["status"], "failed")
		self.assertFalse(checkout.get_order(order["name"])["access_granted"])

	def test_reconcile_fetches_authoritatively_and_does_not_create_payment(self):
		order = self.start()
		with patch("payments.checkout.fetch", return_value={**self.payment, "status": "paid"}) as fetch:
			result = checkout.refresh_order(order["name"])
			fetch.assert_called_once_with(self.gateway, self.payment["provider_payment_id"])
		self.assertTrue(result["access_granted"])
		self.assertEqual(self.begin_mock.call_count, 1)

	def test_payment_order_and_entitlement_cannot_be_manually_forged(self):
		order = self.start()
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Commerce Order", order["name"])
		doc.status = "paid"
		with self.assertRaises(frappe.PermissionError):
			doc.save(ignore_permissions=True)
		grant = frappe.get_doc(
			{
				"doctype": "Commerce Entitlement",
				"member": self.user.name,
				"scope": "Target",
				"target_doctype": "LMS Course",
				"target_name": self.course.name,
				"status": "Active",
				"source_type": "Purchase",
				"source_doctype": "Commerce Order",
				"source_name": order["name"],
			}
		)
		with self.assertRaises(frappe.PermissionError):
			grant.insert(ignore_permissions=True)

	def test_gateway_rotation_does_not_replay_uncertain_creation(self):
		self.begin_mock.side_effect = TimeoutError()
		with self.assertRaises(TimeoutError):
			self.start()
		self.config_mock.return_value["account_fingerprint"] = "another-account"
		self.begin_mock.reset_mock()
		with self.assertRaises(frappe.ValidationError):
			self.start()
		self.begin_mock.assert_not_called()

	def test_new_offering_cannot_duplicate_an_open_course_payment(self):
		order = self.start()
		frappe.set_user("Administrator")
		self.offer.enabled = 0
		self.offer.save(ignore_permissions=True)
		new = self.create_offering(self.course, "Purchase", currency="EUR", amount=30)
		frappe.set_user(self.user.name)
		quotation = checkout.get_quote(new.name)
		self.assertEqual(quotation["pending_order"], order["name"])
		self.assertEqual(quotation["amount"], "25.00")

	def test_named_mollie_controller_webhook_and_native_enrollment(self):
		from payments.payment_gateways.doctype.mollie_settings.checkout import webhook
		from payments.payment_gateways.doctype.mollie_settings.mollie_settings import MollieSettings

		self.begin.stop()
		self.config.stop()
		frappe.set_user("Administrator")
		account = frappe.get_doc(
			{
				"doctype": "Mollie Settings",
				"gateway_name": "Checkout-" + frappe.generate_hash(length=8),
				"enabled": 1,
				"api_key": "test_isolated_not_a_real_key",
			}
		).insert(ignore_permissions=True)
		self.cleanup_items.extend(
			[("Mollie Settings", account.name), ("Payment Gateway", account.payment_gateway)]
		)
		settings = frappe.get_single("Commerce Settings")
		settings.payment_gateway = account.payment_gateway
		settings.save(ignore_permissions=True)
		remote = {}

		def provider(method, path, *, payload=None, idempotency_key=None):
			if method == "POST":
				self.assertEqual(path, "/payments")
				self.assertEqual(payload["sequenceType"], "oneoff")
				remote.update(
					id="tr_integration1",
					status="open",
					mode="test",
					amount=payload["amount"],
					metadata=payload["metadata"],
					sequenceType="oneoff",
					_links={"checkout": {"href": "https://www.mollie.com/checkout/integration"}},
				)
			else:
				self.assertEqual((method, path), ("GET", "/payments/tr_integration1"))
			return dict(remote)

		with patch.object(MollieSettings, "_request", side_effect=provider):
			frappe.set_user(self.user.name)
			order = self.start()
			remote["status"] = "paid"
			frappe.set_user("Guest")
			frappe.form_dict = frappe._dict(id="tr_integration1", status="failed", amount="0.01")
			webhook(account.payment_gateway, account.get_password("webhook_token"))
			webhook(account.payment_gateway, account.get_password("webhook_token"))
			frappe.set_user(self.user.name)
			self.assertTrue(checkout.get_order(order["name"])["access_granted"])
			enrollment = frappe.get_doc(
				{"doctype": "LMS Enrollment", "course": self.course.name, "member": self.user.name}
			).insert()
			self.cleanup_items.append(("LMS Enrollment", enrollment.name))
			self.assertEqual(frappe.db.count("Commerce Entitlement", {"member": self.user.name}), 1)

	def test_course_presentation_uses_native_checkout_route(self):
		from lms.lms_commerce.presentation import decorate_courses

		course = frappe._dict(name=self.course.name)
		decorate_courses([course])
		self.assertIn("/lms/checkout/", course.commerce["offers"][0]["url"])
		self.assertNotIn("mollie.com", course.commerce["offers"][0]["url"])
