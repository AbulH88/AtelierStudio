# Separate Local and Cloud Studios with MiniMax H3 Ref2V

## Goal

Separate local and cloud creation into independent, scalable workspaces while
preserving Atelier Studio's existing visual language. Cloud Studio becomes a
multi-workflow environment containing the existing Scail 2 workflow and a new
MiniMax H3 Ref2V workflow.

## Navigation and workspace structure

- Replace the top-level `Create` and single-purpose `Cloud` destinations with
  adjacent `Local Studio` and `Cloud Studio` navigation items.
- Local Studio retains the current local workflow sidebar, controls, and
  generation behavior.
- Cloud Studio uses the approved dark editorial mockup: a cloud-workflow sidebar
  on the left, workflow content in the center, and a persistent Cloud Queue on
  the right.
- Shared destinations—Gallery, Reels, Enhance, Notes, and Admin—remain
  unchanged.

## Cloud Studio shell

### Left sidebar

- Display `CLOUD WORKFLOWS` and the live RunningHub connection state.
- Use collapsible Image, Video, and Utilities groups with the approved line
  icons, dividers, spacing, Cloud badges, and gold selected-row treatment.
- Video initially contains `Scail 2 Motion` and `MiniMax H3 Ref2V`.
- Utilities contains `Cloud Jobs`. The structure supports future workflows
  without adding new top-level navigation.

### Right sidebar

- Match the approved Cloud Queue design: current job with progress, recent jobs
  with status and media metadata, per-job overflow actions, and Cloud Usage.
- Queue entries aggregate jobs from every cloud workflow and identify the
  originating workflow.
- Usage and cost values must come from available RunningHub responses. Unknown
  values display `Unavailable`; the UI must not invent credits or cost.

### Shared bottom controls

- Use the approved compact control row and full-width gold generation button.
- Each workflow supplies its own applicable settings; H3 initially exposes
  aspect ratio, duration, quality, and instance type.
- Estimated cost is shown only when calculable from real account or task data.

## MiniMax H3 Ref2V workflow

### Modes

1. `Image to Video`: exactly one required image; additional reference types are
   not shown unless the user switches to Omni Reference.
2. `Omni Reference`: at least one image is required. Users may add optional
   images, reference videos, and audio in any supported combination.
3. `First & Last Frame`: exactly two required images. The first is bound as
   `Image1` and the last as `Image2`; the prompt contract explicitly declares
   their boundary-frame roles.

### Reference limits and behavior

- Images: maximum 9.
- Reference videos: maximum 3; each 2–15 seconds, 15 seconds total.
- Audio: maximum 3; each 2–15 seconds, 15 seconds total.
- Mixed media: maximum 12 uploaded files total.
- At least one image is mandatory in this product interface.
- Empty optional slots are omitted from uploads, `nodeInfoList`, and prompt
  reference numbering.
- Audio may accompany one image, multiple images, or image/video combinations.
  Each audio reference can be assigned to a specific image/video subject or a
  global role such as dialogue, singing voice, music, ambience, or effects.
- Reference tokens are deterministic and follow filled upload order:
  `Image1`…`Image9`, `Video1`…`Video3`, and `Audio1`…`Audio3`.

### Reference editor

- The References step uses Images, Videos, and Audio tabs and renders only
  filled cards plus one `Add reference` card, avoiding a wall of empty slots.
- Every card shows preview, file name, assigned role, replace, and remove.
- The UI validates format, file size, duration, per-type limits, combined limit,
  and required mode inputs before submission.
- Prompt & Settings follows References, followed by Generate, matching the
  approved three-step visual treatment.

## RunningHub integration

- Published workflow ID: `2100168430615019522`.
- Upload local media through RunningHub's binary media upload endpoint and pass
  returned `fileName` values as node overrides.
- Build `nodeInfoList` only from the selected mode, filled reference slots,
  prompt, duration/frame count, resolution/aspect, seed, and exposed quality
  controls.
- Submit through `/openapi/v2/run/workflow/2100168430615019522` and query through
  `/openapi/v2/query`.
- Import successful MP4 results into Gallery/R2 immediately because RunningHub
  result URLs expire after 24 hours.
- Preserve the existing encrypted per-user RunningHub API-key storage.

## Errors and recovery

- Upload and submission failures identify the affected reference or workflow
  stage without discarding the user's other selections.
- Queue state persists through page navigation and server restarts using the
  existing cloud-job persistence pattern.
- Failed jobs retain their error details and offer retry after inputs are fixed.
- A failure in one cloud workflow does not block other workflows or Local
  Studio.

## Verification

- Test navigation isolation between Local Studio and Cloud Studio.
- Test cloud workflow selection and queue aggregation.
- Test all H3 modes, mandatory-image behavior, optional blank omission,
  deterministic numbering, per-type limits, total limit, audio assignments,
  and First/Last Frame binding.
- Test RunningHub payload mappings, result polling, MP4 import, restart resume,
  and failure presentation.
- Verify responsive behavior for left sidebar, central editor, and right queue.
