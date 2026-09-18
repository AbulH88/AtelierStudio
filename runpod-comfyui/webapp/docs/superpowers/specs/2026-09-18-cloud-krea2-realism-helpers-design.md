# Cloud Krea2 realism helpers

## Goal

Add the two approved realism helper LoRAs to the Cloud Krea2 Image to Image HQ
workflow on RunningHub, while leaving the Local Krea2 HQ workflow unchanged.

## Scope

- The Cloud Krea2 job sends these fixed LoRAs through its existing
  `LoraLoaderState` payload:
  - `realism_engine_krea2_v3.1.safetensors`
  - `RealisticSnapshotKrea2.safetensors`
- Each helper always uses model and CLIP strength `0.60`.
- The Cloud Krea2 panel gets one `Realism helpers` on/off switch.
- The switch is enabled by default and its value is included when a Cloud Krea2
  job is submitted.
- The switch affects only new Cloud Krea2 jobs. Existing jobs keep their saved
  submission settings.

## Non-goals

- No Cloud batch/variation control.
- No editable helper paths or strengths in the user interface.
- No change to Local Krea2 HQ helpers or any other Cloud workflow.

## Data flow

1. The browser submits `realism_helpers=true|false` with the Cloud Krea2 form.
2. The server validates the value and stores it on the persisted job record.
3. When enabled, the RunningHub `LoraLoaderState` contains the chosen character
   LoRA plus the two fixed helpers at 0.60.
4. When disabled, the payload contains only the chosen character LoRA.

## Error handling and verification

- Preserve the current server error response when RunningHub rejects the
  `LoraLoaderState`.
- Add focused tests for the enabled and disabled payloads and form parsing.
- Verify the existing Cloud Krea2 request fields remain unchanged.
