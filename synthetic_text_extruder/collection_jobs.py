"""Collection jobs: treat a folder (or many files) as one Studio source."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .creation_utils import (
    build_media_creation,
    build_text_creation_from_plain,
    title_from_prompt,
)
from .image_batch import parse_filters_from_prompt, prompt_looks_like_filters
from .modality import infer_report_intent, infer_text_extract_intent
from .studio_sources import (
    _creation_title,
    creation_source_modality,
    original_filename_for_creation,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[Any], None]

MAX_COLLECTION_ITEMS = 100
ALSO_UPSERT_KEY = "_also_upsert"

_BATCH_RE = re.compile(
    r"\b(?:every|each|all|these|those|folder|batch|collection)\b", re.IGNORECASE
)
_MAGAZINE_RE = re.compile(
    r"""
    (?:
        \b(?:skip|ignore|drop|omit)\b.{0,24}?\bads?\b
      | \bads?\b.{0,16}?\b(?:skip|ignore)\b
      | \bmagazine\b
      | \breconstruct(?:ed|ion)?\b
      | \beditorial\b
      | \bextract\b.{0,40}?\b(?:photos?|images?|pictures?)\b.{0,40}?\b(?:pages?|scans?)\b
      | \bscans?\b.{0,24}?\b(?:magazine|article)\b
    )
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_FLIPBOOK_RE = re.compile(
    r"\b(?:flip[\s\-]?book|slideshow|page[\s\-]?turn(?:er)?|kinetics?\s+album)\b",
    re.IGNORECASE,
)
_CONTACT_RE = re.compile(
    r"\b(?:contact\s+sheet|sprite\s+sheet|image\s+grid|thumbnail\s+sheet)\b",
    re.IGNORECASE,
)
_ONE_PDF_RE = re.compile(
    r"""
    (?:
        \b(?:one|single|combined|a)\s+pdf\b
      | \b(?:put|combine|merge|pack|collect)\b.{0,40}?\b(?:one|a|into)\s+pdf\b
      | \ball\s+(?:of\s+)?(?:them|these|the\s+images?)\s+in(?:to)?\s+(?:one\s+)?pdf\b
    )
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_SECONDS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)\s*(?:per\s+(?:page|image|frame))?",
    re.IGNORECASE,
)


def is_collection_creation(creation: dict[str, Any] | None) -> bool:
    if not creation:
        return False
    meta = creation.get("meta") if isinstance(creation.get("meta"), dict) else {}
    col = meta.get("collection")
    return isinstance(col, dict) and bool(col.get("memberIds") or col.get("members"))


def collection_meta(creation: dict[str, Any] | None) -> dict[str, Any]:
    if not creation:
        return {}
    meta = creation.get("meta") if isinstance(creation.get("meta"), dict) else {}
    col = meta.get("collection")
    return dict(col) if isinstance(col, dict) else {}


def build_collection_creation(
    members: list[dict[str, Any]],
    *,
    folder_name: str = "",
    recursive: bool = False,
    prompt: str = "",
) -> dict[str, Any]:
    items = [m for m in members if isinstance(m, dict) and m.get("id")]
    names: list[str] = []
    mods: list[str] = []
    snapshots: list[dict[str, str]] = []
    for item in items:
        filename = original_filename_for_creation(item) or _creation_title(item)
        names.append(filename)
        mod = creation_source_modality(item)
        mods.append(mod)
        snapshots.append(
            {
                "id": str(item.get("id") or ""),
                "title": _creation_title(item),
                "modality": mod,
                "mediaPath": str(item.get("mediaPath") or ""),
                "mimeType": str(item.get("mimeType") or ""),
                "originalFilename": filename,
            }
        )
    folder = (folder_name or "").strip() or "Collection"
    count = len(items)
    title = f"{folder} ({count} file{'s' if count != 1 else ''})"
    listing = "\n".join(names) if names else "(empty collection)"
    creation = build_text_creation_from_plain(
        listing,
        prompt=prompt or f"Collection from {folder}",
        title=title,
    )
    creation["creationType"] = "Collection"
    meta = dict(creation.get("meta") or {})
    meta["originalFilename"] = folder[:200]
    meta["collection"] = {
        "kind": "folder" if folder_name else "files",
        "folderName": folder,
        "memberIds": [str(m.get("id") or "") for m in items],
        "members": snapshots,
        "count": count,
        "recursive": bool(recursive),
        "modalities": sorted(set(mods)),
    }
    creation["meta"] = meta
    return creation


def plan_collection_job(prompt: str, *, has_collection: bool = False) -> dict[str, Any]:
    """Classify a Studio prompt against a collection (regex first)."""
    text = (prompt or "").strip()
    lowered = text.casefold()
    if _MAGAZINE_RE.search(text):
        return {"kind": "magazine", "filters": {}, "secondsPerPage": 1.5}
    if _FLIPBOOK_RE.search(text):
        return {
            "kind": "flipbook",
            "filters": {},
            "secondsPerPage": _seconds_per_page(text),
        }
    if _CONTACT_RE.search(text):
        return {"kind": "contact_sheet", "filters": {}, "secondsPerPage": 1.5}
    filters = parse_filters_from_prompt(text)
    if filters or prompt_looks_like_filters(text):
        return {"kind": "filters", "filters": filters, "secondsPerPage": 1.5}
    batch = bool(_BATCH_RE.search(text) or has_collection)
    if infer_text_extract_intent(text) and (batch or has_collection):
        return {"kind": "ocr", "filters": {}, "secondsPerPage": 1.5}
    if _ONE_PDF_RE.search(text):
        return {"kind": "assemble_pdf", "filters": {}, "secondsPerPage": 1.5}
    if (
        infer_report_intent(text)
        or lowered
        in {
            "",
            "write a single report from the attached sources. combine transcripts, image descriptions, and document text. cite each source by title.",
        }
    ) and (has_collection or batch):
        return {"kind": "report", "filters": {}, "secondsPerPage": 1.5}
    if batch and has_collection:
        return {"kind": "generic_map", "filters": {}, "secondsPerPage": 1.5}
    if has_collection:
        return {"kind": "generic_map", "filters": {}, "secondsPerPage": 1.5}
    return {"kind": "", "filters": {}, "secondsPerPage": 1.5}


def wants_collection_job(prompt: str, sources: list[dict[str, Any]] | None) -> bool:
    items = [s for s in (sources or []) if isinstance(s, dict)]
    if not items:
        return False
    has_col = any(is_collection_creation(s) for s in items)
    members = expand_collection_members(items)
    plan = plan_collection_job(prompt, has_collection=has_col)
    kind = str(plan.get("kind") or "")
    if has_col and kind:
        return True
    visuals = [
        s
        for s in members
        if creation_source_modality(s) in {"image", "video", "pdf", "audio"}
    ]
    images = [s for s in members if creation_source_modality(s) == "image"]
    if kind in {"magazine", "flipbook", "contact_sheet", "filters", "assemble_pdf"}:
        return len(images) >= 1 or len(visuals) >= 2
    if kind == "ocr":
        return len(visuals) >= 2 or has_col
    if kind in {"report", "generic_map"}:
        return has_col or (len(members) >= 2 and bool(_BATCH_RE.search(prompt or "")))
    return False


def expand_collection_members(
    sources: list[dict[str, Any]] | None,
    *,
    lookup: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Tray sources plus collection members (deduped, filename order preserved)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(item: dict[str, Any] | None) -> None:
        if not item:
            return
        sid = str(item.get("id") or "")
        key = sid or str(id(item))
        if key in seen:
            return
        seen.add(key)
        out.append(item)

    for src in sources or []:
        if not isinstance(src, dict):
            continue
        if is_collection_creation(src):
            meta = collection_meta(src)
            ids = [str(i) for i in (meta.get("memberIds") or []) if str(i)]
            snapshots = {
                str(m.get("id") or ""): m
                for m in (meta.get("members") or [])
                if isinstance(m, dict)
            }
            for mid in ids:
                live = (lookup or {}).get(mid)
                if live:
                    _add(live)
                elif snapshots.get(mid):
                    _add(dict(snapshots[mid]))
            continue
        _add(src)
    return out[:MAX_COLLECTION_ITEMS]


def _seconds_per_page(prompt: str) -> float:
    match = _SECONDS_RE.search(prompt or "")
    if not match:
        return 1.5
    try:
        value = float(match.group(1))
    except (TypeError, ValueError):
        return 1.5
    return max(0.2, min(8.0, value))


def _lookup_from_config(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    path = str((config.get("paths") or {}).get("archives") or "").strip()
    if not path:
        return {}
    try:
        from .storage import ArchiveStore

        store = ArchiveStore(path=Path(path))
        return {
            str(item.get("id") or ""): item
            for item in store.load()
            if isinstance(item, dict) and item.get("id")
        }
    except Exception:
        logger.debug("Could not load archives for collection members", exc_info=True)
        return {}


def _emit(
    progress: ProgressCallback | None,
    message: str,
    *,
    percent: float | None = None,
    title: str = "Collection job",
) -> None:
    if not progress:
        return
    from .cancellation import GenerationCancelled

    payload: dict[str, Any] = {
        "message": message,
        "phase": "extract",
        "title": title,
    }
    if percent is not None:
        payload["percent"] = percent
    try:
        progress(payload)
    except GenerationCancelled:
        raise
    except Exception:
        logger.debug("progress callback failed", exc_info=True)


def _attach_extras(result: dict[str, Any], extras: list[dict[str, Any]]) -> dict[str, Any]:
    if extras:
        result[ALSO_UPSERT_KEY] = extras
    return result


def run_collection_job(
    sources: list[dict[str, Any]],
    *,
    prompt: str,
    config: dict[str, Any],
    progress: ProgressCallback | None = None,
    cancel_event: Any = None,
    tool_aliases: list[str] | None = None,
    search_query: str | None = None,
    game: str = "Prompt",
    platform: str = "General",
    creation_type: str = "Custom",
) -> dict[str, Any]:
    """Map/assemble a collection (or implicit multi-file tray)."""
    from .cancellation import raise_if_cancelled

    def _cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    raise_if_cancelled(_cancelled)
    lookup = _lookup_from_config(config)
    has_col = any(is_collection_creation(s) for s in sources)
    members = expand_collection_members(sources, lookup=lookup)
    if not members:
        raise RuntimeError("This collection has no readable files.")
    plan = plan_collection_job(prompt, has_collection=has_col)
    kind = str(plan.get("kind") or "generic_map")
    n = len(members)
    _emit(
        progress,
        f"Collection job ({kind}): {n} file{'s' if n != 1 else ''}…",
        percent=4,
        title="Collection job",
    )
    if kind == "filters":
        return _run_filters(members, prompt=prompt, filters=plan.get("filters") or {}, config=config, progress=progress, cancel_event=cancel_event)
    if kind == "ocr":
        return _run_ocr(members, prompt=prompt, config=config, progress=progress, cancel_event=cancel_event)
    if kind == "magazine":
        return _run_magazine(members, prompt=prompt, config=config, progress=progress, cancel_event=cancel_event)
    if kind == "flipbook":
        return _run_flipbook(
            members,
            prompt=prompt,
            seconds=float(plan.get("secondsPerPage") or 1.5),
            config=config,
            progress=progress,
            cancel_event=cancel_event,
        )
    if kind == "contact_sheet":
        return _run_contact_sheet(members, prompt=prompt, config=config, progress=progress, cancel_event=cancel_event)
    if kind == "assemble_pdf":
        return _run_assemble_pdf(members, prompt=prompt, config=config, progress=progress, cancel_event=cancel_event)
    if kind == "report":
        from .studio_sources import gather_then_synthesize

        return gather_then_synthesize(
            members[:MAX_COLLECTION_ITEMS],
            game=game,
            platform=platform,
            creation_type=creation_type,
            config=config,
            user_prompt=prompt,
            progress=progress,
            cancel_event=cancel_event,
            tool_aliases=tool_aliases,
            search_query=search_query,
            max_items=MAX_COLLECTION_ITEMS,
        )
    return _run_generic_map(
        members,
        prompt=prompt,
        config=config,
        progress=progress,
        cancel_event=cancel_event,
    )


def _image_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in members if creation_source_modality(m) == "image"]


def _media_path(creation: dict[str, Any], config: dict[str, Any]) -> Path | None:
    from .media_store import resolve_media_path

    return resolve_media_path(creation.get("mediaPath"), config=config)


def _run_filters(
    members: list[dict[str, Any]],
    *,
    prompt: str,
    filters: dict[str, Any],
    config: dict[str, Any],
    progress: ProgressCallback | None,
    cancel_event: Any,
) -> dict[str, Any]:
    from .cancellation import raise_if_cancelled
    from .image_batch import apply_still_filters
    from .media_store import write_media_bytes
    from .video_edit import has_active_filters

    def _cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    images = _image_members(members)
    if not images:
        raise RuntimeError("Batch filters need at least one image in the collection.")
    if not has_active_filters(filters):
        raise RuntimeError(
            "Could not tell which filter to apply. Name one (for example: grayscale, sepia, sharpen)."
        )
    extras: list[dict[str, Any]] = []
    total = len(images)
    for index, src in enumerate(images):
        raise_if_cancelled(_cancelled)
        title = _creation_title(src)
        _emit(
            progress,
            f"Filtering image {index + 1} of {total}: {title}",
            percent=8 + int(80 * index / max(total, 1)),
            title="Batch filters",
        )
        path = _media_path(src, config)
        if path is None:
            continue
        import tempfile

        suffix = path.suffix.lower() if path.suffix else ".png"
        with tempfile.TemporaryDirectory(prefix="ste_filter_") as tmp:
            dest = Path(tmp) / f"out{suffix}"
            apply_still_filters(path, dest, filters)
            raw = dest.read_bytes()
        cid = f"doc_{uuid.uuid4().hex[:10]}"
        mime = str(src.get("mimeType") or "image/png")
        stored = write_media_bytes(cid, raw, mime_type=mime, config=config, suffix=suffix)
        created = build_media_creation(
            modality="image",
            prompt=prompt,
            media_path=stored["mediaPath"],
            mime_type=stored["mimeType"],
            title=f"Filtered — {title}",
            creation_id=cid,
        )
        meta = dict(created.get("meta") or {})
        meta["studioJob"] = "collection_filter"
        meta["sourceCreationId"] = str(src.get("id") or "")
        meta["originalFilename"] = original_filename_for_creation(src)
        created["meta"] = meta
        extras.append(created)
    if not extras:
        raise RuntimeError("No images could be filtered.")
    wrapper = build_collection_creation(
        extras, folder_name="Filtered images", prompt=prompt
    )
    meta = dict(wrapper.get("meta") or {})
    meta["studioJob"] = "collection_filter"
    wrapper["meta"] = meta
    wrapper["title"] = f"Filtered images ({len(extras)})"
    wrapper["game"] = wrapper["title"]
    return _attach_extras(wrapper, extras)


def _run_ocr(
    members: list[dict[str, Any]],
    *,
    prompt: str,
    config: dict[str, Any],
    progress: ProgressCallback | None,
    cancel_event: Any,
) -> dict[str, Any]:
    from .cancellation import raise_if_cancelled
    from .extract_text import extract_text_from_creation, get_extracted_text

    def _cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    usable = [
        m
        for m in members
        if creation_source_modality(m) in {"image", "video"}
    ]
    if not usable:
        raise RuntimeError("Batch OCR needs image or video files.")
    extras: list[dict[str, Any]] = []
    blocks: list[str] = []
    total = len(usable)
    for index, src in enumerate(usable):
        raise_if_cancelled(_cancelled)
        title = original_filename_for_creation(src) or _creation_title(src)
        _emit(
            progress,
            f"OCR {index + 1} of {total}: {title}",
            percent=8 + int(80 * index / max(total, 1)),
            title="Batch OCR",
        )
        path = _media_path(src, config)
        if path is None:
            blocks.append(f"## {title}\n(missing file)")
            continue
        try:
            updated = extract_text_from_creation(
                src,
                config=config,
                media_path=path,
                progress=progress,
                cancel_event=cancel_event,
            )
        except Exception as exc:
            from .cancellation import GenerationCancelled

            if isinstance(exc, GenerationCancelled):
                raise
            logger.warning("Collection OCR failed for %s: %s", title, exc)
            blocks.append(f"## {title}\n(Could not read: {exc})")
            continue
        extras.append(updated)
        text = get_extracted_text(updated) or "(no text found)"
        blocks.append(f"## {title}\n{text}")
    body = "\n\n".join(blocks).strip() or "(no text found)"
    result = build_text_creation_from_plain(
        body, prompt=prompt, title=title_from_prompt(prompt, "Batch OCR")
    )
    result["title"] = f"OCR ({len(usable)} files)"
    result["game"] = result["title"]
    meta = dict(result.get("meta") or {})
    meta["studioJob"] = "collection_ocr"
    meta["extractedText"] = body
    meta["extractionKind"] = "ocr"
    result["meta"] = meta
    return _attach_extras(result, extras)


def _run_magazine(
    members: list[dict[str, Any]],
    *,
    prompt: str,
    config: dict[str, Any],
    progress: ProgressCallback | None,
    cancel_event: Any,
) -> dict[str, Any]:
    from .cancellation import raise_if_cancelled
    from .document_reconstruct import (
        PAGE_PROMPT,
        crop_photo_boxes,
        parse_page_analysis,
    )
    from .extract_text import _gemini_multimodal
    from .generator import _active_model_and_provider
    from .media_store import media_dir, write_media_bytes
    from .pdf_build import article_pdf

    def _cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    images = _image_members(members)
    if not images:
        raise RuntimeError("Magazine reconstruct needs scanned page images.")
    model_id, _provider = _active_model_and_provider(config)
    page_prompt = PAGE_PROMPT + "\n\nUser instructions:\n" + (prompt or "").strip()
    sections: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    texts: list[str] = []
    dest_dir = media_dir(config) / "magazine_crops"
    total = len(images)
    for index, src in enumerate(images):
        raise_if_cancelled(_cancelled)
        filename = original_filename_for_creation(src) or _creation_title(src)
        _emit(
            progress,
            f"Reading page {index + 1} of {total}: {filename}",
            percent=6 + int(78 * index / max(total, 1)),
            title="Magazine PDF",
        )
        path = _media_path(src, config)
        if path is None:
            skipped.append({"filename": filename, "reason": "File missing on disk"})
            continue
        mime = str(src.get("mimeType") or "image/png")
        if not mime.startswith("image/"):
            mime = "image/png"
        try:
            raw = path.read_bytes()
            text, _model = _gemini_multimodal(
                raw,
                mime_type=mime,
                prompt=page_prompt,
                config=config,
                model_id=model_id,
                progress=progress,
                cancel_check=_cancelled,
                cancel_event=cancel_event,
            )
        except Exception as exc:
            from .cancellation import GenerationCancelled

            if isinstance(exc, GenerationCancelled):
                raise
            logger.warning("Magazine page failed %s: %s", filename, exc)
            skipped.append({"filename": filename, "reason": str(exc)})
            continue
        analysis = parse_page_analysis(text)
        if analysis["skipPage"]:
            skipped.append(
                {
                    "filename": filename,
                    "reason": analysis["skipReason"] or "Skipped",
                    "pageKind": analysis["pageKind"],
                }
            )
            continue
        photos = crop_photo_boxes(
            path,
            analysis["photos"],
            dest_dir=dest_dir,
            stem=f"{src.get('id') or 'page'!s}_{index + 1}",
        )
        heading = analysis["heading"]
        body = analysis["bodyText"]
        if body:
            texts.append((f"{heading}\n{body}" if heading else body).strip())
        if heading or body:
            sections.append(
                {
                    "heading": heading,
                    "paragraphs": [p for p in body.split("\n\n") if p.strip()] or ([body] if body else []),
                }
            )
        for photo in photos:
            sections.append(
                {
                    "heading": "",
                    "paragraphs": [],
                    "photoPath": str(photo.get("photoPath") or ""),
                    "photoCaption": photo.get("caption") or filename,
                }
            )
    if not sections:
        raise RuntimeError(
            "No editorial pages were kept. Review skipped ads, or change the prompt."
        )
    _emit(progress, "Writing reconstructed PDF…", percent=90, title="Magazine PDF")
    display_title = title_from_prompt(prompt, "Reconstructed article")
    pdf_bytes = article_pdf(title=display_title, sections=sections, skipped_ads=skipped)
    cid = f"doc_{uuid.uuid4().hex[:10]}"
    stored = write_media_bytes(
        cid, pdf_bytes, mime_type="application/pdf", config=config, suffix=".pdf"
    )
    result = build_media_creation(
        modality="pdf",
        prompt=prompt,
        media_path=stored["mediaPath"],
        mime_type="application/pdf",
        title=display_title,
        creation_id=cid,
    )
    extracted = "\n\n".join(texts).strip()
    result["sections"] = [
        {"title": "Reconstructed text", "content": extracted, "keyValues": []},
        {
            "title": "Skipped ads",
            "content": "\n".join(
                f"- {a.get('filename')}: {a.get('reason')}" for a in skipped
            )
            or "(none)",
            "keyValues": [],
        },
    ]
    meta = dict(result.get("meta") or {})
    meta["studioJob"] = "magazine_reconstruct"
    meta["extractedText"] = extracted
    meta["extractionKind"] = "ocr"
    meta["skippedAds"] = skipped
    result["meta"] = meta
    return result


def _run_flipbook(
    members: list[dict[str, Any]],
    *,
    prompt: str,
    seconds: float,
    config: dict[str, Any],
    progress: ProgressCallback | None,
    cancel_event: Any,
) -> dict[str, Any]:
    from .cancellation import raise_if_cancelled
    from .media_store import write_media_bytes
    from .pdf_build import images_to_pdf

    def _cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    images = _image_members(members)
    if len(images) < 2:
        raise RuntimeError("A flipbook needs at least two images.")
    raise_if_cancelled(_cancelled)
    paths: list[Path] = []
    pages: list[dict[str, str]] = []
    for src in images:
        path = _media_path(src, config)
        if path is None:
            continue
        paths.append(path)
        pages.append(
            {
                "id": str(src.get("id") or ""),
                "mediaPath": str(src.get("mediaPath") or ""),
                "mimeType": str(src.get("mimeType") or "image/png"),
                "title": original_filename_for_creation(src) or _creation_title(src),
            }
        )
    if len(paths) < 2:
        raise RuntimeError("A flipbook needs at least two image files on disk.")
    _emit(progress, "Building flipbook PDF…", percent=40, title="Flipbook")
    pdf_bytes = images_to_pdf(paths, title=title_from_prompt(prompt, "Flipbook"))
    cid = f"doc_{uuid.uuid4().hex[:10]}"
    stored = write_media_bytes(
        cid, pdf_bytes, mime_type="application/pdf", config=config, suffix=".pdf"
    )
    extras: list[dict[str, Any]] = []
    video_path = ""
    try:
        from .video_edit import FfmpegNotFoundError, build_image_slideshow

        _emit(progress, "Rendering slideshow video…", percent=70, title="Flipbook")
        raise_if_cancelled(_cancelled)
        import tempfile

        with tempfile.TemporaryDirectory(prefix="ste_flip_") as tmp:
            dest = Path(tmp) / "slideshow.mp4"
            build_image_slideshow(paths, dest, seconds_per_image=seconds)
            raw = dest.read_bytes()
        vid_id = f"doc_{uuid.uuid4().hex[:10]}"
        vstored = write_media_bytes(
            vid_id, raw, mime_type="video/mp4", config=config, suffix=".mp4"
        )
        video_path = vstored["mediaPath"]
        clip = build_media_creation(
            modality="video",
            prompt=prompt,
            media_path=video_path,
            mime_type="video/mp4",
            title=f"Slideshow — {title_from_prompt(prompt, 'Flipbook')}",
            creation_id=vid_id,
        )
        vmeta = dict(clip.get("meta") or {})
        vmeta["studioJob"] = "flipbook_video"
        clip["meta"] = vmeta
        extras.append(clip)
    except Exception as exc:
        from .cancellation import GenerationCancelled
        from .video_edit import FfmpegNotFoundError

        if isinstance(exc, GenerationCancelled):
            raise
        if not isinstance(exc, FfmpegNotFoundError):
            logger.warning("Flipbook slideshow video skipped: %s", exc)

    result = build_media_creation(
        modality="pdf",
        prompt=prompt,
        media_path=stored["mediaPath"],
        mime_type="application/pdf",
        title=title_from_prompt(prompt, "Flipbook"),
        creation_id=cid,
    )
    meta = dict(result.get("meta") or {})
    meta["studioJob"] = "flipbook"
    meta["flipbook"] = {
        "pages": pages,
        "secondsPerPage": seconds,
        "videoMediaPath": video_path,
    }
    result["meta"] = meta
    result["overview"] = f"{len(pages)} pages. Open the Flipbook tab to turn pages."
    return _attach_extras(result, extras)


def _run_contact_sheet(
    members: list[dict[str, Any]],
    *,
    prompt: str,
    config: dict[str, Any],
    progress: ProgressCallback | None,
    cancel_event: Any,
) -> dict[str, Any]:
    from .cancellation import raise_if_cancelled
    from .media_store import write_media_bytes
    from .pdf_build import contact_sheet_png, images_to_pdf

    def _cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    images = _image_members(members)
    if not images:
        raise RuntimeError("A contact sheet needs at least one image.")
    raise_if_cancelled(_cancelled)
    paths = [p for src in images if (p := _media_path(src, config)) is not None]
    if not paths:
        raise RuntimeError("Contact sheet images are missing on disk.")
    _emit(progress, "Building contact sheet…", percent=50, title="Contact sheet")
    png = contact_sheet_png(paths)
    cid = f"doc_{uuid.uuid4().hex[:10]}"
    stored = write_media_bytes(
        cid, png, mime_type="image/png", config=config, suffix=".png"
    )
    result = build_media_creation(
        modality="image",
        prompt=prompt,
        media_path=stored["mediaPath"],
        mime_type="image/png",
        title=title_from_prompt(prompt, "Contact sheet"),
        creation_id=cid,
    )
    meta = dict(result.get("meta") or {})
    meta["studioJob"] = "contact_sheet"
    result["meta"] = meta
    extras: list[dict[str, Any]] = []
    try:
        pdf = images_to_pdf(paths, title=result["title"])
        pdf_id = f"doc_{uuid.uuid4().hex[:10]}"
        pstored = write_media_bytes(
            pdf_id, pdf, mime_type="application/pdf", config=config, suffix=".pdf"
        )
        extra = build_media_creation(
            modality="pdf",
            prompt=prompt,
            media_path=pstored["mediaPath"],
            mime_type="application/pdf",
            title=f"{result['title']} PDF",
            creation_id=pdf_id,
        )
        extras.append(extra)
    except Exception:
        logger.debug("Contact sheet PDF skipped", exc_info=True)
    return _attach_extras(result, extras)


def _run_assemble_pdf(
    members: list[dict[str, Any]],
    *,
    prompt: str,
    config: dict[str, Any],
    progress: ProgressCallback | None,
    cancel_event: Any,
) -> dict[str, Any]:
    from .cancellation import raise_if_cancelled
    from .media_store import write_media_bytes
    from .pdf_build import images_to_pdf

    raise_if_cancelled(
        lambda: bool(cancel_event is not None and cancel_event.is_set())
    )
    images = _image_members(members)
    paths = [p for src in images if (p := _media_path(src, config)) is not None]
    if not paths:
        raise RuntimeError("No images on disk to put in a PDF.")
    _emit(progress, "Writing PDF…", percent=55, title="PDF")
    pdf_bytes = images_to_pdf(paths, title=title_from_prompt(prompt, "Images"))
    cid = f"doc_{uuid.uuid4().hex[:10]}"
    stored = write_media_bytes(
        cid, pdf_bytes, mime_type="application/pdf", config=config, suffix=".pdf"
    )
    result = build_media_creation(
        modality="pdf",
        prompt=prompt,
        media_path=stored["mediaPath"],
        mime_type="application/pdf",
        title=title_from_prompt(prompt, "Image PDF"),
        creation_id=cid,
    )
    meta = dict(result.get("meta") or {})
    meta["studioJob"] = "assemble_pdf"
    result["meta"] = meta
    return result


def _run_generic_map(
    members: list[dict[str, Any]],
    *,
    prompt: str,
    config: dict[str, Any],
    progress: ProgressCallback | None,
    cancel_event: Any,
) -> dict[str, Any]:
    """Per-file Gemini instruction, then one combined text document."""
    from .cancellation import raise_if_cancelled
    from .extract_text import _gemini_multimodal
    from .generator import _active_model_and_provider
    from .media_store import read_media_bytes
    from .studio_sources import TEXT_BODY_MAX, _creation_text_body

    def _cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    model_id, _provider = _active_model_and_provider(config)
    instruction = (prompt or "").strip() or "Describe this file. Do not invent facts."
    blocks: list[str] = []
    total = len(members)
    for index, src in enumerate(members):
        raise_if_cancelled(_cancelled)
        title = original_filename_for_creation(src) or _creation_title(src)
        _emit(
            progress,
            f"Reading file {index + 1} of {total}: {title}",
            percent=8 + int(80 * index / max(total, 1)),
            title="Collection",
        )
        mod = creation_source_modality(src)
        try:
            if mod in {"image", "pdf", "audio", "video"}:
                raw = read_media_bytes(src.get("mediaPath"), config=config) or b""
                if not raw:
                    blocks.append(f"## {title}\n(missing file)")
                    continue
                mime = str(src.get("mimeType") or "")
                if mod == "image" and not mime.startswith("image/"):
                    mime = "image/png"
                if mod == "pdf":
                    mime = "application/pdf"
                if mod == "audio" and not mime.startswith("audio/"):
                    mime = "audio/mpeg"
                if mod == "video" and not mime.startswith("video/"):
                    mime = "video/mp4"
                text, _model = _gemini_multimodal(
                    raw,
                    mime_type=mime,
                    prompt=instruction,
                    config=config,
                    model_id=model_id,
                    progress=progress,
                    cancel_check=_cancelled,
                    cancel_event=cancel_event,
                )
                blocks.append(f"## {title}\n{(text or '').strip() or '(empty)'}")
            else:
                body = _creation_text_body(src)[:TEXT_BODY_MAX]
                from .extract_text import gemini_text_prompt

                text, _model = gemini_text_prompt(
                    f"{instruction}\n\n---\nSource: {title}\n\n{body}",
                    config=config,
                    model_id=model_id,
                    progress=progress,
                    cancel_check=_cancelled,
                    cancel_event=cancel_event,
                )
                blocks.append(f"## {title}\n{(text or '').strip() or body}")
        except Exception as exc:
            from .cancellation import GenerationCancelled

            if isinstance(exc, GenerationCancelled):
                raise
            logger.warning("Generic map failed for %s: %s", title, exc)
            blocks.append(f"## {title}\n(Could not read: {exc})")
    body = "\n\n".join(blocks).strip() or "(empty)"
    result = build_text_creation_from_plain(
        body, prompt=prompt, title=title_from_prompt(prompt, "Collection")
    )
    result["title"] = title_from_prompt(prompt, f"Collection ({len(members)} files)")
    result["game"] = result["title"]
    meta = dict(result.get("meta") or {})
    meta["studioJob"] = "collection_map"
    result["meta"] = meta
    return result
