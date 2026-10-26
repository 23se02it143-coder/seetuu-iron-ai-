"""Turn an uploaded photo/painting into the hero background: crop, upscale, and grade it into the
site's exact crimson palette (the same gradient map scripts/render_scenes.py uses), so it blends into
the WebGL lightning instead of sitting on top of it as a flat rectangle.

Usage: python scripts/hero_from_photo.py <input_image> [--crop L,T,R,B fractions] [--out web/static/img/hero.jpg]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

F = np.float32
ROOT = Path(__file__).resolve().parents[1]

# the exact duotone used across every render on the site (scripts/render_scenes.py: post())
STOPS = np.array([0.0, 0.16, 0.36, 0.58, 0.8, 1.0], F)
COLS = np.array([(6, 3, 5), (30, 6, 15), (77, 6, 28), (176, 52, 82), (240, 116, 138), (245, 236, 230)], F) / 255


def upscale(im: Image.Image, target_w: int) -> Image.Image:
    """Two-pass Lanczos upscale with a light unsharp mask each pass, so a small source photo
    doesn't come out soft or blocky at hero size."""
    w, h = im.size
    while w < target_w:
        w2, h2 = min(target_w, w * 2), round(h * min(2, target_w / w))
        im = im.resize((w2, h2), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=2, percent=70, threshold=2))
        w, h = im.size
    return im


def grade(im: Image.Image, *, crush: float, lift_faces: float) -> Image.Image:
    x = np.asarray(im, F) / 255
    lum = x @ np.array([0.3, 0.59, 0.11], F)
    # push shadows down and stretch the midtones so figures separate from a near-black background
    lum = np.clip((lum - crush) / max(1e-3, 1 - crush), 0, 1) ** 0.85
    lum = np.clip(lum * (1 + lift_faces) - lift_faces * 0.15, 0, 1)
    graded = np.stack([np.interp(lum, STOPS, COLS[:, c]) for c in range(3)], -1)
    # keep a sliver of the original hue/detail so it still reads as a painting, not a flat gradient
    out = 0.86 * graded + 0.14 * x * np.array([1.15, 0.8, 0.85], F)
    return Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8))


def text_band(im: Image.Image, *, band_center: float, band_half_height: float, strength: float) -> Image.Image:
    """A published headline sits mid-frame with mix-blend-mode:screen, which only goes darker where the
    image itself is dark - so darken a horizontal band through that vertical position independent of the
    corner vignette, tapering back to full brightness above and below it."""
    w, h = im.size
    x = np.asarray(im, F) / 255
    yy = np.mgrid[0:h, 0:w][0] / h
    dist = np.clip(np.abs(yy - band_center) / band_half_height, 0, 1)
    mult = 1 - strength * (1 - dist) ** 1.6
    x *= mult[..., None]
    return Image.fromarray((np.clip(x, 0, 1) * 255).astype(np.uint8))


def vignette_and_grain(im: Image.Image, seed: int = 7) -> Image.Image:
    w, h = im.size
    x = np.asarray(im, F) / 255
    yy, xx = np.mgrid[0:h, 0:w]
    # heavier fade on the left/top (behind the nav and headline) than the right, so the scene
    # still reads on the side the eye lands on first
    fx = (xx / w - 0.62) * 1.5
    fy = (yy / h - 0.42) * 1.7
    vig = 1 - np.clip(fx * fx + fy * fy, 0, 1) * 0.72
    edge = 1 - np.clip(((xx / w - 0.5) * 2.1) ** 8 + ((yy / h - 0.5) * 2.3) ** 8, 0, 1)
    x *= np.clip(vig * (0.35 + 0.65 * edge), 0.05, 1)[..., None]
    rng = np.random.default_rng(seed)
    x += rng.normal(0, 0.014, (h, w, 1)).astype(F)
    return Image.fromarray((np.clip(x, 0, 1) * 255).astype(np.uint8))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--crop", default="", help="left,top,right,bottom as fractions 0-1, e.g. 0.03,0.05,0.97,0.9")
    ap.add_argument("--out", default=str(ROOT / "web/static/img/hero.jpg"))
    ap.add_argument("--width", type=int, default=2400)
    ap.add_argument("--crush", type=float, default=0.24)
    ap.add_argument("--lift", type=float, default=0.14)
    args = ap.parse_args()

    im = Image.open(args.input).convert("RGB")
    if args.crop:
        l, t, r, b = (float(v) for v in args.crop.split(","))
        w, h = im.size
        im = im.crop((int(l * w), int(t * h), int(r * w), int(b * h)))

    target_h = round(args.width / 2)  # same 2:1 frame as the other hero renders
    w, h = im.size
    scale = max(args.width / w, target_h / h)
    im = im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    w, h = im.size
    im = im.crop(((w - args.width) // 2, max(0, (h - target_h) // 3), (w - args.width) // 2 + args.width, max(0, (h - target_h) // 3) + target_h))

    im = upscale(im, args.width)  # re-sharpen after the crop/resize softened it
    im = ImageEnhance.Contrast(im).enhance(1.08)
    im = ImageEnhance.Color(im).enhance(0.9)
    im = grade(im, crush=args.crush, lift_faces=args.lift)
    im = text_band(im, band_center=0.46, band_half_height=0.42, strength=0.58)
    im = vignette_and_grain(im)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    im.save(args.out, quality=90, optimize=True, progressive=True)
    print("saved", args.out, im.size, f"{Path(args.out).stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
