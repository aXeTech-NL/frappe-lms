# Native one-time course checkout

## Ownership

- Payments (`payments.checkout`): named gateway resolution, provider transport,
  Mollie oneoff payment creation, authoritative fetch and webhook delivery.
- Internal LMS Commerce: offering/pricing, immutable Commerce Order, customer
  ownership, confirmation, payment-sourced entitlements and recovery policy.
- Native LMS UI: `/lms/checkout/<offering>` and
  `/lms/checkout/return/<order>`, respecting the configured LMS base path.

This first slice sells one published, self-learning, **EUR** course at the exact
configured total. It supports Purchase and Tier or Purchase offerings. It refuses
native `paid_course`, upcoming, unpublished, disabled-self-learning, Program and
Tier-only purchases. It is not a subscription, invoice or tax calculation engine.

## Enable only on a dedicated test site first

1. Install exact compatible commits of Payments and LMS and migrate/build normally.
   No standalone Commerce app, code overlays or running-demo migration is needed.
2. Set a canonical `host_name`, for example `https://checkout-test.example.org`.
   The complete site must be reachable at that HTTPS origin, including login,
   return routes and the provider callback. Do not expose a local development
   server or invent a public callback for `dev.localhost`.
3. Create a named Mollie Settings account using a **test** key, entered directly
   in its encrypted Password field. Do not paste credentials into source/chat.
4. Configure Commerce Settings: Enabled, Checkout Payment Gateway, a published
   **versioned** Terms URL, then Enable Checkout. Leave Allow Live Payments off.
5. Configure an eligible offering with its exact total in EUR. Native course
   cards/details automatically point to native checkout; no purchase URL needs
   to be pasted in. An external purchase URL is the fallback with checkout off.
6. Test a complete provider-hosted checkout, delayed callback, cancel/expiry,
   repeated callbacks, reconciliation, refunds and chargebacks before a go-live
   decision. A test payment grants real access **on that test site only**; never
   run test purchases with production users/data or retain test grants at go-live.

New installations default to checkout off and live payments disallowed. Changing
Allow Live Payments requires System Manager. Neither flag is activated by install
or migration. Configuring a gateway is an explicit operational action.

## Order and money safety

The browser submits an offering ID, quote version and affirmative terms acceptance,
never an amount, currency, member, provider ID or arbitrary return URL. The server
rechecks publication/eligibility and snapshots the price, course, gateway, mode and
versioned terms URL. A changed price/terms/mode requires a new confirmation.

Orders are random IDs and readable by their member only through the narrow API.
Desk reads are available to Commerce administrators/viewers; generic document
creation/editing is blocked, even with an administrator's normal document save.
Payment audit rows cannot be deleted. Checkout URLs are not payment proof.

A unique open-course key and member/row locks serialize double clicks and parallel
tabs. A replacement offering cannot evade an already open course checkout. The
order/request fingerprint is committed before the provider POST. Browser retries
reuse its idempotency key. A provider timeout leaves a recoverable `creating` order,
not a new chance to charge. Callback URL or credential changes prevent unsafe
replays. An uncertain creation older than 20 hours requires operator reconciliation
rather than risking another charge beyond the provider's retention window.

Only authoritative snapshots matching the stored gateway, mode, payment ID, opaque
customer reference, merchant reference, currency and full total can fulfill.
Grant insertion and order updates share one database transaction. Duplicate or
stale notifications cannot create another entitlement or resurrect reversed access.

## Access and reversals

A confirmed payment creates a **Purchase** entitlement linked to its order.
It does not auto-enroll or bypass any native LMS rule. The learner returns to the
normal course page to enroll/continue; the integration test exercises that native
insertion. Quizzes, certification, progress and existing enrollments are untouched.

Each purchase owns a separate grant, so a refund cannot revoke independent manual
or tier access. Full refunds and any chargeback revoke only that order's grant.
A partial refund retains its grant; the refunded amount stays on the order. These
initial policies are explicit and should be reviewed against the business terms.
This code observes reversals; it does **not initiate refunds**.

## Recovery and support

The return page reads the order and can request an authoritative status refresh;
URL parameters and returning from Mollie never fulfill an order. Unknown creation
is retried only by an explicit action using the existing order. A failed/expired
payment can be restarted from its course as a new, separately tracked order.

Hourly recovery fetches up to 50 known payments, oldest checked first, including
paid orders so lost reversal notifications are recoverable. Errors also rotate
through the scan and produce a sanitized error log. The job never creates a
payment. Monitor scheduler health and reconciliation errors; tune frequency/batch
size before higher volume use. Refund/chargeback history is monotonic.

For an uncertain old creation, inspect Mollie using the order's merchant reference
`lms-order:<order-id>`. Use a **server-side** authoritative `payments.checkout.fetch`
and `deliver` for the matching account/payment, in a committed transaction. Never
mark the order paid manually, clear its open key to retry, or fabricate a payment
snapshot. If no payment exists, resolving/releasing the order requires an audited
support procedure; a self-service forced reset is intentionally not shipped.

Disabling new checkout does not discard outstanding orders or suppress payment
reconciliation. Commerce itself can still be disabled to restore native access.

## Still required before production

- A real Mollie test-mode round trip over public HTTPS (not a mocked API).
- Approved consumer terms, any required digital-delivery withdrawal consent,
  price/VAT treatment, invoices and the applicable refund policy.
- Production credentials, secret rotation procedures, observability, backups,
  load/concurrent HTTP tests and remote-only reproducible image validation.
- Explicit publication, deployment and live-provider activation approval.

Basic/Max recurring subscriptions, mandates, renewal/cancellation, business seats,
Program/Batch commerce and tax/invoicing remain separate work. Do not repurpose the
one-time payment as recurring consent.
