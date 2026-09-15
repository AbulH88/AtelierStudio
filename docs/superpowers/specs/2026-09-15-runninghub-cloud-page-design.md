# RunningHub Cloud Page Design

## Goal

Add a top-level **Cloud** page to Atelier Studio for Scail 2 generation on
RunningHub. It is independent from Local generation, ComfyUI, the Home Agent,
and the local Enhance page, so a cloud job can run while the user's computer is
off.

## Scope

- Add Cloud to the main navigation.
- Support the published RunningHub Scail 2 workflow only.
- Accept a reference image and driving video.
- Use a fixed direct output of 720 x 1280 for the first release.
- Save successful videos automatically to the submitting user's Gallery.
- Store each user's RunningHub API key encrypted at rest on the Studio server.
- Run all users on RunningHub Standard (`default`, 24 GB VRAM) by default.
- Allow an administrator to enable RunningHub Plus (`plus`, 48 GB VRAM) for
  specific users. A Plus-enabled user can select it; users without access only
  see Standard.

## Out of scope

- Local ComfyUI, Home Agent, Enhance, RIFE, DLSS, RTX VSR, and RunPod are not
  part of Cloud execution.
- Reels import is not automatic. Users can move a Gallery video to Reels later.
- Ultra instances and arbitrary RunningHub workflows are not included.

## Architecture

### User settings

The Cloud settings panel lets a signed-in user save, replace, test, or remove
their RunningHub key. The browser sends the key only over the authenticated
Studio request. The server encrypts it before persistence and never returns the
full value to the browser. The UI displays only a masked suffix and connection
status.

An admin-only user-management control stores a per-user Plus entitlement. The
server, rather than the browser, validates the requested instance type. Standard
is always available; Plus is accepted only for entitled users.

### Job lifecycle

1. The user uploads the reference image and driving video on Cloud.
2. Studio uploads both files to RunningHub's media upload endpoint using that
   user's key.
3. Studio submits the configured Scail 2 workflow with `nodeInfoList` mappings
   for the image and video upload nodes and `instanceType` of `default` or an
   authorized `plus`.
4. Studio persists a job record before returning it to the browser, then polls
   RunningHub server-side. Refreshing a browser page never re-submits a task.
5. When RunningHub reports success, Studio downloads the returned MP4 before its
   24-hour URL expires and writes it to that user's Gallery.
6. The job record stores status, task ID, timing, consumed RH coins, Gallery
   item reference, and safe error text.

### Cloud UI

The page follows the approved dark Atelier Studio mockup:

- Main create area: reference image, driving video, fixed 720 x 1280 output,
  and a single cloud-generation button.
- Right-side Cloud Settings: key connection state, workflow label, and the
  Standard/Plus selector when permitted.
- Job history: queued, running, success, or failure states plus RH coins,
  elapsed time, and a Gallery link for completed results.

## RunningHub workflow contract

The published API currently exposes an empty `nodeInfoList`. Before end-to-end
execution, RunningHub must expose the reference-image and driving-video nodes
as API-editable parameters. Studio will bind the final published mappings,
rather than relying on the local workflow JSON. This prevents accidental use of
local-only RIFE/RTX nodes.

## Error handling

- Missing/invalid key: block submission and show a connection error.
- Upload/submission failure: create no Gallery item and retain a readable job
  error.
- RunningHub task failure: preserve the task ID and failure reason; do not
  deduct or estimate coins locally.
- Result-download failure: mark the job as needing retrieval and retry server
  download while the RunningHub URL remains valid.
- Unauthorized Plus request: reject it server-side and retain Standard.

## Verification

- Unit tests for encryption/masking, entitlement enforcement, API payloads,
  duplicate-submission protection, and RunningHub status conversion.
- Integration tests with mocked RunningHub upload/run/query/result responses.
- Manual test using the configured test key: Standard generation, Gallery
  import, page refresh during a run, invalid-key error, and Plus UI visibility
  for enabled versus non-enabled users.
