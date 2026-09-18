# Cloud Krea2 Turbo T2I batches

## Goal

Allow a user-selected batch size from 1 through 16 for Cloud Krea2 Turbo
Text-to-Image and import every image that RunningHub returns.

## Batch control

Replace the fixed batch dropdown with a numeric input.  The server validates an
integer from 1 through 16.  This gives users flexible batch generation while
keeping a practical upper bound for the 24 GB RunningHub workflow.

## Gallery organization

Every T2I submission creates a new Gallery folder for that batch.  Its name is
the selected character name followed by the submission timestamp, for example:

`SophieJoyTalking · 2026-09-19 14-32-18`

All images returned by that single RunningHub task are imported into that one
folder.  A later T2I run always creates another timestamped folder, even if the
same character is selected.  This keeps batch images together without filling
the Gallery root.

## Result processing

The RunningHub result importer will collect every supported image result rather
than selecting only the first one.  It uploads every result to the new batch
folder, tags each item with the submitting user, and retains the folder key on
the Cloud job for Gallery navigation.  Queue thumbnails use the first image as
the job preview.

## Tests

- Batch values below 1 or above 16 are rejected.
- A multi-image result imports every image.
- Every imported item has the same character-and-timestamp folder prefix.
- The first imported image remains the queue preview.
