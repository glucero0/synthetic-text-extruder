"""Detect UI chrome in an image (or a video frame) and store structured layout JSON."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from struct import unpack
from typing import Any, Callable

from .extract_text import MAX_INLINE_BYTES, _gemini_multimodal

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[Any], None]

ELEMENT_TYPES = frozenset(
    {
        "window",
        "titlebar",
        "toolbar",
        "tab",
        "menu",
        "button",
        "input",
        "checkbox",
        "radio",
        "label",
        "text",
        "list",
        "image",
        "icon",
        "scrollbar",
        "container",
        "other",
    }
)
FLAG_CODES = frozenset(
    {
        "overlap_parent",
        "overflow",
        "overflow_parent",
        "uneven_margins",
        "clipped",
        "unlabeled_control",
        "not_ui",
    }
)
MAX_ELEMENTS = 120

LAYOUT_PROMPT = (
    "Analyze this picture for graphical user-interface structure "
    "(windows, buttons, fields, menus, text blocks, toolbars).\n"
    "Return ONLY a JSON object, no markdown, with this shape:\n"
    "{\n"
    '  "isUi": true,\n'
    '  "confidence": 0.0,\n'
    '  "width": 0,\n'
    '  "height": 0,\n'
    '  "elements": [\n'
    "    {\n"
    '      "id": "e1",\n'
    '      "type": "button",\n'
    '      "label": "OK",\n'
    '      "box": {"x": 0, "y": 0, "w": 10, "h": 10},\n'
    '      "parentId": null\n'
    "    }\n"
    "  ],\n"
    '  "flags": [\n'
    '    {"code": "overflow_parent", "elementId": "e2", "message": "Control extends outside its window"}\n'
    "  ]\n"
    "}\n"
    "Rules:\n"
    "- width and height are the image size in pixels.\n"
    "- box x,y,w,h are integer pixels, origin at the top-left of the unrotated image.\n"
    "- type is one of: window, titlebar, toolbar, tab, menu, button, input, checkbox, "
    "radio, label, text, list, image, icon, scrollbar, container, other.\n"
    "- parentId is another element's id, or null for top-level chrome.\n"
    "- isUi is false if this is not a UI screenshot (photo, illustration, chart without chrome). "
    "Then elements may be empty and flags may include code not_ui.\n"
    "- flags codes: overlap_parent, overflow, overflow_parent, uneven_margins, clipped, "
    "unlabeled_control, not_ui.\n"
    "- Only list controls you can actually see. Do not invent a full OS desktop."
)


def _emit(
    progress: ProgressCallback | None,
    message: str,
    *,
    percent: float | None = None,
    title: str = "Extracting layout",
) -> None:
    if not progress:
        return
    from .cancellation import GenerationCancelled

    payload: dict[str, Any] = {
        "message": message,
        "phase": "layout",
        "title": title,
    }
    if percent is not None:
        payload["percent"] = percent
    try:
        progress(payload)
    except GenerationCancelled:
        raise
    except Exception:  # noqa: BLE001
        logger.debug("progress callback failed", exc_info=True)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def clear_layout_fields(creation: dict[str, Any]) -> dict[str, Any]:
    """Drop cached UI layout after media is replaced."""
    out = dict(creation)
    meta = dict(out.get("meta") or {})
    for key in (
        "extractedLayout",
        "layoutExtractedAt",
        "layoutExtractionModel",
        "layoutExtractionProvider",
        "layoutSource",
    ):
        meta.pop(key, None)
    out["meta"] = meta
    return out


def apply_layout_fields(
    creation: dict[str, Any],
    *,
    layout: dict[str, Any],
    model: str,
    provider: str,
    source: str = "image",
) -> dict[str, Any]:
    out = dict(creation)
    meta = dict(out.get("meta") or {})
    meta["extractedLayout"] = layout
    meta["layoutExtractedAt"] = _utcnow_iso()
    meta["layoutExtractionModel"] = model
    meta["layoutExtractionProvider"] = provider
    meta["layoutSource"] = source
    meta["studioJob"] = "layout"
    out["meta"] = meta
    return out


def get_extracted_layout(creation: dict[str, Any] | None) -> dict[str, Any] | None:
    if not creation:
        return None
    meta = creation.get("meta") or {}
    layout = meta.get("extractedLayout")
    return layout if isinstance(layout, dict) else None


LAYOUT_BASIS_MARKER = "Layout JSON:"
LAYOUT_BASIS_INTRO = (
    "The screenshot is attached as a Studio media basis. Use this extracted UI layout "
    "(element types, labels, pixel boxes, and flags) to recreate the interface — "
    "for example as HTML/CSS, a desktop app, or another mockup. Address any flags "
    "(overflow, uneven margins, unlabeled controls).\n\n"
    f"{LAYOUT_BASIS_MARKER}\n"
)


def format_layout_basis_prompt(
    layout: dict[str, Any] | None, *, existing: str = ""
) -> str:
    """Seed Studio with layout JSON, appending to an existing prompt when present."""
    if not isinstance(layout, dict):
        return (existing or "").strip()
    block = LAYOUT_BASIS_INTRO + json.dumps(layout, indent=2, ensure_ascii=False)
    prior = (existing or "").strip()
    if not prior:
        return block
    if LAYOUT_BASIS_MARKER in prior:
        return prior
    return prior + "\n\n" + block


def image_size_from_bytes(raw: bytes) -> tuple[int, int] | None:
    """Best-effort PNG/JPEG pixel size without extra dependencies."""
    if not raw or len(raw) < 24:
        return None
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        try:
            width, height = unpack(">II", raw[16:24])
        except Exception:  # noqa: BLE001
            return None
        if width > 0 and height > 0:
            return int(width), int(height)
        return None
    if raw[:2] == b"\xff\xd8":
        i = 2
        end = len(raw) - 8
        while i < end:
            if raw[i] != 0xFF:
                break
            marker = raw[i + 1]
            if marker in {0xC0, 0xC1, 0xC2, 0xC3}:
                try:
                    height, width = unpack(">HH", raw[i + 5 : i + 9])
                except Exception:  # noqa: BLE001
                    return None
                if width > 0 and height > 0:
                    return int(width), int(height)
                return None
            if marker in {0xD8, 0xD9} or marker == 0x01 or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            if i + 4 > len(raw):
                break
            length = unpack(">H", raw[i + 2 : i + 4])[0]
            i += 2 + length
    return None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _clamp_box(box: dict[str, int], width: int, height: int) -> dict[str, int]:
    x = max(0, box.get("x", 0))
    y = max(0, box.get("y", 0))
    w = max(0, box.get("w", 0))
    h = max(0, box.get("h", 0))
    if width > 0:
        x = min(x, width)
        w = min(w, max(0, width - x))
    if height > 0:
        y = min(y, height)
        h = min(h, max(0, height - y))
    return {"x": x, "y": y, "w": w, "h": h}


def _box_contains(parent: dict[str, int], child: dict[str, int], slop: int = 2) -> bool:
    return (
        child["x"] >= parent["x"] - slop
        and child["y"] >= parent["y"] - slop
        and child["x"] + child["w"] <= parent["x"] + parent["w"] + slop
        and child["y"] + child["h"] <= parent["y"] + parent["h"] + slop
    )


def _geometry_flags(
    elements: list[dict[str, Any]], width: int, height: int
) -> list[dict[str, str]]:
    by_id = {str(el.get("id") or ""): el for el in elements if el.get("id")}
    flags: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(code: str, element_id: str, message: str) -> None:
        key = (code, element_id)
        if key in seen:
            return
        seen.add(key)
        flags.append({"code": code, "elementId": element_id, "message": message})

    for el in elements:
        eid = str(el.get("id") or "")
        box = el.get("box") or {}
        if not eid or not isinstance(box, dict):
            continue
        etype = str(el.get("type") or "")
        if etype in {"button", "input", "checkbox", "radio", "tab", "menu"}:
            if not str(el.get("label") or "").strip():
                _add("unlabeled_control", eid, "Interactive control has no visible label.")
        parent_id = el.get("parentId")
        if parent_id and parent_id in by_id:
            parent_box = by_id[parent_id].get("box") or {}
            if isinstance(parent_box, dict) and not _box_contains(parent_box, box):
                _add(
                    "overflow_parent",
                    eid,
                    "Element extends outside its parent container.",
                )
                _add(
                    "overlap_parent",
                    eid,
                    "Element overlaps or escapes its parent container.",
                )

    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    for el in elements:
        pid = el.get("parentId")
        if pid and pid in by_id:
            children_by_parent.setdefault(str(pid), []).append(el)
    for pid, kids in children_by_parent.items():
        if len(kids) < 2:
            continue
        parent_box = by_id[pid].get("box") or {}
        if not isinstance(parent_box, dict) or parent_box.get("w", 0) < 8:
            continue
        lefts = [k["box"]["x"] - parent_box["x"] for k in kids if isinstance(k.get("box"), dict)]
        if len(lefts) < 2:
            continue
        spread = max(lefts) - min(lefts)
        if spread >= 12 and (max(lefts) - min(lefts)) > parent_box["w"] * 0.08:
            _add(
                "uneven_margins",
                pid,
                "Child controls do not share an even left margin.",
            )
    return flags


def normalize_layout(
    raw: dict[str, Any] | None,
    *,
    image_size: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Clamp Gemini output into a stable layout payload."""
    data = dict(raw or {})
    width, height = image_size or (0, 0)
    reported_w = _as_int(data.get("width"), 0)
    reported_h = _as_int(data.get("height"), 0)
    if width <= 0:
        width = reported_w
    if height <= 0:
        height = reported_h

    is_ui = data.get("isUi")
    if not isinstance(is_ui, bool):
        is_ui = bool(data.get("elements"))
    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    elements_out: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    overflow_ids: list[str] = []
    for idx, item in enumerate(data.get("elements") or []):
        if len(elements_out) >= MAX_ELEMENTS:
            break
        if not isinstance(item, dict):
            continue
        eid = str(item.get("id") or f"e{idx + 1}").strip() or f"e{idx + 1}"
        eid = eid[:32]
        if eid in used_ids:
            eid = f"{eid}_{idx + 1}"
        used_ids.add(eid)
        etype = str(item.get("type") or "other").strip().lower()
        if etype not in ELEMENT_TYPES:
            etype = "other"
        box_in = item.get("box") if isinstance(item.get("box"), dict) else {}
        raw_box = {
            "x": _as_int(box_in.get("x"), 0),
            "y": _as_int(box_in.get("y"), 0),
            "w": max(0, _as_int(box_in.get("w"), 0)),
            "h": max(0, _as_int(box_in.get("h"), 0)),
        }
        box = _clamp_box(raw_box, width, height)
        if box["w"] <= 0 or box["h"] <= 0:
            continue
        if width > 0 and height > 0:
            if (
                raw_box["x"] < 0
                or raw_box["y"] < 0
                or raw_box["x"] + raw_box["w"] > width + 1
                or raw_box["y"] + raw_box["h"] > height + 1
            ):
                overflow_ids.append(eid)
        label = str(item.get("label") or "").strip()[:200]
        parent = item.get("parentId")
        parent_id = str(parent).strip()[:32] if parent not in (None, "", "null") else None
        elements_out.append(
            {
                "id": eid,
                "type": etype,
                "label": label,
                "box": box,
                "parentId": parent_id,
            }
        )

    id_set = {el["id"] for el in elements_out}
    for el in elements_out:
        if el["parentId"] and el["parentId"] not in id_set:
            el["parentId"] = None
        if el["parentId"] == el["id"]:
            el["parentId"] = None

    flags_out: list[dict[str, str]] = []
    seen_flags: set[tuple[str, str]] = set()
    for item in data.get("flags") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip().lower()
        if code not in FLAG_CODES:
            continue
        eid = str(item.get("elementId") or "").strip()[:32]
        message = str(item.get("message") or "").strip()[:240]
        key = (code, eid)
        if key in seen_flags:
            continue
        seen_flags.add(key)
        flags_out.append({"code": code, "elementId": eid, "message": message})

    if not is_ui and not any(f["code"] == "not_ui" for f in flags_out):
        flags_out.append(
            {
                "code": "not_ui",
                "elementId": "",
                "message": "This does not look like a user-interface screenshot.",
            }
        )

    for eid in overflow_ids:
        key = ("overflow", eid)
        if key in seen_flags:
            continue
        seen_flags.add(key)
        flags_out.append(
            {
                "code": "overflow",
                "elementId": eid,
                "message": "Element extends outside the image.",
            }
        )

    for extra in _geometry_flags(elements_out, width, height):
        key = (extra["code"], extra["elementId"])
        if key in seen_flags:
            continue
        seen_flags.add(key)
        flags_out.append(extra)

    return {
        "isUi": bool(is_ui),
        "confidence": round(confidence, 3),
        "width": max(0, width),
        "height": max(0, height),
        "elements": elements_out,
        "flags": flags_out,
    }


def extract_layout_from_image_bytes(
    raw: bytes,
    *,
    config: dict[str, Any],
    mime_type: str = "image/png",
    progress: ProgressCallback | None = None,
    cancel_event: Any = None,
) -> tuple[dict[str, Any], str]:
    """Detect UI chrome in image bytes. Returns (normalized layout, model id)."""
    from .cancellation import raise_if_cancelled
    from .creation_utils import extract_json_object
    from .generator import _active_model_and_provider

    def _cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    raise_if_cancelled(_cancelled)

    model_id, provider = _active_model_and_provider(config)
    if provider != "gemini":
        raise RuntimeError(
            "Extracting layout requires Gemini. Paste a Gemini API key in Settings."
        )

    if not raw:
        raise RuntimeError("No image bytes to extract a layout from.")
    if len(raw) > MAX_INLINE_BYTES:
        raise RuntimeError(
            f"Image is too large to extract a layout ({len(raw) // (1024 * 1024)} MB). "
            "Try a smaller image."
        )

    image_mime = mime_type if str(mime_type or "").lower().startswith("image/") else "image/png"
    _emit(progress, "Looking for UI chrome…", percent=40)
    text, used_model = _gemini_multimodal(
        raw,
        mime_type=image_mime,
        prompt=LAYOUT_PROMPT,
        config=config,
        model_id=model_id,
        progress=progress,
        cancel_check=_cancelled,
        cancel_event=cancel_event,
    )
    parsed = extract_json_object(text or "")
    if not parsed:
        raise RuntimeError("Gemini did not return layout JSON. Try the prompt again.")

    layout = normalize_layout(parsed, image_size=image_size_from_bytes(raw))
    _emit(progress, "Saving layout…", percent=90)
    return layout, used_model


def extract_layout_from_creation(
    creation: dict[str, Any],
    *,
    config: dict[str, Any],
    media_path: Any,
    progress: ProgressCallback | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """Run UI layout detection and return updated creation (not yet persisted)."""
    from .cancellation import raise_if_cancelled
    from .generator import _active_model_and_provider
    from .modality import normalize_modality

    def _cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    raise_if_cancelled(_cancelled)

    modality = normalize_modality(creation.get("modality"), default="")
    mime = str(creation.get("mimeType") or "").lower()
    if not modality:
        if mime.startswith("video/"):
            modality = "video"
        elif mime.startswith("image/"):
            modality = "image"
    if modality not in {"image", "video"}:
        raise RuntimeError("Layout extract is only available for image and video creations.")

    path = media_path
    if path is None:
        raise RuntimeError("Media file is missing on disk.")

    raise_if_cancelled(_cancelled)
    source = "image"
    if modality == "video":
        _emit(progress, "Grabbing a video frame…", percent=20)
        from .video_edit import FfmpegNotFoundError, extract_video_frame_png

        try:
            raw = extract_video_frame_png(path, at_seconds=0.5)
        except FfmpegNotFoundError as exc:
            raise RuntimeError(
                "ffmpeg not found — needed to grab a video frame to extract the layout."
            ) from exc
        image_mime = "image/png"
        source = "video-frame"
    else:
        raw = path.read_bytes() if hasattr(path, "read_bytes") else bytes(path)
        image_mime = mime if mime.startswith("image/") else "image/png"

    layout, used_model = extract_layout_from_image_bytes(
        raw,
        config=config,
        mime_type=image_mime,
        progress=progress,
        cancel_event=cancel_event,
    )
    _, provider = _active_model_and_provider(config)
    return apply_layout_fields(
        creation,
        layout=layout,
        model=used_model,
        provider=provider,
        source=source,
    )
