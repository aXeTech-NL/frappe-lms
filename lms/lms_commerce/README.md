# Internal LMS Commerce

This fork keeps Commerce inside LMS, not in a separately installed app or a second
catalog frontend. The upstream LMS remains the source of the course list, filters,
pagination, cards, course pages, navigation, teaching tools and learning records.

## Boundaries

- Backend implementation: `lms/lms_commerce/` (Frappe module **LMS Commerce**).
- Frontend implementation: `frontend/src/commerce/`, using native LMS layouts,
  Frappe UI components and existing design tokens. No separate stylesheet/app shell.
- Small integration points: hook declarations, course response enrichment, the
  existing course card/action panel, sidebar and route table.
- The generic `lms_course_access_policy` seam remains deny-only. Lesson, assessment,
  progress, media and enrollment authorization are checked server-side, not merely
  hidden by the UI. Quiz evaluation and certificate generation stay native. The
  small quiz progress-follow-up guard prevents an independently authorized batch
  submission from being rolled back by a denied course-progress write.

## Configuration

Open **Commerce management** from the LMS sidebar (requires Settings read access),
or `/desk/commerce`. The DocTypes are Commerce Settings, Commerce Tier, Commerce
Offering, Commerce Entitlement and the read-only Commerce Order payment audit.

With Enabled off, or no enabled Offering for a course, native behavior is retained.
With Enabled on, a mapped course can be Free, Tier, Purchase, or Tier or Purchase.
Higher ranked active tiers satisfy lower tier requirements. A direct Target grant
can authorize a course. Dates and revocations are evaluated on the next request;
no scheduler is necessary to enforce expiry.

Grants never bypass native enrollment, paid-course eligibility or other LMS checks.
Avoid accidentally configuring both native LMS payment requirements and Commerce
pricing. Course authors and native administrators retain their intended staff access.

Routes remain native: `/lms`, `/lms/courses`, `/lms/courses/<course>`, and lessons.
The old `/commerce/courses` entry redirects back to the native course list, not the
other way around. `/lms/access` shows only the current user's tier/target grants;
the API is authenticated, bounded and not parameterizable with another member.
The LMS base path may be configured normally through site configuration.

## Installation

Install Payments and this LMS fork, then optional other apps/branding. Do **not**
install `frappe_lms_commerce` alongside it. The local stack is rebuilt from scratch
at the operator's request. There is no automatic migration of legacy Commerce or
`feature/subscription-tiers` sites: those require a separately reviewed data plan.

The distinct module name prevents collisions with the legacy `Commerce` namespace.
No monkey patches, copied native course components or dynamic sibling mounts are
required. Build the normal LMS frontend with Bench.

## One-time checkout

[Checkout setup, safety and recovery](CHECKOUT.md) describes native EUR course
checkout through `payments.checkout` and the separate Payments Mollie adapter.
Checkout and live payments default to disabled. Confirmed payments create an
order-scoped Purchase grant, without replacing native enrollment or eligibility.
Only provider-verified state fulfills; browser returns never do.

## Not implemented

Recurring subscriptions, refund initiation, invoices/tax calculation and business
seats remain separate work. The personal access page does not pretend that manual
tier grants are billed subscriptions. With checkout disabled, missing purchase or
upgrade URLs still display an unavailable action rather than a fictional checkout.

Program/Batch commercial enforcement is not implemented; independent native batch
assessment access remains valid. Historical public media/SCORM and external video
URLs cannot be made private through a Python access hook. Inventory and migrate
such assets before commercial use.

## Verification

- `bench --site <test-site> run-tests --app lms --module lms.lms_commerce.tests.<module>`
- `bench --site <test-site> run-tests --app lms --module lms.tests.test_course_access_policy`
- Existing native security suites under `lms.tests.security`.
- `cd frontend && yarn test && yarn build`.

Keep upstream merges small: do not move quiz/certificate implementations into this
module, duplicate course-list filtering, or add commercial state to lesson records.
