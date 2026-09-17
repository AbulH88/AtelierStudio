# Cloud Queue Media Preview Design

Date: 2026-09-18

## Goal

Let a completed image in the Cloud Queue open immediately in a preview popup, matching the direct-preview experience already provided for completed videos.

## Behavior

- A completed queue item with an image result opens an image popup when clicked.
- A completed queue item with a video result continues to open the existing playable video popup.
- Both popups provide Download, Open in Gallery, and Close actions. Clicking the backdrop closes the popup.
- The image popup must not auto-download or navigate away from Cloud Studio.

## Gallery persistence

Completed cloud videos already download from RunningHub and are stored below `gallery/cloud/` before the job transitions to `done`. This behavior remains unchanged. The implementation will add regression coverage for the gallery URL exposed on completed image and video jobs rather than duplicate or move media.

## Implementation

- Extend the existing Cloud media modal structure and CSS to render either an `<img>` or a `<video>` element.
- Replace the image queue-row navigation to Gallery with the shared popup opener.
- Keep video autoplay, controls, cleanup, and Gallery navigation intact.
- Add focused browser-contract tests for image/video queue click routing and completed-job gallery URLs.

## Error handling and accessibility

- Only queue rows with a `gallery_url` are interactive.
- Closing clears image/video sources and pauses video playback to release browser resources.
- The image uses descriptive alternate text; the video keeps native controls and `playsinline` support.

## Non-goals

- Changing RunningHub job submission, cancellation, result import, or Gallery storage.
- Adding in-popup image editing, deletion, or fullscreen controls.
- Changing the Gallery page layout.
