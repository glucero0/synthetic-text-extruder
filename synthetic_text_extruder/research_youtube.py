"""Discover YouTube URLs from search and pull captions into the research brief."""

from __future__ import annotations

import logging
import re
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[Any], None]

MAX_YOUTUBE_VIDEOS = 2
_MAX_CAPTION_CHARS = 12000

_YOUTUBE_HOSTS = frozenset(
    {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
)
_URL_IN_TEXT_RE = re.compile(r"""https?://[^\s<>"')\]]+""", re.IGNORECASE)


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:  # noqa: BLE001
        return ""


def is_youtube_url(url: str) -> bool:
    host = _domain(url)
    if host in _YOUTUBE_HOSTS:
        return True
    return host.endswith(".youtube.com")


def extract_youtube_video_id(url: str) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:  # noqa: BLE001
        return None
    host = _domain(raw)
    if host == "youtu.be":
        vid = parsed.path.lstrip("/").split("/")[0].strip()
        return vid or None
    if host == "youtube.com" or host.endswith(".youtube.com"):
        if parsed.path == "/watch":
            ids = parse_qs(parsed.query).get("v") or []
            return (ids[0] or "").strip() or None
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else None
        if parsed.path.startswith("/embed/"):
            return parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else None
    return None


def discover_youtube_urls(
    text: str,
    *,
    grounding_sources: list[dict[str, str]] | None,
) -> list[str]:
    """Collect unique YouTube watch URLs from research text and grounding sources."""
    seen_ids: set[str] = set()
    ordered: list[str] = []

    def add(url: str) -> None:
        if not is_youtube_url(url):
            return
        vid = extract_youtube_video_id(url)
        if not vid or vid in seen_ids:
            return
        seen_ids.add(vid)
        ordered.append(f"https://www.youtube.com/watch?v={vid}")

    for match in _URL_IN_TEXT_RE.finditer(text or ""):
        add(match.group(0).rstrip(".,;)"))

    for src in grounding_sources or []:
        add((src.get("url") or "").strip())

    return ordered


def _fetch_captions(video_id: str) -> str:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise RuntimeError(
            "youtube-transcript-api is not installed. Run:\n"
            "  python -m pip install youtube-transcript-api"
        ) from exc

    parts = None
    if hasattr(YouTubeTranscriptApi, "fetch"):
        api = YouTubeTranscriptApi()
        getters = (
            lambda: api.fetch(video_id, languages=["en"]),
            lambda: next(iter(api.list(video_id))).fetch(),
        )
    else:
        getters = (
            lambda: YouTubeTranscriptApi.get_transcript(video_id, languages=["en"]),
            lambda: YouTubeTranscriptApi.get_transcript(video_id),
        )
    for getter in getters:
        try:
            parts = getter()
            break
        except Exception:  # noqa: BLE001
            continue
    if not parts:
        raise RuntimeError("no usable captions found")

    lines = [
        str(
            (item.get("text") if isinstance(item, dict) else getattr(item, "text", ""))
            or ""
        ).strip()
        for item in parts
    ]
    text = "\n".join(line for line in lines if line).strip()
    if not text:
        raise RuntimeError("captions were empty")
    if len(text) > _MAX_CAPTION_CHARS:
        text = text[:_MAX_CAPTION_CHARS] + "\n…[truncated]"
    return text


def _emit_progress(
    progress: ProgressCallback | None,
    message: str,
    *,
    percent: float | None = None,
) -> None:
    if not progress:
        return
    from .cancellation import GenerationCancelled

    payload: dict[str, Any] = {
        "message": message,
        "phase": "generate",
        "title": "Searching",
    }
    if percent is not None:
        payload["percent"] = percent
    try:
        progress(payload)
    except GenerationCancelled:
        raise
    except Exception:  # noqa: BLE001
        logger.debug("progress callback failed", exc_info=True)


def enrich_research_with_youtube_captions(
    research_context: str,
    *,
    grounding_sources: list[dict[str, str]] | None,
    progress: ProgressCallback | None = None,
    cancel_event: Any = None,
) -> tuple[str, dict[str, Any]]:
    """Pull captions for up to MAX_YOUTUBE_VIDEOS cited YouTube URLs."""
    from .cancellation import raise_if_cancelled

    def _cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    raise_if_cancelled(_cancelled)

    candidates = discover_youtube_urls(
        research_context, grounding_sources=grounding_sources
    )
    meta: dict[str, Any] = {
        "youtubeCaptionCount": 0,
        "youtubeUrls": [],
        "youtube_search_captions": False,
    }
    if not candidates:
        return "", meta

    _emit_progress(progress, "Pulling YouTube captions…", percent=34)

    findings: list[str] = []
    processed = 0
    for url in candidates:
        if processed >= MAX_YOUTUBE_VIDEOS:
            break
        raise_if_cancelled(_cancelled)
        vid = extract_youtube_video_id(url)
        if not vid:
            continue
        try:
            captions = _fetch_captions(vid)
        except Exception as exc:  # noqa: BLE001
            from .cancellation import GenerationCancelled

            if isinstance(exc, GenerationCancelled):
                raise
            logger.warning("YouTube captions failed for %s: %s", url, exc)
            continue

        processed += 1
        meta["youtubeUrls"].append(url)
        findings.append(f"- {url}\n  {captions}")

    if not findings:
        return "", meta

    meta["youtubeCaptionCount"] = processed
    meta["youtube_search_captions"] = True
    block = (
        "YOUTUBE CAPTION FINDINGS (from search sources):\n"
        + "\n\n".join(findings)
        + "\n"
    )
    return block, meta
