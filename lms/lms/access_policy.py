# Copyright (c) 2026, Frappe and Contributors
# See license.txt

"""Deny-only extension point for externally managed course access.

Providers are registered under the ``lms_course_access_policy`` hook. Each provider
is called with keyword-only ``user``, ``course``, ``action``, and ``context`` and
returns ``None`` (unmanaged), ``True`` (no external denial), or ``False`` (deny).
This module only tightens access after native LMS authorization; it never grants it.
"""

from collections.abc import Mapping

import frappe

POLICY_HOOK = "lms_course_access_policy"
POLICY_ACTIONS = frozenset({"consume", "progress"})
_CONTEXT_FIELDS = ("lesson", "quiz", "is_preview")
_MAX_CONTEXT_STRING_LENGTH = 140
_CACHE_ATTRIBUTE = "lms_course_access_policy_cache"


def course_access_policy_allows(
	*, user: str, course: str, action: str, context: Mapping | None = None
) -> bool:
	"""Return whether external policy permits otherwise-native processing."""
	return (
		course_access_policy_decision(
			user=user,
			course=course,
			action=action,
			context=context,
		)
		is not False
	)


def course_access_policy_decision(
	*, user: str, course: str, action: str, context: Mapping | None = None
) -> bool | None:
	"""Return aggregate provider opinion: ``None`` (unmanaged), ``True``, or ``False``.

	The result is request-locally memoized. Invalid inputs, provider configuration,
	provider results, and provider exceptions fail closed and are logged server-side.
	No providers, or providers that all return ``None``, leave the course unmanaged.
	"""
	try:
		normalized_context = _normalize_context(context)
	except (TypeError, ValueError):
		_log_warning("Course access policy rejected malformed context", user, course, action)
		return False

	if not _valid_identity(user) or not _valid_identity(course) or action not in POLICY_ACTIONS:
		_log_warning("Course access policy rejected malformed inputs", user, course, action)
		return False

	cache_key = (
		user,
		course,
		action,
		tuple((field, normalized_context[field]) for field in _CONTEXT_FIELDS),
	)
	cache = getattr(frappe.local, _CACHE_ATTRIBUTE, None)
	if not isinstance(cache, dict):
		cache = {}
		setattr(frappe.local, _CACHE_ATTRIBUTE, cache)
	if cache_key in cache:
		return cache[cache_key]

	decision = _evaluate_providers(
		user=user,
		course=course,
		action=action,
		context=normalized_context,
	)
	cache[cache_key] = decision
	return decision


def _evaluate_providers(*, user: str, course: str, action: str, context: dict) -> bool | None:
	try:
		provider_paths = frappe.get_hooks(POLICY_HOOK) or []
	except Exception:
		_log_exception("Course access policy hook discovery failed", user, course, action)
		return False

	if not isinstance(provider_paths, list | tuple):
		_log_warning("Course access policy hook configuration is malformed", user, course, action)
		return False

	has_opinion = False
	for provider_path in provider_paths:
		if not isinstance(provider_path, str) or not provider_path:
			_log_warning("Course access policy provider configuration is malformed", user, course, action)
			return False
		try:
			provider = frappe.get_attr(provider_path)
			if not callable(provider):
				raise TypeError("configured provider is not callable")
			result = provider(user=user, course=course, action=action, context=dict(context))
		except Exception:
			_log_exception("Course access policy provider failed", user, course, action, provider_path)
			return False

		if result is None:
			continue
		if result is True:
			has_opinion = True
			continue
		if result is False:
			return False

		_log_warning(
			"Course access policy provider returned a malformed result",
			user,
			course,
			action,
			provider_path,
		)
		return False

	return True if has_opinion else None


def _normalize_context(context: Mapping | None) -> dict:
	if context is None:
		context = {}
	if not isinstance(context, Mapping):
		raise TypeError
	if set(context) - set(_CONTEXT_FIELDS):
		raise ValueError

	normalized = {field: None for field in _CONTEXT_FIELDS}
	for field in ("lesson", "quiz"):
		value = context.get(field)
		if value is not None and (
			not isinstance(value, str) or not value or len(value) > _MAX_CONTEXT_STRING_LENGTH
		):
			raise ValueError
		normalized[field] = value

	is_preview = context.get("is_preview")
	if is_preview is not None and is_preview is not True and is_preview is not False:
		raise ValueError
	normalized["is_preview"] = is_preview
	return normalized


def _valid_identity(value) -> bool:
	return isinstance(value, str) and bool(value) and len(value) <= _MAX_CONTEXT_STRING_LENGTH


def _log_warning(message, user, course, action, provider=None):
	frappe.logger("lms.security").warning(
		"%s: user=%s course=%s action=%s provider=%s",
		message,
		user,
		course,
		action,
		provider or "-",
	)


def _log_exception(message, user, course, action, provider=None):
	frappe.logger("lms.security").exception(
		"%s: user=%s course=%s action=%s provider=%s",
		message,
		user,
		course,
		action,
		provider or "-",
	)
