# Cloud Studio queue and media redesign

## Goal

Bring the deployed Cloud Studio in line with the approved dark editorial mockups, remove all API-key management from ordinary users, make shared-key concurrency predictable, and make H3 image/video/audio selection immediately understandable.

## Cloud credentials and assignment

- RunningHub credentials are managed only by an administrator through the Admin area or backend.
- A credential may be global, assigned to one user, or assigned to several users.
- An administrator can also use an assigned credential.
- Ordinary users never receive the API key value, suffix, edit control, or removal control in Cloud Studio.
- Keys remain encrypted at rest. Queue grouping uses a one-way key fingerprint, never the plaintext key.
- Resolution order is explicit: a user's private assignment overrides an assigned shared key, which overrides the configured global key.
- The Admin UI shows a label, assignment scope, enabled state, instance permissions, and concurrency limit without revealing the saved secret after creation.

## Shared-key scheduler

- Each credential has a configurable maximum number of simultaneous RunningHub jobs; the default is one.
- Jobs sharing a credential enter one FIFO queue, regardless of which user submitted them.
- Jobs using different credentials may run concurrently.
- When a slot becomes available, the oldest eligible queued job starts automatically.
- A job always belongs to its submitting user. Users see only their own jobs and results; admins may inspect all jobs.
- Restart recovery preserves queued, active, completed, and failed jobs. It must not submit the same job twice.
- Upload preparation does not consume a generation slot; submission and RunningHub execution do.
- Failed or cancelled jobs release their slot and allow the next queued job to start.
- RunningHub terminal states `CANCEL` and `CANCELLED` are both treated as cancelled.
- A user may cancel their own waiting or active job from the Cloud Queue. Waiting jobs are cancelled locally; submitted jobs call RunningHub's `/task/openapi/cancel` endpoint using the server-held credential and task ID.
- Cancellation first displays `Cancelling…`, then a terminal `Cancelled` state. The queue slot is released only after local state is made terminal, and dispatch immediately considers the next waiting job.
- Cancelling a task directly in RunningHub is reconciled by polling and produces the same terminal state in Atelier.
- Cancellation is idempotent: repeated requests return the current terminal state and never cancel a different task.
- Job ownership is enforced server-side; a user cannot cancel another user's job.
- The backend rejects a second active or waiting submission for the same user and workflow with HTTP 409. This protects against rapid double-clicks even if browser state is stale.

## Cloud Studio right rail

- Replace the large raw job output with the approved compact Cloud Queue design.
- The current job uses a progress ring, workflow name, status, and estimated time when available.
- The current-job card provides a Cancel Job action while the job is waiting, uploading, submitting, queued, or running.
- Workflow labels are derived from each job's workflow key: `Scail 2 Motion` and `MiniMax H3 Ref2V`; they are never inferred merely from the presence of a workflow ID.
- Recent jobs appear as compact thumbnail rows with status dots and duration/aspect metadata.
- Completed-job thumbnails open a modal player. Videos are never rendered full-size inside the right rail.
- The modal contains playback, Download, Open in Gallery, and Close actions.
- Remove the Cloud Account/API-key form entirely.
- Add a compact Cloud Usage card showing connection readiness, queue capacity, and available balance when RunningHub supplies it. It never reveals credential material.

## H3 reference editor

- Preserve the three modes: Image to Video, Omni Reference, and First & Last Frame.
- Image to Video displays one large required image card.
- First & Last Frame displays two large cards explicitly labelled First Frame and Last Frame.
- Omni Reference displays clear Images, Videos, and Audio sections instead of hiding access behind small tabs.
- Limits remain nine images, three videos, three audio files, and twelve total references.
- At least one image is required. Video and audio are optional and cannot be submitted alone.
- Every section has an elegant dashed Add card with a type-specific icon, supported formats, and remaining capacity.
- Each Add card accepts either a click-to-browse upload or files dragged from the user's computer. Dragging a valid file over the matching card highlights the drop zone; unsupported media is rejected with a clear message.
- Uploaded media uses clean thumbnail cards with a short filename, type/index label, Replace, and Remove controls.
- Audio cards use an audio icon, filename, optional duration, and playback control.
- Video cards use a poster thumbnail and open the same modal player rather than expanding inline.
- Empty optional references are omitted from submission.
- The H3 settings row contains only workflow-backed Aspect Ratio and Duration controls.
- Quality and Instance are not exposed because they are not user-selectable inputs in the supplied H3 workflow; infrastructure selection remains a backend concern.

## Primary navigation

- Cloud Studio is the second top-level destination, directly after Local Studio and before Gallery.

## Visual language and responsiveness

- Match the approved mockups: near-black layered panels, fine warm-grey borders, ivory serif headings, restrained gold accents, and compact monospace metadata.
- Keep the left workflow navigation, central workflow canvas, and right queue rail on wide screens.
- The center canvas must not be forced off-screen by the queue rail.
- On narrower displays, the right rail moves below the workspace; media cards reflow without horizontal scrolling.
- The three-column Cloud Studio layout is reserved for viewports wider than 1800px. Below that width, the queue rail moves below the workflow canvas so the active workflow remains readable.
- Below 1100px, the workflow navigation, workspace, and queue stack vertically. H3 headings, steppers, mode controls, media cards, and settings must wrap rather than clip.

## Validation and errors

- The Generate control explains missing required media directly beside the relevant section.
- Queue position is shown before a job reaches RunningHub.
- Credential-unavailable, insufficient-balance, upload, submission, and provider failures receive distinct user-facing messages.
- A server-side validation layer enforces all reference and concurrency rules; browser validation is only a convenience.
- While the current user has an active job for a workflow, that workflow's Generate button is disabled and shows the live state (`Queued…`, `Generating…`, or `Cancelling…`). It returns to its normal label only after completion, failure, or cancellation.

## Testing and delivery

- Test credential resolution and ensure non-admin responses never contain secrets.
- Test FIFO scheduling, independent-key concurrency, configurable capacity, slot release, restart recovery, and duplicate-submission prevention.
- Test ownership isolation for job lists and result access.
- Test all three H3 modes, limits, blank omission, media replacement/removal, and modal playback.
- Run existing RunningHub, Gallery, authentication, and media-move regression tests.
- Verify desktop and narrow layouts, then deploy through the existing main-branch workflow.

## Deferred dependency

H3 submission remains guarded until the published RunningHub workflow exposes or safely maps all optional reference nodes. The redesigned editor can ship first without risking submission of baked sample media.
