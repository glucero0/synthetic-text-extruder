"""Reconstruct a readable article PDF from magazine-style page scans."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .creation_utils import extract_json_object

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[Any], None]

PAGE_PROMPT = """You are analyzing one scanned magazine page.
Follow the user instructions. Default: skip advertisements; keep editorial text.

Return ONLY a JSON object (no markdown) with this shape:
{
  "pageKind": "editorial" | "ad" | "mixed" | "blank",
  "skipPage": true or false,
  "skipReason": "short reason if skipPage is true, else empty",
  "bodyText": "editorial text in reading order, no ad copy",
  "heading": "optional article heading visible on this page",
  "photos": [
    {
      "box": [x, y, w, h],
      "caption": "caption next to the photo or empty"
    }
  ]
}
box values are fractions from 0 to 1 relative to the full page (origin top-left).
skipPage should be true for full-page ads, classifieds, or subscription cards.
If mixed, omit ad copy from bodyText and still include editorial photos.
Do not invent text that is not on the page.
"""


def normalize_page_analysis(data: dict[str, Any] | None) -> dict[str, Any]:
    raw = data if isinstance(data, dict) else {}
    kind = str(raw.get("pageKind") or "").strip().lower()
    if kind not in {"editorial", "ad", "mixed", "blank"}:
        kind = "editorial"
    skip = bool(raw.get("skipPage"))
    if kind in {"ad", "blank"}:
        skip = True
    photos: list[dict[str, Any]] = []
    for item in raw.get("photos") or []:
        if not isinstance(item, dict):
            continue
        box = _normalize_box(item.get("box"))
        if not box:
            continue
        photos.append(
            {
                "box": box,
                "caption": str(item.get("caption") or "").strip()[:400],
            }
        )
    body = str(raw.get("bodyText") or "").strip()
    heading = str(raw.get("heading") or "").strip()[:200]
    reason = str(raw.get("skipReason") or "").strip()[:300]
    if skip and not reason:
        reason = "Classified as an advertisement" if kind == "ad" else "Skipped page"
    return {
        "pageKind": kind,
        "skipPage": skip,
        "skipReason": reason,
        "bodyText": body,
        "heading": heading,
        "photos": photos,
    }


def parse_page_analysis(text: str) -> dict[str, Any]:
    parsed = extract_json_object(text or "")
    if parsed is None and (text or "").strip():
        return normalize_page_analysis(
            {
                "pageKind": "editorial",
                "skipPage": False,
                "bodyText": (text or "").strip(),
            }
        )
    return normalize_page_analysis(parsed)


def crop_photo_boxes(
    image_path: Path,
    photos: list[dict[str, Any]],
    *,
    dest_dir: Path,
    stem: str,
) -> list[dict[str, Any]]:
    """Crop normalized boxes from a scan. Returns photos with photoPath set."""
    if not photos:
        return []
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required to extract photos from scans. Run: pip install pillow"
        ) from exc
    if not image_path.is_file():
        return []
    dest_dir.mkdir(parents=True, exist_ok=True)
    image = Image.open(image_path)
    image.load()
    width, height = image.size
    if width < 2 or height < 2:
        return []
    out: list[dict[str, Any]] = []
    for index, photo in enumerate(photos):
        box = photo.get("box") or []
        if len(box) != 4:
            continue
        x, y, w, h = box
        left = int(max(0, min(width - 1, round(x * width))))
        top = int(max(0, min(height - 1, round(y * height))))
        right = int(max(left + 1, min(width, round((x + w) * width))))
        bottom = int(max(top + 1, min(height, round((y + h) * height))))
        if right - left < 8 or bottom - top < 8:
            continue
        crop = image.crop((left, top, right, bottom)).convert("RGB")
        dest = dest_dir / f"{stem}_photo_{index + 1}.jpg"
        crop.save(dest, format="JPEG", quality=90)
        item = dict(photo)
        item["photoPath"] = dest
        item["width"] = crop.width
        item["height"] = crop.height
        out.append(item)
    return out


def _normalize_box(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    nums: list[float] = []
    for item in value:
        try:
            nums.append(float(item))
        except (TypeError, ValueError):
            return None
    x, y, w, h = nums
    if w <= 0 or h <= 0:
        return None
    x = min(max(x, 0.0), 1.0)
    y = min(max(y, 0.0), 1.0)
    w = min(max(w, 0.0), 1.0 - x)
    h = min(max(h, 0.0), 1.0 - y)
    if w < 0.02 or h < 0.02:
        return None
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]
