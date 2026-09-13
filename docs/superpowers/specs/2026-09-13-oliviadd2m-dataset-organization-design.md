# OliviaDD2m Dataset Organization

## Goal

Normalize every image in `E:\DataSet\MyNew` for LoRA training and add one matching caption file per image.

## Naming

All image files will be renamed sequentially in current alphabetical order:

- `oliviaDD2m_001.<extension>` through `oliviaDD2m_069.<extension>`
- The existing `.png` or `.jpeg` extension is retained.
- A paired caption file uses the same stem, for example `oliviaDD2m_001.txt`.

## Captions

Every caption begins with the exact LoRA trigger `oliviaDD2m, `. The remaining caption is a concise visual description inferred from the source filename, including indoor setting, pose, outfit where evident from the name, and general photographic style. Captions avoid personal-identifying claims, text rendered within images, brands, and sexualized descriptions.

## Safety and validation

- Rename through collision-safe temporary names so no image is overwritten.
- Never replace an existing `.txt` caption; stop if a destination exists.
- Verify 69 image files and 69 matching `.txt` files after completion.
