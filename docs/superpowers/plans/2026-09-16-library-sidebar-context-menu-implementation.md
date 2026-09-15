# Library sidebar and context-menu implementation plan

1. Add lightweight library summary APIs for folder counts and total storage use.
2. Refactor shared sidebar rendering for visible folder creation, counts, and
   usage meter in Gallery and Reels.
3. Replace card actions with a shared pointer-anchored context menu, including
   keyboard/outside-click dismissal and long-press support.
4. Route context actions through existing preview, move, download, enhance,
   motion, and delete functions; add focused tests and deploy verification.
