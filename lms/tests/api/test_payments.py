import frappe

from lms.lms import payments as payments_module
from lms.lms.test_helpers import BaseTestUtils


class FakeRazorpayController:
	"""Stands in for the payments app's RazorpaySettings.

	Mirrors the real controller: `get_payment_url` creates the order itself when
	the caller hasn't supplied an `order_id`, `create_order` converts rupees to
	paise, and both write an Integration Request. `direct_create_order_calls`
	records the calls that did *not* come from inside `get_payment_url`, i.e.
	the ones LMS made on its own.
	"""

	def __init__(self):
		self.create_order_calls = []
		self.direct_create_order_calls = []
		self.get_payment_url_calls = []
		self.integration_requests = []
		self._inside_get_payment_url = False

	def create_order(self, **kwargs):
		self.create_order_calls.append(kwargs)
		if not self._inside_get_payment_url:
			self.direct_create_order_calls.append(kwargs)
		paise = dict(kwargs, amount=int(kwargs["amount"] * 100))
		self.integration_requests.append(paise)
		return {"id": "order_TEST123"}

	def get_payment_url(self, **kwargs):
		self.get_payment_url_calls.append(dict(kwargs))
		self._inside_get_payment_url = True
		try:
			if not kwargs.get("order_id"):
				order = self.create_order(**kwargs)
				kwargs.update({"order_id": order.get("id")})
		finally:
			self._inside_get_payment_url = False
		self.integration_requests.append(kwargs)
		return "https://example.test/razorpay_checkout?token=IR-TEST"


class TestPaymentLink(BaseTestUtils):
	"""LMS used to pre-create the Razorpay order and hand the resulting
	`order_id` to `get_payment_url`, which creates the order itself whenever one
	is missing. That put gateway-specific order logic (and a hard-coded
	`if payment_gateway != "Razorpay"`) in LMS, duplicating what the payments app
	owns, while omitting the `receipt` / `payment_capture` fields the controller's
	order payload expects. Ordering the call through `get_payment_url` alone keeps
	LMS gateway-agnostic.
	"""

	def setUp(self):
		super().setUp()
		self.controller = FakeRazorpayController()
		self.original_get_controller = payments_module.get_controller
		payments_module.get_controller = lambda gateway: self.controller

		self.original_gateway = frappe.db.get_single_value("LMS Settings", "payment_gateway")
		self.original_subscriptions = frappe.db.get_single_value("LMS Settings", "enable_subscriptions")
		frappe.db.set_single_value("LMS Settings", "payment_gateway", "Razorpay")

		hash = frappe.generate_hash(length=6)
		self.instructor = self._create_user(
			f"payinstr-{hash}@example.com", "Ina", "Instructor", ["Course Creator"]
		)
		self.course = self._create_course(
			title=f"Paid Payments Course {hash}", instructor=self.instructor.email
		)
		self.course.db_set({"paid_course": 1, "course_price": 500, "currency": "INR"}, update_modified=False)
		self.tier = frappe.get_doc(
			{
				"doctype": "LMS Subscription Tier",
				"tier_name": f"Checkout Tier {hash}",
				"rank": int(hash[:4], 36) + 100,
				"enabled": 1,
			}
		).insert()
		self.cleanup_items.append((self.tier.doctype, self.tier.name))
		self.plan = frappe.get_doc(
			{
				"doctype": "LMS Subscription Plan",
				"plan_name": f"Checkout Plan {hash}",
				"tier": self.tier.name,
				"billing_interval": "Month",
				"interval_count": 1,
				"amount": 500,
				"currency": "INR",
				"enabled": 1,
			}
		).insert()
		self.cleanup_items.append((self.plan.doctype, self.plan.name))

	def tearDown(self):
		payments_module.get_controller = self.original_get_controller
		frappe.db.set_single_value("LMS Settings", "payment_gateway", self.original_gateway)
		frappe.db.set_single_value("LMS Settings", "enable_subscriptions", self.original_subscriptions or 0)
		frappe.clear_document_cache("LMS Settings", "LMS Settings")
		super().tearDown()

	def _buy_course(self):
		return payments_module.get_payment_link(
			doctype="LMS Course",
			docname=self.course.name,
			address={
				"billing_name": "Test Buyer",
				"address_line1": "1 Test Street",
				"city": "Test City",
				"country": "India",
				"pincode": "560001",
				"source": "Website",
				"member_consent": 1,
			},
			payment_for_certificate=0,
		)

	def _buy_subscription(self):
		frappe.db.set_single_value("LMS Settings", "enable_subscriptions", 1)
		frappe.clear_document_cache("LMS Settings", "LMS Settings")
		return payments_module.get_payment_link(
			doctype="LMS Subscription Plan",
			docname=self.plan.name,
			address={
				"billing_name": "Subscription Buyer",
				"address_line1": "1 Test Street",
				"city": "Test City",
				"country": "India",
				"pincode": "560001",
				"source": "Website",
				"member_consent": 1,
			},
			payment_for_certificate=0,
		)

	def test_subscription_checkout_references_pending_subscription(self):
		self._buy_subscription()
		request = self.controller.get_payment_url_calls[-1]
		self.assertEqual(request["reference_doctype"], "LMS Subscription")
		subscription = frappe.get_doc("LMS Subscription", request["reference_docname"])
		self.cleanup_items.append((subscription.doctype, subscription.name))
		self.assertEqual(subscription.plan, self.plan.name)
		self.assertEqual(subscription.status, "Pending")
		payment = frappe.db.get_value(
			"LMS Payment", request["payment"], ["subscription", "member"], as_dict=True
		)
		self.cleanup_items.append(("LMS Payment", request["payment"]))
		self.assertEqual(payment.subscription, subscription.name)
		self.assertEqual(payment.member, frappe.session.user)

	def test_direct_api_cannot_checkout_an_unpublished_program(self):
		frappe.db.set_single_value("LMS Settings", "enable_subscriptions", 1)
		frappe.clear_document_cache("LMS Settings", "LMS Settings")
		program = frappe.get_doc(
			{
				"doctype": "LMS Program",
				"title": f"Unpublished Checkout {frappe.generate_hash(length=6)}",
				"published": 0,
				"paid_program": 1,
				"program_price": 500,
				"currency": "INR",
			}
		).insert()
		self.cleanup_items.append((program.doctype, program.name))
		before = len(self.controller.get_payment_url_calls)

		with self.assertRaises(frappe.PermissionError):
			payments_module.get_payment_link(
				doctype="LMS Program",
				docname=program.name,
				address={
					"billing_name": "Program Buyer",
					"address_line1": "1 Test Street",
					"city": "Test City",
					"country": "India",
					"pincode": "560001",
					"source": "Website",
					"member_consent": 1,
				},
				payment_for_certificate=0,
			)
		self.assertEqual(len(self.controller.get_payment_url_calls), before)
		self.assertFalse(
			frappe.db.exists(
				"LMS Payment",
				{"payment_for_document_type": "LMS Program", "payment_for_document": program.name},
			)
		)

	def test_direct_api_cannot_checkout_a_sold_out_batch(self):
		batch = self._create_batch(
			self.course.name,
			instructor=self.instructor.email,
			title=f"Sold Out Checkout {frappe.generate_hash(length=6)}",
		)
		batch.db_set(
			{"paid_batch": 1, "amount": 500, "currency": "INR", "seat_count": 1},
			update_modified=False,
		)
		other = self._create_user(
			f"sold-out-{frappe.generate_hash(length=6)}@example.com",
			"Sold",
			"Out",
			["LMS Student"],
		)
		self._create_batch_enrollment(other.name, batch.name)
		before = len(self.controller.get_payment_url_calls)

		with self.assertRaises(frappe.PermissionError):
			payments_module.get_payment_link(
				doctype="LMS Batch",
				docname=batch.name,
				address={
					"billing_name": "Batch Buyer",
					"address_line1": "1 Test Street",
					"city": "Test City",
					"country": "India",
					"pincode": "560001",
					"source": "Website",
					"member_consent": 1,
				},
				payment_for_certificate=0,
			)
		self.assertEqual(len(self.controller.get_payment_url_calls), before)

	def test_checkout_rejects_country_that_differs_from_billing_address(self):
		before = len(self.controller.get_payment_url_calls)
		with self.assertRaises(frappe.ValidationError):
			payments_module.get_payment_link(
				doctype="LMS Course",
				docname=self.course.name,
				address={
					"billing_name": "Country Mismatch",
					"address_line1": "1 Test Street",
					"city": "Amsterdam",
					"country": "Netherlands",
					"source": "Website",
					"member_consent": 1,
				},
				payment_for_certificate=0,
				country="India",
			)
		self.assertEqual(len(self.controller.get_payment_url_calls), before)

	def test_lms_never_calls_create_order_itself(self):
		"""The regression guard: order creation belongs to the gateway
		controller. Before the fix LMS called `create_order` directly whenever
		the gateway happened to be named Razorpay."""
		self._buy_course()

		self.assertEqual(self.controller.direct_create_order_calls, [])
		self.assertEqual(len(self.controller.get_payment_url_calls), 1)

	def test_no_create_order_helper_remains(self):
		"""`create_order` in lms.lms.payments was a stale copy of logic that has
		since moved into the payments app."""
		self.assertFalse(
			hasattr(payments_module, "create_order"),
			"lms.lms.payments.create_order duplicates the payments app controller",
		)

	def test_controller_still_gets_an_order_created(self):
		"""Delegating must not lose the order. `get_payment_url` creates one
		because LMS no longer supplies an `order_id`."""
		self._buy_course()

		self.assertEqual(len(self.controller.create_order_calls), 1)
		self.assertIsNone(self.controller.get_payment_url_calls[0].get("order_id"))

	def test_payment_url_receives_the_amount_in_rupees(self):
		"""LMS passes the order total untouched; converting to paise is the
		controller's job."""
		self._buy_course()

		self.assertEqual(self.controller.get_payment_url_calls[0]["amount"], 500)

	def test_the_request_carrying_the_order_id_is_written_last(self):
		"""The controller writes two Integration Requests per attempt: the paise
		order payload, then the checkout payload with the `order_id`.
		`update_payment_record` reads requests newest-first and keeps the newest
		payload for each payment, so it depends on the second one being the newer
		row. This documents that contract; the duplication itself lives
		in the payments app and is unchanged by this fix."""
		self._buy_course()

		self.assertEqual(len(self.controller.integration_requests), 2)
		self.assertNotIn("order_id", self.controller.integration_requests[0])
		self.assertEqual(self.controller.integration_requests[-1]["order_id"], "order_TEST123")
