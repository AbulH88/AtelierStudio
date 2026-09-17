# Shared Library Organization Implementation Plan

**Design:** `docs/superpowers/specs/2026-09-18-shared-library-organization-design.md`

1. Add a locked, atomic server-side media metadata registry and helpers for creator ownership, key moves, and deletion.
2. Register creators for generated, uploaded, Reel, and RunningHub media; enrich Gallery/Reel list responses with creator metadata.
3. Enforce Gallery folder creation and moves as admin-only, preserving existing deletion behavior.
4. Extend Reel folders to nested paths and add a bulk move endpoint that moves original media, thumbnails, and metadata together.
5. Add a shared creator filter and persisted Tiles/Compact view controls to Gallery and Reels; remove the visible Reel new-folder button.
6. Add a shared Cloud image/video popup and make completed Cloud Queue image rows open it.
7. Add GPT-5.6 Luna to the OpenRouter list and update model tests.
8. Add focused tests, run syntax/compilation/full test validation, commit, push, and verify deployment.
