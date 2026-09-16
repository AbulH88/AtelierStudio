# Local/Cloud Studios and MiniMax H3 Ref2V implementation plan

## 1. Cloud workflow backend contract

- Add a cloud-workflow catalog containing Scail 2 and MiniMax H3 Ref2V.
- Generalize persisted RunningHub jobs with a workflow key and workflow ID.
- Preserve the existing Scail submit path while adding H3-specific uploads,
  validation, node overrides, polling, result import, and restart recovery.
- Add pure helpers for H3 reference validation and deterministic node mapping.

## 2. Navigation and Cloud Studio shell

- Rename Create to Local Studio and Cloud to Cloud Studio.
- Replace the single Scail page layout with left workflow navigation, central
  workflow content, and persistent right Cloud Queue/usage rail.
- Reuse current Scail controls in its central content panel.
- Keep the queue shared across workflows and preserve Gallery imports.

## 3. H3 reference editor

- Add Image to Video, Omni Reference, and First & Last Frame modes.
- Build dynamic image/video/audio cards with previews, replacement, removal,
  role assignment, and optional audio target assignment.
- Enforce mode requirements, file types/sizes/durations, per-type limits, and
  the 12-file combined limit before submission.
- Add prompt, aspect, duration, quality, seed, and instance controls.

## 4. Tests and delivery

- Unit-test H3 validation, blank omission, deterministic numbering, first/last
  binding, nodeInfoList construction, and workflow-aware job persistence.
- Run existing RunningHub and gallery import regressions.
- Verify browser rendering and interactions at desktop and narrow widths.
- Commit, push main, monitor the VPS deployment, and verify the live endpoint.
