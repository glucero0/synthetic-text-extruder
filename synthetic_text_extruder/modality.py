"""Model / creation modality helpers (text | image | video | audio)."""

from __future__ import annotations

import re
from typing import Any

Modality = str  # "text" | "image" | "video" | "audio" | "pdf"

_IMAGE_ID_TOKENS: tuple[str, ...] = (
    "imagen",
    "image-generation",
    "flash-image",
    "pro-image",
    "-image-preview",
    "-image-generation",
    "nano-banana",
    "gpt-image",
    "flux",
    "seedream",
    "dall-e",
    "stable-diffusion",
    "sd-turbo",
    "sdxl",
    "dreamshaper",
    "text-to-image",
)

_VIDEO_ID_TOKENS: tuple[str, ...] = (
    "veo",
    "video-generation",
    "-video-preview",
    "-video-generation",
    "text-to-video",
    "zeroscope",
    "cogvideo",
    "modelscope",
    "animatediff",
    "seedance",
    "happyhorse",
    "wan-2",
    "flux-3-video",
)

_AUDIO_ID_TOKENS: tuple[str, ...] = (
    "lyria",
    "text-to-music",
    "music-generation",
)

# Non-generative surfaces still excluded from the studio model list
_SKIP_ID_TOKENS: tuple[str, ...] = (
    "embedding",
    "embed-content",
    "tts",
    "native-audio",
    "aqa",
    "robotics",
    "computer-use",
    "-live-",
    "-live",
    "realtime",
)

_IMAGE_PHRASES: tuple[str, ...] = (
    "image generation",
    "generate images",
    "generates images",
    "image output",
    "text-to-image",
    "text to image",
)

_VIDEO_PHRASES: tuple[str, ...] = (
    "video generation",
    "generate videos",
    "generates videos",
    "video output",
    "text-to-video",
    "text to video",
)

_AUDIO_PHRASES: tuple[str, ...] = (
    "music generation",
    "generate music",
    "generates music",
    "text-to-music",
    "text to music",
)

_SKIP_PHRASES: tuple[str, ...] = (
    "text-to-speech",
    "text to speech",
    "native audio",
    "audio output",
    "speech synthesis",
    "embedding",
)

# Prompt intent: strong signals that the user wants media, not a text document.
_IMAGE_PROMPT_RE = re.compile(
    r"""
    (?:
        \b(?:create|generate|make|draw|paint|render|design|produce)\b
        .{0,48}?
        \b(?:an?\s+)?(?:image|picture|illustration|artwork|drawing|photo|photograph|portrait)\b
      | \b(?:an?\s+)?(?:image|picture|illustration|artwork|drawing|photo|photograph)\s+of\b
      | \btext[\s\-]?to[\s\-]?image\b
      | \b(?:ai[\s\-]?)?(?:image|art)\s+prompt\b
    )
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)

_VIDEO_PROMPT_RE = re.compile(
    r"""
    (?:
        \b(?:create|generate|make|render|produce|shoot|film)\b
        .{0,48}?
        \b(?:an?\s+)?(?:video|clip|animation|footage|movie|cinematic)\b
      | \b(?:turn|convert|transform|morph|change)\b
        .{0,48}?
        \b(?:into|to)\b
        .{0,24}?
        \b(?:an?\s+)?(?:video|clip|animation|footage|movie)\b
      | \b(?:an?\s+)?(?:video|clip|animation|footage)\s+of\b
      | \btext[\s\-]?to[\s\-]?video\b
      | \banimate\b
      | \bveo\b
    )
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)

_AUDIO_PROMPT_RE = re.compile(
    r"""
    (?:
        \b(?:create|generate|make|compose|produce|write|score)\b
        .{0,48}?
        \b(?:an?\s+)?(?:music(?:\s+clip)?|song|soundtrack|jingle|melody|tune|instrumental|chiptune)\b
      | \b(?:an?\s+)?(?:music|song|soundtrack|jingle|melody|chiptune)\s+(?:of|about|for|in)\b
      | \btext[\s\-]?to[\s\-]?music\b
      | \b(?:ai[\s\-]?)?music\s+prompt\b
      | \blyria\b
      | \binstrumental\s+only\b
      | \b(?:background|game)\s+(?:music|soundtrack)\b
    )
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)

_REPORT_PROMPT_RE = re.compile(
    r"""
    \b(?:create|write|make|draft|compose|build|prepare)\b
    .{0,48}?
    \b(?:an?\s+|the\s+)?report\b
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)

_SUMMARIZE_RE = re.compile(
    r"\b(?:summar(?:y|ies|ise|ize|ising|izing)|recap|rundown)\b",
    re.IGNORECASE,
)

_SUMMARIZE_TO_MEDIA_RE = re.compile(
    r"""
    \b(?:into|as|to)\b
    .{0,16}?
    \b(?:an?\s+)?(?:video|clip|animation|image|picture|song|music)\b
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)

_TEXT_PROMPT_RE = re.compile(
    r"""
    (?:
        \b(?:write|draft|compose|summarize|explain|document|create|make)\b
        .{0,40}?
        \b(?:an?\s+|the\s+)?(?:essay|article|manual|guide|document|story|poem|letter|report|overview)\b
      | \b(?:quick\s+)?reference\s+(?:card|sheet)\b
      | \bkeybindings?\b
      | \bwalkthrough\b
      | \bcheat\s*sheet\b
      | \b(?:html|css|javascript|typescript)\b
      | \b(?:web\s+)?(?:app(?:lication)?|website|web\s*page)\b
      | \brecreate\b.{0,48}?\b(?:ui|interface|layout|dialog|window)\b
      | \b(?:source\s+)?code\b.{0,24}?\b(?:for|from|of)\b
    )
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)

# Studio CREATE: OCR an image basis or transcribe a video basis (not img2img).
_TEXT_EXTRACT_RE = re.compile(
    r"""
    (?:
        \b(?:extract|ocr|read|pull|grab|get)\b
        .{0,40}?
        \b(?:the\s+)?(?:text|words|captions?|subtitles?)\b
      | \bocr\b
      | \btranscri(?:be|ption|pt)\b
      | \bspeech[\s\-]?to[\s\-]?text\b
    )
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)

# Studio CREATE: analyze a screenshot/video basis for UI chrome (not img2img).
_LAYOUT_EXTRACT_RE = re.compile(
    r"""
    (?:
        \b(?:extract|find|detect|analyze|map|inspect|pull|grab|get)\b
        .{0,40}?
        \b(?:the\s+)?(?:ui\s+)?layout\b
      | \bextract\b.{0,40}?\b(?:ui(?:\s+chrome)?|coordinates?|regions?)\b
      | \b(?:ui\s+)?layout\s+json\b
      | \bfind\b.{0,32}?\b(?:ui\s+)?chrome\b
    )
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


def normalize_modality(value: Any, default: Modality = "text") -> Modality:
    raw = str(value or "").strip().lower()
    if raw in {"image", "img", "picture", "photo"}:
        return "image"
    if raw in {"video", "vid", "movie", "clip"}:
        return "video"
    if raw in {"audio", "music", "song", "soundtrack", "mp3", "wav"}:
        return "audio"
    if raw in {"text", "document", "doc", "markdown"}:
        return "text"
    if raw in {"pdf", "application/pdf"}:
        return "pdf"
    return default


def classify_model_modality(
    model_id: str,
    *,
    display_name: str | None = None,
    description: str | None = None,
) -> Modality | None:
    """Return text/image/video/audio, or None if the model should not appear in the studio list."""
    mid = (model_id or "").strip().lower().rstrip("/")
    if not mid:
        return None

    for token in _SKIP_ID_TOKENS:
        if token in mid:
            return None

    # Id tokens win over skip phrases so Lyria/Veo/Imagen stay visible
    # even when Google's description mentions "audio output" etc.
    for token in _VIDEO_ID_TOKENS:
        if token in mid:
            return "video"
    for token in _AUDIO_ID_TOKENS:
        if token in mid:
            return "audio"
    for token in _IMAGE_ID_TOKENS:
        if token in mid:
            return "image"
    if mid.endswith("-image") or mid.endswith("/image"):
        return "image"

    meta = f"{display_name or ''} {description or ''}".lower()
    for phrase in _SKIP_PHRASES:
        if phrase in meta:
            return None

    for phrase in _VIDEO_PHRASES:
        if phrase in meta:
            return "video"
    for phrase in _AUDIO_PHRASES:
        if phrase in meta:
            return "audio"
    for phrase in _IMAGE_PHRASES:
        if phrase in meta:
            return "image"

    # Gemini text chat models (and leftover Hub-style ids)
    if "gemini" in mid or "/" in mid or "gpt" in mid or "claude" in mid or "llama" in mid:
        return "text"
    if "instruct" in mid or "chat" in mid:
        return "text"
    return "text"


def modality_label(modality: Modality) -> str:
    return {
        "text": "Text",
        "image": "Image",
        "video": "Video",
        "audio": "Audio",
        "pdf": "PDF",
    }.get(modality, "Text")


def modality_indefinite(modality: Modality) -> str:
    label = modality_label(modality)
    article = "an" if label[:1].lower() in "aeiou" else "a"
    return f"{article} {label}"


def infer_layout_extract_intent(prompt: str) -> bool:
    """True when the Studio prompt asks to extract UI layout from a media basis."""
    text = (prompt or "").strip()
    return bool(text and _LAYOUT_EXTRACT_RE.search(text))


def infer_text_extract_intent(prompt: str) -> bool:
    """True when the Studio prompt asks to OCR or transcribe a media basis."""
    text = (prompt or "").strip()
    if not text or infer_layout_extract_intent(text):
        return False
    return bool(_TEXT_EXTRACT_RE.search(text))


def infer_report_intent(prompt: str) -> bool:
    """True when the Studio prompt asks to write a report (not generate a video)."""
    text = (prompt or "").strip()
    if not text:
        return False
    if _REPORT_PROMPT_RE.search(text):
        return True
    if not _SUMMARIZE_RE.search(text):
        return False
    if _SUMMARIZE_TO_MEDIA_RE.search(text):
        return False
    if (
        _VIDEO_PROMPT_RE.search(text)
        or _IMAGE_PROMPT_RE.search(text)
        or _AUDIO_PROMPT_RE.search(text)
    ):
        return False
    return True


def infer_prompt_modality(prompt: str) -> Modality | None:
    """
    Infer strong user intent from the prompt.

    Returns text/image/video/audio when signals are clear, or None when ambiguous
    (do not block generation).
    """
    text = (prompt or "").strip()
    if not text:
        return None

    # Layout / OCR / transcribe are text analysis jobs, even with media attached.
    if infer_layout_extract_intent(text) or infer_text_extract_intent(text):
        return "text"

    # "Create a report … summary of the video" is a document, not Veo.
    if infer_report_intent(text):
        return "text"

    # Audio before video: "generate a music clip" must not become Veo.
    if _AUDIO_PROMPT_RE.search(text):
        return "audio"
    # Video before image: "create a video of an image morphing…" etc.
    if _VIDEO_PROMPT_RE.search(text):
        return "video"
    if _IMAGE_PROMPT_RE.search(text):
        return "image"
    if _TEXT_PROMPT_RE.search(text):
        return "text"
    return None


def resolve_generation_modality(
    prompt: str,
    *,
    basis_modality: str | None = None,
    layout_basis: bool = False,
) -> Modality | None:
    """
    Choose text/image/video/audio for a Studio CREATE.

    Clear prompt intent (including \"generate a video\" with an image basis →
    image-to-video, or \"generate music\" with an image basis → image-to-music)
    wins. \"Extract the layout\", \"extract the text\", or \"transcribe\" on an
    image/video basis is text analysis, not img2img. An extracted UI layout
    defaults to text (rebuild as HTML/app) unless the prompt asks for
    image/video/music. Otherwise a media basis keeps the same modality.
    """
    prompt_mod = infer_prompt_modality(prompt)
    basis = (basis_modality or "").strip().lower()
    if basis not in {"image", "video"}:
        basis = ""

    if infer_layout_extract_intent(prompt) or infer_text_extract_intent(prompt):
        return "text"
    if prompt_mod in {"image", "video", "audio"}:
        return prompt_mod
    if prompt_mod == "text":
        return "text"
    if layout_basis:
        return "text"
    if basis:
        return basis  # type: ignore[return-value]
    return prompt_mod


def suggested_model_ids_for_modality(modality: Modality) -> list[str]:
    """Curated Gemini model ids matching modality (best-effort suggestions)."""
    try:
        from .gemini_provider import SUGGESTED_GEMINI_MODELS
    except Exception:  # noqa: BLE001
        return []
    wanted = normalize_modality(modality, default="text")
    out: list[str] = []
    for item in SUGGESTED_GEMINI_MODELS:
        mid = str(item.get("repo_id") or "").strip()
        if not mid:
            continue
        mod = normalize_modality(item.get("modality"), default="text")
        if mod == wanted:
            out.append(mid)
    return out


def check_prompt_model_compatibility(
    prompt: str,
    model_id: str,
    *,
    provider: str = "gemini",
    gemini_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Compare prompt intent with Gemini's modality slots.

    Studio routes by prompt intent to the matching configured Gemini model
    (text, image, video, or Lyria audio).
    """
    prompt_mod = infer_prompt_modality(prompt)
    from .gemini_provider import resolve_gemini_model_for_modality

    routed_mod = prompt_mod or "text"
    model = resolve_gemini_model_for_modality(gemini_cfg, routed_mod)
    return {
        "ok": True,
        "promptModality": prompt_mod,
        "modelModality": routed_mod,
        "model": model,
        "routed": True,
    }
