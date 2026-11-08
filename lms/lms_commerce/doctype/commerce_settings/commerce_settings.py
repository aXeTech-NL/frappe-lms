from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from lms.lms_commerce.utils import validate_safe_url


class CommerceSettings(Document):
	def validate(self):
		previous = self.get_doc_before_save()
		if cint(self.allow_live_payments) != cint(previous.allow_live_payments if previous else 0):
			frappe.only_for("System Manager")
		self.terms_url = validate_safe_url(self.terms_url)
		if self.checkout_enabled and (not self.payment_gateway or not self.terms_url):
			frappe.throw(_("Checkout requires a payment gateway and published terms."))
		if self.enabled:
			from lms.lms_commerce.install import validate_lms_policy_capability

			validate_lms_policy_capability()
		if cint(self.contract_version) != 1:
			frappe.throw(_("Only LMS entitlement contract version 1 is supported."))
		self.portal_path = validate_safe_url(self.portal_path, required=True)
		parsed = urlparse(self.portal_path)
		if parsed.query or parsed.fragment:
			frappe.throw(_("Portal Path cannot contain a query string or fragment."))
