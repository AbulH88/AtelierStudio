# Cloud Workflow User Gates Design

Date: 2026-09-18

## Goal

Give administrators per-user control over Cloud Studio workflow access. Non-admin users start with no Cloud workflow access; admins grant only the workflows a user should be able to use.

## Permission model

- Admins always have access to every Cloud workflow.
- Every non-admin user has a `cloud_workflows` allowlist in the existing user record.
- Missing, malformed, or empty allowlists deny all Cloud workflow access.
- Existing non-admin users receive no Cloud access until an admin enables one or more workflows.
- The allowed identifiers are `krea2_i2i_hq`, `scail`, `h3`, and `jobs`.

## Admin controls

- Admin → Users shows four per-user Cloud workflow toggles: Krea2 Image to Image HQ, Scail 2 Motion, MiniMax H3 Ref2V, and Cloud Jobs.
- Saving updates only the selected user's allowlist. It does not expose credentials or alter RunningHub concurrency/entitlements.

## Enforcement

- Cloud Studio configuration exposes only the current user's allowed workflows so the sidebar hides unavailable choices.
- Every corresponding job-submission and Cloud Jobs API endpoint checks the allowlist server-side and returns `403` when denied.
- This is an authorization boundary: browser manipulation cannot grant access.

## Validation

- Add focused tests for deny-by-default behavior, admin bypass, per-workflow API denial, and allowlist update validation.
- Run Python compilation and the focused Cloud test suite.

## Non-goals

- Restricting Local Studio, Gallery, Reels, or any non-Cloud page.
- Changing account roles, API-key ownership, job concurrency, or billing.
- Migrating user records to a database.
