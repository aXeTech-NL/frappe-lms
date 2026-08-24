# External LMS entitlement providers

Frappe Learning can optionally delegate commercial eligibility and offer presentation to one installed app. LMS continues to own publication, instructors, local enrollment, lesson ordering, progress, and certificates.

Configure one hook in the provider app:

```python
lms_entitlement_provider = "my_app.entitlements.decide_many"
```

The provider exposes a bulk-first versioned function:

```python
def decide_many(*, user: str, requests: list[dict], contract_version: int = 1) -> dict[str, dict]:
    ...
```

Requests contain a stable `key`, `resource_type` (`course` or `program`), `resource_name`, `action` (`catalog`, `view`, `enroll`, `consume`, or `progress`) and a bounded context containing optional `lesson`, `quiz`, and `is_preview` values.

A response is keyed by the request key:

```python
{
    "course:python:catalog": {
        "handled": True,
        "allowed": False,
        "reason": "subscription_required",
        "badge": {"label": "Max", "theme": "violet", "icon": "lock"},
        "offers": [
            {
                "kind": "upgrade",
                "label": "Upgrade to Max",
                "url": "/commerce/plans?course=python",
                "variant": "outline",
                "icon": "layers",
            }
        ],
    }
}
```

## Semantics

- `handled=False` preserves native LMS behavior for that resource.
- `handled=True` makes the provider authoritative for the requested commercial action.
- Catalog entries remain visible when `allowed=False`; the decision supplies a lock badge and safe calls to action.
- Enrollment remains explicit learner intent. A provider grant permits enrollment but does not create it.
- Managed lesson consumption and progress require both a local LMS Enrollment and provider approval.
- Staff/instructor bypass, publication, duplicate enrollment, self-learning settings, sequential lesson ordering, and progress ownership remain LMS-owned.
- Provider output is normalized. Labels/counts are bounded; themes/icons/variants are allowlisted; offer URLs must be relative or HTTPS. HTML and arbitrary components are not accepted.
- Zero or one provider is supported. Multiple configured providers are rejected.
- Provider absence preserves existing sites exactly. Provider failures fail closed for managed authorization and are shown as a generic temporary lock without leaking exception text.
- LMS uses request-local memoization only. Providers own any cross-request caching and invalidation.

Provider apps that can manage SCORM courses must call
`lms.page_renderers.protect_legacy_scorm_packages` from their install/sync hook.
LMS also runs it after migrate for providers that are already installed. The helper
is a no-op without a provider, preserving unmanaged legacy deployments.

See `lms/entitlements.py` for the canonical contract constants and normalizer.
