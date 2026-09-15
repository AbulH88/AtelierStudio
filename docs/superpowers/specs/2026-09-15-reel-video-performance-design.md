# Reel Library video performance

## Goal

Apply the private, thumbnail-first Gallery behavior to the Reel Library.

## Design

Reel uploads and Instagram downloads create a small WebP preview beside the
original video under `thumbs-reels/`. The reel list returns that preview URL.
The Reel grid lazy-loads only the previews and opens the existing full video
player on click; it no longer starts MP4 downloads merely because a card is
visible or hovered.

Old reels without previews self-heal on first view, using the existing private
media proxy. The original remains private and is requested only when selected
for playback, download, frame extraction, or motion use.

## Verification

Tests cover Reel preview URLs and missing-preview recovery. Run the complete
Python suite and JavaScript syntax validation before deployment.
