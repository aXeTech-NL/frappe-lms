import frappe
from frappe import _
from frappe.utils import cint, fmt_money

from lms.lms_commerce.utils import is_active_window, validate_safe_url

CONTRACT_VERSION = 1
MAX_REQUESTS = 120
MAX_KEY_LENGTH = 300
MAX_RESOURCE_NAME_LENGTH = 180
MAX_CONTEXT_VALUE_LENGTH = 180
CONTEXT_FIELDS = {"lesson", "quiz", "is_preview"}
ALLOWED_RESOURCE_TYPES = {"course": "LMS Course", "program": "LMS Program"}
ALLOWED_ACTIONS = {"catalog", "view", "enroll", "consume", "progress"}
TIER_POLICIES = {"Tier", "Tier or Purchase"}
PURCHASE_POLICIES = {"Purchase", "Tier or Purchase"}


def course_access_policy(*, user: str, course: str, action: str, context: dict) -> bool | None:
	"""Adapt Commerce decisions to LMS's deny-only course access hook."""
	if action not in {"consume", "progress"}:
		raise ValueError("Unsupported LMS course access policy action")

	key = "course-access"
	decision = decide_many(
		user=user,
		requests=[
			{
				"key": key,
				"resource_type": "course",
				"resource_name": course,
				"action": action,
				"context": context,
			}
		],
	)[key]
	if decision.get("handled") is False:
		return None
	allowed = decision.get("allowed")
	if decision.get("handled") is not True or (allowed is not True and allowed is not False):
		raise ValueError("Malformed Commerce access decision")
	return allowed


def decide_many(
	*,
	user: str,
	requests: list[dict],
	contract_version: int = CONTRACT_VERSION,
) -> dict[str, dict]:
	"""Resolve Commerce decisions in bounded bulk for the LMS v1 contract."""
	if cint(contract_version) != CONTRACT_VERSION:
		frappe.throw(_("Unsupported LMS entitlement contract version."))
	validated = _validate_requests(requests)
	if not validated:
		return {}
	if not _commerce_enabled():
		return {item["key"]: {"handled": False, "allowed": False} for item in validated}

	target_keys = list({item["target_key"] for item in validated})
	offerings = frappe.get_all(
		"Commerce Offering",
		filters={"enabled": 1, "active_target_key": ["in", target_keys]},
		fields=[
			"name",
			"active_target_key",
			"access_policy",
			"required_tier",
			"amount",
			"currency",
			"badge_label",
			"purchase_url",
			"upgrade_url",
		],
	)
	offerings_by_target = {row.active_target_key: row for row in offerings}
	if not offerings_by_target:
		return {item["key"]: {"handled": False, "allowed": False} for item in validated}
	identity = _load_identity(user, offerings)

	decisions = {}
	for item in validated:
		offering = offerings_by_target.get(item["target_key"])
		if not offering:
			decisions[item["key"]] = {"handled": False, "allowed": False}
			continue
		decisions[item["key"]] = _decide(offering, identity)
	return decisions


def _validate_requests(requests: list[dict]) -> list[dict]:
	if not isinstance(requests, list) or len(requests) > MAX_REQUESTS:
		frappe.throw(_("Entitlement requests must be a bounded list."))
	validated = []
	seen = set()
	for request in requests:
		if not isinstance(request, dict):
			frappe.throw(_("Entitlement request entries must be objects."))
		key = request.get("key")
		resource_type = request.get("resource_type")
		resource_name = request.get("resource_name")
		action = request.get("action")
		context = request.get("context") if "context" in request else {}
		if context is None:
			context = {}
		if (
			not isinstance(key, str)
			or not key
			or len(key) > MAX_KEY_LENGTH
			or key in seen
			or resource_type not in ALLOWED_RESOURCE_TYPES
			or not isinstance(resource_name, str)
			or not resource_name
			or len(resource_name) > MAX_RESOURCE_NAME_LENGTH
			or action not in ALLOWED_ACTIONS
			or not _valid_context(context)
		):
			frappe.throw(_("Invalid entitlement request."))
		seen.add(key)
		validated.append(
			{
				"key": key,
				"resource_type": resource_type,
				"resource_name": resource_name,
				"action": action,
				"target_key": f"{ALLOWED_RESOURCE_TYPES[resource_type]}:{resource_name}",
			}
		)
	return validated


def _valid_context(context: dict) -> bool:
	if not isinstance(context, dict) or set(context) - CONTEXT_FIELDS:
		return False
	for key, value in context.items():
		if key == "is_preview":
			if value is not None and not isinstance(value, bool):
				return False
		elif value is not None and (not isinstance(value, str) or len(value) > MAX_CONTEXT_VALUE_LENGTH):
			return False
	return True


def _commerce_enabled() -> bool:
	# Single DocTypes live in tabSingles and never have a physical table.
	return bool(frappe.db.get_single_value("Commerce Settings", "enabled"))


def _load_identity(user: str, offerings: list) -> frappe._dict:
	is_authenticated = bool(user and user != "Guest" and frappe.db.get_value("User", user, "enabled"))
	if not is_authenticated:
		return frappe._dict(
			authenticated=False,
			targets=set(),
			tier_ranks={},
			max_tier_rank=0,
		)

	rows = frappe.get_all(
		"Commerce Entitlement",
		filters={"member": user, "status": "Active"},
		fields=["scope", "target_key", "tier", "starts_on", "ends_on"],
	)
	active = [row for row in rows if is_active_window(row.starts_on, row.ends_on)]
	targets = {row.target_key for row in active if row.scope == "Target" and row.target_key}
	entitled_tiers = {row.tier for row in active if row.scope == "Tier" and row.tier}
	tier_names = entitled_tiers | {row.required_tier for row in offerings if row.required_tier}
	ranks = (
		{
			row.name: cint(row.rank)
			for row in frappe.get_all(
				"Commerce Tier",
				filters={"enabled": 1, "name": ["in", list(tier_names)]},
				fields=["name", "rank"],
			)
		}
		if tier_names
		else {}
	)
	return frappe._dict(
		authenticated=True,
		targets=targets,
		tier_ranks=ranks,
		max_tier_rank=max((ranks.get(tier, 0) for tier in entitled_tiers), default=0),
	)


def _decide(offering, identity) -> dict:
	policy = offering.access_policy
	target_grant = offering.active_target_key in identity.targets
	required_rank = identity.tier_ranks.get(offering.required_tier, 0) if offering.required_tier else 0
	tier_grant = bool(required_rank and identity.max_tier_rank >= required_rank)
	if policy == "Free":
		allowed = identity.authenticated
	elif policy == "Tier":
		allowed = target_grant or tier_grant
	elif policy == "Purchase":
		allowed = target_grant
	else:
		allowed = target_grant or tier_grant

	badge = _badge(offering, allowed)
	if allowed:
		return {
			"handled": True,
			"allowed": True,
			"reason": "entitled",
			"badge": badge,
			"offers": [],
		}

	offers = []
	if not identity.authenticated:
		offers.append(
			{
				"kind": "login",
				"label": _("Log in"),
				"url": "/login",
				"variant": "solid",
				"icon": "log-in",
			}
		)
	else:
		if policy in PURCHASE_POLICIES and offering.purchase_url:
			offers.append(
				{
					"kind": "purchase",
					"label": _("Buy for {0}").format(fmt_money(offering.amount, currency=offering.currency)),
					"url": validate_safe_url(offering.purchase_url, required=True),
					"variant": "solid",
					"icon": "credit-card",
				}
			)
		if policy in TIER_POLICIES and offering.upgrade_url:
			offers.append(
				{
					"kind": "upgrade",
					"label": _("Upgrade to {0}").format(offering.required_tier),
					"url": validate_safe_url(offering.upgrade_url, required=True),
					"variant": "outline",
					"icon": "layers",
				}
			)

	reason = "login_required" if not identity.authenticated else _locked_reason(policy)
	return {
		"handled": True,
		"allowed": False,
		"reason": reason,
		"badge": badge,
		"offers": offers,
	}


def _badge(offering, allowed: bool) -> dict:
	label = offering.badge_label
	if not label:
		if offering.required_tier:
			label = offering.required_tier
		elif offering.access_policy == "Free":
			label = _("Free")
		else:
			label = _("Purchase")
	if offering.access_policy == "Free":
		theme = "green"
	elif offering.required_tier:
		theme = "purple"
	else:
		theme = "amber"
	return {
		"label": label,
		"theme": theme,
		"icon": "unlock" if allowed else "lock",
	}


def _locked_reason(policy: str) -> str:
	if policy == "Free":
		return "login_required"
	if policy == "Tier":
		return "tier_required"
	if policy == "Purchase":
		return "purchase_required"
	return "purchase_or_tier_required"
