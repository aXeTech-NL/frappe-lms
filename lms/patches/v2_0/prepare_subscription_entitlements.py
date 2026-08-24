# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import os
import shutil

import frappe


def execute():
	"""Grandfather existing memberships and normalize historical Program rows.

	Blank provenance is also treated as permanent by the runtime resolver, so the
	patch is safe during rolling deploys and idempotent when retried.
	"""
	if frappe.db.table_exists("LMS Enrollment") and frappe.db.has_column("LMS Enrollment", "access_source"):
		frappe.db.set_value(
			"LMS Enrollment",
			{"access_source": ["is", "not set"]},
			{"access_source": "Legacy", "permanent_access": 1},
			update_modified=False,
		)
		# Batch/Program grants are membership-derived and must remain revocable.
		# Normalize rows created by an interrupted rollout of this feature too.
		frappe.db.set_value(
			"LMS Enrollment",
			{"access_source": ["in", ["Batch", "Program"]], "permanent_access": 1},
			"permanent_access",
			0,
			update_modified=False,
		)

	if frappe.db.table_exists("LMS Program Member"):
		for filters in (
			{"parentfield": ["is", "not set"]},
			{"parentfield": ["!=", "program_members"]},
		):
			frappe.db.set_value(
				"LMS Program Member",
				filters,
				"parentfield",
				"program_members",
				update_modified=False,
			)
		if frappe.db.has_column("LMS Program Member", "access_source"):
			frappe.db.set_value(
				"LMS Program Member",
				{"access_source": ["is", "not set"]},
				{"access_source": "Legacy", "permanent_access": 1},
				update_modified=False,
			)
			frappe.db.set_value(
				"LMS Program Member",
				{
					"access_source": ["not in", ["Legacy", "Manual", "Purchase"]],
					"permanent_access": 1,
				},
				"permanent_access",
				0,
				update_modified=False,
			)

	if frappe.db.table_exists("LMS Payment") and frappe.db.has_column("LMS Payment", "payment_status"):
		frappe.db.set_value(
			"LMS Payment",
			{"payment_received": 1},
			"payment_status",
			"Paid",
			update_modified=False,
		)

	if frappe.db.table_exists("LMS Subscription"):
		populate_subscription_snapshots()
		frappe.db.add_index("LMS Subscription", ["member", "status", "current_period_end"])
	if frappe.db.table_exists("LMS Program Course"):
		frappe.db.add_index("LMS Program Course", ["course", "parent"])
	if frappe.db.table_exists("LMS Program Member"):
		frappe.db.add_index("LMS Program Member", ["parent", "member"])
	if frappe.db.table_exists("LMS Payment"):
		populate_provider_event_keys()
		frappe.db.add_index("LMS Payment", ["subscription", "payment_status"])
		frappe.db.add_index("LMS Payment", ["subscription", "payment_gateway", "provider_payment_reference"])

	if frappe.db.get_single_value("LMS Settings", "enable_subscriptions"):
		move_public_scorm_packages()


def populate_subscription_snapshots():
	if not frappe.db.has_column("LMS Subscription", "billing_interval"):
		return
	rows = frappe.get_all(
		"LMS Subscription",
		filters={"billing_interval": ["is", "not set"]},
		fields=["name", "plan"],
	)
	for row in rows:
		plan = frappe.db.get_value(
			"LMS Subscription Plan",
			row.plan,
			["billing_interval", "interval_count", "amount", "currency"],
			as_dict=True,
		)
		if not plan:
			continue
		frappe.db.set_value(
			"LMS Subscription",
			row.name,
			{
				"billing_interval": plan.billing_interval,
				"interval_count": plan.interval_count,
				"billing_amount": plan.amount,
				"billing_currency": plan.currency,
			},
			update_modified=False,
		)


def populate_provider_event_keys():
	if not frappe.db.has_column("LMS Payment", "provider_event_key"):
		return
	from lms.lms.subscriptions import get_provider_event_key

	rows = frappe.get_all(
		"LMS Payment",
		filters={"provider_event_id": ["is", "set"], "provider_event_key": ["is", "not set"]},
		fields=["name", "payment_gateway", "provider_event_id"],
		order_by="creation asc",
	)
	for row in rows:
		key = get_provider_event_key(row.payment_gateway or "default", row.provider_event_id)
		if frappe.db.exists("LMS Payment", {"provider_event_key": key, "name": ["!=", row.name]}):
			key = get_provider_event_key(
				row.payment_gateway or "default", f"{row.provider_event_id}:{row.name}"
			)
		frappe.db.set_value("LMS Payment", row.name, "provider_event_key", key, update_modified=False)


def move_public_scorm_packages():
	"""Move legacy public SCORM bytes behind the subscription-aware renderer.

	Nginx serves public/scorm without invoking Python. New uploads already use
	private/scorm; moving old extractions makes the existing /scorm URLs fall
	through to SCORMRenderer without changing database paths. If a private copy
	already exists it wins and the duplicate public file is removed.
	"""
	public_root = os.path.join(frappe.local.site_path, "public", "scorm")
	private_root = os.path.join(frappe.local.site_path, "private", "scorm")
	if not os.path.isdir(public_root):
		return

	os.makedirs(private_root, exist_ok=True)
	for root, directories, files in os.walk(public_root, topdown=False, followlinks=False):
		relative = os.path.relpath(root, public_root)
		destination_root = private_root if relative == "." else os.path.join(private_root, relative)
		os.makedirs(destination_root, exist_ok=True)
		for filename in files:
			source = os.path.join(root, filename)
			destination = os.path.join(destination_root, filename)
			if os.path.islink(source) or os.path.exists(destination):
				os.unlink(source)
			else:
				shutil.move(source, destination)
		for directory in directories:
			path = os.path.join(root, directory)
			if os.path.islink(path):
				os.unlink(path)
			elif os.path.isdir(path) and not os.listdir(path):
				os.rmdir(path)
	if os.path.isdir(public_root) and not os.listdir(public_root):
		os.rmdir(public_root)
