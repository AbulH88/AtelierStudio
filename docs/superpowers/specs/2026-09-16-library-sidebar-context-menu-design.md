# Library sidebar and context-menu design

## Goal

Make Gallery and Reels folders obvious to manage, and replace persistent
per-card actions with a familiar desktop-style context menu.

## Shared sidebar

Both library pages use the same enhanced sidebar design:

- A prominent `+ New Folder` button sits immediately below the library title.
- Folder rows use clear contextual icons and show each folder's item count.
- The existing active-folder state remains visually distinct.
- A bottom Cloud Storage section displays total used storage against the
configured capacity and a progress bar. It is informational only.

## Context menu

Right-clicking a media card opens a menu anchored near the pointer. Long-press
opens the same menu on touch devices. The card itself does not show permanent
action buttons.

- All media: Preview, Move to folder…, Download, Enhance, and Delete.
- Images also include Use as Motion reference.
- Videos include Use as Motion video reference when the existing flow supports
  it; otherwise the unavailable image-only item is omitted.
- Delete is visually separated as the final destructive action and keeps the
  existing confirmation step.
- Clicking outside, pressing Escape, or selecting an action closes the menu.

## Data and error behavior

- Folder creation uses the existing safe folder APIs. Reels retain their
  existing admin-only server authorization; Gallery follows its existing
  authorization behavior.
- Folder counts reuse library list data or lightweight count endpoints; no
  media originals are downloaded just to render navigation.
- Storage usage is obtained from a lightweight R2 listing summary. If it cannot
  be read, the sidebar remains usable and shows an unavailable state.
- Context-menu actions call the current preview, download, enhancement, motion,
  move, and delete APIs, preserving their validation and error handling.

## Verification

- Test sidebar folder creation, relevant context-menu item selection, image vs.
  video action visibility, and menu dismissal.
- Preserve the existing move-and-thumbnail tests.
