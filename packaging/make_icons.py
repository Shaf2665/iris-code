"""Generate the Iris Code app icon as PNG + ICO (and ICNS where supported).

A 'forge' mark: an ember-gradient rounded square with the brand spark (✦) in
champagne gold, plus a small secondary spark. Run from the repo root:

    python packaging/make_icons.py

Outputs packaging/icon.png (1024²), packaging/icon.ico, and attempts
packaging/icon.icns (Pillow's ICNS writer; macOS builds regenerate it natively).
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SIZE = 1024

# Brand palette (mirrors gui/style.py).
EMBER = (255, 138, 76)
EMBER_DEEP = (181, 83, 42)
CHARCOAL = (21, 23, 28)
GOLD = (240, 214, 144)
CREAM = (255, 244, 222)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _gradient(size: int) -> Image.Image:
    """Diagonal ember→deep→charcoal gradient."""
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            if t < 0.5:
                c = _lerp(EMBER, EMBER_DEEP, t / 0.5)
            else:
                c = _lerp(EMBER_DEEP, CHARCOAL, (t - 0.5) / 0.5)
            px[x, y] = c
    return img


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def _spark(draw: ImageDraw.ImageDraw, cx, cy, r, color, waist=0.18):
    """A 4-point sparkle (concave diamond) centred at (cx, cy)."""
    w = r * waist
    draw.polygon(
        [(cx, cy - r), (cx + w, cy - w), (cx + r, cy), (cx + w, cy + w),
         (cx, cy + r), (cx - w, cy + w), (cx - r, cy), (cx - w, cy - w)],
        fill=color,
    )


def build() -> str:
    base = _gradient(SIZE).convert("RGBA")
    base.putalpha(_rounded_mask(SIZE, radius=int(SIZE * 0.22)))

    draw = ImageDraw.Draw(base)
    cx, cy = SIZE * 0.52, SIZE * 0.50
    # Soft glow behind the main spark.
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([cx - SIZE * 0.34, cy - SIZE * 0.34, cx + SIZE * 0.34, cy + SIZE * 0.34],
               fill=(255, 200, 140, 60))
    base.alpha_composite(glow)

    draw = ImageDraw.Draw(base)
    _spark(draw, cx, cy, r=SIZE * 0.30, color=CREAM)
    _spark(draw, cx, cy, r=SIZE * 0.20, color=GOLD)
    # Secondary small spark, upper-left.
    _spark(draw, SIZE * 0.27, SIZE * 0.28, r=SIZE * 0.085, color=CREAM)

    png = os.path.join(HERE, "icon.png")
    base.save(png)

    ico = os.path.join(HERE, "icon.ico")
    base.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                          (128, 128), (256, 256)])

    try:
        icns = os.path.join(HERE, "icon.icns")
        base.save(icns)
        made_icns = True
    except Exception:
        made_icns = False

    return f"wrote icon.png, icon.ico{' , icon.icns' if made_icns else ' (icns skipped)'}"


if __name__ == "__main__":
    print(build())
