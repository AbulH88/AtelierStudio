# Cloud Krea2 Turbo Text-to-Image

## Goal

Add a separate Cloud workflow named **Krea2 Turbo Text-to-Image** backed by
RunningHub workflow `2100976623406669826`.  It is pure text-to-image: no source
image is uploaded or required.

## Shared character library and triggers

The existing administrator-managed RunningHub Characters list remains the sole
character source for both Cloud Krea2 workflows.  Each character version gains
an editable `trigger_words` field.  The field is a comma-separated string such
as `1NST4GR4M, oliviaDD2m`.

Whenever a user selects a character version, the server prepends its saved
trigger words to the user's prompt automatically.  This applies to both:

- Krea2 Image-to-Image HQ
- Krea2 Turbo Text-to-Image

The user never has to type trigger words manually.  Empty trigger words remain
valid for character versions that do not require them.

## T2I workflow controls

Cloud Studio adds **Krea2 Turbo Text-to-Image** in the Image workflow group.
The panel includes:

- Prompt
- Resolution selector
- Batch count
- Seed and random/fixed seed choice
- Character and version selectors
- T2I helper LoRAs
- Generate control and Cloud job feedback

The T2I panel does not include source image upload, denoise, face reference, or
character-locked describe controls.

## RunningHub mapping

The server submits to workflow `2100976623406669826` using the existing
per-user/global encrypted RunningHub key system.

- Node 6: final positive prompt, including saved character trigger words
- Node 10: width, height, and batch size
- Node 98: seed, steps, CFG, sampler, scheduler, denoise (fixed defaults except
  seed and user batch count)
- Node 117: selected character LoRA and enabled helper LoRAs
- Node 111: workflow-owned final post-processing remains untouched

The workflow defaults remain aligned with the supplied JSON: 8 steps, CFG 1,
Euler Ancestral, beta57 scheduler, AuraFlow shift 6, and the workflow's CRT
post-process suite.

## Helper LoRAs

T2I helpers have a separate admin-managed registry.  An entry has a filename,
default enabled state, and strength.  Administrators may add/remove helpers;
users can enable/disable them and retune strength for one job.  Helpers are
sent through the workflow's Pixaroma LoRA loader together with the selected
character LoRA.

## Access, jobs, and tests

`krea2_t2i` is a new Cloud permission which admins can enable per user.  It uses
the existing queue, cancellation, results import, gallery saving, and global or
private key behavior.  Tests cover trigger normalization and automatic prompt
assembly, T2I node mapping, helper validation, permission gating, and T2I job
creation without an image upload.
