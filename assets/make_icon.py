"""Generate assets/app.ico - the app/installer/exe icon.

Original artwork (not the Pulsar brand logo): a battery with a lightning
'pulse' bolt on a violet-to-indigo tile. Drawn at 4x and downsampled for clean
antialiasing, then packed into a multi-resolution .ico.

Run:  python assets/make_icon.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

SS = 4  # supersampling factor
SIZES = [16, 24, 32, 48, 64, 128, 256]

VIOLET = (124, 58, 237)   # #7C3AED
INDIGO = (79, 70, 229)    # #4F46E5
WHITE = (255, 255, 255, 255)
BOLT = (250, 204, 21, 255)  # amber


def _rounded_rect(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def render(size: int) -> Image.Image:
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Background tile with a vertical violet->indigo gradient.
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    for y in range(S):
        t = y / max(1, S - 1)
        r = round(VIOLET[0] + (INDIGO[0] - VIOLET[0]) * t)
        g = round(VIOLET[1] + (INDIGO[1] - VIOLET[1]) * t)
        b = round(VIOLET[2] + (INDIGO[2] - VIOLET[2]) * t)
        for x in range(S):
            tile.putpixel((x, y), (r, g, b, 255))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
    img.paste(tile, (0, 0), mask)

    # Battery body (horizontal), white outline with a rounded shell.
    bw = int(S * 0.60)
    bh = int(S * 0.34)
    bx = int(S * 0.16)
    by = (S - bh) // 2
    stroke = max(SS, int(S * 0.045))
    _rounded_rect(d, [bx, by, bx + bw, by + bh], radius=int(bh * 0.28), fill=WHITE)
    # Hollow out the inside to leave an outline.
    inset = stroke
    inner = (bx + inset, by + inset, bx + bw - inset, by + bh - inset)
    d.rounded_rectangle(inner, radius=int(bh * 0.20), fill=(0, 0, 0, 0))
    # Punch inner back to gradient by pasting the tile through an inner mask.
    inner_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(inner_mask).rounded_rectangle(inner, radius=int(bh * 0.20), fill=255)
    img.paste(tile, (0, 0), inner_mask)

    # Positive terminal nub on the right.
    nub_w = int(S * 0.05)
    nub_h = int(bh * 0.42)
    nx = bx + bw
    ny = (S - nub_h) // 2
    _rounded_rect(d, [nx, ny, nx + nub_w, ny + nub_h], radius=int(nub_w * 0.4), fill=WHITE)

    # Lightning 'pulse' bolt inside the battery.
    cx = bx + bw * 0.5
    cy = S * 0.5
    u = bh * 0.5
    bolt = [
        (cx + 0.15 * u, cy - 0.85 * u),
        (cx - 0.45 * u, cy + 0.12 * u),
        (cx - 0.02 * u, cy + 0.12 * u),
        (cx - 0.15 * u, cy + 0.85 * u),
        (cx + 0.45 * u, cy - 0.12 * u),
        (cx + 0.02 * u, cy - 0.12 * u),
    ]
    d.polygon(bolt, fill=BOLT)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    master = render(256)  # save from the largest; Pillow downsamples the rest.
    out = os.path.join(here, "app.ico")
    master.save(out, format="ICO", sizes=[(s, s) for s in SIZES])
    # Also drop a PNG for READMEs / previews.
    master.save(os.path.join(here, "app.png"))
    print(f"Wrote {out} and app.png ({', '.join(str(s) for s in SIZES)})")


if __name__ == "__main__":
    main()
