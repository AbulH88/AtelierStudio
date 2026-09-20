# Gallery character and batch browser

## Goal

Keep the Gallery navigable as cloud batches accumulate: the sidebar shows one entry per character, the main area shows that character's generation batches, and a selected batch shows its images. Newest content appears first throughout.

## Navigation

- **All Images** remains the root view and displays individual Gallery media, newest first.
- The left sidebar contains one entry for each character that has generated a cloud text-to-image batch. It does not contain one entry per timestamped batch.
- Selecting a character changes the middle area into a batch-folder view. Each card represents one dated batch and opens that batch.
- Selecting a batch changes the middle area to the image grid for that batch. A visible back/breadcrumb control returns to the character’s batch-folder view.
- Existing timestamped batch folders are interpreted as `Character · YYYY-MM-DD HH-MM-SS`; no existing R2 objects are renamed or migrated.

## Ordering and performance

- Character entries, batch-folder cards, and image cards default to newest first.
- Ordering uses the timestamp embedded in cloud batch folder names. Media that does not have that naming convention uses its available storage timestamp, with filename ordering only as a last fallback.
- The browser loads only the active level: character folders for the sidebar, a selected character’s direct batch folders for the batch view, or a selected batch’s direct media. It must not enumerate every Gallery image merely to render a folder list.

## API and UI responsibilities

- The Gallery API exposes a lightweight character list and direct-batch list derived from the existing `gallery/Character · timestamp/` object prefixes.
- The existing media-list endpoint continues to return individual media for All Images and a selected batch.
- The client keeps navigation state as `all`, `character`, or `batch`, renders the appropriate card type, and preserves current search/view controls where they apply.
- Folder cards show the batch timestamp, item count, and a representative preview when available.

## Error handling and tests

- Malformed/legacy folders remain accessible and sort behind timestamped batches unless storage metadata provides a more precise time.
- An empty character or empty batch gets the existing empty-state treatment.
- Tests cover character grouping, newest-first batch ordering, direct media listing, and fallback sorting for legacy content.
