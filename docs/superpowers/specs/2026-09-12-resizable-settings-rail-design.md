# Resizable Settings Rail

## Goal

Let the user widen or narrow the Studio Settings rail when long model, checkpoint, and LoRA names need more space.

## Interaction

- A narrow, visible drag handle sits on the left edge of the Settings rail.
- Dragging left widens the rail; dragging right narrows it.
- The rail width is constrained to 300–620px.
- The selected width is saved in browser storage and restored on the next visit.
- Double-clicking the handle restores the default 360px width.

## Layout and safety

- The Studio main grid uses the selected width for its right column, leaving the workspace to occupy remaining space.
- During a drag, text selection is disabled and the pointer uses an east/west resize cursor.
- At tablet/mobile widths where the Studio already becomes one column, the handle is hidden and the Settings rail remains full width.

## Verification

- Confirm the rail can be resized within the stated limits.
- Confirm the selected width survives a page refresh.
- Confirm the default can be restored with a double-click.
- Run JavaScript syntax validation and the existing test suite.
