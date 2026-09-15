# Reel Library internal folders

## Goal

Keep Gallery originals and thumbnail objects out of the user-facing Reel Library
without deleting any stored media.

## Design

The Reel Library treats `gallery/`, `thumbs/`, and `thumbs-reels/` as internal
storage prefixes. They are excluded from the Reel sidebar folder list and from
the `All Reels` listing/count. User Reel folders such as Joy, Sami, and Shoron
remain unchanged.

## Safety and verification

This is a display/listing filter only: no R2 object is removed or moved. Tests
verify that internal keys and prefixes do not reach Reel Library results.
