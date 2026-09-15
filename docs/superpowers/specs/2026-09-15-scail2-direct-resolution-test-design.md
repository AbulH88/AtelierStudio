# SCAIL 2 direct-resolution test workflow

## Goal

Create a separate Studio test workflow that sends fixed, model-safe portrait
dimensions directly through SCAIL 2, rather than calculating a megapixel target
from the driving video's aspect ratio. The current SCAIL 2 V2 workflow remains
unchanged during the test.

## Test UI

Add `High Quality Motion Control Scail 2 · Direct Resolution Test` under Video.
It provides a `Generation resolution · before RTX` selector with these exact
portrait sizes:

- 480p: 480 × 864
- 720p: 704 × 1280, default
- 1080p: 1088 × 1920

704 and 1088 are used instead of nominal 720 and 1080 because the SCAIL pipeline
requires dimensions divisible by 32. RTX remains an independent later toggle.

## Workflow data flow

The test graph is a copy of the working V2 graph. Two fixed integer controls
receive the preset width and height from the server. The existing crop node uses
those integers to crop and resize the reference image to the exact target. Its
output supplies CLIP Vision, SAM3 reference tracking, and SCAIL reference input.
GetImageSize then passes the same exact dimensions to the SCAIL sampler and the
driving-video loader. The former 0.9 MP resize nodes remain idle in the test copy
and no longer influence the selected size.

## Safety and verification

The test mode has its own workflow file and server route. V1 and V2 stay
unchanged. Tests verify every preset maps to the fixed width/height controls,
that crop/SCAIL/video inputs use the direct chain, and that the original V2
continues to use its existing megapixel chain. Run the complete test suite and
JavaScript syntax validation before deployment.
