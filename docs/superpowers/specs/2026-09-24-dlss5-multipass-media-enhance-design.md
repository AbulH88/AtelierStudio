# Atelier Studio DLSS5 Multipass Media Enhance Design

## Goal

Extend the existing Atelier Studio **Enhance** page so its current DLSS option
becomes a configurable **DLSS5 Neural Rendering** processor for both images and
videos. The processor must use the installed Visual Enhancer v9 feature-18
runtime and its native multipass implementation. It must not simulate multiple
passes by repeatedly encoding an intermediate file.

For video, the existing optional RIFE interpolation stage remains available and
runs before DLSS5. DLSS5 must also work independently when interpolation is off.
Images use DLSS5 without interpolation.

## Existing System

The existing Enhance page and Home Agent already provide:

- Local video upload and preview.
- RIFE or DLSSG frame interpolation.
- DLSS detail refinement or RTX VSR enhancement.
- A fixed interpolation-before-enhancement processing order.
- A single local enhancement job with progress, cancellation, and result
  download.
- An installed Visual Enhancer v9 runtime under the configured
  `ATELIER_ENHANCER_ROOT`.

The current DLSS adapter already calls the Visual Enhancer neural-rendering
video API, but hard-codes `nr_passes=1` and the rest of the neural controls. The
page accepts videos only.

## Product Behavior

### Media sources

The existing source selector accepts one image or video.

- Supported image inputs initially include PNG, JPEG, WebP, AVIF, and TIFF.
- Existing supported video inputs remain MP4, MOV, MKV, and WebM.
- Selecting an image switches the before/after preview to image mode and hides
  all frame-interpolation controls.
- Selecting a video keeps the existing video preview and interpolation controls.
- The primary action changes between **Enhance Image** and **Enhance Video**.

### Processing combinations

The supported flows are:

```text
Image -> DLSS5 x1-4 -> image output

Video -> DLSS5 x1-4 -> final video encode

Video -> RIFE x2/x4 -> DLSS5 x1-4 -> final video encode

Video -> DLSSG -> DLSS5 x1-4 -> final video encode
```

The existing RTX VSR path remains available and mutually exclusive with DLSS5.
The existing DLSSG interpolation option also remains available.

For video, RIFE or DLSSG creates the interpolated intermediate video first.
DLSS5 then decodes that result and performs all requested neural passes inside
the Visual Enhancer runtime. The DLSS5 stage performs one final video encode;
it does not encode once per neural pass. Original audio is remuxed or preserved
with the same duration and synchronization behavior as the existing pipeline.

## Enhance Page Design

The page retains its current black-and-champagne visual language, spacing,
typography, borders, and control proportions.

The existing **Video enhancement** engine option is renamed from the generic
`DLSS` label to:

`DLSS5 · Neural Rendering`

When selected, the following primary controls appear:

- **Neural passes:** integer selection from 1 through 4; default 2.
- **Neural resolution:** Source/100%, 75%, 50%, or 25%; default Source/100%.
  These are the exact scales supported by the installed Visual Enhancer v9
  feature-18 runtime. Enlargement remains available through RTX VSR.
- **Style:** Default, Natural, or Cinematic; default Default.
- **Intensity:** 0.00 through 2.00; default 1.00.

A collapsed **Advanced DLSS5** section contains:

- Local tone strength: 0.00 through 2.00; default 1.00.
- Local structure strength: 0.00 through 2.00; default 1.50.
- Skin structure strength: -1.00 through 2.00; default -1.00.
- Automatic skin mask: off by default.
- Color strength: 0.00 through 1.00; default 1.00.
- Tone preservation: 0.00 through 1.00; default 0.00.
- Face/skin protection: 0.00 through 1.00; default 0.00.
- Grain preservation: 0.00 through 1.00; default 0.00.
- Mask feather: 0 through 128 output pixels; default 0.

The UI displays the effective processing order using the selected values. For
example:

```text
RIFE 2x -> DLSS5 x2 -> EXPORT
```

With interpolation disabled, it displays:

```text
DLSS5 x2 -> EXPORT
```

The two-pass default is intended to reproduce the sequential multipass behavior
used by current game modifications. Offline media does not provide the complete
game-engine geometry, lighting, material, motion, or developer-mask inputs of an
official game integration. The UI must not claim equivalence to official
3D-guided in-game DLSS5.

## Home Agent Architecture

The long-running Home Agent continues to validate jobs and starts an isolated
runner subprocess. Native NVIDIA and Visual Enhancer modules remain outside the
long-running Flask process so a native crash is recoverable and cancellation can
terminate the owned subprocess tree.

### Request model

The allowlisted job request adds:

- `media_kind`: `image` or `video`, derived server-side from the validated file.
- `nr_passes`: integer 1-4.
- `nr_style`: `Default`, `Natural`, or `Cinematic`.
- `nr_intensity`: float 0.00-2.00.
- `local_tone_strength`: float 0.00-2.00.
- `local_structure_strength`: float 0.00-2.00.
- `skin_structure_strength`: float -1.00-2.00.
- `automatic_mask`: boolean.
- `nr_color_strength`: float 0.00-1.00.
- `tone_preservation`: float 0.00-1.00.
- `face_skin_protection`: float 0.00-1.00.
- `grain_preservation`: float 0.00-1.00.
- `mask_feather`: integer 0-128.
- `dlss_scale`: one of 1.0, 0.75, 0.5, or 0.25.

Arbitrary runtime arguments, executable paths, output paths, and model files are
not accepted from the browser.

### Runtime adapters

The video adapter builds the installed runtime's video `ConversionOptions` using
the validated neural settings and calls its batch conversion entry point.

The new image adapter builds `ImageConversionOptions` and calls
`convert_images`. Initial single-image output defaults to PNG, quality 95, and
metadata preservation. Transparency is preserved where the selected output
format and runtime support it.

Both adapters require the runtime result to contain a successful output and a
feature-18 verification report. A result that contains only ordinary upscaling
or lacks neural-rendering evidence is a failed job, not a silent success.

## Data Flow

1. The browser selects an image or video and derives only preview state locally.
2. The Studio server validates authentication, file type, size, and request
   schema, then sends the upload and normalized options to the authenticated
   Home Agent.
3. The Home Agent derives `media_kind`, checks runtime capabilities, reserves the
   single local GPU job slot, and writes the upload to its job directory.
4. For video with interpolation enabled, the isolated runner executes RIFE or
   DLSSG and records the intermediate result.
5. The runner invokes the Visual Enhancer v9 image or video neural-rendering API
   with `nr_passes` and all other validated settings.
6. The runtime evaluates feature 18 sequentially for the requested number of
   passes and writes one final media output.
7. The runner checks success and feature-18 evidence before reporting completion.
8. The Studio server streams the completed result back for preview and download.
9. Existing retention cleanup removes job inputs, intermediate files, reports,
   and partial outputs after the configured retention period.

## Progress and Cancellation

Normalized progress messages distinguish:

- Uploading media.
- Probing video, when applicable.
- Interpolating with RIFE or DLSSG.
- DLSS5 preparation.
- Neural rendering, including current pass when the runtime reports it.
- Encoding or writing the final output.
- Downloading the completed result.
- Complete, failed, or cancelled.

The Studio continues polling normalized job state and never receives local paths,
native command lines, or raw tracebacks.

Cancellation terminates only the runner subprocess tree owned by the job. The
job is marked cancelled and partial outputs are removed. A completed RIFE
intermediate may be retained only for the existing bounded retry/retention
window; it is never exposed as the successful final result of a cancelled job.

## Validation and Failure Handling

- Image interpolation options are ignored by neither layer: they are rejected
  during validation if supplied for an image.
- At least one applicable processing stage must be enabled.
- Unsupported formats, invalid option ranges, excessive dimensions, and unsafe
  filenames fail before native processing begins.
- Only one local enhancement job runs at a time.
- Missing runtime components produce a capability error that identifies DLSS5
  as unavailable without exposing local filesystem details to ordinary users.
- Failure to initialize or evaluate feature 18 produces a DLSS5 failure, not an
  RTX VSR fallback.
- Native crashes and GPU out-of-memory failures preserve the original upload for
  the bounded retry window and release the active-job lock.
- Video outputs must remain within an acceptance tolerance for source duration
  and audio synchronization.
- Image metadata preservation failures may produce a warning while retaining a
  valid rendered image; pixel-rendering or file-publication failures fail the
  job.

## Testing

Automated tests cover:

- Image/video media-kind detection and supported-extension validation.
- Image requests rejecting RIFE and DLSSG interpolation.
- DLSS5 working independently with interpolation off.
- Video stage ordering for RIFE-to-DLSS5 and DLSSG-to-DLSS5.
- Pass counts 1 through 4 reaching the runtime adapter unchanged.
- Every neural option's allowlist and boundary validation.
- Image adapter construction, output publication, metadata behavior, and alpha
  preservation using mocked runtime calls.
- Video adapter construction, one final encode, audio preservation, and duration
  tolerance using mocked runtime calls.
- Missing feature-18 evidence becoming a failed job.
- Progress normalization, cancellation, cleanup, busy-GPU locking, and lock
  release after native failures.
- Conditional UI visibility for image versus video, DLSS5 versus RTX VSR, and
  collapsed advanced controls.
- Dynamic pipeline summary and image/video action labels.

Manual RTX 5090 acceptance uses one representative portrait image and one short
24 FPS video:

1. Render the image with one pass and two passes; confirm two passes have a
   visibly cumulative result and the runtime report records two passes.
2. Render the video with DLSS5 alone at two passes; verify feature-18 evidence,
   duration, playback, and audio synchronization.
3. Render the video with RIFE 2x followed by DLSS5 at two passes; verify doubled
   frame rate, unchanged duration, synchronized audio, and the displayed stage
   order.
4. Cancel during RIFE and during DLSS5; verify the process tree stops, partial
   results are not published, and a new job can start.
5. Verify existing DLSSG and RTX VSR workflows still operate unchanged.

## Security and Licensing

The implementation reuses the already installed Visual Enhancer v9 runtime. It
does not download or replace native binaries as part of a media job. Existing
runtime hash validation, license files, Home Agent authentication, server-side
path generation, and option allowlists remain in force.

The Studio UI describes the feature as unofficial DLSS5 Neural Rendering and
does not claim NVIDIA endorsement or official game-engine equivalence.

## Out of Scope

- Real-time game injection or ReShade installation.
- Access to game-engine geometry, material, lighting, or developer masks.
- User-supplied neural model binaries or arbitrary runtime DLL selection.
- Batch image upload in the first iteration.
- Custom neural masks painted in the Studio UI.
- User-reorderable video stages.
- Simultaneous local GPU enhancement jobs.
