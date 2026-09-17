# Krea2 Cloud Controls Design

## Goal

Extend the existing Krea2 Image-to-Image HQ Cloud Studio workflow with the useful controls from Local Studio while preserving the current Cloud Studio visual design.

## User interface

The existing Krea2 cloud panel remains the visual foundation. Add a compact Cloud-styled settings area below the current Resolution, Character, and Version selectors.

- Add **Denoise · base** using the same functional pattern as Local Studio: a range slider synchronized with an editable numeric value.
- Use a `0.00`–`1.00` range, `0.01` increments, and a default of `0.60`.
- Add an expandable **Describe with AI settings** section containing the same functional choices as Local Studio:
  - Vision Model
  - Style Preset
  - Body Type
  - Shot Type
  - Detail Level
  - Explicit / NSFW
  - Clothing Note
  - Custom Instruction
- These controls must use the current Cloud Studio typography, spacing, borders, and layout. Local Studio UI markup or visual layout will not be copied.

## Data flow

When **Describe source with AI** is clicked, the selected source image and description settings are sent to the existing `/api/describe` endpoint. The resulting prompt replaces the Cloud prompt text.

When **Generate on RunningHub** is clicked, the existing Krea2 submission includes the selected denoise value. The server validates it as a finite number from `0` through `1` and sends it to RunningHub as:

- node `4`
- field `denoise`
- selected decimal value

The second ClownsharKSampler remains unchanged at its published workflow value of `0.27`; no UI control or API override is added for node `1`.

## Architecture

- Reuse the existing description parameter names and server-side prompt-building path used by Local Studio.
- Keep independent Cloud UI state rather than reading or modifying hidden Local Studio controls.
- Add one Krea2 denoise field to the persisted cloud job so queued jobs retain the exact submitted value.
- Extend the existing RunningHub node override builder for Krea2; no new queue system is needed.

## Validation and errors

- The UI shows the exact numeric denoise value and keeps the number input and slider synchronized.
- Invalid, missing, non-finite, or out-of-range denoise values are rejected server-side with a clear error.
- AI-description failures remain in the Krea2 cloud error area without clearing the source image or chosen settings.
- Existing duplicate-job prevention and cancellation behavior remain unchanged.

## Testing

- Verify description requests contain all supported Local Studio option values.
- Verify node `4` receives the selected denoise value.
- Verify node `1` receives no override and remains fixed by the published workflow.
- Verify the default is `0.60` and invalid values are rejected.
- Parse the complete inline JavaScript and run the focused RunningHub tests before deployment.

## Out of scope

- Copying the Local Studio visual design.
- Exposing the second sampler's denoise.
- Changing sampler, scheduler, steps, CFG, or other workflow internals.
- Refactoring Local and Cloud Studio into a shared UI component.
