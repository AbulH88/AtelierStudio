# Gallery and Reels folder creation and moving

## Goal

Let users organize individual Reel videos and Gallery media into folders without
leaving either library. A per-card Move control is the single interaction for
both libraries and can create a destination folder when needed.

## User experience

- Each Reel and Gallery card gains a `Move` action alongside its existing card
  actions.
- Selecting Move opens a compact destination picker showing the library root,
  all current folders, and `New folder…`.
- Choosing `New folder…` prompts for a name, creates the folder, and moves the
  selected media into it in the same flow.
- After a successful move, the card list and folder navigation refresh. If the
  moved item no longer belongs to the active folder, it disappears from that
  view.
- Reels only offer Reel folders; Gallery only offers Gallery folders.

## Backend and storage behavior

- Add a shared R2 move helper that copies an object to a validated destination
  key, then deletes the source only after the copy succeeds.
- Moving a Reel changes its object key between the root or a top-level Reel
  folder. Its matching `thumbs-reels/<source-stem>.webp` thumbnail is moved to
  the matching destination stem when it exists.
- Moving Gallery media changes its key between `gallery/` root and its immediate
  group folder. Its matching `thumbs/<source-stem>.webp` thumbnail moves with
  it when present.
- Creating a Gallery folder writes the existing `.keep` marker beneath
  `gallery/<folder>/`; Reel folder creation continues to write its marker at
  the Reel-library root.
- Folder names are normalized to one top-level segment and reject empty names,
  path separators, traversal, and reserved internal prefixes. Source keys must
  belong to their respective library. The server preserves the media filename.
- A destination that already contains the same filename returns an error rather
  than overwriting media.

## Errors and tests

- The UI presents server errors in its existing status/alert pattern and leaves
  the original card visible when a move fails.
- Unit tests cover valid key transformations, forbidden folder names and source
  keys, no-overwrite behavior, and moving/deleting matching thumbnails.
- Existing Reel folder and Gallery thumbnail tests remain green.
