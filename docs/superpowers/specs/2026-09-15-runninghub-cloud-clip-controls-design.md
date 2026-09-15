# RunningHub Cloud Clip Controls Design

## Goal

Allow a Cloud user to generate only the desired segment of a driving video,
rather than always submitting the full clip to Scail 2.

## UI

The Cloud page adds three controls above the generate button:

- **Start at**: whole seconds from the beginning of the driving video.
- **Generate**: Full clip, or a selected 3, 5, 8, or 10 second duration.
- **Frame sampling**: every frame by default, optionally every second or third
  frame for a deliberately sparser motion source.

## Workflow mapping

Cloud overrides the published `VHS_LoadVideo` node `113` using its API fields:

- `force_rate = 24`, so the duration is deterministic.
- `skip_first_frames = start_seconds * 24`.
- `frame_load_cap = duration_seconds * 24`; the field stays `0` for Full clip.
- `select_every_nth = 1`, `2`, or `3` from the sampling control.

The workflow's final Video Combine output remains 24 fps. This keeps a selected
five-second segment at five seconds, and prevents accidental full-clip GPU use.

## Verification

Test the generated `nodeInfoList` for Full clip and a five-second segment that
starts at two seconds, then manually submit a short Standard test after deploy.
