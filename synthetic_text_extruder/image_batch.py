"""Parse Image-Editor-style filters from a prompt and apply them to stills."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .video_edit import DEFAULT_FILTERS, has_active_filters, normalize_filters

logger = logging.getLogger(__name__)

_EVERY_RE = re.compile(
    r"\b(?:every|each|all|these|those|folder|batch)\b", re.IGNORECASE
)


def parse_filters_from_prompt(prompt: str) -> dict[str, Any]:
    """Best-effort Image Editor filter dict from a natural-language prompt."""
    text = (prompt or "").strip().lower()
    if not text:
        return {}
    out: dict[str, Any] = dict(DEFAULT_FILTERS)

    def _num_for(*names: str) -> float | None:
        for name in names:
            match = re.search(
                rf"{re.escape(name)}\s*(?:to|by|=|:)?\s*([+-]?\d+(?:\.\d+)?)",
                text,
            )
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    return None
            match = re.search(
                rf"([+-]?\d+(?:\.\d+)?)\s*%?\s*{re.escape(name)}",
                text,
            )
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    return None
        return None

    if re.search(r"\b(?:gr[ae]yscale|black\s+and\s+white|b\s*/\s*w)\b", text):
        out["grayscale"] = True
    if re.search(r"\bsepia\b", text):
        amount = _num_for("sepia")
        out["sepia"] = int(amount) if amount is not None else 80
    if re.search(r"\bsharpen(?:ed|ing)?\b", text):
        out["sharpen"] = True
    if re.search(r"\binvert(?:ed)?\b", text):
        out["invert"] = 100
    brightness = _num_for("brightness")
    if brightness is not None:
        out["brightness"] = int(brightness)
    elif re.search(r"\b(?:brighter|lighten)\b", text):
        out["brightness"] = 20
    elif re.search(r"\b(?:darker|darken)\b", text):
        out["brightness"] = -20
    contrast = _num_for("contrast")
    if contrast is not None:
        out["contrast"] = int(contrast)
    saturation = _num_for("saturation", "saturate")
    if saturation is not None:
        out["saturation"] = int(saturation)
    elif re.search(r"\bdesaturat", text):
        out["saturation"] = 40
    hue = _num_for("hue")
    if hue is not None:
        out["hueRotate"] = int(hue)
    blur = _num_for("blur")
    if blur is not None:
        out["blur"] = float(blur)
    elif re.search(r"\bblur(?:ry|red)?\b", text):
        out["blur"] = 2
    exposure = _num_for("exposure")
    if exposure is not None:
        out["exposure"] = int(exposure)
    gamma = _num_for("gamma")
    if gamma is not None:
        out["gamma"] = float(gamma)
    vignette = _num_for("vignette")
    if vignette is not None:
        out["vignette"] = int(vignette)
    elif re.search(r"\bvignette\b", text):
        out["vignette"] = 40
    return out if has_active_filters(out) else {}


def prompt_looks_like_filters(prompt: str) -> bool:
    text = (prompt or "").strip()
    if not text:
        return False
    if parse_filters_from_prompt(text):
        return True
    return bool(
        re.search(
            r"\b(?:filter|filters|preset)\b",
            text,
            re.IGNORECASE,
        )
        and _EVERY_RE.search(text)
    )


def apply_still_filters(
    src: str | Path,
    dest: str | Path,
    filters: dict[str, Any] | None,
) -> Path:
    """Apply still-image filters with Pillow (ffmpeg is not required)."""
    source = Path(src)
    out = Path(dest)
    if not source.is_file():
        raise FileNotFoundError(f"Image not found: {source}")
    out.parent.mkdir(parents=True, exist_ok=True)
    settings = normalize_filters(filters)
    if not has_active_filters(settings):
        out.write_bytes(source.read_bytes())
        return out
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required for batch image filters. Run: pip install pillow"
        ) from exc

    image = Image.open(source)
    image.load()
    work = image.convert("RGBA") if image.mode in {"P", "LA"} else image.convert("RGB")
    if work.mode != "RGB":
        work = work.convert("RGB")

    brightness = 1.0 + settings["brightness"] / 100.0 + (settings["exposure"] / 100.0) * 0.5
    if abs(brightness - 1.0) > 1e-6:
        work = ImageEnhance.Brightness(work).enhance(max(0.0, brightness))
    contrast = 1.0 + settings["contrast"] / 100.0
    if abs(contrast - 1.0) > 1e-6:
        work = ImageEnhance.Contrast(work).enhance(max(0.0, contrast))
    saturation = settings["saturation"] / 100.0
    if abs(saturation - 1.0) > 1e-6 and not settings["grayscale"]:
        work = ImageEnhance.Color(work).enhance(max(0.0, saturation))
    if abs(settings["gamma"] - 1.0) > 1e-6:
        gamma = max(0.1, float(settings["gamma"]))
        work = work.point(lambda i: int(255 * ((i / 255.0) ** (1.0 / gamma))))
    if settings["grayscale"]:
        work = ImageOps.grayscale(work).convert("RGB")
    if settings["invert"] >= 50:
        work = ImageOps.invert(work.convert("RGB"))
    if settings["sepia"] > 0:
        work = _apply_sepia(work, settings["sepia"] / 100.0)
    if settings["blur"] > 0:
        work = work.filter(ImageFilter.GaussianBlur(radius=min(20.0, float(settings["blur"]))))
    if settings["sharpen"]:
        work = work.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
    if settings["vignette"] > 0:
        work = _apply_vignette(work, settings["vignette"] / 100.0)
    if settings["tintRed"] or settings["tintGreen"] or settings["tintBlue"]:
        work = _apply_tint(
            work,
            settings["tintRed"] / 100.0,
            settings["tintGreen"] / 100.0,
            settings["tintBlue"] / 100.0,
        )

    suffix = out.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        work = work.convert("RGB")
        work.save(out, format="JPEG", quality=92)
    elif suffix == ".webp":
        work.save(out, format="WEBP", quality=90)
    else:
        work.save(out, format="PNG")
    return out


def _apply_sepia(image: Any, amount: float) -> Any:
    from PIL import Image, ImageOps

    amount = max(0.0, min(1.0, amount))
    src = image.convert("RGB")
    gray = ImageOps.grayscale(src)
    sepia = ImageOps.colorize(gray, "#2b1b0e", "#ffe2b3")
    return Image.blend(src, sepia.convert("RGB"), amount)


def _apply_vignette(image: Any, amount: float) -> Any:
    from PIL import Image, ImageDraw, ImageFilter

    amount = max(0.0, min(1.0, amount))
    width, height = image.size
    overlay = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(overlay)
    inset = int(min(width, height) * 0.08)
    draw.ellipse((-inset, -inset, width + inset, height + inset), fill=255)
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=min(width, height) / 6))
    darkened = ImageEnhanceBrightness(image).enhance(max(0.2, 1.0 - amount * 0.65))
    return Image.composite(image, darkened, overlay)


def ImageEnhanceBrightness(image: Any) -> Any:
    from PIL import ImageEnhance

    return ImageEnhance.Brightness(image)


def _apply_tint(image: Any, red: float, green: float, blue: float) -> Any:
    from PIL import ImageEnhance

    work = image.convert("RGB")
    if abs(red) > 1e-6:
        r, g, b = work.split()
        r = ImageEnhance.Brightness(r).enhance(max(0.2, 1.0 + red))
        work = __merge_rgb(r, g, b)
    if abs(green) > 1e-6:
        r, g, b = work.split()
        g = ImageEnhance.Brightness(g).enhance(max(0.2, 1.0 + green))
        work = __merge_rgb(r, g, b)
    if abs(blue) > 1e-6:
        r, g, b = work.split()
        b = ImageEnhance.Brightness(b).enhance(max(0.2, 1.0 + blue))
        work = __merge_rgb(r, g, b)
    return work


def __merge_rgb(r: Any, g: Any, b: Any) -> Any:
    from PIL import Image

    return Image.merge("RGB", (r, g, b))
