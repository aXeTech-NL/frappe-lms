# Subscription tiers

Frappe LMS can optionally combine hierarchical subscriptions with one-time Course and Program purchases.

## Enable the feature

1. Install and configure the Frappe Payments app and a Payment Gateway.
2. Open **Settings → General** and enable **Subscriptions**.
3. Open **Settings → Payment → Subscriptions**.
4. Create tiers in ascending rank order, for example Basic (`10`) and Max (`20`).
5. Create one or more monthly/yearly plans for each tier.

Every authenticated LMS user implicitly has Free access. A persisted Free subscription is not required. When subscriptions are disabled, LMS keeps its legacy enrollment/payment and guest-preview behavior.

## Course and Program access

Courses retain the existing **Paid course** option for one-time purchase and gain an optional **Required subscription tier**. Programs gain equivalent one-time pricing and tier fields.

This supports:

- free content: no one-time price and no required tier;
- subscription-only content: required tier only;
- purchase-only content: one-time price only;
- subscription or purchase: both fields configured.

Higher-ranked tiers include lower-ranked content. A direct purchase remains valid independently of a user's subscription. Enrollment and progress records are retained after a subscription expires; current entitlement is checked separately whenever protected content is read or progress is written.

A Program entitlement dynamically covers its current Courses. Adding a Course makes it available to entitled Program members; removing it removes only the Program-derived grant and preserves progress and any direct, Batch, or other Program entitlement. A Program's required tier cannot be lower than the highest required tier of its Courses.

## Checkout and lifecycle

The existing Payments controller handles one-time Course/Program purchases and the first subscription period. `LMS Payment` is the transaction and provider-event ledger. LMS records subscription status and inclusive billing periods in `LMS Subscription`.

Core lifecycle behavior includes:

- replay-safe first-period activation and renewals;
- Failed → Paid recovery;
- expiry and cancellation-at-period-end;
- immediate cancellation;
- non-prorated upgrades to a higher tier;
- daily expiry and Program enrollment reconciliation.

Automatic recurring debit is provider-specific and is not performed by LMS core.

## Payment-provider integration

A provider adapter must verify its own webhook signature before calling the trusted Python API:

```python
from lms.lms.subscriptions import (
    record_subscription_event,
    set_provider_references,
)

set_provider_references(
    subscription,
    payment_gateway="Mollie",
    gateway_customer_id=customer_id,
    gateway_subscription_id=provider_subscription_id,
)

record_subscription_event(
    subscription,
    "Paid",  # Paid, Failed, or Refunded
    provider_event_id,
    provider_payment_id=provider_payment_id,
    payment_gateway="Mollie",
    amount=amount,
    currency=currency,
    paid_on=paid_on,
    failure_reason=None,
)
```

`record_subscription_event` is intentionally not a guest-whitelisted endpoint. The provider adapter owns webhook authentication, mandate creation, automatic debit, and mapping provider customer/subscription IDs.

Adapters can register hooks:

```python
lms_subscription_event_handlers = ["my_app.subscriptions.on_lms_event"]
lms_subscription_cancel_handlers = ["my_app.subscriptions.cancel_provider_subscription"]
```

Event handlers run after commit. Cancellation handlers are called before LMS confirms a user-requested cancellation. They should raise when provider cancellation fails.

## Deliberate limitations

The core implementation does not provide:

- Mollie-specific API or webhook code;
- automatic recurring debit without a provider adapter;
- upgrade/downgrade proration;
- recurring coupon policies;
- automatic entitlement reversal after a refund;
- ERPNext invoice/accounting integration.

Refund events are retained for audit. Provider/admin policy must explicitly cancel access when a refund should also terminate the subscription.

## Deployment

Run the normal app migration after updating:

```bash
bench --site <site> migrate
```

Before enabling subscriptions on an existing production site, test migration and SCORM-file relocation on a recent copy. Existing Course enrollments and Program memberships are grandfathered as permanent legacy access.
