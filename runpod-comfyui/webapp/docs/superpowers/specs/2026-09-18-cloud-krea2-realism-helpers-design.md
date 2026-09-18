# Cloud Krea2 helper LoRA management

## Goal

Give Cloud Krea2 Image to Image HQ a managed helper-LoRA stack on RunningHub,
while leaving the Local Krea2 HQ workflow unchanged.

## Scope

- Admin has a dedicated **Cloud Krea2 Helper LoRAs** section in Administration.
  It manages a separate persistent registry of helper file names, enabled state,
  and default strength.
- The registry begins with these enabled defaults at `0.60`:
  - `realism_engine_krea2_v3.1.safetensors`
  - `RealisticSnapshotKrea2.safetensors`
- Admin can add a helper filename, set its default strength, enable or disable
  it, or remove it. Filename and strength are validated server-side.
- Cloud Krea2 reads the registry and shows one row per helper: a per-helper
  on/off switch, a strength slider, and an editable numeric strength field.
- New Cloud Krea2 jobs inherit the admin defaults. A user can adjust helper
  state and strength for that job without changing the admin registry.
- Submission sends only enabled helpers through the existing `LoraLoaderState`,
  alongside the selected character LoRA. Each helper stores the exact state and
  strength on its persisted job record.

## Non-goals

- No Cloud batch/variation control.
- No change to Local Krea2 HQ helpers or any other Cloud workflow.

## Data flow

1. Admin saves the validated registry to a server-side JSON file. The API never
   exposes credentials or accepts filesystem paths.
2. Cloud Krea2 loads the registry and seeds its user controls from it.
3. The browser sends job-specific helper `{filename, enabled, strength}` values.
4. The server rejects helper names not in the enabled admin registry and clamps
   strengths to the supported range before storing the job.
5. RunningHub receives the chosen character LoRA plus only the enabled helper
   entries in `LoraLoaderState`.

## Error handling and verification

- Preserve the current server error response when RunningHub rejects the
  `LoraLoaderState`.
- Admin endpoints require the existing admin authorization.
- Add focused tests for registry validation, job-specific helper validation,
  and the enabled/disabled RunningHub payload.
- Verify the existing Cloud Krea2 request fields remain unchanged.
