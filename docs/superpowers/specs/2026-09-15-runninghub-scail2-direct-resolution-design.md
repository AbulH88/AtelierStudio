# RunningHub SCAIL 2 direct-resolution workflow

## Goal

Create an upload-ready copy of `C:\Users\jimi\Videos\Scail RunningHUB.json`
that generates at a direct portrait resolution of 720 × 1280 before RTX
upscaling. Preserve the user's working RunningHub model locations, API node,
LoRAs, output nodes, and all unrelated workflow settings.

## Graph change

Keep the source file untouched and produce a separate JSON. Replace the active
reference-image `0.9 MP → multiple of 32` path with a standard ComfyUI
`ImageScale` node configured for 720 × 1280 and crop mode. Route that exact
image to `GetImageSize`, SAM3 reference tracking, CLIP Vision, and the SCAIL
reference input. Continue routing `GetImageSize` width and height to both the
driving-video loader and `WanSCAILInfinity`, ensuring all inputs share one size.

The old resize nodes may remain disconnected for visual reference, but they
must not influence execution.

## Compatibility

`ImageScale` is a core ComfyUI node, avoiding a new RunningHub custom-node
dependency. The requested width 720 is not divisible by 32. This copy
intentionally tests whether RunningHub's installed SCAIL pipeline accepts the
nominal dimensions. If execution rejects the shape, the fallback will be a
second isolated copy using 704 × 1280.

## Output and verification

Save the result beside the source with a distinct name indicating direct 720p.
Validate JSON parsing, node IDs, links, and the complete direct-resolution data
flow. Do not deploy or connect the Studio API during this step; API integration
begins only after the workflow runs successfully on RunningHub.
