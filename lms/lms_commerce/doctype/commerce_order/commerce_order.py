import frappe
from frappe import _
from frappe.model.document import Document

# An object identity cannot be supplied through Frappe's JSON document API.
CHECKOUT_WRITE = object()


class CommerceOrder(Document):
	def validate(self):
		if self.flags.get("checkout_write") is not CHECKOUT_WRITE:
			frappe.throw(_("Orders are managed by the checkout service."), frappe.PermissionError)

	def on_trash(self):
		if not frappe.flags.in_test:
			frappe.throw(_("Payment audit records cannot be deleted."), frappe.PermissionError)
