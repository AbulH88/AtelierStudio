# DLSS5 Multipass Media Enhance Implementation Plan

## Objective

Implement the approved design in
`docs/superpowers/specs/2026-09-24-dlss5-multipass-media-enhance-design.md`.
Extend the existing Enhance page to accept one image or video, expose genuine
Visual Enhancer v9 DLSS5 multipass controls, and preserve the existing optional
`RIFE -> DLSS5` video order.

## Constraints

- Reuse the installed Visual Enhancer v9 APIs; do not build a new NGX host.
- Use native `nr_passes` support; do not loop file encodes to simulate passes.
- Keep DLSSG and RTX VSR working unchanged.
- Keep native NVIDIA modules inside the isolated runner subprocess.
- Accept only allowlisted media formats and option values.
- Run one local enhancement job at a time.
- Do not commit proprietary runtime binaries or model weights.

## Phase 1: Lock Request Validation With Tests

### Files

- Modify `runpod-comfyui/tests/test_enhance_service.py`.
- Modify `runpod-comfyui/home_agent/enhance_service.py`.

### Work

1. Add failing tests for every DLSS5 request field and boundary:
   `nr_passes`, `nr_style`, `nr_intensity`, tone, structure, skin structure,
   automatic mask, color strength, tone preservation, face/skin protection,
   grain preservation, mask feather, and DLSS scale.
2. Add media extension classification tests for image and video formats.
3. Test that image jobs reject RIFE and DLSSG interpolation settings.
4. Test that DLSS5 alone is valid for images and videos.
5. Split the existing single video-extension allowlist into image and video
   allowlists and derive `media_kind` from the uploaded filename.
6. Return a normalized options dictionary containing explicit defaults. Never
   pass raw browser dictionaries into the runner.
7. Keep RTX VSR's existing scale and quality validation separate from DLSS5's
   output-scale validation.

### Verification

Run:

```powershell
pytest runpod-comfyui/tests/test_enhance_service.py -q
```

## Phase 2: Add Genuine DLSS5 Image and Video Adapters

### Files

- Modify `runpod-comfyui/home_agent/enhance_runner.py`.
- Add `runpod-comfyui/tests/test_enhance_runner.py`.

### Work

1. Refactor the current `run_dlss` into a focused video adapter that constructs
   Visual Enhancer v9 `ConversionOptions` from normalized CLI arguments.
2. Pass `nr_passes` directly to the runtime together with every approved neural
   option and the selected `upscaling_factor`.
3. Add an image adapter using
   `src.neural_rendering.image.models.ImageConversionOptions` and
   `src.neural_rendering.image.batch.convert_images`.
4. Default single-image output to PNG at quality 95 with metadata preservation.
5. Require exactly one successful result for the single uploaded image/video;
   surface the runtime failure detail when no output succeeds.
6. Inspect the returned runtime result/report fields available in v9 and reject
   results without feature-18 evidence. Keep this check in a small helper that
   can be unit tested without loading native DLLs.
7. Extend runner arguments with `--media-kind` and explicit allowlisted DLSS5
   settings. Retain the current RIFE, DLSSG, and RTX VSR arguments.
8. Route image jobs directly to DLSS5 and reject impossible interpolation
   combinations defensively in the runner as well as the service.
9. Preserve video order: interpolation first, DLSS5 second. Do not introduce an
   encode between individual DLSS5 passes.
10. Emit structured progress messages for interpolation, DLSS5 preparation,
    neural rendering, final writing/encoding, and completion.

### Tests

- Mock the Visual Enhancer import boundary and assert all neural fields reach the
  image and video option objects unchanged.
- Assert pass values 1, 2, 3, and 4 are not expanded into repeated adapter calls.
- Assert image and video success paths return the runtime-produced path.
- Assert missing output and missing feature-18 evidence fail.
- Assert RIFE executes before the DLSS5 video adapter.
- Assert DLSS5-alone video skips RIFE.

### Verification

Run:

```powershell
pytest runpod-comfyui/tests/test_enhance_runner.py -q
```

## Phase 3: Generalize Home Agent Uploads and Results

### Files

- Modify `runpod-comfyui/home_agent/enhance_service.py`.
- Modify `runpod-comfyui/home_agent/agent.py`.
- Modify `runpod-comfyui/tests/test_enhance_service.py`.
- Add or extend Home Agent route tests if an existing route-test module covers
  `agent.py`.

### Work

1. Change the multipart field from `video` to `media` at the Home Agent boundary.
2. Save validated uploads using a server-generated `source` filename with the
   allowlisted original suffix.
3. Add `media_kind` and normalized neural settings to the owned job record and
   isolated runner command.
4. Keep the result containment check: the published result must be a regular
   file directly inside the job directory.
5. Derive response MIME type and download name from the actual result suffix
   instead of always returning `video/mp4`.
6. Preserve the single-job lock and release it on success, cancellation, runner
   failure, and native crash.
7. Ensure cancellation kills only the active runner subprocess tree and removes
   unpublished partial files.

### Verification

Run the focused service and agent tests, then verify an image result is returned
with an image MIME type and a video result remains inline-playable.

## Phase 4: Generalize the Studio Proxy

### Files

- Modify `runpod-comfyui/webapp/app.py`.
- Modify `runpod-comfyui/tests/test_enhance_proxy_api.py`.

### Work

1. Accept the multipart field `media`, validate that a file was supplied, and
   forward its filename and MIME type to the Home Agent.
2. Keep existing per-session job ownership and opaque 404 behavior for another
   user's job.
3. Stream the result using the upstream content type and content-disposition
   filename rather than forcing MP4.
4. Add proxy tests for image submission, video submission, missing media,
   upstream validation errors, result MIME forwarding, and ownership checks.

### Verification

Run:

```powershell
pytest runpod-comfyui/tests/test_enhance_proxy_api.py -q
```

## Phase 5: Implement the Existing-Page UI Extension

### Files

- Modify `runpod-comfyui/webapp/index.html`.
- Extend the repository's existing UI/HTML tests if present; otherwise add
  `runpod-comfyui/tests/test_enhance_ui.py` for static contract assertions.

### Work

1. Change the source input to accept the approved image and video MIME types.
2. Rename video-only variables and messages to media terminology where needed
   without changing unrelated Gallery/Reels flows.
3. Add an image before/after preview alongside the existing video elements and
   switch visibility based on detected media kind.
4. Hide the entire interpolation section for images. Restore the user's video
   interpolation selection when a video is selected again.
5. Rename the dropdown option to `DLSS5 · Neural Rendering`.
6. Add the approved primary DLSS5 controls:
   passes, output scale, style, and intensity.
7. Add a collapsed `Advanced DLSS5` section containing the approved advanced
   controls and defaults.
8. Show DLSS5 controls only when DLSS5 is selected; preserve existing RTX VSR
   scale and quality controls when RTX VSR is selected.
9. Render the dynamic pipeline summary using effective values, such as
   `RIFE 2x -> DLSS5 x2 -> EXPORT`.
10. Change the action label between `Enhance Image` and `Enhance Video`.
11. Submit one normalized `media` upload plus options. Do not send local paths.
12. Preview completed images with an `<img>` and videos with a `<video>` using
    the existing owned result endpoint.
13. Preserve the approved black-and-champagne styling shown in the accepted
    mockup; do not redesign other pages.

### Tests

- Assert all DLSS5 controls and defaults exist.
- Assert the advanced section is collapsed initially.
- Assert image selection hides interpolation and changes the action label.
- Assert engine switching hides irrelevant controls.
- Assert the submitted option names match the Home Agent request model.

### Verification

Run any existing JavaScript syntax validation, then exercise the page in a
browser at desktop and narrow widths to ensure the settings rail still scrolls
and collapses correctly.

## Phase 6: Progress, Diagnostics, and Cleanup

### Files

- Modify `runpod-comfyui/home_agent/enhance_service.py`.
- Modify `runpod-comfyui/home_agent/enhance_runner.py`.
- Modify associated focused tests.

### Work

1. Normalize runner progress across one-stage and two-stage jobs without allowing
   progress to move backward.
2. Preserve runtime pass information in user-facing messages when available,
   without parsing fragile prose when structured information exists.
3. Sanitize native failures before returning them through the Studio proxy:
   retain actionable stage and feature-18 information but omit local paths,
   command lines, and tracebacks.
4. Ensure source files, intermediate RIFE/DLSSG outputs, reports, and failed
   partial files follow the existing bounded retention policy.
5. Add tests for cancellation during interpolation and DLSS5, lock release after
   failure, and no final publication after cancellation.

## Phase 7: Regression and Manual RTX Acceptance

### Automated regression

Run the focused enhancement suite first, followed by the full project suite:

```powershell
pytest runpod-comfyui/tests/test_enhance_service.py `
       runpod-comfyui/tests/test_enhance_runner.py `
       runpod-comfyui/tests/test_enhance_proxy_api.py `
       runpod-comfyui/tests/test_enhance_ui.py -q
pytest runpod-comfyui/tests -q
```

If the UI test is merged into an existing module, substitute that module in the
focused command.

### Manual acceptance on the RTX 5090 host

1. Confirm capabilities report RIFE, DLSSG, DLSS5, and RTX VSR accurately.
2. Process one portrait image at one pass and two passes, Source/1x. Confirm the
   runtime report identifies the selected pass count and feature-18 execution.
3. Process one short 24 FPS video with DLSS5 alone at two passes. Confirm one
   final encode, playable output, original duration, and synchronized audio.
4. Process the same video with RIFE 2x followed by DLSS5 at two passes. Confirm
   doubled output FPS, unchanged duration, synchronized audio, and correct stage
   order.
5. Test 75% DLSS5 neural resolution and confirm displayed and actual output
   dimensions agree; test enlargement separately through RTX VSR.
6. Cancel once during RIFE and once during DLSS5. Confirm no partial output is
   published and the next job starts normally.
7. Run one existing DLSSG job and one RTX VSR job to prove no regression.

## Commit Sequence

Keep commits reviewable and avoid staging unrelated working-tree files:

1. `test: define DLSS5 media enhancement validation`
2. `feat: add multipass DLSS5 image and video adapters`
3. `feat: support image enhancement through Home Agent`
4. `feat: proxy image and video enhancement results`
5. `feat: add DLSS5 controls to Enhance page`
6. `test: cover DLSS5 progress cancellation and regressions`

## Rollback

The work remains isolated behind the existing Enhance page and `/api/enhance`
plus `/enhance` endpoints. Rollback restores the previous video-only UI and
single-pass option schema while leaving Create, Gallery, Reels, cloud workflows,
and ComfyUI generation untouched. Runtime binaries are not changed, so rollback
does not require reinstalling Visual Enhancer.
