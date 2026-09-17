# Shared Library Organization and Media Preview Design

Date: 2026-09-18

## Goals

1. Add `openai/gpt-5.6-luna` to the curated Describe with AI selector as a SFW/OpenAI option.
2. Open completed Cloud Queue images in a preview popup, alongside the existing playable video popup.
3. Keep Gallery and Reels shared while making each creator's media easy to find.
4. Add practical file-browser-style organization to Reels without adding new Gallery organization features for regular users.

## Model selector

- Add GPT-5.6 Luna as the seventh model, after DeepSeek V4.1 Flash.
- Label it `GPT-5.6 Luna (SFW · OpenAI)`.
- Retain Qwen 3.8 27B as the default and retain the other six approved choices.

## Cloud Queue previews

- Completed image rows open an image preview popup rather than navigating directly to Gallery.
- Completed video rows continue to open the playable video popup.
- Both popups provide Download, Open in Gallery, and Close controls; backdrop click closes the popup.
- Completed cloud videos continue to be saved under `gallery/cloud/` before their job becomes `done`.

## Shared creator organization

- Gallery and Reels remain visible to every authenticated user; this is organization, not access control.
- New media records the logged-in creator in server-side metadata without changing existing object keys.
- Both libraries offer All media and My creations filtering, plus a creator label on each item.
- Older untagged items remain available as `Unknown / legacy` rather than being hidden or reassigned.
- Both libraries offer a browser-persisted Tiles or Compact list view. Search, sorting, selection, previews, and existing actions work in either view.

## Gallery administration

- Gallery does not gain new nested-folder behavior.
- Only admins may create Gallery folders or move Gallery media.
- The backend enforces this authorization; non-admin UI controls are hidden so a crafted request cannot bypass the rule.
- Existing Gallery deletion behavior is not changed by this scope.

## Reel organization

- Remove the visible Reel `+ New Folder` button.
- Right-click menus provide Create folder and Create subfolder. Reels allow nested paths of any depth, such as `Joy / April / Outfits`.
- Users can select multiple Reels, right-click any selected item, and move the whole selection to an existing destination or a newly created subfolder.
- Moving a Reel retains its creator metadata and media/thumbnail association.

## Data handling and migration

- Store creator metadata in a server-side JSON registry keyed by the R2 object key, rather than encoding usernames into object paths.
- Register metadata whenever Gallery/Reel media is created or uploaded. Move operations update the registry key; delete operations remove the registry entry.
- Old items receive no guessed owner. Their creator field is `Unknown / legacy`.

## Validation

- Add server tests for creator registration, filtering, legacy handling, and Gallery admin authorization.
- Add tests for Reel multi-select move and nested-destination validation.
- Add static UI tests covering the view switch, creator filter, image preview route, and removal of the visible Reel new-folder button.
- Run Python compilation, focused tests, full webapp tests, and inline JavaScript syntax validation.

## Non-goals

- Making Gallery or Reels private to their creators.
- Reassigning historical media to guessed users.
- Adding Gallery nested folders or regular-user Gallery folder/move privileges.
- Changing RunningHub submission, cancellation, or media storage behavior.
