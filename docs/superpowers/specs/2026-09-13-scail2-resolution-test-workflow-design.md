# SCAIL 2 resolution test workflow

## Goal

Add an isolated Studio test option for base generation resolution before RTX
upscaling, without changing the existing SCAIL 2 V1 or V2 workflows.

## Test workflow

Create a separate copy of the shipped V2 graph named `workflow_scail2motiontest.json`.
Expose it under Video as `High Quality Motion Control Scail 2 · Resolution Test`.
It uses V2's same model, tracking, character-LoRA, raw-output, and optional
RTX/RIFE chain.

## Resolution behavior

The test UI adds a pre-RTX generation-resolution picker:

- 480p: node 102 `resize_type.megapixels` = 0.4
- 720p: node 102 `resize_type.megapixels` = 0.9 (default)
- 1080p: node 102 `resize_type.megapixels` = 2.1

Node 103 retains its existing multiple-of-32 safety rounding. Node 104 then
passes the derived dimensions into WanSCAILInfinity. The existing RTX toggle
continues to control only the later RTX/RIFE output tail.

## Wan-style reference crop

Before node 102, the test graph will use the same built-in nodes and behavior
as the existing Wan Video workflow: `VHS_VideoInfo` reads the driving video's
width and height, and `ImageResizeKJv2` crops the uploaded reference photo to
that aspect ratio with `keep_proportion: crop`, `crop_position: top`, Lanczos
resampling, and CPU processing. Node 102 then applies the selected base
megapixel setting to that cropped image. The resized dimensions continue to
drive the SCAIL sampler and the resampled driving video as they do today.

## Isolation and replacement

The test mode has its own workflow identifier and routes only to the copied
graph. V1 and V2 retain their current files and behavior. After the user has
tested it successfully, V2 can be switched to this implementation and the test
entry removed in a follow-up change.

## Verification

Tests will verify mode routing, all preset mappings, default/invalid fallback,
and unchanged V1/V2 behavior. The complete test suite, JavaScript syntax check,
and deployment will run before handoff.
