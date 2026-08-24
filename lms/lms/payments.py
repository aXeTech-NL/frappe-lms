import frappe
from frappe import _

from lms.lms.utils import (
	complete_enrollment,
	get_lms_route,
	get_order_summary,
)

GATEWAY_NOT_CONFIGURED_TITLE = "Payment Gateway Not Configured"


def get_payment_gateway():
	return frappe.db.get_single_value("LMS Settings", "payment_gateway")


def get_controller(payment_gateway):
	validate_payment_gateway(payment_gateway)

	from payments.utils import get_payment_gateway_controller

	return get_payment_gateway_controller(payment_gateway)


def validate_payment_gateway(payment_gateway):
	"""Fail with an actionable message instead of a permission error from the payments app."""
	if "payments" not in frappe.get_installed_apps():
		frappe.throw(
			_("The Payments app is not installed. Please contact the administrator."),
			title=_(GATEWAY_NOT_CONFIGURED_TITLE),
		)

	if not payment_gateway:
		frappe.throw(
			_("No payment gateway is configured. Please contact the administrator."),
			title=_(GATEWAY_NOT_CONFIGURED_TITLE),
		)

	if not frappe.db.exists("Payment Gateway", payment_gateway):
		frappe.throw(
			_("The configured payment gateway {0} does not exist. Please contact the administrator.").format(
				frappe.bold(payment_gateway)
			),
			title=_(GATEWAY_NOT_CONFIGURED_TITLE),
		)


@frappe.whitelist()
def get_payment_link(
	doctype: str,
	docname: str,
	address: dict,
	payment_for_certificate: int,
	coupon_code: str | None = None,
	country: str | None = None,
):
	"""Start a one-time checkout for content or a subscription's first period."""
	payment_gateway = get_payment_gateway()
	address = frappe._dict(address)
	address_country = (address.get("country") or "").strip()
	requested_country = (country or "").strip()
	if requested_country and address_country and requested_country != address_country:
		frappe.throw(_("Billing country does not match the submitted address."))
	# Tax and multicurrency treatment are properties of the saved billing
	# address. Never let a second caller-controlled argument select another
	# country's price while a different address is stored on the payment.
	country = address_country or None
	pricing_doctype = doctype
	pricing_docname = docname
	billing_types = {
		"LMS Course": "certificate" if int(payment_for_certificate) else "course",
		"LMS Batch": "batch",
		"LMS Program": "program",
		"LMS Subscription Plan": "subscription",
	}
	billing_type = billing_types.get(pricing_doctype)
	if not billing_type:
		frappe.throw(_("Unsupported billing document type."))

	# Billing.vue calls this gate for UX, but the payment endpoint is public API
	# surface too. Recheck here before a gateway redirect can charge an invalid,
	# sold-out, started, unpublished, or already-purchased target.
	from lms.lms.api import verify_billing_access

	access, message = verify_billing_access(pricing_doctype, pricing_docname, billing_type)
	if not access:
		frappe.throw(message or _("You cannot purchase this item."), frappe.PermissionError)

	redirect_to = get_redirect_url(pricing_doctype, pricing_docname, payment_for_certificate)

	if pricing_doctype in ("LMS Program", "LMS Subscription Plan"):
		from lms.lms.access import subscriptions_enabled

		if not subscriptions_enabled():
			frappe.throw(_("Subscriptions are not enabled."))
	if pricing_doctype == "LMS Subscription Plan" and coupon_code:
		frappe.throw(_("Coupons are not supported for recurring subscription plans."))

	details = frappe._dict(
		get_order_summary(pricing_doctype, pricing_docname, coupon=coupon_code, country=country)
	)
	title = details.title
	currency = details.currency
	original_amount = details.original_amount
	discount_amount = details.get("discount_amount", 0)
	gst_amount = details.get("gst_applied", 0)
	amount = original_amount - discount_amount
	amount_with_gst = get_amount_with_gst(amount, gst_amount)
	coupon = details.get("coupon")
	total_amount = amount_with_gst if amount_with_gst else amount

	# A progress enrollment is not necessarily current access: expired subscribers
	# must still be able to buy a permanent Course/Program entitlement.
	if already_has_access(pricing_doctype, pricing_docname, payment_for_certificate):
		save_address(address)
		return redirect_to

	# Validate the gateway before creating a pending subscription, Address, or
	# Payment record. The existing controller handles the hosted first-period
	# checkout; automatic recurring debit is delegated to a future provider.
	controller = get_controller(payment_gateway) if total_amount > 0 else None

	reference_doctype = pricing_doctype
	reference_docname = pricing_docname
	subscription = None
	if pricing_doctype == "LMS Subscription Plan":
		from lms.lms.subscriptions import get_or_create_pending_subscription

		subscription = get_or_create_pending_subscription(
			pricing_docname, frappe.session.user, payment_gateway
		)
		reference_doctype = "LMS Subscription"
		reference_docname = subscription.name

	payment = record_payment(
		address,
		reference_doctype,
		reference_docname,
		amount,
		original_amount,
		currency,
		amount_with_gst,
		discount_amount,
		payment_for_certificate,
		coupon_code,
		coupon,
		member=frappe.session.user,
		subscription=subscription and subscription.name,
		payment_gateway=payment_gateway,
	)

	if total_amount <= 0:
		frappe.db.set_value("LMS Payment", payment.name, {"payment_received": 1, "payment_status": "Paid"})
		complete_enrollment(payment.name, reference_doctype, reference_docname)
		return redirect_to

	payment_details = {
		"amount": total_amount,
		"title": f"Payment for {pricing_doctype} {title} {pricing_docname}",
		"description": f"{address.billing_name}'s payment for {title}",
		"reference_doctype": reference_doctype,
		"reference_docname": reference_docname,
		"payer_email": frappe.session.user,
		"payer_name": address.billing_name,
		"currency": currency,
		"payment_gateway": payment_gateway,
		"redirect_to": redirect_to,
		"payment": payment.name,
	}

	# The controller creates the order itself when no `order_id` is supplied.
	return controller.get_payment_url(**payment_details)


def already_has_access(doctype: str, docname: str, payment_for_certificate: int) -> bool:
	member = frappe.session.user

	if int(payment_for_certificate):
		return bool(
			frappe.db.get_value(
				"LMS Enrollment", {"member": member, "course": docname}, "purchased_certificate"
			)
		)

	if doctype in ("LMS Course", "LMS Program"):
		from lms.lms.access import subscriptions_enabled

		if not subscriptions_enabled() and doctype == "LMS Course":
			return bool(frappe.db.exists("LMS Enrollment", {"member": member, "course": docname}))
		membership_doctype = "LMS Enrollment" if doctype == "LMS Course" else "LMS Program Member"
		membership_filters = (
			{"member": member, "course": docname}
			if doctype == "LMS Course"
			else {"member": member, "parent": docname}
		)
		membership = frappe.db.get_value(
			membership_doctype,
			membership_filters,
			["access_source", "permanent_access"],
			as_dict=True,
		)
		from lms.lms.access import PERMANENT_ACCESS_SOURCES

		if membership and (
			not membership.access_source
			or (membership.permanent_access and membership.access_source in PERMANENT_ACCESS_SOURCES)
		):
			return True
		return bool(
			frappe.db.exists(
				"LMS Payment",
				{
					"member": member,
					"payment_for_document_type": doctype,
					"payment_for_document": docname,
					"payment_received": 1,
				},
			)
		)

	if doctype == "LMS Subscription Plan":
		from lms.lms.access import get_qualifying_subscription

		tier = frappe.db.get_value("LMS Subscription Plan", docname, "tier")
		return bool(tier and get_qualifying_subscription(member, tier))

	return bool(frappe.db.exists("LMS Batch Enrollment", {"member": member, "batch": docname}))


def get_amount_with_gst(amount: float, gst_amount: float) -> float:
	amount_with_gst = 0
	if gst_amount:
		amount_with_gst = amount + gst_amount

	return amount_with_gst


def record_payment(
	address: dict,
	doctype: str,
	docname: str,
	amount: float,
	original_amount: float,
	currency: str,
	amount_with_gst: float = 0,
	discount_amount: float = 0,
	payment_for_certificate: int = 0,
	coupon_code: str | None = None,
	coupon: str | None = None,
	*,
	member: str | None = None,
	subscription: str | None = None,
	payment_gateway: str | None = None,
):
	address = frappe._dict(address)
	member = member or frappe.session.user
	address_name = save_address(address)

	payment_doc = frappe.new_doc("LMS Payment")
	payment_doc.update(
		{
			"member": member,
			"billing_name": address.billing_name,
			"address": address_name,
			"amount": amount,
			"currency": currency,
			"discount_amount": discount_amount,
			"amount_with_gst": amount_with_gst,
			"gstin": address.gstin,
			"pan": address.pan,
			"source": address.source,
			"payment_for_document_type": doctype,
			"payment_for_document": docname,
			"payment_for_certificate": payment_for_certificate,
			"member_consent": address.member_consent,
			"original_amount": original_amount,
			"subscription": subscription,
			"payment_gateway": payment_gateway,
		}
	)
	if coupon_code:
		payment_doc.update(
			{
				"coupon": coupon,
				"coupon_code": coupon_code,
				"discount_amount": discount_amount,
				"original_amount": original_amount,
			}
		)

	payment_doc.save(ignore_permissions=True)
	return payment_doc


def get_redirect_url(doctype: str, docname: str, payment_for_certificate: int) -> str:
	if int(payment_for_certificate):
		return get_lms_route(f"courses/{docname}/certification")
	if doctype == "LMS Course":
		return get_lms_route(f"courses/{docname}")
	if doctype == "LMS Program":
		return get_lms_route(f"programs/{docname}")
	if doctype == "LMS Subscription Plan":
		return get_lms_route("subscriptions")
	return get_lms_route(f"batches/{docname}")


def save_address(address: dict) -> str:
	filters = {"email_id": frappe.session.user}
	exists = frappe.db.exists("Address", filters)
	if exists:
		address_doc = frappe.get_last_doc("Address", filters=filters)
	else:
		address_doc = frappe.new_doc("Address")

	address_doc.update(address)
	address_doc.update(
		{
			"address_title": frappe.db.get_value("User", frappe.session.user, "full_name"),
			"address_type": "Billing",
			"is_primary_address": 1,
			"email_id": frappe.session.user,
		}
	)
	address_doc.save(ignore_permissions=True)
	return address_doc.name
