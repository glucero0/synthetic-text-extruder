"""Filename suggestions from the creation's actual content, not the prompt.

Embeddings are vectors, so naming is two steps:

1. Look at the file (image / video / audio bytes, or document text) and
   propose a few short titles that describe what is there.
2. Embed that same file with Gemini Embedding 2 (multimodal) and pick the
   title whose embedding is closest to the media embedding.

The native save dialog still lets the user edit the name. Falls back to a
prompt slug only when the file cannot be read or Gemini is unavailable.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Sequence
from typing import Any

from .creation_utils import title_from_prompt
from .extract_text import MAX_INLINE_BYTES

logger = logging.getLogger("synthetic_text_extruder.embedding_filename")

MEDIA_EMBED_MODEL = "gemini-embedding-2"
MAX_SOURCE_CHARS = 4000
MAX_CANDIDATES = 32
MAX_NAME_LEN = 48
WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?")
_TITLE_LINE_RE = re.compile(
    r"^\s*(?:\d+[\).:-]\s*|[-*•]\s*)?(?P<title>.+?)\s*$"
)

# Function words that never make a useful filename by themselves.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "from",
        "with",
        "without",
        "by",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "into",
        "over",
        "under",
        "about",
        "than",
        "then",
        "so",
        "very",
        "just",
        "also",
        "not",
        "no",
        "yes",
    }
)

# Prompt-style boilerplate that is a poor filename.
_STYLE_NOISE = frozenset(
    {
        "generate",
        "generated",
        "create",
        "created",
        "creating",
        "make",
        "please",
        "image",
        "images",
        "photo",
        "photograph",
        "picture",
        "pictures",
        "video",
        "clip",
        "song",
        "music",
        "track",
        "audio",
        "photorealistic",
        "hyperrealistic",
        "realistic",
        "masterpiece",
        "quality",
        "detailed",
        "highly",
        "ultra",
        "uhd",
        "hdr",
        "4k",
        "8k",
        "16k",
        "resolution",
        "illustration",
        "render",
        "rendering",
        "prompt",
        "style",
    }
)

_EMBED_IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/jpg"})
_EMBED_VIDEO_MIMES = frozenset({"video/mp4", "video/quicktime"})
_EMBED_AUDIO_MIMES = frozenset(
    {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/mp4"}
)

ProposeFn = Callable[..., list[str]]
EmbedMediaFn = Callable[..., list[float]]
EmbedTextsFn = Callable[[Sequence[str]], list[list[float]]]


def slugify_filename(
    text: str,
    *,
    fallback: str = "creation",
    max_len: int = MAX_NAME_LEN,
) -> str:
    """Filesystem-safe basename: letters, digits, hyphens. No path parts."""
    cleaned: list[str] = []
    prev_dash = False
    for ch in str(text or "").strip():
        if ch.isalnum():
            cleaned.append(ch.lower() if ("a" <= ch <= "z" or "A" <= ch <= "Z") else ch)
            prev_dash = False
        elif ch in {" ", "-", "_"}:
            if cleaned and not prev_dash:
                cleaned.append("-")
                prev_dash = True
    slug = "".join(cleaned).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
        cut = slug.rfind("-")
        if cut >= 8:
            slug = slug[:cut]
    if not slug or slug in {".", ".."}:
        slug = fallback
    if slug.upper() in WINDOWS_RESERVED:
        slug = f"{slug}-file"
    if "/" in slug or "\\" in slug:
        slug = fallback
    return slug


def title_is_prompt_dump(title: str, prompt: str) -> bool:
    """True when title is missing, generic, or just the first prompt line."""
    t = str(title or "").strip()
    p = str(prompt or "").strip()
    if not t or t.casefold() in {"untitled", "creation"}:
        return True
    derived = title_from_prompt(p, "")
    if derived and (
        t == derived
        or t.rstrip("…") == derived.rstrip("…")
        or t.rstrip(".") == derived.rstrip(".")
    ):
        return True
    compact_t = re.sub(r"\W+", "", t).casefold()
    compact_p = re.sub(r"\W+", "", p).casefold()
    if compact_t and compact_p and compact_t[:36] == compact_p[:36]:
        return True
    return False


def candidate_phrases(text: str, *, max_candidates: int = MAX_CANDIDATES) -> list[str]:
    """1–3 word phrases from document text, skipping stopwords and style noise."""
    words = [w.casefold() for w in _WORD_RE.findall(str(text or ""))]
    phrases: list[str] = []
    seen: set[str] = set()
    n = len(words)
    for size in (3, 2, 1):
        for i in range(0, n - size + 1):
            gram = words[i : i + size]
            if all(w in _STOPWORDS or w in _STYLE_NOISE for w in gram):
                continue
            if size == 1 and gram[0] in _STOPWORDS:
                continue
            if any(len(w) < 2 for w in gram):
                continue
            phrase = " ".join(gram)
            if phrase in seen or not (2 <= len(phrase) <= 40):
                continue
            seen.add(phrase)
            phrases.append(phrase)
            if len(phrases) >= max_candidates:
                return phrases
    return phrases


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        na += fx * fx
        nb += fy * fy
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


def mmr_select(
    doc_vec: Sequence[float],
    candidate_vecs: Sequence[Sequence[float]],
    candidates: Sequence[str],
    *,
    k: int = 3,
    diversity: float = 0.4,
) -> list[str]:
    """Pick up to k phrases similar to the document and unlike each other."""
    if not candidates or not candidate_vecs:
        return []
    n = min(len(candidates), len(candidate_vecs))
    remaining = list(range(n))
    selected: list[int] = []
    while remaining and len(selected) < k:
        best_i = remaining[0]
        best_score = float("-inf")
        for i in remaining:
            sim_doc = _cosine(doc_vec, candidate_vecs[i])
            sim_sel = 0.0
            if selected:
                sim_sel = max(_cosine(candidate_vecs[i], candidate_vecs[j]) for j in selected)
            score = (1.0 - diversity) * sim_doc - diversity * sim_sel
            if score > best_score:
                best_score = score
                best_i = i
        selected.append(best_i)
        remaining.remove(best_i)
    return [candidates[i] for i in selected]


def name_from_phrases(phrases: Sequence[str], *, max_len: int = MAX_NAME_LEN) -> str:
    """Join ranked phrases, dropping repeated words, then slugify."""
    words: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        for word in str(phrase or "").split():
            key = word.casefold()
            if key in seen or key in _STOPWORDS or key in _STYLE_NOISE:
                continue
            seen.add(key)
            words.append(word)
    return slugify_filename(" ".join(words), max_len=max_len)


def _normalize_embed_mime(mime: str) -> str:
    raw = (mime or "").split(";")[0].strip().lower()
    if raw == "image/jpg":
        return "image/jpeg"
    if raw in {"audio/mp3", "audio/mpeg"}:
        return "audio/mpeg"
    return raw


def _embedding_values(item: Any) -> list[float]:
    values = getattr(item, "values", None)
    if values is None and isinstance(item, dict):
        values = item.get("values")
    if not values:
        raise ValueError("Embedding response missing values")
    return [float(v) for v in values]


def _parse_title_lines(text: str) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    for raw_line in str(text or "").replace("\r\n", "\n").split("\n"):
        match = _TITLE_LINE_RE.match(raw_line)
        if not match:
            continue
        line = match.group("title").strip().strip("\"'`")
        line = re.sub(r"\.(png|jpe?g|webp|gif|mp4|mov|mp3|wav|txt)$", "", line, flags=re.I)
        slug = slugify_filename(line, fallback="")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        titles.append(line)
        if len(titles) >= 8:
            break
    return titles


def _creation_body_text(creation: dict[str, Any] | None) -> str:
    """Document / lyrics body — not the generation prompt."""
    if not creation:
        return ""
    parts: list[str] = []
    overview = str(creation.get("overview") or "").strip()
    sections = creation.get("sections") or []
    skip_overview = False
    if overview and sections:
        body = str((sections[0] or {}).get("content") or "").strip()
        clipped = overview.rstrip("…").rstrip(".").strip()
        if body and clipped and body.startswith(clipped):
            skip_overview = True
    if overview and not skip_overview:
        parts.append(overview)
    for section in sections:
        content = str((section or {}).get("content") or "").strip()
        if content:
            parts.append(content)
    extracted = ""
    meta = creation.get("meta") if isinstance(creation.get("meta"), dict) else {}
    if meta:
        extracted = str(meta.get("extractedText") or "").strip()
    if not extracted:
        extracted = str(creation.get("extractedText") or "").strip()
    if extracted:
        parts.append(extracted)
    return "\n\n".join(parts).strip()[:MAX_SOURCE_CHARS]


def load_creation_content(
    creation: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load the file or document body that should be named (never the prompt)."""
    from .media_store import mime_for_path, resolve_media_path
    from .modality import normalize_modality

    creation = creation or {}
    modality = normalize_modality(
        creation.get("modality") or creation.get("creationType"),
        default="text",
    )
    out: dict[str, Any] = {"modality": modality, "bytes": None, "mime": "", "text": ""}
    if modality == "text":
        out["text"] = _creation_body_text(creation)
        return out

    path = resolve_media_path(creation.get("mediaPath"), config)
    if path is None or not path.is_file():
        out["text"] = _creation_body_text(creation)
        return out

    mime = _normalize_embed_mime(
        str(creation.get("mimeType") or mime_for_path(path) or "")
    )
    try:
        size = path.stat().st_size
    except OSError:
        out["text"] = _creation_body_text(creation)
        return out

    if modality == "video" and (
        size > MAX_INLINE_BYTES or mime not in _EMBED_VIDEO_MIMES
    ):
        try:
            from .video_edit import extract_video_frame_png

            out["bytes"] = extract_video_frame_png(path, at_seconds=0.0)
            out["mime"] = "image/png"
            out["modality"] = "image"
            return out
        except Exception:
            logger.debug("Video frame extract for naming failed", exc_info=True)

    if size > MAX_INLINE_BYTES:
        out["text"] = _creation_body_text(creation)
        return out

    try:
        out["bytes"] = path.read_bytes()
        out["mime"] = mime
    except OSError:
        logger.debug("Could not read media for naming", exc_info=True)
        out["text"] = _creation_body_text(creation)
    return out


def _title_prompt(modality: str) -> str:
    if modality == "audio":
        target = "this audio"
        what = "what it sounds like (mood, genre, instruments) — not the prompt"
    elif modality == "video":
        target = "this video"
        what = "what is actually on screen"
    elif modality == "image":
        target = "this image"
        what = "what is actually shown"
    else:
        target = "this document"
        what = "what the document is about"
    return (
        f"Look at {target}. Reply with 5 alternative titles, one per line. "
        f"Each title is 2 to 6 words describing {what}. "
        "No quotes, no file extension, no camera or style jargon, no numbering required."
    )


def propose_titles_from_content(
    *,
    data: bytes | None,
    mime_type: str,
    text: str,
    modality: str,
    api_key: str,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """Ask Gemini to describe the file/document. Does not send the user prompt."""
    key = (api_key or "").strip()
    if not key:
        raise ValueError("Gemini API key is not set")
    from google import genai
    from google.genai import types

    from .gemini_provider import DEFAULT_GEMINI_TEXT_MODEL, normalize_gemini_model

    gemini_cfg = (config or {}).get("gemini") or {}
    model_name = normalize_gemini_model(
        gemini_cfg.get("text_model") or DEFAULT_GEMINI_TEXT_MODEL
    )
    client = genai.Client(api_key=key)
    prompt = _title_prompt(modality)
    contents: list[Any] = []
    if data and mime_type:
        contents.append(types.Part.from_bytes(data=data, mime_type=mime_type))
    if text.strip():
        contents.append(text.strip()[:MAX_SOURCE_CHARS])
    contents.append(prompt)
    if len(contents) == 1:
        raise ValueError("No media or document text to describe")
    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=types.GenerateContentConfig(temperature=0.2),
    )
    raw = getattr(response, "text", None) or ""
    if not raw:
        parts: list[str] = []
        for cand in getattr(response, "candidates", None) or []:
            content = getattr(cand, "content", None)
            for part in getattr(content, "parts", None) or []:
                t = getattr(part, "text", None)
                if t:
                    parts.append(str(t))
        raw = "\n".join(parts)
    titles = _parse_title_lines(raw)
    if not titles:
        raise ValueError("Gemini returned no usable titles")
    return titles


def embed_media_bytes(
    data: bytes,
    mime_type: str,
    *,
    api_key: str,
    model: str = MEDIA_EMBED_MODEL,
) -> list[float]:
    """Embed image, video, or audio bytes with gemini-embedding-2."""
    key = (api_key or "").strip()
    if not key:
        raise ValueError("Gemini API key is not set")
    mime = _normalize_embed_mime(mime_type)
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)
    result = client.models.embed_content(
        model=model,
        contents=[
            types.Content(
                parts=[types.Part.from_bytes(data=data, mime_type=mime)],
            )
        ],
    )
    embeddings = getattr(result, "embeddings", None) or []
    if not embeddings:
        raise ValueError("Media embedding response was empty")
    return _embedding_values(embeddings[0])


def embed_texts(
    texts: Sequence[str],
    *,
    api_key: str,
    model: str = MEDIA_EMBED_MODEL,
) -> list[list[float]]:
    """Embed each string separately (gemini-embedding-2 Content wrapping)."""
    key = (api_key or "").strip()
    if not key:
        raise ValueError("Gemini API key is not set")
    cleaned = [str(t or "").strip() or "." for t in texts]
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)
    result = client.models.embed_content(
        model=model,
        contents=[
            types.Content(
                parts=[
                    types.Part.from_text(
                        text=f"task: sentence similarity | query: {item}"
                    )
                ]
            )
            for item in cleaned
        ],
    )
    embeddings = getattr(result, "embeddings", None) or []
    vectors = [_embedding_values(item) for item in embeddings]
    if len(vectors) != len(cleaned):
        raise ValueError("Embedding count did not match inputs")
    return vectors


def _can_embed_bytes(mime: str) -> bool:
    mime = _normalize_embed_mime(mime)
    return mime in _EMBED_IMAGE_MIMES or mime in _EMBED_VIDEO_MIMES or mime in _EMBED_AUDIO_MIMES


def _pick_closest_title(
    media_vec: Sequence[float],
    titles: Sequence[str],
    title_vecs: Sequence[Sequence[float]],
) -> str:
    best = titles[0]
    best_sim = float("-inf")
    n = min(len(titles), len(title_vecs))
    for i in range(n):
        sim = _cosine(media_vec, title_vecs[i])
        if sim > best_sim:
            best_sim = sim
            best = titles[i]
    return best


def _name_from_text_body(
    body: str,
    *,
    api_key: str | None,
    embed_fn: EmbedTextsFn | None,
    fallback_name: str,
) -> str:
    """Keyphrase name from the document body (not the prompt)."""
    source = (body or "").strip()[:MAX_SOURCE_CHARS]
    if not source:
        return fallback_name
    candidates = candidate_phrases(source)
    if not candidates:
        return slugify_filename(source.split("\n")[0], fallback=fallback_name) or fallback_name
    if embed_fn is None and not (api_key or "").strip():
        return name_from_phrases(candidates[:3]) or fallback_name
    embed = embed_fn or (lambda texts: embed_texts(texts, api_key=api_key or ""))
    try:
        vectors = embed([source] + candidates)
        if len(vectors) != 1 + len(candidates):
            return fallback_name
        picked = mmr_select(vectors[0], vectors[1:], candidates, k=3)
        name = name_from_phrases(picked)
        if name and name != "creation":
            return name
    except Exception:
        logger.exception("Document embedding filename failed")
    return name_from_phrases(candidates[:3]) or fallback_name


def suggest_media_filename(
    prompt: str,
    *,
    title: str | None = None,
    extra_text: str | None = None,
    api_key: str | None = None,
    embed_fn: EmbedTextsFn | None = None,
    fallback: str = "creation",
) -> str:
    """Back-compat helper: name from provided text. Prefer suggest_filename_for_creation."""
    title = str(title or "").strip()
    if title and not title_is_prompt_dump(title, prompt):
        return slugify_filename(title, fallback=fallback)
    source = str(extra_text or "").strip() or str(prompt or "").strip()
    fallback_name = slugify_filename(
        title or title_from_prompt(source, fallback),
        fallback=fallback,
    )
    return _name_from_text_body(
        source,
        api_key=api_key,
        embed_fn=embed_fn,
        fallback_name=fallback_name,
    )


def suggest_filename_for_creation(
    creation: dict[str, Any] | None,
    *,
    api_key: str | None = None,
    config: dict[str, Any] | None = None,
    embed_fn: EmbedTextsFn | None = None,
    propose_fn: ProposeFn | None = None,
    embed_media_fn: EmbedMediaFn | None = None,
    embed_texts_fn: EmbedTextsFn | None = None,
    content: dict[str, Any] | None = None,
    fallback: str = "creation",
) -> str:
    """Suggest a basename by looking at the creation's file or document text."""
    creation = creation or {}
    meta = creation.get("meta") if isinstance(creation.get("meta"), dict) else {}
    cached = str((meta or {}).get("embeddingFilename") or "").strip()
    if cached:
        return slugify_filename(cached, fallback=fallback)

    prompt = str(creation.get("prompt") or "")
    title = str(creation.get("title") or creation.get("game") or "").strip()
    if title and not title_is_prompt_dump(title, prompt):
        return slugify_filename(title, fallback=fallback)

    fallback_name = slugify_filename(
        title or title_from_prompt(prompt, fallback),
        fallback=fallback,
    )
    payload = content if content is not None else load_creation_content(creation, config)
    data = payload.get("bytes") if isinstance(payload.get("bytes"), (bytes, bytearray)) else None
    mime = str(payload.get("mime") or "")
    body = str(payload.get("text") or "")
    modality = str(payload.get("modality") or "text")

    if (not data) and body and modality == "text":
        return _name_from_text_body(
            body,
            api_key=api_key,
            embed_fn=embed_fn or embed_texts_fn,
            fallback_name=fallback_name,
        )

    if not data and not body:
        return fallback_name
    if not (api_key or "").strip() and propose_fn is None:
        if body:
            return _name_from_text_body(
                body,
                api_key=None,
                embed_fn=embed_fn or embed_texts_fn,
                fallback_name=fallback_name,
            )
        return fallback_name

    propose = propose_fn or (
        lambda **kwargs: propose_titles_from_content(api_key=api_key or "", config=config, **kwargs)
    )
    try:
        titles = propose(
            data=bytes(data) if data else None,
            mime_type=mime,
            text=body,
            modality=modality,
        )
    except Exception:
        logger.exception("Title proposal from media failed")
        titles = []
    if not titles:
        if body:
            return _name_from_text_body(
                body,
                api_key=api_key,
                embed_fn=embed_fn or embed_texts_fn,
                fallback_name=fallback_name,
            )
        return fallback_name

    embed_titles = embed_texts_fn or embed_fn
    can_rank = bool(data) and _can_embed_bytes(mime)
    if can_rank and (embed_media_fn is not None or (api_key or "").strip()):
        try:
            media_embed = embed_media_fn or (
                lambda **kwargs: embed_media_bytes(api_key=api_key or "", **kwargs)
            )
            media_vec = media_embed(data=bytes(data or b""), mime_type=mime)
            title_embed = embed_titles or (
                lambda texts: embed_texts(texts, api_key=api_key or "")
            )
            title_vecs = title_embed(titles)
            picked = _pick_closest_title(media_vec, titles, title_vecs)
            name = slugify_filename(picked, fallback=fallback_name)
            if name:
                return name
        except Exception:
            logger.exception("Media embedding rank failed; using first media title")

    return slugify_filename(titles[0], fallback=fallback_name)
