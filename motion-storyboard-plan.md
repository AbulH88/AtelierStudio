# Motion Storyboard — v1 Plan

Goal: replace the manual CapCut round-trip. A driving video that contains a
**transition** (outfit change, scene change) can't be motion-transferred in one Wan
Animate pass — each gen is one consistent character/outfit. So the user cuts the clip
into segments, animates each separately, then stitches them. This brings that whole
flow into the app.

All **app-side** (app.py + index.html + comfy_common) — no worker-image rebuild.

---

## v1 scope

IN:
- **Cut** one driving video into N **segments** by time (the user marks the cut points).
- Per-segment **reference image** (outfit/look) + optional per-segment prompt; same
  character LoRA across segments by default (overridable later).
- **Generate** one motion clip per segment, animating only that time range.
- **Auto-stitch** the clips in order into one final mp4 (with audio) → saved to Gallery.
- Transitions: **hard cut**, **crossfade** (default ~0.5s), **fade-to-black**.

OUT (deferred to v2):
- Auto scene-detection (app finds the cut points itself).
- Per-segment different character LoRA.
- Fancy transitions (zoom, glitch, wipe), per-transition timing UI.
- Re-ordering / re-generating a single segment without redoing all.

---

## The "cut" model (core of v1)

One driving video + an ordered list of segments. Each segment:

```
segment = {
  start_sec, end_sec,        # the cut — what slice of the driving video to animate
  ref_b64,                   # reference image (outfit) for this segment
  prompt,                    # optional per-segment description (defaults to global)
  out_video_b64 / out_url,   # filled after generation
}
transition = "crossfade" | "cut" | "fadeblack"   # applied between consecutive segments
```

Cutting maps to the existing Wan workflow inputs — **no actual video splitting needed**:
- `skip_first_frames = round(start_sec * fps)`
- `frame_load_cap   = round((end_sec - start_sec) * fps)`

So each segment's gen animates exactly its slice. `comfy_common._build_video` already
sets `frame_cap`; add `skip_first_frames` passthrough (one line).

---

## UI — Storyboard panel (Motion page)

Below the existing driving-video + ref-photo cards, add a collapsible **Storyboard**:

- **Timeline strip** of the driving video with draggable cut markers (or numeric
  start/end inputs per segment for v1 — simpler, exact).
- **Segment rows**: each shows its time range, a **ref thumbnail** (pull a frame from
  that segment via the existing "describe ref / frame grab", or upload), and an optional
  prompt field.
- **+ Add segment** / remove segment.
- **Transition** dropdown (global for v1): Crossfade / Hard cut / Fade to black.
- **Generate storyboard** button → runs each segment as a motion job (reuse the async
  job system), shows per-segment progress, then auto-stitches.
- Result appears in Gallery as one clip.

Hidden unless Motion mode. Single-segment = today's behavior (no stitch).

---

## Backend

1. **`comfy_common._build_video`** — accept `skip_first_frames` (and keep `frame_cap`)
   so a gen animates a sub-range. ~2 lines.
2. **Generation orchestration (app.py)** — a storyboard job that loops segments,
   submits each (cloud `/run`+poll or local), collects the output mp4s in order.
   Reuse `_run_gen_job` per segment; track sub-progress in `GEN_JOBS`.
3. **Stitch (app.py, ffmpeg on VPS)** — concatenate the ordered clips with the chosen
   transition:
   - hard cut → `concat` demuxer
   - crossfade → chained `xfade` (+ `acrossfade` for audio), `offset = sum(prev durations) - 0.5`
   - fade-to-black → `xfade=transition=fadeblack`
   All clips share resolution/fps (same workflow), so xfade chains cleanly.
   Mux audio per the existing `_mux_audio` path. Upload final to R2 + register in Gallery.
4. **Endpoints** — `POST /api/storyboard` (segments + transition → job_id),
   `GET /api/storyboard/result?job_id=` (per-segment progress + final url). Mirrors the
   existing `/api/generate` async pattern.

---

## Implementation steps
1. `comfy_common`: add `skip_first_frames` passthrough in `_build_video`. (deploy: VPS for
   local; the cloud worker already has frame_cap — confirm skip works without rebuild,
   else fold into the next image build.)
2. app.py: `_stitch_clips(clips, transition)` ffmpeg helper + storyboard job runner +
   the two endpoints.
3. index.html: Storyboard panel UI (segment rows, transition picker, generate button,
   per-segment progress), wired to the new endpoints.
4. Test: 2-segment clip (outfit A 0–5s, outfit B 5–10s) → crossfade → one mp4 in Gallery.

## Risks / notes
- `skip_first_frames` on node 75 — verify the cloud worker honors it; if it's baked and
  not exposed, it folds into the next image rebuild (cheap).
- xfade needs exact per-clip durations (probe with ffprobe) to compute offsets.
- Keep single-segment path = current behavior (no regression).
