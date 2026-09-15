# Atelier Studio Local Video Enhance Design

## Goal

Add a separate **Enhance** page to Atelier Studio that matches the approved black-and-gold mockup and performs video post-processing on the owner's Windows RTX 5090 through the existing Home Agent. The feature must not consume RunningHub coins and must not require ComfyUI.

Approved visual reference:

`C:\Users\jimi\.codex\generated_images\01a02e1c-bb2c-7a30-907e-7530f5222495\exec-ec36006e-3410-4a5e-8462-5fdcc3d7ce1a.png`

## Scope

The first release supports:

- A dedicated top-navigation item named **Enhance**.
- Input from a local upload, Atelier Gallery, or Reel Library.
- Optional standalone RIFE frame interpolation.
- Optional DLSS enhancement or NVIDIA RTX Video Super Resolution.
- Local NVENC MP4 export with source audio preserved.
- Progress, cancellation, result preview, download, and optional save to Gallery.
- Clear local-GPU online/offline state.

Color-match controls are not included in the first release. They require a second reference image and are not needed for normal post-processing. The copied enhancer may retain its internal color utilities, but Atelier will not expose them until a later approved feature.

## Visual Design

The implementation must follow the approved mockup closely rather than merely borrowing its colors.

### Header

- Preserve the Atelier Studio logo and existing global header.
- Navigation order: **Create, Gallery, Reels, Enhance, Notes, Admin**.
- The active Enhance item uses the existing thin champagne underline.

### Three-column page

1. **Video Source** rail
   - Source tabs: Upload, Gallery, Reels.
   - Portrait preview, filename, resolution, FPS, and duration.
   - Replace Video action.
2. **Main workspace**
   - Eyebrow: `LOCAL GPU ENHANCEMENT`.
   - Heading: `Finish your film locally.`
   - Three pipeline cards: Frame Interpolation, AI Upscale, Export.
   - Before/after split preview with playback controls.
   - Footer status: local estimate, no RH coins, detected GPU, privacy, destination.
3. **Enhance Settings** rail
   - `Local RTX 5090 · Online` or `Local GPU · Offline`.
   - Frame Interpolation toggle.
   - Engine selector: RIFE or DLSSG.
   - RIFE model selector when RIFE is selected.
   - Output FPS selector.
   - Collapsible advanced interpolation controls.
   - AI Upscale toggle.
   - Upscaler selector: DLSS or RTX VSR.
   - Scale/target resolution and quality controls.
   - Read-only processing order.
   - Primary `Enhance Locally` button.

The settings rail follows the existing Studio resizable/collapsible behavior. Controls that do not apply to the selected engine are hidden, not disabled clutter.

## Processing Options

### RIFE

RIFE runs as a standalone process without ComfyUI. The model selector discovers compatible weights from the configured local RIFE model directory instead of using a static list. Expected initial models include:

- `rife47.pth`
- `rife49.pth` (default)
- `rife417.pth`
- `rife426.pth`
- Experimental weights, clearly labeled as experimental

The default is RIFE 4.9 because it is already proven in the existing SCAIL workflow. The user may choose 2x interpolation or an exact supported output rate such as 48 or 60 FPS. Audio duration and synchronization must be preserved.

### DLSSG

DLSSG uses the copied Visual Enhancer runtime and is an alternative interpolation engine. It is not presented as RIFE. Availability is determined at runtime from the detected GPU, driver, HAGS state, and bundled bridge/runtime.

### DLSS and RTX VSR

The upscaler selector offers exactly one active engine at a time:

- **DLSS** uses the tested Visual Enhancer neural-rendering pipeline.
- **RTX VSR** uses its NVIDIA RTX Video SDK path.

The UI supports Off, 2x, and valid target resolutions. It displays the calculated output dimensions before processing. Quality defaults to High; Ultra remains available.

### Processing order

The initial fixed order is:

`RIFE or DLSSG -> DLSS or RTX VSR -> NVENC export`

Interpolation runs before upscaling to minimize GPU time and memory use. The order is shown in the UI but is not user-reorderable in the first release.

## Architecture

### Studio web application

The VPS-hosted Flask app owns authentication, page rendering, source selection, job records, and result storage. It never performs GPU enhancement itself.

New server endpoints provide:

- Local enhancer capabilities/status.
- Job submission.
- Job status/progress.
- Cancellation.
- Result retrieval and save-to-Gallery.

The browser never receives `AGENT_SECRET`, direct Home Agent URLs, or unrestricted filesystem paths.

### Home Agent

The existing authenticated Home Agent receives a source video, validates options, creates a local job, and runs the selected processors. It exposes bounded status, progress, cancellation, and result-download endpoints to the VPS.

Only one enhancement job runs at a time in the first release to avoid GPU contention with ComfyUI. If ComfyUI is generating, Enhance reports the GPU as busy and queues or rejects the new job with a clear message.

### Vendored runtime

The MIT-licensed source from `C:\Users\jimi\Desktop\DLSS.5.Visual.Enhancer.v9.0` is copied into an isolated Home Agent video-enhancer package. The original copyright and MIT license remain intact.

Large/proprietary NVIDIA runtime binaries are not committed blindly to Git. The Home Agent installer copies the tested local runtime into a configured runtime directory and validates its hashes and required DLLs. NVIDIA license files remain beside the copied binaries. Paths are configurable through environment variables, with safe defaults under the Home Agent installation.

Standalone RIFE code and model weights are isolated from the DLSS runtime. Their licenses are retained, and model discovery is filesystem-based.

## Data Flow

1. User chooses an upload, Gallery video, Reel, or completed RunningHub result.
2. VPS validates authentication, media type, size, and requested options.
3. VPS transfers the source to the authenticated Home Agent using a private server-to-agent request.
4. Home Agent probes the source and reports dimensions, frame rate, duration, codec, and audio.
5. Home Agent runs optional interpolation, optional upscale, and final NVENC encoding.
6. Browser polls the VPS for normalized progress; it never polls the agent directly.
7. On success, VPS retrieves the result and stores it temporarily or in the selected Gallery folder.
8. Temporary local and VPS files are removed after a bounded retention period.

## Job States and Error Handling

Normalized states are `queued`, `probing`, `interpolating`, `upscaling`, `encoding`, `uploading`, `done`, `failed`, and `cancelled`.

- Offline agent: disable submission and show `Local GPU offline`.
- Unsupported engine: explain which GPU/runtime requirement failed.
- Missing RIFE model: refresh discovery and ask the user to choose an available model.
- GPU busy or out of memory: preserve the source and permit retry with lower quality.
- Processor failure: keep the prior completed stage temporarily so a retry can resume from it when safe.
- Cancellation: terminate only the owned subprocess tree, mark the job cancelled, and clean partial outputs.
- Agent disconnect: retain the server-side job record and reconcile when the agent returns.

Raw tracebacks, local paths, secrets, and command lines are not returned to ordinary users.

## Security and Privacy

- All Home Agent endpoints require the existing agent secret.
- Source and result filenames are generated server-side; user paths are never executed.
- Processor options use allowlists rather than arbitrary command-line arguments.
- Upload size, duration, pixel count, and concurrency are bounded.
- Videos remain on the owner's PC during enhancement except for the necessary authenticated transfer from/to Atelier storage.
- No RunningHub API key, task identifier, or RH temporary result URL is involved in local enhancement.

## Testing

Automated tests cover:

- Capability and model discovery.
- Option validation and output-size calculation.
- Authentication on every agent endpoint.
- Submission, progress normalization, cancellation, and cleanup.
- Busy-GPU behavior.
- Source audio preservation and output duration tolerance.
- RIFE 2x FPS behavior using a short fixture.
- DLSS and RTX VSR adapter invocation with mocked native runtimes.
- Gallery/Reel/upload source routing.
- UI visibility, conditional controls, offline state, and result rendering.

Manual acceptance testing uses one nine-second 720x1280, 24 FPS source and verifies:

- RIFE 4.9 produces 48 FPS at the same duration.
- DLSS and RTX VSR each produce the displayed target resolution.
- Combined RIFE plus upscale preserves audio synchronization.
- Cancel stops work and frees the GPU.
- The finished result previews, downloads, and saves to Gallery.

## Out of Scope

- Cloud enhancement while the owner's PC is offline.
- Simultaneous enhancement jobs.
- User-defined processing order.
- Color matching and reference-image color transfer.
- Arbitrary third-party executable invocation.
