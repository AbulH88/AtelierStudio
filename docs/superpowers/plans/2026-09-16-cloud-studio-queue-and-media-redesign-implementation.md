# Cloud Studio queue and media redesign implementation plan

1. Move RunningHub credential mutation behind admin-only endpoints and add global-key fallback.
2. Store a non-reversible key fingerprint and concurrency limit on jobs; add a FIFO dispatcher per fingerprint.
3. Extend admin user cards with credential assignment, removal, and concurrency controls.
4. Replace the Cloud Studio account block and inline video output with compact usage/queue cards plus a video modal.
5. Rebuild the H3 media editor as mode-aware image, video, and audio sections with polished add/media cards.
6. Add backend and static UI regression tests, run the focused suite, commit, push, and verify deployment.
