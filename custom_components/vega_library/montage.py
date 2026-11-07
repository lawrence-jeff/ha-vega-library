"""Build one picture out of several book covers."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

# Typical book cover aspect ratio (width / height), used for the "+N" tile and the fixed canvas width.
COVER_ASPECT = 0.67


def build_montage(
    images: list[bytes | None],
    height: int,
    gap: int,
    columns: int,
    max_covers: int,
) -> bytes:
    """Lay covers out in a centred grid and return PNG bytes.

    The canvas is always a full row wide, so covers keep the same on-screen size
    whether there are 2 holds or 8. If there are more covers than ``max_covers``
    the last slot becomes a "+N" tile.
    """
    covers: list[Image.Image] = []
    for raw in images:
        if not raw:
            continue
        try:
            im = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception:  # noqa: BLE001 - any decode problem just skips the cover
            continue
        if im.width < 20 or im.height < 20:  # Syndetics returns a 1x1 gif when it has no cover
            continue
        covers.append(im.resize((max(1, round(im.width * height / im.height)), height)))

    tile_width = round(height * COVER_ASPECT)

    if not covers:
        canvas = Image.new("RGBA", (columns * tile_width + gap * (columns - 1), height // 2), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text((10, height // 4 - 5), "No holds ready", fill=(150, 150, 150, 255))
        return _png(canvas)

    if len(covers) > max_covers:
        extra = len(covers) - (max_covers - 1)
        covers = covers[: max_covers - 1]
        covers.append(_more_tile(extra, tile_width, height))

    rows = [covers[i : i + columns] for i in range(0, len(covers), columns)]
    row_widths = [sum(c.width for c in row) + gap * (len(row) - 1) for row in rows]
    width = max(max(row_widths), columns * tile_width + gap * (columns - 1))
    canvas = Image.new(
        "RGBA", (width, len(rows) * height + (len(rows) - 1) * gap), (0, 0, 0, 0)
    )
    for r, row in enumerate(rows):
        x = (width - row_widths[r]) // 2
        for cover in row:
            canvas.paste(cover, (x, r * (height + gap)))
            x += cover.width + gap
    return _png(canvas)


def _more_tile(extra: int, width: int, height: int) -> Image.Image:
    tile = Image.new("RGB", (width, height), (60, 60, 60))
    draw = ImageDraw.Draw(tile)
    try:
        font = ImageFont.load_default(size=height // 4)
    except TypeError:  # older Pillow without a sized default font
        font = ImageFont.load_default()
    label = f"+{extra}"
    box = draw.textbbox((0, 0), label, font=font)
    draw.text(
        ((width - (box[2] - box[0])) // 2 - box[0], (height - (box[3] - box[1])) // 2 - box[1]),
        label,
        fill=(230, 230, 230),
        font=font,
    )
    return tile


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
