# Gallery and Reels folder move implementation plan

1. Extend `r2_store.py` with a safe copy-then-delete move primitive and helpers
   for media plus optional thumbnail pairs.
2. Add protected APIs to create Gallery folders and move a single Reel or
   Gallery object, validating source keys, folder names, root destinations, and
   collisions.
3. Add shared client-side picker helpers and per-card Move actions for Reels
   and Gallery; refresh folder lists and the active media view after success.
4. Add focused Flask/R2 unit tests and run the relevant existing tests.
