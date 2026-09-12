# Standalone Admin Page Design

## Goal

Replace the clipped Admin overlay with a dedicated page that uses the Atelier Studio navigation and visual system.

## Layout

- Opening **Admin** hides Studio, Gallery, Reels, and Notes content.
- Admin occupies the normal page area below the persistent header.
- A page heading and short management description introduce the screen.
- Users appear in a full-width section.
- Workflows appear below in two responsive columns: **Enabled workflows** and **Disabled workflows**.
- Each workflow card keeps its name, explicit state text, and reliable switch control.
- The layout uses the existing cream, charcoal, gold, green, and red Atelier tokens.
- Narrow screens collapse the two workflow columns into one without introducing an inner scrollbar.

## Behavior

- The existing explicit workflow-state API remains unchanged.
- A successful switch refreshes the workflow list and Studio navigation visibility.
- A failed switch restores its prior visual state and shows the existing error message.
- Admin is accessible only when the signed-in user has the admin role, as it is today.

## Verification

- Confirm Admin is not positioned over Studio and has no backdrop blur.
- Confirm navigation between Admin and Create restores the correct page.
- Confirm enabled and disabled workflow cards render in their correct columns.
- Run the existing Python test suite and JavaScript syntax check.
