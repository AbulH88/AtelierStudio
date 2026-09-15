# Gallery video performance

## Goal

Keep the R2 bucket private while making the Gallery responsive even when it
contains many generated videos.

## Design

When a generated motion video is saved, the VPS creates one small WebP preview
from its first usable frame and stores it under the matching `thumbs/` key.
Gallery list responses provide that thumbnail URL for both images and videos.
The gallery grid displays lazy-loaded thumbnails only; it does not request MP4
metadata or video bytes for every card. Clicking a video thumbnail opens the
existing video player, which is the first time the full MP4 is requested.

Older Gallery videos without previews are self-healed on their first gallery
view: the VPS reads the original once, builds and saves the WebP thumbnail, then
serves it. If ffmpeg cannot make a preview, the card still exposes the existing
video player path rather than failing the gallery.

## Privacy and scope

R2 remains private. The browser continues to access all media through the
authenticated same-origin `/api/media` route; this change removes unnecessary
video requests from the grid rather than publishing direct bucket URLs. Reels
are outside this focused Gallery change.

## Verification

Tests cover video thumbnail-key discovery and thumbnail building behavior. The
full Python test suite and JavaScript syntax check run before deployment.
