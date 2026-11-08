"""Commerce owns prices, immutable orders and payment-sourced access.

Payments owns provider transport. A browser return never fulfils an order.
Only an authoritative, account/amount/member-correlated payment can do that.
"""

import hashlib
import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlsplit
from uuid import uuid4

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from lms.lms_commerce.doctype.commerce_order.commerce_order import CHECKOUT_WRITE
from lms.lms_commerce.integrations.lms import decide_many
from lms.lms_commerce.utils import validate_safe_url

OPEN = {"creating", "open", "pending", "authorized"}
FAILED = {"failed", "canceled", "expired"}
REVERSALS = {"partially_refunded", "refunded", "partially_charged_back", "charged_back"}


def _payments():
	# Lazy import preserves native behavior with the old Payments pin and checkout off.
	from payments import checkout

	return checkout


def _digest(value):
	return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _open_key(user, offering):
	if not isinstance(offering, str) or not offering or len(offering) > 140:
		frappe.throw(_("Invalid offering."))
	target = frappe.db.get_value("Commerce Offering", offering, ["target_doctype", "target_name"])
	if not target:
		frappe.throw(_("Invalid offering."))
	return _digest([user, *target])


def _fingerprint(order, config):
	return _digest([_request(order, config), config["account_fingerprint"]])


def _user():
	user = frappe.session.user
	if user == "Guest" or not frappe.db.get_value("User", user, "enabled"):
		frappe.throw(_("Please log in to continue."), frappe.PermissionError)
	return user


def _settings():
	settings = frappe.get_single("Commerce Settings")
	if not settings.enabled or not settings.checkout_enabled or not settings.payment_gateway:
		frappe.throw(_("Checkout is currently unavailable."))
	if not settings.terms_url:
		frappe.throw(_("Checkout terms have not been configured."))
	return settings


def _amount(value):
	try:
		amount = Decimal(str(value))
		if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
			raise ValueError
		return format(amount, ".2f")
	except (InvalidOperation, ValueError):
		frappe.throw(_("Checkout requires a positive amount with at most two decimal places."))


def _origin():
	origin = (frappe.conf.get("host_name") or "").rstrip("/")
	parsed = urlsplit(origin)
	if (
		parsed.scheme != "https"
		or not parsed.netloc
		or parsed.path
		or parsed.query
		or parsed.fragment
		or parsed.username
	):
		frappe.throw(_("Checkout requires an explicit HTTPS host_name origin."))
	return origin


def _portal():
	from lms.hooks import get_lms_path

	return "/" + get_lms_path().strip("/")


def _quote(offering, user, settings, config=None):
	if not isinstance(offering, str) or not offering or len(offering) > 140:
		frappe.throw(_("Invalid offering."))
	offer = frappe.get_doc("Commerce Offering", offering)
	if (
		not offer.enabled
		or offer.target_doctype != "LMS Course"
		or offer.access_policy not in {"Purchase", "Tier or Purchase"}
	):
		frappe.throw(_("This offering cannot be purchased."))
	course = frappe.get_doc("LMS Course", offer.target_name)
	# No second paywall, unpublished/pre-order sale, or bypass of native eligibility.
	if not course.published or course.upcoming or course.disable_self_learning or course.paid_course:
		frappe.throw(_("This course is not available through Commerce checkout."))
	decision = decide_many(
		user=user,
		requests=[
			{
				"key": "checkout",
				"resource_type": "course",
				"resource_name": course.name,
				"action": "enroll",
			}
		],
	)["checkout"]
	if not decision.get("handled") or decision.get("allowed"):
		frappe.throw(_("You already have access or this course is not managed by Commerce."))
	# First release is deliberately EUR-only; do not silently round other currencies.
	if offer.currency != "EUR":
		frappe.throw(_("Checkout currently supports EUR offerings only."))
	amount = _amount(offer.amount)
	terms = validate_safe_url(settings.terms_url, required=True)
	config = config or _payments().configuration(settings.payment_gateway)
	if config["mode"] == "live" and not settings.allow_live_payments:
		frappe.throw(_("Live payments are not enabled for Commerce."))
	return {
		"offering": offer.name,
		"course": course.name,
		"title": course.title,
		"amount": amount,
		"currency": "EUR",
		"terms_url": terms,
		"mode": config["mode"],
		"quote_token": _digest(
			[
				offer.name,
				offer.modified,
				course.name,
				amount,
				"EUR",
				terms,
				settings.payment_gateway,
				config["mode"],
				config["account_fingerprint"],
			]
		),
	}


@frappe.whitelist(methods=["GET", "POST"])
def get_quote(offering: str):
	user = _user()
	settings = _settings()
	existing = frappe.db.get_value("Commerce Order", {"open_order_key": _open_key(user, offering)}, "name")
	if existing:
		order = frappe.get_doc("Commerce Order", existing)
		return {
			"offering": order.offering,
			"course": order.course,
			"title": order.course_title,
			"amount": _amount(order.amount),
			"currency": order.currency,
			"terms_url": order.terms_url,
			"mode": order.mode,
			"quote_token": order.quote_token,
			"pending_order": order.name,
		}
	return _quote(offering, user, settings)


@frappe.whitelist(methods=["POST"])
def start_checkout(offering: str, quote_token: str, accept_terms: bool = False):
	user = _user()
	settings = _settings()
	if accept_terms is not True:
		frappe.throw(_("Please accept the checkout terms."))
	if not isinstance(quote_token, str) or len(quote_token) != 64:
		frappe.throw(_("Please refresh the checkout before paying."))
	# Serialize tabs, retries and webhook fulfilment on the same member.
	frappe.db.get_value("User", user, "name", for_update=True)
	open_key = _open_key(user, offering)
	existing = frappe.db.get_value("Commerce Order", {"open_order_key": open_key}, "name")
	if existing:
		order = frappe.get_doc("Commerce Order", existing)
		if order.quote_token != quote_token:
			frappe.throw(_("An earlier checkout is still open. Finish it before starting another."))
	else:
		config = _payments().configuration(settings.payment_gateway)
		quotation = _quote(offering, user, settings, config=config)
		if quotation["quote_token"] != quote_token:
			frappe.throw(_("The price or terms changed. Refresh and confirm the new checkout."))
		if config["mode"] != "test" and not settings.allow_live_payments:
			frappe.throw(_("Live payments are not enabled for Commerce."))
		name = uuid4().hex
		order = frappe.get_doc(
			{
				"doctype": "Commerce Order",
				"member": user,
				"offering": offering,
				"course": quotation["course"],
				"course_title": quotation["title"],
				"amount": quotation["amount"],
				"currency": quotation["currency"],
				"status": "creating",
				"payment_gateway": settings.payment_gateway,
				"mode": config["mode"],
				"customer_reference": "lms-customer:" + uuid4().hex,
				"quote_token": quote_token,
				"terms_url": quotation["terms_url"],
				"accepted_on": now_datetime(),
				"redirect_url": _origin() + _portal() + "/checkout/return/" + name,
				"open_order_key": open_key,
			}
		)
		order.flags.checkout_write = CHECKOUT_WRITE
		order.insert(ignore_permissions=True, set_name=name)
		order.db_set("request_fingerprint", _fingerprint(order, config))
		# Persist the exact merchant reference BEFORE contacting a provider. A timeout
		# must not roll it back and cause a second charge on the next browser retry.
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
	return _resume(order.name)


def _request(order, config):
	return {
		"merchant_reference": "lms-order:" + order.name,
		"customer_reference": order.customer_reference,
		"amount": _amount(order.amount),
		"currency": order.currency,
		"description": order.course_title[:255],
		"redirect_url": order.redirect_url,
		"webhook_url": config["webhook_url"],
		"idempotency_key": "lms-order:" + order.name,
		"mode": order.mode,
		"account_fingerprint": config["account_fingerprint"],
	}


def _lock_order(name):
	member = frappe.db.get_value("Commerce Order", name, "member")
	if not member:
		frappe.throw(_("Order not found."), frappe.DoesNotExistError)
	frappe.db.get_value("User", member, "name", for_update=True)
	frappe.db.get_value("Commerce Order", name, "name", for_update=True)
	return frappe.get_doc("Commerce Order", name, for_update=True)


def _resume(name):
	order = _lock_order(name)
	if order.status != "creating":
		return _public(order)
	settings = _settings()
	config = _payments().configuration(order.payment_gateway)
	if order.mode != config["mode"] or (order.mode == "live" and not settings.allow_live_payments):
		frappe.throw(_("Payment configuration changed. Please contact the administrator."))
	request = _request(order, config)
	if _fingerprint(order, config) != order.request_fingerprint:
		frappe.throw(_("Payment configuration changed. Please contact the administrator."))
	# Never replay an uncertain creation outside the provider's idempotency window.
	# The open-order key remains occupied until an operator reconciles it.
	if get_datetime(order.creation) < now_datetime() - timedelta(hours=20):
		frappe.throw(_("This checkout requires payment reconciliation. Please contact the administrator."))
	payment = _payments().begin(order.payment_gateway, request)
	payment_updated(order.payment_gateway, payment)
	return _public(frappe.get_doc("Commerce Order", name))


def _owned_order(name):
	user = _user()
	if not isinstance(name, str) or frappe.db.get_value("Commerce Order", name, "member") != user:
		frappe.throw(_("Order not found."), frappe.PermissionError)
	return frappe.get_doc("Commerce Order", name)


@frappe.whitelist(methods=["GET", "POST"])
def get_order(order: str):
	return _public(_owned_order(order))


@frappe.whitelist(methods=["POST"])
def refresh_order(order: str):
	owned = _owned_order(order)
	if owned.status == "creating":
		return _resume(owned.name)
	_reconcile(owned.name)
	return _public(frappe.get_doc("Commerce Order", owned.name))


def _public(order):
	grant_active = bool(
		order.entitlement
		and frappe.db.get_value("Commerce Entitlement", order.entitlement, "status") == "Active"
	)
	return {
		"name": order.name,
		"title": order.course_title,
		"course": order.course,
		"amount": _amount(order.amount),
		"currency": order.currency,
		"status": order.status,
		"mode": order.mode,
		"access_granted": grant_active,
		"checkout_url": order.checkout_url if order.status in {"open", "pending"} else None,
		"course_url": _portal() + "/courses/" + quote(order.course, safe=""),
	}


def payment_updated(payment_gateway, payment):
	"""Internal hook, deliberately not whitelisted. Lock, correlate, fulfil atomically."""
	payment = _payments().normalize_payment(payment)
	reference = payment["merchant_reference"]
	if not reference.startswith("lms-order:"):
		return  # A payment owned by another application.
	order = _lock_order(reference.removeprefix("lms-order:"))
	if (
		order.payment_gateway != payment_gateway
		or order.customer_reference != payment["customer_reference"]
		or Decimal(str(order.amount)) != Decimal(payment["amount"])
		or order.currency != payment["currency"]
		or order.mode != payment["mode"]
		or (order.provider_payment_id and order.provider_payment_id != payment["provider_payment_id"])
	):
		raise ValueError("Payment does not match its Commerce order")
	status = payment["status"]
	# Delayed notifications must not undo a payment or a financial reversal.
	refunded = max(Decimal(str(order.refunded_amount or 0)), Decimal(payment.get("refunded_amount", "0")))
	charged_back = max(
		Decimal(str(order.charged_back_amount or 0)), Decimal(payment.get("charged_back_amount", "0"))
	)
	revoked = bool(order.access_revoked or charged_back > 0 or refunded >= Decimal(str(order.amount)))
	if charged_back:
		status = "charged_back" if charged_back >= Decimal(str(order.amount)) else "partially_charged_back"
	elif refunded:
		status = "refunded" if refunded >= Decimal(str(order.amount)) else "partially_refunded"
	elif order.status in {"paid", *FAILED} and status in OPEN:
		status = order.status
	elif order.status == "paid" and status in FAILED:
		status = "paid"
	elif order.status in FAILED and status == "paid":
		raise ValueError("A terminal unpaid checkout unexpectedly became paid; reconcile manually")
	values = {
		"provider_payment_id": payment["provider_payment_id"],
		"payment_key": _digest([payment_gateway, payment["provider_payment_id"]]),
		"status": status,
		"refunded_amount": str(refunded),
		"charged_back_amount": str(charged_back),
		"access_revoked": int(revoked),
		"last_checked_on": now_datetime(),
		"open_order_key": order.open_order_key if status in OPEN else None,
	}
	if payment.get("checkout_url"):
		values["checkout_url"] = validate_safe_url(payment["checkout_url"], required=True)
	frappe.db.set_value("Commerce Order", order.name, values)
	if revoked:
		_revoke_purchase(order)
	elif status in {"paid", "partially_refunded"} and not order.entitlement:
		_grant_purchase(order)


def _grant_purchase(order):
	grant = frappe.get_doc(
		{
			"doctype": "Commerce Entitlement",
			"member": order.member,
			"scope": "Target",
			"target_doctype": "LMS Course",
			"target_name": order.course,
			"source_type": "Purchase",
			"source_doctype": "Commerce Order",
			"source_name": order.name,
			"idempotency_key": "commerce-order:" + order.name,
			"status": "Active",
		}
	)
	grant.flags.checkout_write = CHECKOUT_WRITE
	grant.insert(ignore_permissions=True)
	frappe.db.set_value("Commerce Order", order.name, "entitlement", grant.name)


def _revoke_purchase(order):
	if not order.entitlement:
		return
	grant = frappe.db.get_value(
		"Commerce Entitlement", order.entitlement, ["status", "source_type", "source_name"], as_dict=True
	)
	if not grant or grant.source_type != "Purchase" or grant.source_name != order.name:
		raise ValueError("Order entitlement source mismatch")
	if grant.status == "Active":
		frappe.db.set_value(
			"Commerce Entitlement",
			order.entitlement,
			{
				"status": "Revoked",
				"active_grant_key": None,
				"revoked_by": frappe.session.user,
				"revoked_on": now_datetime(),
			},
		)


def _reconcile(name):
	order = _lock_order(name)
	if not order.provider_payment_id:
		return
	# Serialize provider fetches too: an older response cannot overwrite a newer one.
	payment_updated(
		order.payment_gateway, _payments().fetch(order.payment_gateway, order.provider_payment_id)
	)


def reconcile_orders():
	"""Bounded recovery for lost webhooks; never creates a replacement payment.

	Paid orders remain eligible for refund/chargeback reconciliation. Failures are
	rotated too, so a broken account cannot starve every other order indefinitely.
	"""
	rows = frappe.get_all(
		"Commerce Order",
		filters={"provider_payment_id": ["is", "set"], "status": ["not in", list(FAILED)]},
		pluck="name",
		order_by="last_checked_on asc, creation asc",
		limit_page_length=50,
	)
	for name in rows:
		try:
			_reconcile(name)
			frappe.db.commit()  # nosemgrep
		except Exception:
			frappe.db.rollback()
			frappe.db.set_value("Commerce Order", name, "last_checked_on", now_datetime())
			frappe.log_error(
				title="Commerce payment reconciliation failed",
				message=f"Order {name}; inspect its gateway configuration and provider state.",
			)
			frappe.db.commit()  # nosemgrep
