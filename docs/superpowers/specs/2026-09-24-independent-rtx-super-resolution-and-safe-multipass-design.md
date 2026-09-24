# Independent RTX Super Resolution and Safe Multipass Design

## Purpose

Extend Atelier Studio's existing local Enhance page so video resolution upscaling is an independent, optional final stage. Keep DLSS5 Neural Rendering optional, preserve the user's ability to select the neural pass count, and make multipass use safer by default without claiming parity with a game engine.

The feature is for prerecorded video processed by the Windows Home Agent. Images continue to use the existing DLSS5-only path because the installed RTX VSR runtime is video-only.

## User experience

### Frame interpolation

The existing Frame interpolation section remains optional. Its default changes to off. The user can still enable RIFE or DLSSG and choose the existing engine settings.

### DLSS5 Neural Rendering

The existing Media enhancement section becomes the DLSS5 stage rather than an engine chooser.

- Its checkbox remains the master on/off control for DLSS5.
- Neural passes remain selectable from 1 through 4.
- One pass becomes the default.
- Two, three, and four passes are labelled Experimental because more passes strengthen reconstruction and can make some footage worse.
- Existing style, intensity, resolution, tone, structure, skin, mask, colour, preservation, and feather controls remain available.
- When more than one pass is selected, a `Multipass protection` checkbox appears and defaults to on.
- Multipass protection can be turned off so advanced users can request the runtime's raw multipass behavior.

The installed native runtime exposes one shared setting set for the whole cascade, not independent settings for each pass. Multipass protection therefore applies conservative effective limits to the native cascade rather than pretending to provide the per-pass controls available in some game mods:

| Passes | Maximum effective intensity | Maximum effective structure | Minimum face/skin protection |
| --- | ---: | ---: | ---: |
| 1 | User value | User value | User value |
| 2 | 0.70 | 1.00 | 0.35 |
| 3 | 0.55 | 0.90 | 0.50 |
| 4 | 0.45 | 0.80 | 0.60 |

The interface shows the effective protected values before the job starts. Turning protection off sends the user's raw settings unchanged. No attached or downloaded RenoDX/ReShade binary is loaded by Atelier.

### RTX Super Resolution

A new video-only section appears below DLSS5:

- Independent checkbox labelled `RTX Super Resolution`.
- Off by default.
- Output scale choices: 1.5x, 2x, 3x, and 4x.
- Quality choices: 1 Low, 2 Medium, 3 High, and 4 Ultra.
- Default scale is 2x and default quality is 3 High.
- When the source dimensions are known, the selected option shows the expected output dimensions, for example `2x - 1440 x 2560` for a 720 x 1280 source.
- Helper copy states `Runs last - videos only`.

RTX Super Resolution may run by itself, after DLSS5, or after interpolation plus DLSS5. Turning it off preserves the current output resolution.

### Pipeline summary

The existing pipeline summary reflects only enabled stages, in execution order:

`Optional RIFE/DLSSG -> Optional DLSS5 -> Optional RTX Super Resolution -> EXPORT`

The Enhance button is enabled when at least one processing stage is active and a supported media file is selected.

## Architecture and data flow

### Browser request

Replace the mutually exclusive `upscaler` choice with two explicit booleans and retain the existing settings:

- `dlss_enabled`
- `rtx_vsr_enabled`
- `multipass_protection`
- `nr_passes`
- `scale`
- `quality`

The web server forwards these allowlisted fields to the authenticated Home Agent. During a compatibility window, the Home Agent accepts the previous `upscaler` field and maps `dlss` or `rtx_vsr` to the corresponding single enabled stage.

### Home Agent validation

Validation enforces the following:

- At least one of interpolation, DLSS5, or RTX Super Resolution must be enabled.
- RTX Super Resolution is rejected for images.
- Images still require DLSS5.
- Scale and quality remain allowlisted.
- Neural pass and advanced setting ranges remain allowlisted.
- Protected effective values are calculated server-side as well as displayed client-side, so a crafted browser request cannot bypass the selected protection mode.

### Runner execution

The isolated enhancement runner executes enabled stages in this order:

1. RIFE or DLSSG, when enabled.
2. DLSS5 Neural Rendering, when enabled.
3. RTX VSR, when enabled.
4. Return the final file.

The runner continues to verify native Feature-18 evidence for every requested DLSS5 pass. RTX VSR uses the installed native video upscaler. Intermediate outputs remain inside the job directory and only the final result is returned to the Studio.

The current runtime encodes between native video stages. This design does not claim a lossless, game-engine framebuffer path. A future native worker may remove intermediate encodes, but that is not required for this change.

## Progress and errors

Progress is apportioned across the number of enabled stages rather than assuming two stages. Status text names the active stage.

Failures are stage-specific:

- Interpolation errors identify RIFE or DLSSG.
- Feature-18 evidence failures identify DLSS5.
- RTX VSR failures identify Super Resolution.

Cancellation stops the active child process and retains the existing cleanup behavior. A failed later stage does not silently return an earlier intermediate as a successful final output.

## Compatibility and safety

- Existing single-stage jobs remain supported through legacy option mapping.
- The attached unsigned `renodx-dlss.addon64` is not executed, copied, or bundled.
- Atelier does not claim exact RenoDX/OptiScaler game-mod parity because prerecorded video lacks genuine game motion vectors, depth, exposure, and uncompressed render buffers.
- Raw 2-4 pass mode remains available only because the user explicitly requested that controls and off switches not be removed.

## Testing

Automated tests cover:

- Validation for DLSS5 only, RTX VSR only, and both stages.
- Rejection of RTX VSR for images.
- Legacy `upscaler` mapping.
- Protected effective values for 1-4 passes and raw-mode bypass.
- Runner ordering for interpolation, DLSS5, and RTX VSR.
- Feature-18 pass evidence checks.
- Three-stage progress calculation.
- UI visibility for video versus image.
- UI pipeline summaries and expected output-dimension labels.
- Default states: interpolation off, DLSS5 on with one pass, RTX Super Resolution off, protection on when applicable.

A local smoke test uses a short video on the RTX 5090 and verifies:

- DLSS5 one-pass output at source resolution.
- RTX VSR-only 2x output dimensions.
- DLSS5 followed by RTX VSR 2x output dimensions.
- Protected two-pass DLSS5 completes with verified native pass evidence.

## Out of scope

- Loading RenoDX, ReShade, or OptiScaler game add-ons inside Atelier.
- Claiming exact game-mod results.
- Per-pass native DLSS5 settings, separate pass histories, or pass-specific edge masks; the installed native runtime API does not expose them.
- RTX VSR for still images.
- Replacing RIFE or DLSSG.
