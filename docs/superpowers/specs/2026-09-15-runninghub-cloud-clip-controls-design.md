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

## Job status and estimated time

After Cloud submission, the page immediately shows the RunningHub task ID,
selected instance, uploaded-file stage, and the live API state: `QUEUED`,
`RUNNING`, `SUCCESS`, or `FAILED`.

The UI shows elapsed time from submission. RunningHub's query API does not
provide a reliable percentage or time-remaining field, so Standard jobs display
an explicitly labelled estimate based on observed Scail 2 Standard runtimes.
Queued jobs state that they are waiting for RunningHub capacity rather than
pretending to have a countdown. On completion, the estimate is replaced with
RunningHub's actual runtime and RH coin usage.

## Completed video access

Each completed Cloud job expands below its compact detail row. The expanded
card plays the Studio Gallery copy of the MP4 and provides a direct `Download
MP4` link alongside `Open Gallery`. The player never relies on RunningHub's
temporary result URL, so it remains available after the 24-hour RunningHub link
expires. Queued, running, and failed jobs remain compact.

## Verification

Test the generated `nodeInfoList` for Full clip and a five-second segment that
starts at two seconds, then manually submit a short Standard test after deploy.
Verify queued, running, failed, and completed job displays with mocked API
responses, including explicit estimated versus actual timing text and a direct
download URL for the imported Gallery MP4.
