"""Generate GreenLit brand assets (mark, full logo, favicons).

The real artwork was not present in the workspace, so this script draws the brand mark
described in the specification: a green ring-shaped "G" arm combined with a dark slate "L"
and a glowing green dot. Run from the repository root:

    python scripts/generate_brand_assets.py [--force]

It refuses to overwrite existing root artwork unless --force is passed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
GREEN = (26, 192, 58, 255)
DARK_SLATE = (40, 49, 58, 255)
LIGHT_BG = (255, 255, 255, 255)
CANVAS = 1024

FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def _glow(color: tuple[int, int, int, int], radius: int) -> Image.Image:
    """Soft radial halo, fully transparent at its edge, centred on its own canvas."""
    spread = radius * 2
    size = 2 * (radius + spread) + 4
    centre = size / 2
    pixels: list[tuple[int, int, int, int]] = []
    for y in range(size):
        for x in range(size):
            distance = ((x - centre) ** 2 + (y - centre) ** 2) ** 0.5
            fade = max(0.0, 1.0 - distance / (radius + spread))
            pixels.append((*color[:3], int(90 * fade**2.2)))
    layer = Image.new("RGBA", (size, size))
    layer.putdata(pixels)
    return layer.filter(ImageFilter.GaussianBlur(4))


def draw_mark(size: int = CANVAS) -> Image.Image:
    """Draw the GreenLit symbol on a transparent canvas."""
    scale = size / CANVAS
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    def s(value: float) -> int:
        return round(value * scale)

    # Green "G": a thick ring, open above the crossbar that meets the ring on the east.
    ring = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ring_draw = ImageDraw.Draw(ring)
    cx, cy, outer, thickness = s(410), s(512), s(290), s(106)
    ring_draw.arc(
        (cx - outer, cy - outer, cx + outer, cy + outer),
        start=2,
        end=300,
        fill=GREEN,
        width=thickness,
    )
    ring_draw.rounded_rectangle(
        (s(470), s(459), s(700), s(565)), radius=s(53), fill=GREEN
    )
    image.alpha_composite(ring)

    # Dark slate "L" tucked in front of the G's right side.
    l_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    l_draw = ImageDraw.Draw(l_layer)
    l_draw.rounded_rectangle((s(636), s(232), s(758), s(792)), radius=s(26), fill=DARK_SLATE)
    l_draw.rounded_rectangle((s(636), s(672), s(892), s(792)), radius=s(26), fill=DARK_SLATE)
    image.alpha_composite(l_layer)

    # Glowing green dot above the L, like a status light.
    dot_cx, dot_cy, dot_r = s(856), s(300), s(46)
    glow = _glow(GREEN, dot_r)
    image.alpha_composite(glow, dest=(dot_cx - glow.width // 2, dot_cy - glow.height // 2))
    dot = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(dot).ellipse(
        (dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r), fill=GREEN
    )
    image.alpha_composite(dot)
    return image


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def draw_full_logo() -> Image.Image:
    """Mark plus wordmark on a light background (README / printed reports)."""
    width, height = 1800, 560
    image = Image.new("RGBA", (width, height), LIGHT_BG)
    mark = draw_mark(420)
    image.alpha_composite(mark, dest=(70, 70))

    draw = ImageDraw.Draw(image)
    font = _font(200)
    x = 560
    baseline = 180
    for text, color in (("Green", GREEN[:3]), ("Lit", DARK_SLATE[:3])):
        draw.text((x, baseline), text, font=font, fill=color)
        x += int(draw.textlength(text, font=font))
    tagline_font = _font(52)
    draw.text(
        (566, 400),
        "Pre-launch testing for LLM apps",
        font=tagline_font,
        fill=(90, 101, 112),
    )
    return image


def _write(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print(f"wrote {path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing root logo files",
    )
    args = parser.parse_args()

    root_mark = ROOT / "GreenLit_mark.png"
    root_logo = ROOT / "GreenLit_logo_full_light_bg.png"
    if (root_mark.exists() or root_logo.exists()) and not args.force:
        print("Root logo files already exist; pass --force to regenerate.", file=sys.stderr)
        return 1

    mark = draw_mark()
    logo = draw_full_logo()

    _write(mark, root_mark)
    _write(logo, root_logo)
    _write(mark, ROOT / "frontend" / "public" / "greenlit-mark.png")
    _write(mark, ROOT / "frontend" / "src" / "assets" / "greenlit-mark.png")
    _write(logo, ROOT / "docs" / "greenlit-logo.png")

    for px in (16, 32):
        icon = ROOT / "frontend" / "public" / f"favicon-{px}x{px}.png"
        _write(mark.resize((px, px), Image.LANCZOS), icon)
    _write(
        mark.resize((180, 180), Image.LANCZOS),
        ROOT / "frontend" / "public" / "apple-touch-icon.png",
    )

    ico_path = ROOT / "frontend" / "public" / "favicon.ico"
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    mark.save(ico_path, sizes=[(16, 16), (32, 32), (48, 48)])
    print(f"wrote {ico_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
