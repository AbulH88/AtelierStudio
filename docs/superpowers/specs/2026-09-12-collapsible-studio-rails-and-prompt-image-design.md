# Collapsible Studio Rails and Prompt Image Design

## Goal

Complete the approved Atelier Studio interaction design: accurate high-contrast workflow icons, independently collapsible left and right rails, and an image-assisted prompt control.

## Workflow Icon Corrections

- All sidebar icons use bright cream outlines with a consistent 2px optical stroke.
- Group icons render larger than workflow-row icons.
- Image group and image workflows use a framed landscape.
- Carousel Maker uses twin mountain peaks.
- Text workflows use a serif-style `T` icon.
- Video group and LTX use a filmstrip.
- Animate uses a play symbol inside a rounded frame.
- Advanced uses a detailed gear.
- Motion Control uses a framed landscape.
- Instaraw uses a framed lens/photo symbol.
- Text-to-Video uses a framed mountain/motion symbol when that workflow is available.
- Image, Video, and Advanced headings include matching down chevrons.
- The selected workflow icon inherits the gold active color.

## Collapsible Workflow Sections

- The workflow rail always remains full width with its heading and labels intact.
- Image, Video, and Advanced each have an independent chevron that folds only that group's workflow rows.
- No icon-only rail state is used.
- Each group's state persists independently in `localStorage`.

## Prompt Image Description

- The prompt bar includes a framed-image button matching the approved mockup.
- Clicking it opens the existing image file picker.
- The selected image shows as a compact thumbnail with remove and **Describe with AI** actions.
- Describe uses the existing Krea2 image-description endpoint and writes the returned description into the active prompt.
- Upload and description errors appear inline without clearing an existing prompt.

## Collapsible Settings Sections

- The Settings rail always remains full width and never becomes a vertical tab.
- Controls are grouped into Workflow, Character & LoRAs, Output, and Advanced sections.
- Each section has an independent chevron that folds only that section's controls.
- The Develop action remains visible regardless of section state.
- Each section's state persists independently in `localStorage`.

## Verification

- Confirm the icon assignment, size, weight, default cream, and active gold states.
- Confirm each left and right section opens and closes independently and persists after reload.
- Confirm both rails remain full width in every section state.
- Confirm prompt image upload, thumbnail, removal, AI description, and inline errors.
- Confirm workflow selection and generation logic remain unchanged.
- Run JavaScript syntax validation and the complete Python test suite before deployment.
