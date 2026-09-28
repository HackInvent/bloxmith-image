# IMAGE GEN artwork

This image is a concept illustration of the `image` BloxSmith block.
The implemented function is: Generates one image from an input instruction and exports its path.

- `cover.png`: selected original square PNG, copied byte for byte.
- `thumbnail.webp`: 320 × 320 WebP export for the README and catalog cards.
- Accent: magenta pink.
- Geometry reference: the scanner pilot cover. It is a visual reference only;
  its block-specific content was replaced.
- Creation: built-in image generation tool, 2026-09-28.
- License: [Apache-2.0](../LICENSE), like the rest of this block repository.

The image is not a Studio screenshot or a description of additional controls.
The artwork is documentation; its presence does not register it automatically
with Studio or the website. The block version and runtime contract are unchanged.

Export command (ImageMagick):

```sh
convert media/cover.png -thumbnail 320x320 -strip -quality 88 -define webp:method=6 media/thumbnail.webp
```

## Exact generation prompt

```text
Use case: stylized-concept.
Asset type: one square BloxSmith block cover illustration, to be read as a small catalog thumbnail.
Input image: the scanner pilot cover is a STYLE AND GEOMETRY REFERENCE ONLY. Use its centered graphite and steel industrial cube, exact front/top/right three-quarter perspective, reinforced corners, neat vents and ports, plain near-white background, subtle grounded shadow, upper-left light, scale and generous margins. Replace every subject-specific icon, display and accent from the reference; create a new original cover for image.
Primary request: visualize the real software block role accurately: Generates one image from an input instruction and exports its path.
Main roof symbol: one large framed landscape-image symbol with a small sparkle.
Front panel: a prominent upper title plate, and directly below it an instruction card leads to one newly rendered image card and a small file-output glyph. Keep the concept legible at 320 pixels. Only a few large functional details; no microtext.
Color palette: one dominant restrained magenta pink accent, otherwise charcoal housing and brushed steel structural edges. The palette identifies a family but the symbols must distinguish the block without color.
Style/medium: polished, crisp industrial pixel-art product illustration with stepped edges and deliberate pixel clusters. Restrained glow, tactile surfaces, no photorealistic rendering.
Composition: one isolated complete near-cubical module on a 1:1 square canvas, about 84 percent of frame, no crop, no extra scene or props; match the pilot's geometry and consistent clean framing.
Text (verbatim): "IMAGE GEN" exactly once in bold white uppercase pixel lettering on the front title plate. This is the ONLY writing in the picture. Spell it exactly; never add a subtitle, version, badge, copied text, fake small labels, watermark or slogan. The README carries the full technical name.
Accuracy constraints: image viewer only, camera capture, photo editor, gallery. The picture should communicate function through simple symbols and one primary flow. Do not copy the pilot's icon, title, faders, waveform, code screen or scanning page unless actually relevant. No cats, people, desks, mascots, official third-party logos, detached modules or floating objects.
```
