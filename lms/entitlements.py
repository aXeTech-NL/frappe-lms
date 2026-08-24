# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""Optional external entitlement and commerce-offer bridge.

LMS owns publication, instructors, enrollments and learning progress. An installed
app can own commercial eligibility by exposing one ``lms_entitlement_provider``
hook. The provider is deliberately bulk-first so a catalog page costs one hook
call, not one call per card.

The contract is presentation-neutral and contains no subscription/payment schema.
When no provider handles a resource, callers must preserve the native LMS rules.
"""

import json
from collections.abc import Mapping
from urllib.parse import urlsplit

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

CONTRACT_VERSION = 1
RESOURCE_TYPES = {"course", "program"}
ACTIONS = {"catalog", "view", "enroll", "consume", "progress"}
BADGE_THEMES = {"gray", "blue", "green", "orange", "red", "violet"}
ICONS = {"lock", "unlock", "layers", "credit-card", "arrow-up-right", "log-in", "refresh-cw"}
OFFER_KINDS = {"purchase", "subscribe", "upgrade", "renew", "login", "external"}
BUTTON_VARIANTS = {"solid", "outline", "subtle", "ghost"}
MAX_REQUESTS = 120
MAX_OFFERS = 4
MAX_LABEL_LENGTH = 100
MAX_REASON_LENGTH = 180
MAX_CONTEXT_VALUE_LENGTH = 180
_CONTEXT_FIELDS = {"lesson", "quiz", "is_preview"}


def make_key(resource_type: str, resource_name: str, action: str) -> str:
	return f"{resource_type}:{resource_name}:{action}"


def make_request(
	resource_type: str,
	resource_name: str,
	action: str,
	*,
	context: dict | None = None,
	key: str | None = None,
) -> dict:
	return _normalize_request(
		{
			"key": key or make_key(resource_type, resource_name, action),
			"resource_type": resource_type,
			"resource_name": resource_name,
			"action": action,
			"context": context or {},
		}
	)


def decide(
	resource_type: str,
	resource_name: str,
	action: str,
	*,
	user: str | None = None,
	context: dict | None = None,
) -> frappe._dict:
	request = make_request(resource_type, resource_name, action, context=context)
	return decide_many([request], user=user)[request["key"]]


def decide_many(requests: list[dict], *, user: str | None = None) -> dict[str, frappe._dict]:
	"""Return normalized decisions keyed by the request's stable key.

	Provider absence returns ``handled=False``. Once a provider is configured,
	missing/malformed output and provider errors fail closed with a generic reason;
	provider exception text is logged, never returned to a learner.
	"""
	if not isinstance(requests, list) or not requests or len(requests) > MAX_REQUESTS:
		frappe.throw(_("Invalid entitlement request batch."), frappe.ValidationError)

	normalized = [_normalize_request(request) for request in requests]
	keys = [request["key"] for request in normalized]
	if len(keys) != len(set(keys)):
		frappe.throw(_("Entitlement request keys must be unique."), frappe.ValidationError)

	provider = get_provider()
	if not provider:
		return {key: unmanaged_decision() for key in keys}

	user = user or frappe.session.user
	cache_key = _cache_key(user, normalized)
	cache = _request_cache()
	if cache_key in cache:
		return cache[cache_key]

	try:
		raw = frappe.get_attr(provider)(
			user=user,
			requests=normalized,
			contract_version=CONTRACT_VERSION,
		)
		decisions = _normalize_response(raw, keys)
	except Exception:
		_log_provider_failure(provider)
		decisions = {key: unavailable_decision() for key in keys}

	cache[cache_key] = decisions
	return decisions


def decide_many_batched(requests: list[dict], *, user: str | None = None) -> dict[str, frappe._dict]:
	"""Resolve an unbounded internal set through bounded provider calls."""
	decisions = {}
	for start in range(0, len(requests), MAX_REQUESTS):
		decisions.update(decide_many(requests[start : start + MAX_REQUESTS], user=user))
	return decisions


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=500, seconds=60 * 60)
def get_entitlement_decision(
	resource_type: str,
	resource_name: str,
	action: str = "view",
	context: dict | None = None,
):
	"""Safe normalized decision endpoint for shells that cannot use course detail.

	Authorization never trusts this presentation endpoint; protected reads and
	writes independently call the same provider from their server-side boundary.
	"""
	return decide(resource_type, resource_name, action, context=context)


def get_provider() -> str | None:
	"""Resolve exactly zero or one provider from the merged Frappe hooks."""
	configured = frappe.get_hooks("lms_entitlement_provider") or []
	if isinstance(configured, str):
		configured = [configured]
	providers = []
	for value in configured:
		if isinstance(value, str) and value.strip():
			providers.append(value.strip())
		elif isinstance(value, list | tuple):
			providers.extend(item.strip() for item in value if isinstance(item, str) and item.strip())
	providers = list(dict.fromkeys(providers))
	if len(providers) > 1:
		frappe.throw(
			_("Only one LMS entitlement provider can be configured."),
			frappe.ValidationError,
		)
	return providers[0] if providers else None


def has_provider() -> bool:
	return bool(get_provider())


def unmanaged_decision() -> frappe._dict:
	return frappe._dict(handled=False, allowed=False, reason="", badge=None, offers=[])


def unavailable_decision() -> frappe._dict:
	return frappe._dict(
		handled=True,
		allowed=False,
		reason="entitlement_provider_unavailable",
		badge=frappe._dict(label=_("Temporarily unavailable"), theme="gray", icon="lock"),
		offers=[],
	)


def _normalize_request(request: dict) -> dict:
	if not isinstance(request, Mapping):
		frappe.throw(_("Invalid entitlement request."), frappe.ValidationError)
	resource_type = request.get("resource_type")
	resource_name = request.get("resource_name")
	action = request.get("action")
	key = request.get("key")
	if resource_type not in RESOURCE_TYPES or action not in ACTIONS:
		frappe.throw(_("Invalid entitlement request."), frappe.ValidationError)
	if not isinstance(resource_name, str) or not resource_name or len(resource_name) > 180:
		frappe.throw(_("Invalid entitlement resource."), frappe.ValidationError)
	if not isinstance(key, str) or not key or len(key) > 300:
		frappe.throw(_("Invalid entitlement request key."), frappe.ValidationError)

	context = request.get("context") or {}
	if not isinstance(context, Mapping):
		frappe.throw(_("Invalid entitlement context."), frappe.ValidationError)
	normalized_context = {}
	for field in _CONTEXT_FIELDS:
		value = context.get(field)
		if field == "is_preview":
			normalized_context[field] = bool(value)
		elif value is None:
			normalized_context[field] = None
		elif isinstance(value, str):
			normalized_context[field] = value[:MAX_CONTEXT_VALUE_LENGTH]
		else:
			frappe.throw(_("Invalid entitlement context."), frappe.ValidationError)

	return {
		"key": key,
		"resource_type": resource_type,
		"resource_name": resource_name,
		"action": action,
		"context": normalized_context,
	}


def _normalize_response(raw, keys: list[str]) -> dict[str, frappe._dict]:
	if not isinstance(raw, Mapping):
		raise ValueError("provider response must be a mapping")
	return {key: _normalize_decision(raw.get(key)) for key in keys}


def _normalize_decision(value) -> frappe._dict:
	if not isinstance(value, Mapping) or not isinstance(value.get("handled"), bool):
		raise ValueError("provider decision is missing handled")
	if not value["handled"]:
		return unmanaged_decision()
	if not isinstance(value.get("allowed"), bool):
		raise ValueError("provider decision is missing allowed")

	reason = value.get("reason") or ""
	if not isinstance(reason, str):
		raise ValueError("invalid decision reason")
	reason = reason.strip()[:MAX_REASON_LENGTH]

	return frappe._dict(
		handled=True,
		allowed=value["allowed"],
		reason=reason,
		badge=_normalize_badge(value.get("badge")),
		offers=_normalize_offers(value.get("offers")),
	)


def _normalize_badge(value):
	if value in (None, ""):
		return None
	if not isinstance(value, Mapping):
		raise ValueError("invalid badge")
	label = _label(value.get("label"))
	if not label:
		return None
	theme = value.get("theme") or "gray"
	icon = value.get("icon") or "lock"
	if theme not in BADGE_THEMES or icon not in ICONS:
		raise ValueError("invalid badge presentation")
	return frappe._dict(label=label, theme=theme, icon=icon)


def _normalize_offers(value) -> list[frappe._dict]:
	if value in (None, ""):
		return []
	if not isinstance(value, list) or len(value) > MAX_OFFERS:
		raise ValueError("invalid offers")
	offers = []
	for offer in value:
		if not isinstance(offer, Mapping):
			raise ValueError("invalid offer")
		kind = offer.get("kind")
		label = _label(offer.get("label"))
		url = offer.get("url")
		variant = offer.get("variant") or "outline"
		icon = offer.get("icon")
		if kind not in OFFER_KINDS or not label or not _safe_url(url):
			raise ValueError("invalid offer fields")
		if variant not in BUTTON_VARIANTS or (icon is not None and icon not in ICONS):
			raise ValueError("invalid offer presentation")
		offers.append(frappe._dict(kind=kind, label=label, url=url, variant=variant, icon=icon))
	return offers


def _label(value) -> str:
	return value.strip()[:MAX_LABEL_LENGTH] if isinstance(value, str) else ""


def _safe_url(value) -> bool:
	if not isinstance(value, str) or not value or len(value) > 500:
		return False
	if "\\" in value or any(ord(character) < 32 or ord(character) == 127 for character in value):
		return False
	if value.startswith("/"):
		return not value.startswith("//")
	parts = urlsplit(value)
	return parts.scheme == "https" and bool(parts.netloc) and not parts.username and not parts.password


def _cache_key(user: str, requests: list[dict]) -> str:
	return f"{user}:{json.dumps(requests, sort_keys=True, separators=(',', ':'))}"


def _request_cache() -> dict:
	cache = getattr(frappe.local, "lms_entitlement_decisions", None)
	if cache is None:
		cache = {}
		frappe.local.lms_entitlement_decisions = cache
	return cache


def _log_provider_failure(provider: str):
	if getattr(frappe.local, "lms_entitlement_failure_logged", False):
		return
	frappe.local.lms_entitlement_failure_logged = True
	frappe.log_error(
		title="LMS entitlement provider failed",
		message=f"Provider {provider} failed or returned an invalid response.\n\n{frappe.get_traceback()}",
		defer_insert=True,
	)
