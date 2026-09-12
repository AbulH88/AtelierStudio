# SCAIL 2 generation-resolution selector

## Goal

Give both SCAIL 2 Motion Control workflows a simple base-generation resolution
selector before their optional RTX Super Resolution stage. The default is 720p.

## UI

The shared Motion pane will show a `Generation resolution · before RTX` select
only when High Quality Motion Control Scail 2 V1 or V2 is active. Choices are
480p, 720p (default), and 1080p. The existing RTX Upscale toggle remains a
separate post-generation choice.

## Workflow mapping

SCAIL 2 already sizes the reference image before sampling:

1. Node `102` (`ResizeImageMaskNode`) uses `scale total pixels`.
2. Node `103` rounds the result to a multiple of 32.
3. Node `104` supplies that size to `WanSCAILInfinity` node `132`.

The server will map the selected preset to Node `102`'s
`resize_type.megapixels`: 480p = 0.4 MP, 720p = 0.9 MP, 1080p = 2.1 MP.
Node `103`, the SCAIL sampler, and the optional RTX/RIFE tail are unchanged.
The source aspect ratio is therefore preserved and the final dimensions remain
safe for the workflow.

## Data flow and safeguards

The browser sends `generation_resolution` with the existing SCAIL motion
payload. The server accepts only `480p`, `720p`, or `1080p`; missing or invalid
values fall back to `720p`. The mapping applies to both V1 and V2 workflow
graphs. Existing saved/browser submissions without the new field continue to
generate at the present 720p-equivalent 0.9 MP setting.

## Verification

Unit tests will verify the default, all three preset mappings, invalid fallback,
and unchanged optional-upscale behavior for both SCAIL versions. The full test
suite and JavaScript syntax check will run before deployment.
