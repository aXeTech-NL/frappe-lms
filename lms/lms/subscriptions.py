# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Provider-neutral subscription lifecycle and Program bundle fulfillment.

The Payments app is used for the first period's hosted checkout. Recurring
providers (for example a future Mollie integration) call
:func:`record_subscription_event` only after verifying their own webhook. This
module intentionally exposes no guest-whitelisted paid-event endpoint. Gateway
apps may register ``lms_subscription_event_handlers`` (after-commit lifecycle
notifications) and ``lms_subscription_cancel_handlers`` (provider cancellation
before local state changes).
"""

import hashlib

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, flt, getdate, now_datetime, nowdate

PAYMENT_EVENT_STATUSES = {"Paid", "Failed", "Refunded"}
BILLABLE_SUBSCRIPTION_STATUSES = ("Trial", "Active", "Past Due")


def get_or_create_pending_subscription(
	plan: str,
	member: str | None = None,
	payment_gateway: str | None = None,
):
	"""Return a reusable pending subscription for the member and plan."""
	from lms.lms.access import subscriptions_enabled

	if not subscriptions_enabled():
		frappe.throw(_("Subscriptions are not enabled."))
	member = member or frappe.session.user
	if member == "Guest":
		frappe.throw(_("Please login to start a subscription."), frappe.PermissionError)

	plan_row = get_plan(plan)
	# Serialize every checkout for one member, not only one plan. This makes the
	# tier comparison and pending-subscription creation one atomic decision.
	frappe.db.get_value("User", member, "name", for_update=True)
	target_rank = _tier_rank(plan_row.tier)
	billable = frappe.get_all(
		"LMS Subscription",
		filters={"member": member, "status": ["in", BILLABLE_SUBSCRIPTION_STATUSES]},
		fields=["name", "plan", "tier", "status"],
	)
	# Active access includes lower/equal tiers. Past-due access has already
	# lapsed: let the member retry the same plan or move up, but never create a
	# lower-tier checkout alongside the unresolved higher subscription.
	if any(
		(row.status in ("Trial", "Active") and _tier_rank(row.tier) >= target_rank)
		or (row.status == "Past Due" and _tier_rank(row.tier) > target_rank)
		for row in billable
	):
		frappe.throw(_("Your current subscription already includes this tier."))

	existing = frappe.db.get_value(
		"LMS Subscription",
		{"member": member, "plan": plan, "status": "Pending"},
		"name",
		order_by="creation desc",
	)
	if existing:
		subscription = frappe.get_doc("LMS Subscription", existing)
		values = {}
		if not subscription.billing_interval:
			values.update(_plan_snapshot_values(plan_row))
		if payment_gateway:
			values["payment_gateway"] = payment_gateway
		if values:
			frappe.db.set_value("LMS Subscription", existing, values, update_modified=False)
		return frappe.get_doc("LMS Subscription", existing)

	renewable = frappe.db.get_value(
		"LMS Subscription",
		{"member": member, "plan": plan, "status": ["in", ["Expired", "Past Due"]]},
		"name",
		order_by="modified desc",
	)
	if renewable:
		values = {
			"status": "Pending",
			"cancel_at_period_end": 0,
			"cancelled_on": None,
			"payment_gateway": payment_gateway,
			**_plan_snapshot_values(plan_row),
		}
		frappe.db.set_value("LMS Subscription", renewable, values, update_modified=False)
		return frappe.get_doc("LMS Subscription", renewable)

	subscription = frappe.get_doc(
		{
			"doctype": "LMS Subscription",
			"member": member,
			"plan": plan,
			"tier": plan_row.tier,
			"status": "Pending",
			"payment_gateway": payment_gateway,
		}
	)
	subscription.insert(ignore_permissions=True)
	return subscription


def _tier_rank(tier: str) -> int:
	return cint(frappe.db.get_value("LMS Subscription Tier", tier, "rank"))


def _plan_snapshot_values(plan: frappe._dict) -> dict:
	return {
		"tier": plan.tier,
		"billing_interval": plan.billing_interval,
		"interval_count": plan.interval_count,
		"billing_amount": plan.amount,
		"billing_currency": plan.currency,
	}


def get_plan(plan: str, *, require_enabled: bool = True) -> frappe._dict:
	plan_row = frappe.db.get_value(
		"LMS Subscription Plan",
		plan,
		[
			"name",
			"plan_name",
			"tier",
			"enabled",
			"billing_interval",
			"interval_count",
			"amount",
			"currency",
			"amount_usd",
		],
		as_dict=True,
	)
	if not plan_row or (require_enabled and not plan_row.enabled):
		frappe.throw(_("The subscription plan is not enabled."))
	return plan_row


def record_subscription_event(
	subscription: str,
	status: str,
	provider_event_id: str,
	*,
	provider_payment_id: str | None = None,
	payment_name: str | None = None,
	payment_gateway: str | None = None,
	amount: float | None = None,
	currency: str | None = None,
	paid_on=None,
	failure_reason: str | None = None,
) -> frappe._dict:
	"""Record one verified provider event and apply it exactly once.

	The adapter verifies the webhook before calling this trusted Python seam.
	Events are idempotent per gateway, while every distinct lifecycle event keeps
	its own immutable LMS Payment audit row. Refunds remain audit-only by policy.
	"""
	if status not in PAYMENT_EVENT_STATUSES:
		frappe.throw(_("Unsupported subscription payment status {0}.").format(status))
	if not provider_event_id:
		frappe.throw(_("Provider event ID is required."))

	member = frappe.db.get_value("LMS Subscription", subscription, "member")
	if not member:
		frappe.throw(_("Subscription {0} does not exist.").format(subscription))
	# Member-first lock ordering serializes simultaneous upgrades/events without
	# two event handlers each holding one subscription row and waiting on the other.
	frappe.db.get_value("User", member, "name", for_update=True)
	subscription_row = frappe.db.get_value(
		"LMS Subscription",
		subscription,
		[
			"name",
			"member",
			"plan",
			"tier",
			"status",
			"starts_on",
			"current_period_start",
			"current_period_end",
			"cancel_at_period_end",
			"payment_gateway",
			"latest_payment",
			"billing_interval",
			"interval_count",
			"billing_amount",
			"billing_currency",
		],
		as_dict=True,
		for_update=True,
	)
	if not subscription_row:
		frappe.throw(_("Subscription {0} does not exist.").format(subscription))

	gateway = (payment_gateway or subscription_row.payment_gateway or "default").strip()
	event_key = get_provider_event_key(gateway, provider_event_id)
	replayed = frappe.db.get_value(
		"LMS Payment",
		{"provider_event_key": event_key},
		["name", "subscription", "payment_status"],
		as_dict=True,
	)
	if replayed:
		if replayed.subscription != subscription:
			frappe.throw(_("The provider event is already linked to another subscription."))
		return frappe._dict(
			payment=replayed.name,
			replayed=True,
			status=replayed.payment_status,
			applied=False,
		)

	# A provider may first report failure and later success for the same payment.
	# Failed rows keep provider_payment_reference, not the globally unique legacy
	# payment_id. Normalize pre-existing failed rows before the paid event lands.
	previous_paid_payment = None
	if provider_payment_id and status == "Paid":
		other = frappe.db.get_value(
			"LMS Payment",
			{"payment_id": provider_payment_id, "name": ["!=", payment_name or ""]},
			["name", "subscription", "payment_status", "payment_received"],
			as_dict=True,
		)
		if other:
			if other.subscription != subscription:
				frappe.throw(_("The provider payment is already linked to another transaction."))
			if other.payment_received or other.payment_status == "Paid":
				previous_paid_payment = other.name
			else:
				frappe.db.set_value(
					"LMS Payment",
					other.name,
					{"payment_id": None, "provider_payment_reference": provider_payment_id},
					update_modified=False,
				)

	payment = _get_or_create_event_payment(
		subscription_row,
		payment_name=payment_name,
		amount=amount,
		currency=currency,
	)
	original_payment = None
	if payment.provider_event_key or (status == "Refunded" and payment.payment_received):
		original_payment = payment.name
		payment = _get_or_create_event_payment(
			subscription_row,
			payment_name=None,
			amount=amount if amount is not None else payment.amount,
			currency=currency or payment.currency,
		)

	_validate_event_payment(payment, subscription_row)
	related_payment = (
		previous_paid_payment
		or original_payment
		or _related_provider_payment(subscription, gateway, provider_payment_id, payment.name)
	)

	values = {
		"subscription": subscription,
		"provider_event_id": provider_event_id,
		"provider_event_key": event_key,
		"provider_payment_reference": provider_payment_id,
		"payment_status": status,
		"payment_received": int(status == "Paid"),
		"payment_gateway": gateway,
	}
	if provider_payment_id and status == "Paid" and not previous_paid_payment:
		values["payment_id"] = provider_payment_id
	if related_payment:
		values["related_payment"] = related_payment
	if paid_on:
		values["paid_on"] = paid_on
	elif status == "Paid":
		values["paid_on"] = now_datetime()
	if failure_reason:
		values["failure_reason"] = failure_reason

	period_start = period_end = None
	applied = False
	if status == "Paid" and not previous_paid_payment and _prepare_paid_activation(subscription_row):
		period_start, period_end = _next_period(subscription_row, paid_on)
		values.update(
			{
				"billing_period_start": period_start,
				"billing_period_end": period_end,
				"failure_reason": None,
			}
		)
		applied = True

	frappe.db.set_value("LMS Payment", payment.name, values, update_modified=False)

	if applied:
		_update_subscription_for_paid_event(subscription_row, payment.name, period_start, period_end)
	elif status == "Failed":
		_mark_subscription_past_due_if_uncovered(subscription_row)
	_notify_subscription_event_handlers(subscription, payment.name, status)

	return frappe._dict(
		payment=payment.name,
		replayed=False,
		status=status,
		applied=applied,
		period_start=period_start,
		period_end=period_end,
	)


def get_provider_event_key(payment_gateway: str, provider_event_id: str) -> str:
	gateway = str(payment_gateway or "default").strip().casefold()
	event_id = str(provider_event_id).strip()
	identity = f"{gateway}\0{event_id}"
	return hashlib.sha256(identity.encode()).hexdigest()


def _validate_event_payment(payment: frappe._dict, subscription: frappe._dict):
	if payment.subscription and payment.subscription != subscription.name:
		frappe.throw(_("The payment belongs to another subscription."))
	if (
		payment.payment_for_document_type != "LMS Subscription"
		or payment.payment_for_document != subscription.name
	):
		frappe.throw(_("The payment does not reference this subscription."))
	if payment.member != subscription.member:
		frappe.throw(_("The payment member does not match the subscription member."))


def _related_provider_payment(
	subscription: str, gateway: str, provider_payment_id: str | None, exclude: str
) -> str | None:
	if not provider_payment_id:
		return None
	return frappe.db.get_value(
		"LMS Payment",
		{
			"subscription": subscription,
			"payment_gateway": gateway,
			"provider_payment_reference": provider_payment_id,
			"name": ["!=", exclude],
		},
		"name",
		order_by="creation desc",
	)


def _notify_subscription_event_handlers(subscription: str, payment: str, status: str):
	"""Notify installed gateway adapters after the transaction commits."""
	for handler in frappe.get_hooks("lms_subscription_event_handlers") or []:
		frappe.enqueue(
			handler,
			queue="short",
			enqueue_after_commit=True,
			subscription=subscription,
			payment=payment,
			status=status,
		)


def set_provider_references(
	subscription: str,
	*,
	payment_gateway: str,
	gateway_customer_id: str | None = None,
	gateway_subscription_id: str | None = None,
):
	"""Trusted adapter seam for provider-side customer/subscription references."""
	row = frappe.db.get_value("LMS Subscription", subscription, "name", for_update=True)
	if not row:
		frappe.throw(_("Subscription does not exist."))
	values = {"payment_gateway": payment_gateway}
	if gateway_customer_id:
		values["gateway_customer_id"] = gateway_customer_id
	if gateway_subscription_id:
		values["gateway_subscription_id"] = gateway_subscription_id
	frappe.db.set_value("LMS Subscription", subscription, values, update_modified=False)


def complete_initial_subscription_payment(payment_name: str) -> frappe._dict:
	payment = frappe.db.get_value(
		"LMS Payment",
		payment_name,
		["name", "subscription", "payment_id", "order_id", "payment_gateway", "provider_event_id"],
		as_dict=True,
	)
	if not payment or not payment.subscription:
		frappe.throw(_("The subscription payment record is incomplete."))
	event_id = (
		payment.provider_event_id or f"checkout:{payment.payment_id or payment.order_id or payment.name}"
	)
	return record_subscription_event(
		payment.subscription,
		"Paid",
		event_id,
		provider_payment_id=payment.payment_id,
		payment_name=payment.name,
		payment_gateway=payment.payment_gateway,
	)


def _get_or_create_event_payment(
	subscription: frappe._dict,
	*,
	payment_name: str | None,
	amount: float | None,
	currency: str | None,
):
	if payment_name:
		payment = frappe.db.get_value(
			"LMS Payment",
			payment_name,
			[
				"name",
				"member",
				"subscription",
				"payment_for_document_type",
				"payment_for_document",
				"billing_name",
				"source",
				"address",
				"amount",
				"currency",
				"provider_event_id",
				"provider_event_key",
				"payment_received",
			],
			as_dict=True,
			for_update=True,
		)
		if not payment:
			frappe.throw(_("Payment record {0} does not exist.").format(payment_name))
		return payment

	template = None
	if subscription.latest_payment:
		template = frappe.db.get_value(
			"LMS Payment",
			subscription.latest_payment,
			["billing_name", "source", "address", "gstin", "pan", "member_consent"],
			as_dict=True,
		)
	if not template:
		# An initial provider attempt can fail before latest_payment exists. Keep
		# that failed row immutable, but reuse its trusted billing details when a
		# later event reports the same provider payment as paid.
		template = frappe.db.get_value(
			"LMS Payment",
			{"subscription": subscription.name},
			["billing_name", "source", "address", "gstin", "pan", "member_consent"],
			as_dict=True,
			order_by="creation desc",
		)
	if not template:
		frappe.throw(_("A recurring event requires an initial subscription payment."))

	payment = frappe.new_doc("LMS Payment")
	payment.update(
		{
			"member": subscription.member,
			"billing_name": template.billing_name,
			"source": template.source,
			"address": template.address,
			"gstin": template.gstin,
			"pan": template.pan,
			"member_consent": template.member_consent,
			"payment_for_document_type": "LMS Subscription",
			"payment_for_document": subscription.name,
			"subscription": subscription.name,
			"payment_status": "Pending",
			"amount": flt(amount if amount is not None else subscription.billing_amount),
			"original_amount": flt(amount if amount is not None else subscription.billing_amount),
			"currency": currency or subscription.billing_currency,
		}
	)
	payment.insert(ignore_permissions=True)
	return payment


def _next_period(subscription: frappe._dict, paid_on=None):
	paid_date = getdate(paid_on or nowdate())
	current_end = getdate(subscription.current_period_end) if subscription.current_period_end else None
	start = add_days(current_end, 1) if current_end and current_end >= paid_date else paid_date
	months = cint(subscription.interval_count) * (12 if subscription.billing_interval == "Year" else 1)
	end = add_days(add_months(start, months), -1)
	return start, end


def _prepare_paid_activation(subscription: frappe._dict) -> bool:
	"""Lock competing subscriptions and apply the no-proration upgrade policy."""
	if subscription.status == "Cancelled" or subscription.cancel_at_period_end:
		return False

	frappe.db.get_value("User", subscription.member, "name", for_update=True)
	other_names = frappe.get_all(
		"LMS Subscription",
		filters={
			"member": subscription.member,
			"status": ["in", BILLABLE_SUBSCRIPTION_STATUSES],
			"name": ["!=", subscription.name],
		},
		pluck="name",
		order_by="name asc",
	)
	target_rank = _tier_rank(subscription.tier)
	others = []
	for name in other_names:
		row = frappe.db.get_value(
			"LMS Subscription",
			name,
			["name", "tier", "status"],
			as_dict=True,
			for_update=True,
		)
		if row and row.status in BILLABLE_SUBSCRIPTION_STATUSES:
			others.append(row)
	if any(_tier_rank(row.tier) >= target_rank for row in others):
		return False

	for row in others:
		frappe.db.set_value(
			"LMS Subscription",
			row.name,
			{"status": "Cancelled", "cancel_at_period_end": 0, "cancelled_on": now_datetime()},
			update_modified=False,
		)
		_enqueue_provider_cancellation(row.name, at_period_end=False)
	return True


def _enqueue_provider_cancellation(subscription: str, *, at_period_end: bool):
	for handler in frappe.get_hooks("lms_subscription_cancel_handlers") or []:
		frappe.enqueue(
			handler,
			queue="short",
			enqueue_after_commit=True,
			subscription=subscription,
			at_period_end=at_period_end,
		)


def _update_subscription_for_paid_event(subscription, payment_name, period_start, period_end):
	values = {
		"status": "Active",
		"starts_on": subscription.get("starts_on") or period_start,
		"current_period_start": period_start,
		"current_period_end": period_end,
		"latest_payment": payment_name,
	}
	frappe.db.set_value("LMS Subscription", subscription.name, values, update_modified=False)


def _mark_subscription_past_due_if_uncovered(subscription):
	if subscription.status == "Cancelled" or subscription.cancel_at_period_end:
		return
	current_end = getdate(subscription.current_period_end) if subscription.current_period_end else None
	if not current_end:
		# Initial payment failure remains retryable through the same pending record.
		frappe.db.set_value("LMS Subscription", subscription.name, "status", "Pending")
	elif current_end < getdate(nowdate()):
		frappe.db.set_value("LMS Subscription", subscription.name, "status", "Past Due")


def expire_subscriptions(as_of=None) -> int:
	"""Expire ended periods without deleting enrollments or progress."""
	as_of = getdate(as_of or nowdate())
	names = frappe.get_all(
		"LMS Subscription",
		filters={
			"status": ["in", ["Trial", "Active", "Past Due"]],
			"current_period_end": ["<", as_of],
		},
		pluck="name",
	)
	updated = 0
	for name in names:
		subscription = frappe.db.get_value(
			"LMS Subscription",
			name,
			["name", "status", "current_period_end", "cancel_at_period_end"],
			as_dict=True,
			for_update=True,
		)
		if not subscription or not subscription.current_period_end:
			continue
		if getdate(subscription.current_period_end) >= as_of:
			continue
		values = {
			"status": "Cancelled" if subscription.cancel_at_period_end else "Expired",
		}
		if subscription.cancel_at_period_end:
			values["cancelled_on"] = now_datetime()
		frappe.db.set_value("LMS Subscription", name, values, update_modified=False)
		updated += 1
	return updated


@frappe.whitelist()
def get_subscription_catalog(country: str | None = None) -> frappe._dict:
	"""Return the public plan catalogue plus the caller's safe subscription summary.

	Checkout still resolves prices and authorization server-side.  This payload is
	only the presentation contract and deliberately omits provider/customer IDs.
	"""
	from frappe.utils import fmt_money

	from lms.lms.access import subscriptions_enabled
	from lms.lms.utils import check_multicurrency

	if not subscriptions_enabled():
		return frappe._dict(enabled=False, tiers=[], plans=[], subscriptions=[], current_subscription=None)
	if frappe.session.user == "Guest":
		frappe.throw(_("Please login to view subscription plans."), frappe.PermissionError)

	tiers = frappe.get_all(
		"LMS Subscription Tier",
		filters={"enabled": 1},
		fields=["name", "tier_name", "rank", "description"],
		order_by="rank asc",
	)
	tier_ranks = {tier.name: cint(tier.rank) for tier in tiers}
	plans = frappe.get_all(
		"LMS Subscription Plan",
		filters={"enabled": 1, "tier": ["in", list(tier_ranks)]},
		fields=[
			"name",
			"plan_name",
			"tier",
			"billing_interval",
			"interval_count",
			"amount",
			"currency",
			"amount_usd",
		],
		order_by="creation asc",
	)
	for plan in plans:
		plan.amount, plan.currency = check_multicurrency(plan.amount, plan.currency, country, plan.amount_usd)
		plan.price = fmt_money(plan.amount, currency=plan.currency)
		plan.tier_rank = tier_ranks.get(plan.tier, 0)

	subscriptions = frappe.get_all(
		"LMS Subscription",
		filters={"member": frappe.session.user},
		fields=[
			"name",
			"plan",
			"tier",
			"status",
			"starts_on",
			"current_period_start",
			"current_period_end",
			"cancel_at_period_end",
			"billing_interval",
			"interval_count",
			"billing_amount",
			"billing_currency",
		],
		order_by="modified desc",
	)
	current = next(
		(subscription for subscription in subscriptions if subscription.status in ("Trial", "Active")),
		None,
	) or next(
		(subscription for subscription in subscriptions if subscription.status in ("Past Due", "Pending")),
		None,
	)
	return frappe._dict(
		enabled=True,
		tiers=tiers,
		plans=plans,
		subscriptions=subscriptions,
		current_subscription=current,
	)


def reconcile_subscriptions():
	"""Daily provider-neutral maintenance.

	Gateway-specific reconciliation belongs to its adapter. Core expires ended
	periods and ensures dynamic Program memberships have course progress rows.
	"""
	if not frappe.db.table_exists("LMS Subscription"):
		return
	from lms.lms.access import subscriptions_enabled

	if not subscriptions_enabled():
		return
	expire_subscriptions()
	sync_program_course_enrollments()


@frappe.whitelist()
def cancel_subscription(subscription: str, at_period_end: bool = True):
	"""Request cancellation with owner/staff authorization and a locked state transition."""
	user = frappe.session.user
	member = frappe.db.get_value("LMS Subscription", subscription, "member")
	if not member:
		frappe.throw(_("Subscription does not exist."))
	frappe.db.get_value("User", member, "name", for_update=True)
	row = frappe.db.get_value(
		"LMS Subscription",
		subscription,
		["name", "member", "status", "cancel_at_period_end"],
		as_dict=True,
		for_update=True,
	)
	if not row:
		frappe.throw(_("Subscription does not exist."))
	roles = set(frappe.get_roles(user))
	if user != row.member and user != "Administrator" and not roles & {"Moderator", "System Manager"}:
		frappe.throw(_("You cannot cancel this subscription."), frappe.PermissionError)
	if row.status not in ("Trial", "Active", "Past Due"):
		frappe.throw(_("This subscription can no longer be cancelled."))

	at_period_end = bool(cint(at_period_end))
	# Explicit user/admin cancellation keeps the provider call synchronous: if an
	# adapter cannot cancel, local state must not falsely claim success.
	for handler in frappe.get_hooks("lms_subscription_cancel_handlers") or []:
		frappe.get_attr(handler)(subscription=subscription, at_period_end=at_period_end)
	if at_period_end:
		frappe.db.set_value(
			"LMS Subscription", subscription, "cancel_at_period_end", 1, update_modified=False
		)
	else:
		frappe.db.set_value(
			"LMS Subscription",
			subscription,
			{"status": "Cancelled", "cancel_at_period_end": 0, "cancelled_on": now_datetime()},
			update_modified=False,
		)


def sync_program_course_enrollments(program: str | None = None, member: str | None = None) -> int:
	"""Create missing course progress rows for entitled Program memberships.

	Rows for removed courses are retained so progress is never lost. Their
	Program-derived grant is dynamic and therefore stops authorizing immediately.
	"""
	from lms.lms.access import get_course_access, get_program_access, subscriptions_enabled

	if not subscriptions_enabled():
		return 0
	filters = {}
	if program:
		filters["parent"] = program
	if member:
		filters["member"] = member
	memberships = frappe.get_all("LMS Program Member", filters=filters, fields=["parent", "member"])
	created = 0
	affected_members = set()
	for membership in memberships:
		affected_members.add(membership.member)
		if not get_program_access(membership.parent, membership.member).allowed:
			continue
		courses = frappe.get_all("LMS Program Course", {"parent": membership.parent}, pluck="course")
		for course in courses:
			if not get_course_access(course, membership.member, require_enrollment=False).allowed:
				continue
			if frappe.db.exists("LMS Enrollment", {"course": course, "member": membership.member}):
				continue
			enrollment = frappe.get_doc(
				{
					"doctype": "LMS Enrollment",
					"course": course,
					"member": membership.member,
					"enrollment_from_program": membership.parent,
				}
			)
			enrollment.insert(ignore_permissions=True)
			created += 1

	# Existing course rows do not fire LMS Enrollment.on_update, and removing a
	# course creates no enrollment event at all. Recompute from the current Program
	# composition so reused rows and add/remove operations cannot leave stale totals.
	from lms.lms.doctype.lms_enrollment.lms_enrollment import update_program_progress

	for affected_member in affected_members:
		update_program_progress(affected_member)
	return created
