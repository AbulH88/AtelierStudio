# RunningHub Krea2 Image Workflows Design

## Goal

Replace the Cloud Studio Image placeholder with a working **Krea2 Image to Image High Quality** workflow while establishing a reusable pattern for additional RunningHub image workflows. Reuse Atelier's existing Local Studio prompt, image, resolution, and character concepts instead of creating a second incompatible authoring experience.

## Confirmed RunningHub contract

- Workflow ID: `2100309003213901825`
- Instance: RunningHub `default` unless later configured otherwise
- Source image: node `33`, field `image`
- Positive prompt: node `5`, field `text`
- Resize width: node `13`, field `width`
- Resize height: node `13`, field `height`
- Character LoRA: node `46`, class `PixaromaLoraLoader`
- Output: image output returned by the workflow query and imported into Atelier Gallery

The published API-format workflow was read successfully using RunningHub's authenticated `getJsonApiFormat` endpoint. Node 13's width and height are direct values, not links, so Atelier can override them. Node 39 is not part of the executable workflow. Node 46 exposes both `lora_name` and `LoraLoaderState`.

## Cloud Studio experience

The Image group in the left Cloud Studio navigation contains **Krea2 Image to Image HQ** instead of “Future Image Workflow.” Selecting it opens an image workspace consistent with the existing Cloud Studio visual language.

The workspace contains:

1. A source-image drop zone with click-to-upload and drag-and-drop.
2. The same prompt field and image-description flow used by Local Studio Krea2 HQ.
3. The existing grouped Krea2 HQ resolution presets from `RES_PRESETS`.
4. A character card selector sourced from the Cloud LoRA registry.
5. A version selector for the chosen character.
6. A Generate on RunningHub button integrated with the existing queue, cancellation, loading, and duplicate-run behavior.

Only one character LoRA version is active for a generation. Users may choose a character and one of its enabled versions. The character's admin-selected default version is preselected.

## Cloud LoRA registry

Private RunningHub “My Models” and their version lists are not returned by the documented API-key model-list endpoint. Atelier therefore maintains its own server-side registry. This is configuration data, not hardcoded HTML.

Each character record contains:

- Stable ID
- Display name
- Optional preview image
- Enabled/disabled state
- Ordered versions

Each version contains:

- Stable ID
- Display label, such as `V1.0`, `V1.1`, or `V3`
- Exact RunningHub `.safetensors` filename expected by node 46
- Optional preview image
- Enabled/disabled state
- Default marker, unique within the character

The Admin page supports creating, editing, disabling, reordering, and deleting characters and versions. It also validates that filenames end in `.safetensors`, normalizes backslashes to forward slashes, and strips a leading `models/loras/` because the currently published node value is a basename. Subfolders are otherwise preserved if RunningHub's node presents them.

Registry updates take effect immediately without an application deployment. Removing or disabling an entry prevents new submissions but does not alter historical jobs.

## Submission data flow

1. The browser sends the source image, prompt, resolution-preset key, character ID, and version ID to the Atelier backend.
2. The backend resolves width and height from the server-owned `RES_PRESETS`; it never trusts arbitrary client dimensions.
3. The backend resolves the LoRA filename from the server-owned Cloud LoRA registry; it never accepts an arbitrary filename from a regular user.
4. The backend uploads the source image with RunningHub's binary media endpoint.
5. The backend submits workflow `2100309003213901825` with node overrides for nodes 33, 5, 13, and 46.
6. The backend polls through the existing persistent RunningHub queue.
7. On success, it downloads the returned image and saves it beneath `gallery/cloud/`, where existing Gallery behavior applies.

Node 46 receives both fields per job:

- `lora_name`: the selected exact filename
- `LoraLoaderState`: generated JSON containing only the selected character LoRA, enabled with `sm: 1` and `sc: 1`

This avoids depending on stale state baked into the published workflow and keeps LoRA strength fixed at 1.0. The disabled realism LoRAs are not enabled by Atelier.

## Extensible workflow registry

Cloud image workflows are represented by a small backend registry rather than one-off navigation markup. A workflow definition owns:

- Stable workflow key
- Display name and category
- RunningHub workflow ID
- Input capability declaration
- Node mapping
- Result media type
- Enabled/disabled state

The first registered image workflow is Krea2 I2I HQ. Future image workflows can add their own form and node mapping while reusing credentials, upload helpers, queue persistence, cancellation, result import, and Gallery integration.

## Queue and concurrency

The job uses workflow key `krea2_i2i_hq`. Existing per-API-key concurrency applies. A second active submission by the same user for this workflow is rejected with HTTP 409. The Generate button remains disabled with a workflow-specific queued/generating/cancelling label until the job reaches a terminal state.

Jobs from different workflows may wait behind the same RunningHub credential according to its configured concurrency. Each job stores the resolved LoRA filename, version label, prompt, and resolution so later registry edits cannot change an already queued job.

## Admin and security

- Only admins may mutate the Cloud LoRA registry or workflow registry.
- Regular users receive only enabled characters and enabled versions.
- API keys remain encrypted and are never returned to the browser.
- Submitted LoRA filenames must resolve from the registry.
- Resolution keys must resolve from `RES_PRESETS`.
- Upload size and MIME type are validated before persistence or RunningHub upload.
- Admin preview uploads are stored in durable application media storage and exposed through controlled URLs.

## Failure behavior

- No configured character/version: Generate remains disabled with a clear message.
- Missing or disabled selected version: return 400 and ask the user to refresh.
- RunningHub rejects a LoRA filename: mark the job failed and show the provider error; do not silently retry another character.
- Invalid prompt, image, or resolution: reject before creating a cloud task.
- Cancellation before submission deletes staged uploads.
- Cancellation after submission calls RunningHub's cancellation endpoint and releases the queue slot after acknowledgement.
- Successful output import failure remains a visible failed/import error rather than reporting generation success without a Gallery asset.

## Verification

Automated tests cover:

- Admin-only character/version CRUD and validation
- Default-version uniqueness
- Public registry filtering of disabled entries
- Server-side resolution and LoRA resolution
- Exact nodeInfoList mapping for nodes 33, 5, 13, and 46
- LoraLoaderState generation with one enabled LoRA at strength 1
- Duplicate submission prevention
- Image-result import into Gallery
- Cancellation and queue compatibility
- Browser syntax and responsive Cloud Studio layout

A final controlled RunningHub test uses one source image, one prompt, one low-cost resolution, and one registered private LoRA version. The generated image must appear in Gallery and the RunningHub task must show the selected filename on node 46.
