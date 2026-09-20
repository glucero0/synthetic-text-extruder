"""Studio Sources: gather briefs from mixed attachments, then synthesize a report."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable

from .creation_utils import extract_json_object
from .modality import (
    infer_layout_extract_intent,
    infer_prompt_modality,
    infer_report_intent,
    infer_text_extract_intent,
    normalize_modality,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[Any], None]

MAX_SOURCES = 12
TEXT_BODY_MAX = 80_000
_MAX_FIGURE_BYTES = 18 * 1024 * 1024
_MAX_LAYOUT_SECTIONS = 24
_MAX_PARAS_PER_SECTION = 12
_MAX_PARA_CHARS = 4000
_MAX_ORIGINAL_FILENAME = 200
DEFAULT_REPORT_PROMPT = (
    "Write a single report from the attached sources. Combine transcripts, "
    "image descriptions, and document text. Cite each source by title."
)

IMAGE_BRIEF_PROMPT = (
    "Write a concise research brief for this image (about 120–200 words). "
    "Include the subject, setting, any readable text (OCR), and notable details. "
    "Do not invent facts you cannot see."
)

AUDIO_BRIEF_PROMPT = (
    "Transcribe all spoken words from this audio as plain text. Then, in one "
    "short paragraph, note whether it is speech, music, or both, and any other "
    "useful context. If there is no speech, say so."
)

PDF_BRIEF_PROMPT = (
    "Extract the useful content of this PDF for a research brief. Preserve "
    "headings and key facts. Summarize long passages. Do not invent content "
    "that is not in the document."
)


def safe_original_filename(name: str | None) -> str:
    """Basename only — never a path — for prompt/clipboard use."""
    # pathlib.Path is OS-specific: on POSIX, "C:\inbox\file.pdf" is one name.
    # Treat both separators as path parts so Windows uploads still sanitize on Linux.
    normalized = str(name or "").replace("\\", "/")
    base = Path(normalized).name.strip()
    if not base or base in {".", ".."}:
        return ""
    if "/" in base or "\\" in base:
        return ""
    return base[:_MAX_ORIGINAL_FILENAME]


def apply_original_filename(creation: dict[str, Any], name: str | None) -> dict[str, Any]:
    """Stamp the imported basename onto a creation record."""
    out = dict(creation)
    filename = safe_original_filename(name)
    if not filename:
        return out
    meta = dict(out.get("meta") or {})
    meta["originalFilename"] = filename
    out["meta"] = meta
    return out


def original_filename_for_creation(creation: dict[str, Any] | None) -> str:
    if not creation:
        return ""
    meta = creation.get("meta") if isinstance(creation.get("meta"), dict) else {}
    named = safe_original_filename(str(meta.get("originalFilename") or ""))
    if named:
        return named
    prompt = str(creation.get("prompt") or "")
    prefix = "Imported from "
    if prompt.startswith(prefix):
        named = safe_original_filename(prompt[len(prefix) :].strip())
        if named:
            return named
    return safe_original_filename(str(creation.get("title") or creation.get("game") or ""))


def creation_source_modality(creation: dict[str, Any] | None) -> str:
    """Return text/image/video/audio/pdf for a Studio source item."""
    if not creation:
        return "text"
    mime = str(creation.get("mimeType") or "").lower().split(";", 1)[0].strip()
    raw = str(creation.get("modality") or "").strip().lower()
    if raw == "pdf" or mime == "application/pdf":
        return "pdf"
    mod = normalize_modality(creation.get("modality"), default="")
    if mod:
        return mod
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime == "application/pdf":
        return "pdf"
    return "text"


def wants_source_report(prompt: str, sources: list[dict[str, Any]] | None) -> bool:
    """True when CREATE should gather sources and write a text report."""
    items = [s for s in (sources or []) if isinstance(s, dict)]
    if not items:
        return False
    text = (prompt or "").strip() or DEFAULT_REPORT_PROMPT
    prompt_mod = infer_prompt_modality(text)
    mods = [creation_source_modality(s) for s in items]
    if infer_report_intent(text):
        return True
    if prompt_mod in {"image", "video", "audio"}:
        return False

    extract = infer_layout_extract_intent(text) or infer_text_extract_intent(text)
    if extract:
        named, _err = match_quoted_source(
            text, items, modalities={"image", "video"}
        )
        if named:
            return False
        if any(creation_source_modality(s) in {"image", "video"} for s in items):
            return False

    if len(items) >= 2:
        return True

    only = mods[0]
    if only in {"text", "pdf", "audio"}:
        return True
    if only in {"image", "video"}:
        if infer_layout_extract_intent(text) or infer_text_extract_intent(text):
            return False
        return prompt_mod == "text"
    return False


def last_visual_source(sources: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    items = [s for s in (sources or []) if isinstance(s, dict)]
    for item in reversed(items):
        if creation_source_modality(item) in {"image", "video"}:
            return item
    return None


_QUOTED_NAME_RE = re.compile(r'"([^"]{1,200})"|“([^”]{1,200})”')
_GENERIC_SOURCE_ALIAS = {
    "extract",
    "text",
    "image",
    "video",
    "photo",
    "picture",
    "clip",
    "layout",
    "report",
    "untitled",
    "prompt",
    "screenshot",
    "source",
    "audio",
    "song",
    "pdf",
}


def fold_source_name(value: str | None) -> str:
    """Casefold a title/filename for matching (spaces, hyphens, extension ignored)."""
    text = (value or "").strip().casefold()
    if not text:
        return ""
    stem, _sep, ext = text.rpartition(".")
    if stem and 1 <= len(ext) <= 8 and ext.isalnum():
        text = stem
    text = re.sub(r"[\s_\-]+", " ", text)
    return text.strip()


def quoted_source_needles(prompt: str) -> list[str]:
    """Double-quoted names in the prompt (⋯ Add filename uses this shape)."""
    out: list[str] = []
    for match in _QUOTED_NAME_RE.finditer(prompt or ""):
        needle = (match.group(1) or match.group(2) or "").strip()
        if needle:
            out.append(needle)
    return out


def source_match_aliases(creation: dict[str, Any] | None) -> list[str]:
    if not creation:
        return []
    raw = [
        str(creation.get("title") or ""),
        str(creation.get("game") or ""),
        original_filename_for_creation(creation),
        str(creation.get("prompt") or "").split("\n", 1)[0],
    ]
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        folded = fold_source_name(item)
        if not folded or folded in seen or folded in _GENERIC_SOURCE_ALIAS:
            continue
        seen.add(folded)
        out.append(folded)
    return out


def match_quoted_source(
    prompt: str,
    sources: list[dict[str, Any]] | None,
    *,
    modalities: set[str] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Return the unique source named in quotes, or an error if quotes do not match."""
    needles = quoted_source_needles(prompt)
    if not needles:
        named = _match_unquoted_source_title(prompt, sources, modalities=modalities)
        return named, ""
    items = [s for s in (sources or []) if isinstance(s, dict)]
    last_error = ""
    allowed = modalities or set()
    for needle in needles:
        folded = fold_source_name(needle)
        if len(folded) < 2:
            continue
        exact: list[dict[str, Any]] = []
        partial: list[dict[str, Any]] = []
        for src in items:
            aliases = source_match_aliases(src)
            if folded in aliases:
                exact.append(src)
            elif any(
                len(alias) >= 4
                and len(folded) >= 4
                and (folded in alias or alias in folded)
                for alias in aliases
            ):
                partial.append(src)
        hits = exact or partial
        if not hits:
            last_error = f'No Studio source matches "{needle}".'
            continue
        typed = hits
        if allowed:
            typed = [s for s in hits if creation_source_modality(s) in allowed]
            if hits and not typed:
                last_error = (
                    f'"{needle}" is in Sources but is not an image or video.'
                )
                continue
        uniq = _unique_sources(typed)
        if len(uniq) == 1:
            return uniq[0], ""
        last_error = (
            f'Several sources match "{needle}". Use the exact filename from ⋯.'
        )
    return None, last_error


def _unique_sources(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for src in items:
        sid = str(src.get("id") or "")
        key = sid or str(id(src))
        if key in seen:
            continue
        seen.add(key)
        out.append(src)
    return out


def _match_unquoted_source_title(
    prompt: str,
    sources: list[dict[str, Any]] | None,
    *,
    modalities: set[str] | None = None,
) -> dict[str, Any] | None:
    """If one source title/filename appears in the prompt, use it."""
    folded_prompt = fold_source_name(prompt)
    if not folded_prompt:
        return None
    items = [s for s in (sources or []) if isinstance(s, dict)]
    if modalities:
        items = [s for s in items if creation_source_modality(s) in modalities]
    hits: list[dict[str, Any]] = []
    for src in items:
        aliases = source_match_aliases(src)
        if any(len(alias) >= 6 and alias in folded_prompt for alias in aliases):
            hits.append(src)
    uniq = _unique_sources(hits)
    if len(uniq) == 1:
        return uniq[0]
    return None


def list_source_files_in_folder(
    folder: Path, *, recursive: bool = False
) -> list[Path]:
    """List supported files; skip hidden files, directories, and symlinks.

    Immediate children by default. ``recursive=True`` walks subfolders but still
    skips hidden names, symlinks, and anything outside the chosen folder.
    """
    from .media_store import modality_for_path

    try:
        parent = folder.expanduser().resolve()
    except OSError:
        return []
    if not parent.is_dir():
        return []
    out: list[Path] = []

    def _accept(child: Path) -> Path | None:
        if child.name.startswith("."):
            return None
        if child.is_symlink() or not child.is_file():
            return None
        try:
            resolved = child.resolve()
            resolved.relative_to(parent)
        except (OSError, ValueError):
            return None
        if not resolved.is_file() or modality_for_path(resolved) is None:
            return None
        return resolved

    try:
        if recursive:
            candidates = sorted(
                (p for p in parent.rglob("*") if p.is_file() and not p.is_symlink()),
                key=lambda p: str(p).lower(),
            )
            filtered: list[Path] = []
            for child in candidates:
                if any(part.startswith(".") for part in child.relative_to(parent).parts):
                    continue
                accepted = _accept(child)
                if accepted is not None:
                    filtered.append(accepted)
            return filtered
        children = sorted(parent.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    for child in children:
        accepted = _accept(child)
        if accepted is not None:
            out.append(accepted)
    return out


def _creation_title(creation: dict[str, Any]) -> str:
    return str(
        creation.get("title")
        or creation.get("game")
        or (str(creation.get("prompt") or "").split("\n", 1)[0].strip())
        or "Untitled"
    ).strip() or "Untitled"


def _creation_text_body(creation: dict[str, Any]) -> str:
    parts: list[str] = []
    overview = str(creation.get("overview") or "").strip()
    if overview:
        parts.append(overview)
    for sec in creation.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        title = str(sec.get("title") or "").strip()
        content = str(sec.get("content") or "").strip()
        if title and content:
            parts.append(f"{title}\n{content}")
        elif content:
            parts.append(content)
        elif title:
            parts.append(title)
    body = "\n\n".join(parts).strip()
    if len(body) > TEXT_BODY_MAX:
        return body[:TEXT_BODY_MAX].rstrip() + "\n…(truncated)"
    return body


def _emit(
    progress: ProgressCallback | None,
    message: str,
    *,
    percent: float | None = None,
    title: str = "Reading sources",
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
    except Exception:  # noqa: BLE001
        logger.debug("progress callback failed", exc_info=True)


def _truncate_brief(text: str) -> str:
    body = (text or "").strip()
    if len(body) > TEXT_BODY_MAX:
        return body[:TEXT_BODY_MAX].rstrip() + "\n…(truncated)"
    return body


def _brief_from_creation(
    creation: dict[str, Any],
    *,
    config: dict[str, Any],
    progress: ProgressCallback | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    from .cancellation import raise_if_cancelled
    from .extract_text import (
        MAX_INLINE_BYTES,
        _extract_video,
        _gemini_multimodal,
    )
    from .generator import _active_model_and_provider
    from .media_store import read_media_bytes, resolve_media_path

    def _cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    cid = str(creation.get("id") or "")
    title = _creation_title(creation)
    modality = creation_source_modality(creation)
    out: dict[str, Any] = {
        "id": cid,
        "title": title,
        "modality": modality,
        "brief": "",
        "error": "",
    }
    raise_if_cancelled(_cancelled)
    model_id, _provider = _active_model_and_provider(config)

    if modality == "text":
        out["brief"] = _creation_text_body(creation)
        if not out["brief"]:
            out["error"] = "Text source is empty."
        return out

    path = resolve_media_path(creation.get("mediaPath"), config=config)
    raw = read_media_bytes(creation.get("mediaPath"), config=config)
    mime = str(creation.get("mimeType") or "").lower() or "application/octet-stream"

    try:
        if modality == "image":
            if not raw:
                raise RuntimeError("Image file is missing on disk.")
            if len(raw) > MAX_INLINE_BYTES:
                raise RuntimeError("Image is too large to attach as a source.")
            image_mime = mime if mime.startswith("image/") else "image/png"
            text, _model = _gemini_multimodal(
                raw,
                mime_type=image_mime,
                prompt=IMAGE_BRIEF_PROMPT,
                config=config,
                model_id=model_id,
                progress=progress,
                cancel_check=_cancelled,
                cancel_event=cancel_event,
            )
            out["brief"] = _truncate_brief(text)
        elif modality == "video":
            if path is None:
                raise RuntimeError("Video file is missing on disk.")
            text, _model, _kind = _extract_video(
                path,
                mime_type=mime if mime.startswith("video/") else "video/mp4",
                config=config,
                model_id=model_id,
                progress=progress,
                cancel_check=_cancelled,
                cancel_event=cancel_event,
            )
            out["brief"] = _truncate_brief(text)
        elif modality == "audio":
            if not raw:
                raise RuntimeError("Audio file is missing on disk.")
            if len(raw) > MAX_INLINE_BYTES:
                raise RuntimeError("Audio is too large to attach as a source.")
            audio_mime = mime if mime.startswith("audio/") else "audio/mpeg"
            text, _model = _gemini_multimodal(
                raw,
                mime_type=audio_mime,
                prompt=AUDIO_BRIEF_PROMPT,
                config=config,
                model_id=model_id,
                progress=progress,
                cancel_check=_cancelled,
                cancel_event=cancel_event,
            )
            out["brief"] = _truncate_brief(text)
        elif modality == "pdf":
            if not raw:
                raise RuntimeError("PDF file is missing on disk.")
            if len(raw) > MAX_INLINE_BYTES:
                raise RuntimeError("PDF is too large to attach as a source.")
            text, _model = _gemini_multimodal(
                raw,
                mime_type="application/pdf",
                prompt=PDF_BRIEF_PROMPT,
                config=config,
                model_id=model_id,
                progress=progress,
                cancel_check=_cancelled,
                cancel_event=cancel_event,
            )
            out["brief"] = _truncate_brief(text)
        else:
            raise RuntimeError(f"Unsupported source type: {modality}")
    except Exception as exc:  # noqa: BLE001
        from .cancellation import GenerationCancelled

        if isinstance(exc, GenerationCancelled):
            raise
        logger.warning("Studio source gather failed for %s: %s", cid or title, exc)
        out["error"] = str(exc)
    if not out["brief"] and not out["error"]:
        out["error"] = "No content extracted."
    return out


def gather_source_briefs(
    sources: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    progress: ProgressCallback | None = None,
    cancel_event: Any = None,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    """Read each source into a brief. Does not write back onto Archive items."""
    from .cancellation import raise_if_cancelled

    cap = MAX_SOURCES if max_items is None else max(1, int(max_items))
    items = [s for s in sources if isinstance(s, dict)][:cap]
    briefs: list[dict[str, Any]] = []
    total = max(len(items), 1)
    for index, creation in enumerate(items):
        raise_if_cancelled(
            lambda: bool(cancel_event is not None and cancel_event.is_set())
        )
        title = _creation_title(creation)
        pct = 8 + int(52 * index / total)
        _emit(
            progress,
            f"Reading source {index + 1} of {len(items)}: {title}",
            percent=pct,
        )
        briefs.append(
            _brief_from_creation(
                creation,
                config=config,
                progress=progress,
                cancel_event=cancel_event,
            )
        )
    return briefs


def _format_briefs_for_prompt(briefs: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for brief in briefs:
        title = str(brief.get("title") or "Untitled")
        modality = str(brief.get("modality") or "text")
        header = f"### {title} ({modality})"
        body = str(brief.get("brief") or "").strip()
        error = str(brief.get("error") or "").strip()
        if body:
            blocks.append(f"{header}\n{body}")
        elif error:
            blocks.append(f"{header}\n(Could not read this source: {error})")
        else:
            blocks.append(f"{header}\n(No content.)")
    return "\n\n".join(blocks)


def _sources_appendix(briefs: list[dict[str, Any]]) -> str:
    lines = []
    for brief in briefs:
        title = str(brief.get("title") or "Untitled")
        modality = str(brief.get("modality") or "text")
        extra = ""
        if brief.get("error") and not str(brief.get("brief") or "").strip():
            extra = f" — unread ({brief.get('error')})"
        lines.append(f"- {title} ({modality}){extra}")
    return "\n".join(lines)


def report_figure_candidates(sources: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Image/video sources the report can place as figures (ids the model may cite)."""
    out: list[dict[str, str]] = []
    for src in sources or []:
        if not isinstance(src, dict):
            continue
        mod = creation_source_modality(src)
        if mod == "image":
            kind = "image"
        elif mod == "video":
            kind = "video-frame"
        else:
            continue
        sid = str(src.get("id") or "").strip()
        if not sid:
            continue
        out.append(
            {
                "sourceId": sid,
                "title": _creation_title(src),
                "kind": kind,
            }
        )
    return out


def _plain_prose(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").strip()
    t = re.sub(r"^```(?:json|markdown|md)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t).strip()
    t = re.sub(r"[*]{2,3}(.+?)[*]{2,3}", r"\1", t)
    t = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", t)
    t = re.sub(r"^#{1,6}\s+", "", t, flags=re.MULTILINE)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    return t.strip()


def _paragraphs_from_text(text: str) -> list[str]:
    body = _plain_prose(text)
    if not body:
        return []
    out: list[str] = []
    for chunk in re.split(r"\n\s*\n", body):
        para = " ".join(
            line.strip() for line in chunk.split("\n") if line.strip()
        ).strip()
        if para:
            out.append(para[:_MAX_PARA_CHARS])
        if len(out) >= _MAX_PARAS_PER_SECTION:
            break
    return out


def _paragraphs_from_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return _paragraphs_from_text(value)
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            para = _plain_prose(str(item or ""))
            if para:
                out.append(para[:_MAX_PARA_CHARS])
            if len(out) >= _MAX_PARAS_PER_SECTION:
                break
        return out
    return []


def _match_figure(
    token: str,
    figures: list[dict[str, Any]],
) -> dict[str, Any] | None:
    needle = (token or "").strip()
    if not needle:
        return None
    for fig in figures:
        if str(fig.get("sourceId") or "") == needle or str(fig.get("id") or "") == needle:
            return fig
    lowered = needle.casefold()
    title_hits = [
        fig
        for fig in figures
        if str(fig.get("title") or "").strip().casefold() == lowered
    ]
    if len(title_hits) == 1:
        return title_hits[0]
    return None


def normalize_report_layout(
    data: dict[str, Any] | None,
    figures: list[dict[str, Any]],
    *,
    fallback_title: str,
    fallback_body: str,
) -> dict[str, Any]:
    """Sanitize model JSON into a Viewer layout. Always append unused figures."""
    title = _plain_prose(str((data or {}).get("title") or fallback_title))[:200]
    if not title:
        title = (fallback_title or "Sources report").strip()[:200] or "Sources report"
    sections_out: list[dict[str, Any]] = []
    used: set[str] = set()
    raw_sections = (data or {}).get("sections") if isinstance(data, dict) else None
    if not isinstance(raw_sections, list) or not raw_sections:
        paras = _paragraphs_from_text(fallback_body)
        if not paras:
            paras = ["Source pictures from this CREATE are attached below."]
        sections_out.append(
            {
                "heading": "",
                "paragraphs": paras[:_MAX_PARAS_PER_SECTION],
                "figureId": "",
                "figureCaption": "",
            }
        )
    else:
        for sec in raw_sections:
            if not isinstance(sec, dict):
                continue
            heading = _plain_prose(str(sec.get("heading") or ""))[:200]
            paras = _paragraphs_from_value(sec.get("paragraphs"))
            token = str(
                sec.get("figureSourceId")
                or sec.get("figure_source_id")
                or sec.get("figureId")
                or ""
            ).strip()
            fig = _match_figure(token, figures)
            figure_id = ""
            caption = _plain_prose(
                str(sec.get("figureCaption") or sec.get("figure_caption") or "")
            )[:300]
            if fig:
                fid = str(fig.get("id") or "")
                if fid and fid not in used:
                    figure_id = fid
                    used.add(fid)
                    if not caption:
                        caption = str(fig.get("title") or "")[:300]
            if not heading and not paras and not figure_id:
                continue
            sections_out.append(
                {
                    "heading": heading,
                    "paragraphs": paras,
                    "figureId": figure_id,
                    "figureCaption": caption if figure_id else "",
                }
            )
            if len(sections_out) >= _MAX_LAYOUT_SECTIONS:
                break
        if not sections_out:
            paras = _paragraphs_from_text(fallback_body)
            sections_out.append(
                {
                    "heading": "",
                    "paragraphs": paras
                    or ["Source pictures from this CREATE are attached below."],
                    "figureId": "",
                    "figureCaption": "",
                }
            )
    for fig in figures:
        fid = str(fig.get("id") or "")
        if not fid or fid in used:
            continue
        if len(sections_out) >= _MAX_LAYOUT_SECTIONS:
            break
        caption = str(fig.get("title") or "Figure")[:300]
        sections_out.append(
            {
                "heading": caption,
                "paragraphs": [],
                "figureId": fid,
                "figureCaption": caption,
            }
        )
        used.add(fid)
    return {"title": title, "sections": sections_out}


def layout_to_plain_sections(layout: dict[str, Any]) -> list[dict[str, Any]]:
    """Archive/export-text copy of an illustrated layout (no HTML)."""
    parts: list[dict[str, Any]] = []
    for sec in layout.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        chunks = [str(p).strip() for p in (sec.get("paragraphs") or []) if str(p).strip()]
        cap = str(sec.get("figureCaption") or "").strip()
        if sec.get("figureId"):
            chunks.append(f"[Figure: {cap}]" if cap else "[Figure]")
        parts.append(
            {
                "title": str(sec.get("heading") or ""),
                "content": "\n\n".join(chunks),
                "keyValues": [],
            }
        )
    return parts


def snapshot_report_figures(
    sources: list[dict[str, Any]],
    *,
    report_id: str,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Copy source stills onto the new report so clearing Sources does not blank the PDF."""
    from .media_store import read_media_bytes, resolve_media_path, write_media_bytes

    figures: list[dict[str, Any]] = []
    stem = str(report_id or "report").strip() or "report"
    index = 0
    for src in sources:
        if not isinstance(src, dict):
            continue
        mod = creation_source_modality(src)
        raw: bytes | None = None
        mime = "image/png"
        kind = "image"
        try:
            if mod == "image":
                raw = read_media_bytes(src.get("mediaPath"), config=config)
                src_mime = str(src.get("mimeType") or "").lower()
                mime = src_mime if src_mime.startswith("image/") else "image/png"
            elif mod == "video":
                from .video_edit import extract_video_frame_png

                path = resolve_media_path(src.get("mediaPath"), config=config)
                if path is None:
                    raise RuntimeError("Video file is missing on disk.")
                raw = extract_video_frame_png(path, at_seconds=0.5)
                mime = "image/png"
                kind = "video-frame"
            else:
                continue
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Studio report figure snapshot skipped for %s: %s",
                src.get("id") or _creation_title(src),
                exc,
            )
            continue
        if not raw:
            continue
        if len(raw) > _MAX_FIGURE_BYTES:
            logger.warning(
                "Studio report figure skipped (too large) for %s",
                src.get("id") or _creation_title(src),
            )
            continue
        try:
            stored = write_media_bytes(
                f"{stem}_fig{index}",
                raw,
                mime_type=mime,
                config=config,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Studio report figure write failed: %s", exc)
            continue
        figures.append(
            {
                "id": f"fig_{index}",
                "sourceId": str(src.get("id") or ""),
                "title": _creation_title(src),
                "mediaPath": stored["mediaPath"],
                "mimeType": stored["mimeType"],
                "kind": kind,
            }
        )
        index += 1
    return figures


def _format_figure_catalog(candidates: list[dict[str, str]]) -> str:
    if not candidates:
        return "(none — leave figureSourceId empty on every section)"
    lines = []
    for item in candidates:
        lines.append(
            f"- figureSourceId: {item['sourceId']}  title: {item['title']}  "
            f"kind: {item['kind']}"
        )
    return "\n".join(lines)


def _illustrated_synth_prompt(
    request: str,
    briefs: list[dict[str, Any]],
    candidates: list[dict[str, str]],
) -> str:
    return (
        "You are writing one illustrated report from gathered source briefs.\n\n"
        f"User request:\n{request}\n\n"
        "Available figures (figureSourceId must be one of these ids, or empty). "
        "Place each figure at most once, next to the section that discusses it. "
        "You may omit figureSourceId when a section has no picture.\n"
        f"{_format_figure_catalog(candidates)}\n\n"
        "Source briefs (cite each by title when you use it). "
        "Do not invent facts that are not in the briefs. "
        "If a source could not be read, say so.\n\n"
        f"{_format_briefs_for_prompt(briefs)}\n\n"
        "Return ONLY a JSON object (no markdown fences, no HTML) with this shape:\n"
        "{\n"
        '  "title": "short document title",\n'
        '  "sections": [\n'
        "    {\n"
        '      "heading": "section heading or empty string",\n'
        '      "paragraphs": ["plain prose sentences", "no markdown"],\n'
        '      "figureSourceId": "id from the available figures list, or empty string",\n'
        '      "figureCaption": "caption if a figure is placed, else empty string"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Rules: paragraphs are plain sentences. Do not use markdown, HTML, or asterisks "
        "for bold. End with a Sources section listing attached titles."
    )


def _fallback_body_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if extract_json_object(text) is not None:
        return ""
    if text.lstrip().startswith("{"):
        return ""
    return _plain_prose(text)


def gather_then_synthesize(
    sources: list[dict[str, Any]],
    *,
    game: str,
    platform: str,
    creation_type: str,
    config: dict[str, Any],
    user_prompt: str,
    progress: ProgressCallback | None = None,
    cancel_event: Any = None,
    tool_aliases: list[str] | None = None,
    search_query: str | None = None,
    max_items: int | None = None,
) -> dict[str, Any]:
    """Gather per-source briefs, then write one cited illustrated report."""
    from .cancellation import raise_if_cancelled
    from .gemini_provider import generate_with_gemini

    def _cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    raise_if_cancelled(_cancelled)
    briefs = gather_source_briefs(
        sources,
        config=config,
        progress=progress,
        cancel_event=cancel_event,
        max_items=max_items,
    )
    usable = [b for b in briefs if str(b.get("brief") or "").strip()]
    if not usable:
        errors = "; ".join(
            str(b.get("error") or "unread") for b in briefs if b.get("error")
        )
        raise RuntimeError(
            "Could not read any Studio sources"
            + (f": {errors}" if errors else ".")
        )

    request = (user_prompt or "").strip() or DEFAULT_REPORT_PROMPT
    candidates = report_figure_candidates(sources)
    synth_prompt = _illustrated_synth_prompt(request, briefs, candidates)
    _emit(progress, "Writing report from sources…", percent=70, title="Creating…")
    raise_if_cancelled(_cancelled)

    system_extra = (config.get("prompt") or {}).get("extra_instructions", "") or ""
    result = generate_with_gemini(
        (game or "").strip() or "Sources report",
        (platform or "").strip() or "General",
        (creation_type or "").strip() or "Report",
        gemini_cfg=config.get("gemini") or {},
        system_extra=system_extra,
        creation_description=synth_prompt,
        progress=progress,
        exact_title=True,
        forced_modality="text",
        cancel_event=cancel_event,
        tool_aliases=tool_aliases,
        search_query=search_query,
    )
    raise_if_cancelled(_cancelled)
    raw_body = _creation_text_body(result)
    parsed = extract_json_object(raw_body)
    report_id = str(result.get("id") or "report")
    _emit(progress, "Attaching source pictures…", percent=88, title="Creating…")
    figures = snapshot_report_figures(sources, report_id=report_id, config=config)
    fallback_title = str(result.get("title") or request).strip() or "Sources report"
    layout = normalize_report_layout(
        parsed if isinstance(parsed, dict) else None,
        figures,
        fallback_title=fallback_title,
        fallback_body=_fallback_body_text(raw_body) or request,
    )
    appendix = _sources_appendix(briefs)
    has_sources_heading = any(
        re.search(r"^sources$", str(sec.get("heading") or ""), re.I)
        for sec in layout["sections"]
    )
    if appendix and not has_sources_heading:
        layout["sections"].append(
            {
                "heading": "Sources",
                "paragraphs": [
                    line.lstrip("- ").strip()
                    for line in appendix.splitlines()
                    if line.strip()
                ],
                "figureId": "",
                "figureCaption": "",
            }
        )
    display_title = str(layout.get("title") or fallback_title).strip() or "Sources report"
    result["title"] = display_title
    result["game"] = display_title
    result["prompt"] = request
    result["overview"] = ""
    result["creationType"] = "Report"
    result["sections"] = layout_to_plain_sections(layout)
    if appendix:
        sections = list(result["sections"])
        if not any(
            re.search(r"^attached sources$", str(sec.get("title") or ""), re.I)
            for sec in sections
        ):
            sections.append(
                {"title": "Attached sources", "content": appendix, "keyValues": []}
            )
        result["sections"] = sections
    meta = dict(result.get("meta") or {})
    meta["studioJob"] = "report"
    meta["sourceCreationIds"] = [
        str(b.get("id") or "") for b in briefs if b.get("id")
    ]
    meta["reportLayout"] = layout
    meta["reportFigures"] = figures
    result["meta"] = meta
    # Illustrated reports are documents (Export PDF / PNG), even when every
    # source was a video. Do not keep a leftover mediaPath that would make
    # Viewer offer Save MP4.
    result["modality"] = "text"
    result.pop("mediaPath", None)
    result.pop("mimeType", None)
    return result
