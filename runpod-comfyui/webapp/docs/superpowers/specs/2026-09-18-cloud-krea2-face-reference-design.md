# Cloud Krea2 face reference

## Goal

Let a Cloud Krea2 Image to Image HQ user add an optional close-up face image so
AI can produce a short, focused identity note without re-describing the main
source image's pose, clothing, or scene.

## User experience

- The main source-image card remains the composition reference.
- A second optional **Face Reference** card appears below it, with an image
  loader and a short optional **Face note** text field.
- Pressing **Describe source with AI** describes the main source as it does
  today. When a face reference is present, it also makes a focused face-only
  description covering facial features, skin, hair, eyes, makeup, and visible
  expression.
- The main prompt receives the source description followed by a separate
  `Face identity:` paragraph. The optional Face note is included in the
  face-description request as direction.
- No uploaded face image is sent to RunningHub for generation; it is used only
  for the Describe-with-AI request and is not persisted.

## Implementation boundaries

- Extend the existing `/api/describe` endpoint with optional `face_image` and
  `face_note` multipart fields.
- Keep the original endpoint response compatible by returning the completed
  prompt in `prompt`.
- Validate face input as the same safe image types and upload limits as the
  current description image.
- Do not change Local Krea2, Cloud Krea2 helper LoRAs, or the generation job
  payload.

## Verification

- Test source-only description behavior remains compatible.
- Test the face prompt is concise and face-focused, and is appended under the
  exact `Face identity:` heading.
- Test unsupported or oversized optional face images return a clear error.
