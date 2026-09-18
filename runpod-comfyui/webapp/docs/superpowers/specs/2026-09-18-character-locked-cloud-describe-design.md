# Character-locked Cloud Krea2 descriptions

## Goal

When a user selects a Cloud Krea2 character, AI description must preserve that
character's identity.  An uploaded source image supplies only the visual
attributes the user explicitly chooses, such as pose or lighting.

## Admin character identity

Each Cloud character version has an optional saved identity profile.  It is a
short, editable description of the character's face, hair, eyes, makeup, and
signature accessories.  Only an administrator can change it.

Administrators can either write the profile manually or upload a face reference
and use the existing vision AI to draft the profile.  The generated text is
always editable before saving.  The profile belongs to the selected character
and version so multiple LoRA characters never share an identity by mistake.

## User description controls

The Cloud Krea2 **Describe source with AI** area gains a Character-locked mode
and a compact **Borrow from source** control.  In that mode, users can enable:

- Pose
- Expression
- Outfit
- Background
- Lighting and camera
- Hair and makeup

The defaults are pose, expression, background, and lighting/camera enabled;
outfit and hair/makeup disabled.  Identity, facial features, age, ethnicity,
and body identity are never taken from the source image.

## Prompt assembly

On a describe request, the server reads the selected character and version,
then retrieves its saved identity profile.  It sends the vision model a strict
instruction that the identity profile is the only subject identity.  The source
image is inspected solely for the enabled categories.  The response is one
natural image-generation prompt, not separate labelled sections.

If Character-locked mode is disabled, the current description behavior is
unchanged.  If it is enabled but the character has no profile, the request
returns a clear message asking the administrator to save one first.

## Generation boundary

The description system improves prompt content only.  Actual identity
consistency is supplied by the selected character LoRA/version during the
RunningHub job.  This feature does not retrain a LoRA and does not change the
workflow's helper LoRAs.

## Validation and tests

- Admin-only profile read/write and profile-generation endpoints.
- Character/version validation before the profile is used.
- Describe tests prove that a profile is inserted, only selected source
  attributes are requested, and no source identity is requested.
- Existing normal describe and Cloud Krea2 submission behavior remain covered.
