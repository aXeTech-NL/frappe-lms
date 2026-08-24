# Copyright (c) 2026, Frappe and Contributors
# See license.txt

import frappe
from frappe.tests import UnitTestCase

from lms import entitlements


class TestExternalEntitlementContract(UnitTestCase):
	def setUp(self):
		self.original_get_hooks = frappe.get_hooks
		self.original_get_attr = frappe.get_attr
		self.original_log_error = frappe.log_error
		self.addCleanup(setattr, frappe, "get_hooks", self.original_get_hooks)
		self.addCleanup(setattr, frappe, "get_attr", self.original_get_attr)
		self.addCleanup(setattr, frappe, "log_error", self.original_log_error)
		for field in ("lms_entitlement_decisions", "lms_entitlement_failure_logged"):
			if hasattr(frappe.local, field):
				delattr(frappe.local, field)

	def _install_provider(self, provider):
		frappe.get_hooks = lambda hook=None, *args, **kwargs: (
			["test.provider"]
			if hook == "lms_entitlement_provider"
			else self.original_get_hooks(hook, *args, **kwargs)
		)
		frappe.get_attr = lambda path: provider if path == "test.provider" else self.original_get_attr(path)

	def test_no_provider_is_exact_unmanaged_fallback(self):
		frappe.get_hooks = lambda hook=None, *args, **kwargs: (
			[] if hook == "lms_entitlement_provider" else self.original_get_hooks(hook, *args, **kwargs)
		)
		decision = entitlements.decide("course", "course-a", "catalog", user="Guest")
		self.assertFalse(decision.handled)
		self.assertFalse(decision.allowed)
		self.assertEqual(decision.offers, [])

	def test_bulk_provider_is_called_once_and_request_cached(self):
		calls = []

		def provider(**kwargs):
			calls.append(kwargs)
			return {
				request["key"]: {
					"handled": True,
					"allowed": request["resource_name"] == "course-a",
					"badge": {"label": "Max", "theme": "violet", "icon": "lock"},
					"offers": [
						{
							"kind": "upgrade",
							"label": "Upgrade",
							"url": "/commerce/plans",
							"variant": "outline",
						}
					],
				}
				for request in kwargs["requests"]
			}

		self._install_provider(provider)
		requests = [
			entitlements.make_request("course", "course-a", "catalog"),
			entitlements.make_request("course", "course-b", "catalog"),
		]
		first = entitlements.decide_many(requests, user="member@example.com")
		second = entitlements.decide_many(requests, user="member@example.com")
		self.assertEqual(len(calls), 1)
		self.assertEqual(calls[0]["contract_version"], 1)
		self.assertEqual(calls[0]["user"], "member@example.com")
		self.assertTrue(first[requests[0]["key"]].allowed)
		self.assertFalse(first[requests[1]["key"]].allowed)
		self.assertEqual(second, first)

	def test_request_cache_is_isolated_by_user(self):
		calls = []

		def provider(**kwargs):
			calls.append(kwargs["user"])
			return {request["key"]: {"handled": True, "allowed": True} for request in kwargs["requests"]}

		self._install_provider(provider)
		request = entitlements.make_request("course", "course-a", "catalog")
		entitlements.decide_many([request], user="first@example.com")
		entitlements.decide_many([request], user="second@example.com")
		entitlements.decide_many([request], user="first@example.com")
		self.assertEqual(calls, ["first@example.com", "second@example.com"])

	def test_provider_output_is_bounded_and_unsafe_url_fails_closed(self):
		logged = []

		def provider(**kwargs):
			key = kwargs["requests"][0]["key"]
			return {
				key: {
					"handled": True,
					"allowed": False,
					"offers": [
						{
							"kind": "purchase",
							"label": "Pay",
							"url": "javascript:alert(1)",
							"variant": "solid",
						}
					],
				}
			}

		self._install_provider(provider)
		frappe.log_error = lambda **kwargs: logged.append(kwargs)
		decision = entitlements.decide("course", "course-a", "enroll")
		self.assertTrue(decision.handled)
		self.assertFalse(decision.allowed)
		self.assertEqual(decision.reason, "entitlement_provider_unavailable")
		self.assertEqual(decision.offers, [])
		self.assertEqual(len(logged), 1)

	def test_provider_exception_is_logged_once_per_request(self):
		logged = []

		def provider(**kwargs):
			raise RuntimeError("provider secret")

		self._install_provider(provider)
		frappe.log_error = lambda **kwargs: logged.append(kwargs)
		one = entitlements.decide("course", "course-a", "consume")
		two = entitlements.decide("course", "course-b", "consume")
		self.assertEqual(one.reason, "entitlement_provider_unavailable")
		self.assertEqual(two.reason, "entitlement_provider_unavailable")
		self.assertEqual(len(logged), 1)

	def test_multiple_providers_are_rejected(self):
		frappe.get_hooks = lambda hook=None, *args, **kwargs: (
			["first.provider", "second.provider"]
			if hook == "lms_entitlement_provider"
			else self.original_get_hooks(hook, *args, **kwargs)
		)
		with self.assertRaises(frappe.ValidationError):
			entitlements.get_provider()

	def test_context_drops_unknown_fields_and_truncates_values(self):
		request = entitlements.make_request(
			"course",
			"course-a",
			"consume",
			context={"lesson": "x" * 500, "quiz": None, "is_preview": 1, "secret": "drop"},
		)
		self.assertNotIn("secret", request["context"])
		self.assertEqual(len(request["context"]["lesson"]), entitlements.MAX_CONTEXT_VALUE_LENGTH)
		self.assertTrue(request["context"]["is_preview"])
