# Atelier Sidebar Icon Set Design

## Goal

Replace the sidebar's Unicode placeholders with the consistent outlined icon set shown in the approved Atelier Studio mockup.

## Icon Map

- Brand: stylized Atelier triangular `A` mark.
- Image group: framed landscape.
- Carousel Maker: twin mountain peaks.
- Image-to-image workflows: framed landscape.
- Text-to-image workflows: serif `T` glyph rendered as SVG paths/lines.
- Video group and LTX: filmstrip.
- Animate: play button inside a rounded frame.
- Advanced group: outlined gear.
- Motion Control: framed landscape.
- Instaraw: framed lens/image symbol.

## Rendering

- Icons are inline SVG, not external images or an icon-library dependency.
- Every icon uses a 24×24 viewBox, round line joins, and consistent optical weight.
- Icons inherit `currentColor`: muted cream normally, bright cream on hover, and gold for the selected workflow.
- Group icons are slightly larger than workflow icons.
- SVGs are decorative and hidden from assistive technology; the adjacent workflow text remains the accessible label.

## Scope and Verification

- Existing workflow IDs, click handlers, visibility settings, and generation behavior remain unchanged.
- Verify every visible sidebar entry receives the correct icon.
- Verify active, hover, and disabled color states.
- Run the JavaScript syntax check and Python test suite before deployment.
