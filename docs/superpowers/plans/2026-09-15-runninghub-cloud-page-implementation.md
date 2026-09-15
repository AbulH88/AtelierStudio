# RunningHub Cloud Page Implementation Plan

## 1. Persistent Cloud data and credentials

- Add a small server-side store for per-user Cloud settings, user Plus access,
  and cloud job records.
- Encrypt RunningHub API keys with a server-only encryption key; expose only a
  masked suffix to the browser.
- Provide authenticated endpoints to save, test, and remove a user's key.
- Provide admin-only endpoints to enable or disable Plus for a user.

## 2. RunningHub client

- Add a focused client module for media upload, workflow submission, task query,
  and result download.
- Read the default workflow ID from server configuration.
- Require configured API node mappings for image and video inputs.
- Validate `default` for all users and permit `plus` only for users with the
  stored entitlement.

## 3. Cloud job service

- Persist the Studio job before submission and record the RunningHub task ID.
- Poll asynchronously from the server rather than the browser.
- Convert RunningHub states and usage to Studio job states.
- On success, import the final MP4 into the submitting user's Gallery.
- Retain errors and add safe retry/retrieval behavior without duplicate submit.

## 4. Cloud UI

- Add Cloud to the top navigation and create the approved two-column page.
- Implement reference image and driving video selection/upload.
- Show fixed 720 x 1280 output and Standard by default.
- Show Plus only to users authorized by admin.
- Display masked key state, current job progress, cost/time, errors, and Gallery
  links after completion.

## 5. Tests and release

- Add unit tests for credential masking/encryption, entitlement enforcement,
  RunningHub payload construction, job de-duplication, and result import.
- Add mocked HTTP integration tests for RunningHub calls.
- Run the app test suite, build, commit only scoped files, push, and verify the
  deployed Cloud page without submitting a billable task.
