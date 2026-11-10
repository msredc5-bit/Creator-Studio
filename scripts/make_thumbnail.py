#!/usr/bin/env python3
"""Build a 1280x720 YouTube thumbnail from an image + short text.

Stdlib + PIL only, $0, no network, no keys. Full-bleed image
(cover-cropped to 16:9), a dark gradient at the bottom, bold
white text (max 3 words) on top of it.

Usage:
  python3 scripts/make_thumbnail.py --image scene1.jpg \
      --text "5 EDITS TESTED" --out thumbnail.jpg

The runner (stage 3 / stage 4) calls build_thumbnail() directly;
the CLI is for the owner or the agent by hand. Text longer than
3 words is cut to the first 3 (noted in the returned dict) —
thumbnails hold at most 3 words (ToolPilot VOICE.md rule).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THUMB_W, THUMB_H = 1280, 720
MAX_WORDS = 3
FONT_BOLD = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"


def shorten_text(text: str, max_words: int = MAX_WORDS) -> tuple[str, str]:
    """Uppercase text, cut to max_words. Returns (text, note)."""
    words = (text or "").split()
    used = " ".join(words[:max_words]).upper()
    note = ""
    if len(words) > max_words:
        note = (f"text had {len(words)} words; only the first "
                f"{max_words} were used")
    return used, note


def _fit_font(draw, text: str, max_w: int, start: int = 110):
    """Largest bold size at which the text fits inside max_w."""
    from PIL import ImageFont
    size = start
    while size > 24:
        try:
            font = ImageFont.truetype(FONT_BOLD, size)
        except OSError:
            return ImageFont.load_default()
        bb = draw.textbbox((0, 0), text, font=font, stroke_width=2)
        if bb[2] - bb[0] <= max_w:
            return font
        size -= 4
    try:
        return ImageFont.truetype(FONT_BOLD, 24)
    except OSError:
        return ImageFont.load_default()


def build_thumbnail(image_path: str | Path, text: str,
                    out_path: str | Path) -> dict:
    """Build the thumbnail. Returns a result dict, never raises.

    {"ok": True, "path", "text", "note"} on success;
    {"ok": False, "error"} when the image cannot be read or the
    file cannot be written.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return {"ok": False, "error": "PIL not available"}
    src = Path(image_path)
    if not src.exists():
        return {"ok": False, "error": f"image not found: {src}"}
    used_text, note = shorten_text(text)
    if not used_text:
        return {"ok": False, "error": "no thumbnail text given"}
    try:
        img = Image.open(src).convert("RGB")
    except Exception as exc:  # noqa: BLE001 - record, don't crash
        return {"ok": False, "error": f"image could not be read ({exc})"}
    # Cover-crop to 16:9, centred.
    target_ratio = THUMB_W / THUMB_H
    w, h = img.size
    if w / h > target_ratio:
        new_w = int(h * target_ratio)
        x0 = (w - new_w) // 2
        img = img.crop((x0, 0, x0 + new_w, h))
    else:
        new_h = int(w / target_ratio)
        y0 = (h - new_h) // 2
        img = img.crop((0, y0, w, y0 + new_h))
    img = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
    # Dark gradient at the bottom: transparent at ~55% height,
    # nearly opaque black at the bottom edge.
    overlay = Image.new("RGBA", (THUMB_W, THUMB_H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    top = int(THUMB_H * 0.55)
    for y in range(top, THUMB_H):
        alpha = int(200 * (y - top) / max(1, THUMB_H - top))
        od.line([(0, y), (THUMB_W, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    # Bold white text, centred, sitting on the gradient.
    draw = ImageDraw.Draw(img)
    font = _fit_font(draw, used_text, int(THUMB_W * 0.92))
    bb = draw.textbbox((0, 0), used_text, font=font, stroke_width=2)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    x = (THUMB_W - tw) // 2 - bb[0]
    y = THUMB_H - th - 48 - bb[1]
    draw.text((x, y), used_text, font=font, fill=(255, 255, 255),
              stroke_width=2, stroke_fill=(0, 0, 0))
    try:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, "JPEG", quality=88)
    except Exception as exc:  # noqa: BLE001 - record, don't crash
        return {"ok": False, "error": f"thumbnail could not be written ({exc})"}
    return {"ok": True, "path": str(out_path), "text": used_text,
            "note": note}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Build a 1280x720 YouTube thumbnail.")
    ap.add_argument("--image", required=True,
                    help="Source image (a still, or a video frame).")
    ap.add_argument("--text", required=True,
                    help="Thumbnail text (max 3 words).")
    ap.add_argument("--out", required=True,
                    help="Output JPG path.")
    args = ap.parse_args(argv)
    res = build_thumbnail(args.image, args.text, args.out)
    print(json.dumps(res))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
