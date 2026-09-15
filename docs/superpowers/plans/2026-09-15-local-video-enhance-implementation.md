# Local Video Enhance Implementation Plan

## Objective

Implement the approved Atelier Studio Enhance page and local RTX processing path described in `docs/superpowers/specs/2026-09-15-local-video-enhance-design.md`.

## Phase 1: Home Agent enhancement service

1. Add a focused `video_enhancer` package under `runpod-comfyui/home_agent`.
2. Define allowlisted request/result models and normalized job states.
3. Add runtime discovery for the copied DLSS Visual Enhancer installation and standalone RIFE models.
4. Add adapters for RIFE, DLSSG, DLSS, RTX VSR, probing, NVENC export, and audio preservation.
5. Add a single-job manager with progress, cancellation, cleanup, and safe subprocess termination.
6. Add authenticated Home Agent endpoints for capabilities, submit, status, cancel, and result transfer.
7. Add unit tests using mocked native processors; keep GPU acceptance tests opt-in.

## Phase 2: VPS Studio proxy and storage

1. Add authenticated Studio endpoints that proxy capability and job operations without exposing the agent secret.
2. Support upload, Gallery, and Reel sources with strict media validation.
3. Store server-side enhancement job ownership and normalized progress.
4. Retrieve completed output from the Home Agent and optionally persist it to Gallery/R2.
5. Add limits for upload size, duration, pixel count, and one active job.
6. Add tests for authentication, source routing, failures, cancellation, and storage.

## Phase 3: Enhance page

1. Add Enhance to the global navigation in the approved order.
2. Build the exact three-column black-and-gold layout from the approved mockup.
3. Add source tabs, media picker, metadata, and replace behavior.
4. Add conditional interpolation controls for RIFE and DLSSG.
5. Add conditional upscale controls for DLSS and RTX VSR.
6. Add output-dimension calculation and fixed processing-order display.
7. Add GPU status, polling progress, cancellation, error states, preview, download, and Save to Gallery.
8. Preserve responsive behavior and the existing resizable/collapsible rail conventions.

## Phase 4: Runtime packaging

1. Preserve the Visual Enhancer MIT license and bundled NVIDIA license files.
2. Add a local installer/copy script that validates the source runtime and copies it to the configured Home Agent runtime directory.
3. Do not commit large proprietary binaries to Git.
4. Add environment examples for enhancer runtime, RIFE code, model directory, output directory, and limits.
5. Validate capability reporting on the RTX 5090 machine.

## Phase 5: Verification and deployment

1. Run the existing test suite and new focused tests.
2. Run JavaScript syntax validation.
3. Test a nine-second 720x1280 24 FPS fixture with RIFE 4.9 to 48 FPS.
4. Test DLSS and RTX VSR separately, then the combined pipeline.
5. Verify audio synchronization, cancellation, cleanup, Gallery save, and offline behavior.
6. Deploy the VPS changes and update/restart the Windows Home Agent.
7. Perform an end-to-end production smoke test without RunningHub coin usage.

## Rollback

The feature is isolated behind the Enhance navigation and new endpoints. Rollback removes or disables that navigation item and the Home Agent enhancement routes without changing Create workflows, RunningHub integration, Gallery, or Reels.
