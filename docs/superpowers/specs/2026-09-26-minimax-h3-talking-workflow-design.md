# MiniMax H3 Optimized for Talking Design

## Goal

Add a separate RunningHub cloud-video workflow named **MiniMax H3 · Optimized for Talking**. It creates portrait talking videos from one image and an AI-structured MiniMax H3 prompt, while keeping the existing MiniMax H3 Ref2V workflow unchanged.

## RunningHub Workflow

- Published workflow ID: `2103082156684087297`.
- Submission endpoint: `/openapi/v2/run/workflow/2103082156684087297`.
- Result endpoint: `/openapi/v2/query`.
- Media upload endpoint: `/openapi/v2/media/upload/binary`.
- The result MP4 must be imported into Atelier Gallery before RunningHub's temporary result URL expires.
- Actual `usage.consumeCoins` and `usage.taskCostTime` remain the sources for RH coin usage and runtime in Cloud Jobs.

Only user-controlled nodes are overridden:

- Node `9`, `image`: uploaded source image.
- Node `14`, `value`: final generated or manually edited H3 prompt.
- Node `20`, `value`: requested duration in seconds.

All model, sampler, latent-upscale, refinement, audio, and export settings remain locked to the published workflow.

## Navigation and Permission

- Add **MiniMax H3 · Optimized for Talking** as a separate item under Cloud Studio → Video.
- Keep **MiniMax H3 Ref2V** unchanged.
- Add a separate workflow permission controlled through the existing administrator Cloud Access interface.
- Jobs use their own workflow key and display label so Queue and Cloud Jobs can distinguish them from H3 Ref2V.

## User Interface

The page exposes only the controls needed for this specialized workflow:

1. **Source image** — one PNG, JPEG, or WebP image.
2. **Custom description** — desired action, expression, gestures, camera behavior, setting, and other visual instructions.
3. **Spoken script** — the exact dialogue to be spoken.
4. **Audio direction** — voice, accent, pace, volume, delivery, ambience, breathing, and sound effects.
5. **Background music** — optional direction or an explicit no-music choice.
6. **Duration** — numeric whole-second input, minimum `5`, maximum `15`, default `10`.
7. **Generate H3 Prompt** — analyzes the source image and user fields, then creates the structured prompt.
8. **Final H3 Prompt** — editable text area containing the generated prompt.
9. **Generate Video** — submits the image, final prompt, and duration to RunningHub.

The Generate Video button remains disabled until an image, valid duration, and non-empty final prompt are present.

## AI Prompt Builder

The server uses the existing administrator-configured vision model and embeds the Atelier `h3-prompt-writing` I2VA rules into its system instruction. A local Codex skill is not invoked at runtime; its validated format and constraints become the app's prompt-building contract.

The builder receives:

- The source image.
- Custom description.
- Spoken script.
- Audio direction.
- Background-music preference.
- Selected duration.

It returns exactly this I2VA structure:

```text
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] ...

overall_soundscape: ...

non_diegetic_music: ...
```

Prompt-builder rules:

- Start from the uploaded image as the actual first frame.
- Preserve identity, clothing, composition, objects, lighting, and spatial relationships unless the user explicitly requests a change.
- Use a stable speaker ID such as `(S1)`.
- Place dialogue inside `<d>[Language] ...</d>`.
- Preserve the spoken script verbatim, including its punctuation and language.
- Never shorten, paraphrase, translate, or invent dialogue.
- Fit action, delivery, and any cut timing inside the selected 5–15 second duration.
- Prefer a continuous stable shot for talking content unless the custom description requests a cut.
- Put ambient and non-verbal sounds in `overall_soundscape`, without repeating dialogue.
- Put audience-only music in `non_diegetic_music`; use `N/A` when no music is requested.

The user can edit the final prompt before submission. Regenerating the prompt replaces the generated text only after a successful AI response.

## Resolution and Media Pipeline

- Orientation is always portrait `9:16`.
- The source is fit to portrait without stretching; crop behavior is previewed in the interface.
- The first sampling stage remains a lower-resolution portrait stage as defined by the workflow.
- Audio and video latents are separated before latent upscaling.
- Only the video latent is upscaled.
- The original audio latent is merged back unchanged.
- The 3D latent upscaler uses target-dimensions mode with `720 × 1280` and alignment `16`.
- A second sampling stage refines the upscaled latent.
- Final video and generated audio are decoded and exported to H.264 MP4 at 24 FPS.
- The delivered video resolution is exactly `720 × 1280`.

## Duration Validation

- The browser input uses `type=number`, `min=5`, `max=15`, and `step=1`.
- The server accepts only integer seconds from 5 through 15 inclusive.
- Invalid, fractional, missing, or out-of-range durations return HTTP 400 and are never submitted to RunningHub.
- Duration is sent to node `20`; the workflow's frame expression converts it to the required H3 frame grid at 24 FPS.
- The prompt builder and video submission use the same validated duration.

## Job Lifecycle

- The new workflow uses the existing persisted RunningHub job queue, credential concurrency controls, cancellation, polling, restart recovery, Gallery import, and usage accounting.
- A user may have no more than one active Talking workflow job at a time.
- Queue and history label jobs **H3 Optimized for Talking**.
- Job records include creator, Atelier ID, RunningHub task ID, status, runtime, and actual RH coins.

## Error Handling

- Reject unsupported or missing image files before upload.
- Prompt-generation failures preserve all user-entered fields and any previous final prompt.
- Submission failures expose RunningHub's safe error message without revealing API credentials.
- A completed RunningHub task with no MP4 result becomes a failed Atelier job with an actionable error.
- Temporary local uploads are removed after submission, cancellation, or failure.

## Testing

Backend tests cover:

- Permission enforcement.
- Image, prompt, and duration validation.
- Exact mappings for nodes `9`, `14`, and `20`.
- Correct workflow ID and standard instance submission.
- Prompt-builder I2VA structure and script-preservation instruction.
- Independent active-job gating.
- Gallery MP4 import and usage persistence.

UI tests cover:

- New navigation item and independent permission entry.
- Image upload and portrait preview.
- Custom description, spoken script, audio, and music fields.
- Integer duration limits from 5 through 15.
- Generate Prompt and editable final-prompt states.
- Generate Video validation and submission route.
- Correct Queue and Cloud Jobs labels.

## Out of Scope

- Additional image, video, or audio references.
- Landscape or square output.
- User-selectable resolution, FPS, latent-upscale settings, model, LoRAs, sampler, or export codec.
- Replacing or altering the existing MiniMax H3 Ref2V workflow.
