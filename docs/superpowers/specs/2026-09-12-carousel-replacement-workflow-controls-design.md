# Carousel Workflow Replacement and Admin Controls Design

## Objective

Replace the existing Krea2 Carousel Maker execution graph with the user-provided `Aiorbust Krea 2 NSFW V1.5 (1).json` workflow while retaining the studio's existing dynamic controls. Redesign the admin workflow-visibility interface so administrators can reliably enable and disable modes, including Krea2 Text to Image High Quality, without deleting any workflow.

## Scope

The change has two connected parts:

1. Replace the internal Carousel Maker graph in place. Its mode ID remains `krea2carousel`, so bookmarks, gallery grouping, permissions, and the existing mode button continue to work.
2. Replace the small Hide/Show workflow controls on the admin page with explicit stateful switches and reliable save feedback.

No new generation mode will be added. Krea2 Text to Image High Quality will remain installed and recoverable; administrators can disable it through the visibility manager.

## Carousel Workflow Integration

The attached ComfyUI canvas export is the source of truth for the new generation pipeline. It uses:

- `INT8Convert/selforaV21NightFix_selfora21Int8.safetensors`
- Krea2 CLIP and Wan bf16 VAE
- AuraFlow sampling shift 6
- Eight sampling steps, CFG 1, Euler ancestral, beta57
- Camera Look, Renoise, CRT post-processing, and metadata-free JPEG saving

The web app will convert this canvas graph into a compact API graph. Canvas-only or disconnected nodes will not be shipped to ComfyUI: ResolutionSelector, Grok prompt generation, image batch loader, image comparer, and preview nodes.

Existing studio controls remain authoritative and override fixed values from the export:

- The prompt field and prompt library set positive conditioning.
- The Character picker supplies LoRA slot 1; the fixed PSGoth LoRA from the export is not retained.
- Existing helper-LoRA rows populate the remaining Power Lora Loader slots.
- Resolution presets set latent width and height.
- Variations sets latent batch size and therefore carousel image count.
- Random/manual seed controls both sampling and Renoise deterministically.

The public mode label and ID remain `Krea2 Carousel Maker` and `krea2carousel`.

## Admin Workflow Controls

The Workflows area will be split into Enabled and Disabled sections. Each workflow is represented by a full-width state card with:

- Workflow name
- Clear `Enabled` or `Disabled` status text
- A large accessible ON/OFF switch
- Green-accented enabled state
- Dimmed, red-accented disabled state

Changing a switch will:

1. Lock that switch and show `Saving…`.
2. POST the requested explicit state to the server.
3. Confirm the returned persisted state.
4. Refresh the studio mode bar immediately.
5. Move the card into the correct Enabled or Disabled section.

If the request fails, the control will return to its previous state and show the server error. It will never silently appear to save.

## API and Persistence

The current toggle-only endpoint is vulnerable to duplicate clicks and retry ambiguity because each request merely reverses the stored value. It will be replaced or supplemented by an idempotent endpoint accepting an explicit `enabled: true|false` value.

The server will validate:

- The caller is an administrator.
- The workflow ID exists.
- `enabled` is a Boolean.

The persisted `workflows.json` format remains unchanged. Existing saved visibility choices remain compatible.

## Error Handling

- A failed workflow-state save leaves both the stored value and visible switch unchanged.
- Network, authentication, authorization, invalid workflow, and invalid payload errors are displayed beside the affected card.
- Switches are disabled while a request is pending to prevent duplicate operations.
- After a successful disable, if the hidden workflow is currently selected, the studio switches to the first available enabled mode using the existing mode-bar logic.
- If all modes are disabled, the studio displays its existing no-modes state rather than selecting a hidden mode.

## Testing

Automated tests will verify:

- The replacement Carousel Maker graph uses the attached workflow's model, sampler, VAE, CLIP, and post-processing values.
- Canvas-only nodes are absent from the API graph.
- Prompt, character LoRA, helper LoRAs, resolution, variations, and seed are injected from the existing UI request.
- Variations 4 and 5 produce batch sizes 4 and 5.
- The explicit workflow-state endpoint persists both enabled and disabled states.
- Invalid workflow IDs, non-Boolean values, and non-admin callers are rejected.
- Existing `workflows.json` settings remain readable.
- Front-end inline JavaScript remains syntactically valid and all referenced element IDs exist.

The full existing test suite must pass before deployment. After deployment, the VPS workflow file, visibility endpoint, service health, and public studio response will be checked.

## Deployment

The replacement graph and web application files will be included in the existing GitHub Actions deployment manifest. The change will be committed and pushed to `main`, which restarts the Atelier service. No model download is included; the replacement assumes the attached workflow's referenced model already exists on the local ComfyUI model storage. Model presence will be checked before deployment, and a missing model will be reported rather than silently substituted.

## Success Criteria

- Carousel Maker runs the attached workflow's core pipeline through the existing studio controls.
- Four or five carousel images can be requested through Variations without editing JSON.
- An administrator can disable Krea2 Text to Image High Quality with one obvious switch.
- The saved state is confirmed by the server and survives page refresh and service restart.
- Failed state changes display a useful error instead of silently reverting.
- No workflow is permanently deleted.
