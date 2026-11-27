"""Google Gemini API document generation (optional two-pass search + verify)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from .creation_utils import (
    build_media_creation,
    build_text_creation_from_plain,
    extract_json_object,
    finalize_creation,
    is_ambiguous,
    is_game_not_found,
    is_generic_studio_request,
    normalize_source_snippets,
    title_from_prompt,
)
from .media_store import write_media_bytes
from .modality import classify_model_modality
from .prompts import (
    build_general_text_prompt,
    build_prompt,
    build_search_extract_prompt,
    build_tools_research_prompt,
    build_verification_prompt,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[Any], None]

# Model slots are discovered dynamically from Google's live catalog (never hardcoded).
DEFAULT_GEMINI_TEXT_MODEL = ""
DEFAULT_GEMINI_IMAGE_MODEL = ""
DEFAULT_GEMINI_VIDEO_MODEL = ""
DEFAULT_GEMINI_AUDIO_MODEL = ""

RETIRED_SENTINEL = "__retired__"

# Known shut-down / blocked ids hidden from live pickers and cleared from saved config.
# Learned aliases are merged from config.yaml → gemini.retired_model_aliases at runtime.
GEMINI_RETIRED_MODEL_ALIASES: dict[str, str] = {
    "gemini-2.0-flash": RETIRED_SENTINEL,
    "gemini-2.0-flash-001": RETIRED_SENTINEL,
    "gemini-2.0-flash-lite": RETIRED_SENTINEL,
    "gemini-2.0-flash-lite-001": RETIRED_SENTINEL,
    "gemini-2.0-flash-lite-preview": RETIRED_SENTINEL,
    "gemini-2.0-flash-lite-preview-02-05": RETIRED_SENTINEL,
    "gemini-2.5-flash-lite": RETIRED_SENTINEL,
    "gemini-2.5-flash-lite-preview": RETIRED_SENTINEL,
    "gemini-2.5-flash-lite-preview-06-17": RETIRED_SENTINEL,
    "gemini-2.5-flash-lite-preview-09-2025": RETIRED_SENTINEL,
    "gemini-2.0-flash-preview-image-generation": RETIRED_SENTINEL,
    "veo-2.0-generate-001": RETIRED_SENTINEL,
}

_MODEL_IN_ERR_RE = re.compile(
    r"(?i)(?:models/)?((?:gemini|veo|imagen|lyria)[-a-z0-9.]+)"
)


def learned_retired_aliases(gemini_cfg: dict[str, Any] | None) -> dict[str, str]:
    """User/runtime-learned aliases from config.yaml."""
    raw = (gemini_cfg or {}).get("retired_model_aliases") or {}
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for src, dst in raw.items():
        s = _gemini_model_id(str(src or ""))
        d = _gemini_model_id(str(dst or ""))
        if s and d and s.lower() != d.lower():
            out[s] = d
    return out


def merged_retired_aliases(gemini_cfg: dict[str, Any] | None = None) -> dict[str, str]:
    """Built-in aliases plus learned ones (learned wins on conflict)."""
    return {**GEMINI_RETIRED_MODEL_ALIASES, **learned_retired_aliases(gemini_cfg)}


def is_retired_gemini_error(exc: BaseException | str) -> bool:
    """True when Google rejects a model as missing / retired / blocked for new users."""
    text = str(exc or "")
    if not text:
        return False
    low = text.lower()
    modelish = bool(_MODEL_IN_ERR_RE.search(text))
    if "no longer available" in low or "not available to new users" in low:
        return True
    if modelish and (
        "not_found" in low
        or ("404" in low and ("model" in low or "models/" in low))
        or "is not found" in low
        or "was not found" in low
        or "is not supported" in low
    ):
        return True
    return False


def extract_model_from_gemini_error(exc: BaseException | str) -> str | None:
    text = str(exc or "")
    matches = _MODEL_IN_ERR_RE.findall(text)
    if not matches:
        return None
    # Prefer the last explicit model token (message usually names the bad id)
    return _gemini_model_id(matches[-1])


def suggest_replacement_for_retired(
    model_id: str,
    *,
    config: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return ``(live_replacement_or_empty, modality)`` using Google's live catalog when possible."""
    mid = _gemini_model_id(model_id)
    modality = classify_model_modality(mid.lower()) or "text"
    cfg = dict(config or {})
    g = dict(cfg.get("gemini") or {})
    if resolve_api_key(g):
        try:
            from .recommend_models import recommend_models_for_config

            temp_learned = learned_retired_aliases(g)
            temp_learned[mid] = RETIRED_SENTINEL
            g_temp = {**g, "retired_model_aliases": temp_learned}
            rec = recommend_models_for_config({**cfg, "gemini": g_temp}, "balanced")
            cand = _gemini_model_id((rec.get("picks") or {}).get(modality) or "")
            if cand and cand.lower() != mid.lower():
                return cand, modality
        except Exception:  # noqa: BLE001
            logger.debug("Live replacement lookup failed for %s", mid, exc_info=True)
    return "", modality


def learn_retired_gemini_model(
    config: dict[str, Any],
    model_id: str,
    *,
    replacement: str | None = None,
) -> dict[str, Any]:
    """
    Persist a retired model alias, switch or clear the active Settings slot,
    and return UI-facing details.
    """
    from .config import save_config

    mid = _gemini_model_id(model_id)
    if not mid:
        raise ValueError("Missing retired model id")
    repl, modality = suggest_replacement_for_retired(mid, config=config)
    if replacement is not None:
        repl = _gemini_model_id(replacement)

    # Never alias a retired model to itself
    if repl and repl.lower() == mid.lower():
        repl = ""

    gemini = dict(config.get("gemini") or {})
    learned = learned_retired_aliases(gemini)
    learned[mid] = repl or RETIRED_SENTINEL
    gemini["retired_model_aliases"] = learned

    slot = {
        "text": "text_model",
        "image": "image_model",
        "video": "video_model",
        "audio": "audio_model",
    }[modality]
    current = _gemini_model_id(gemini.get(slot) or "")
    switched = False
    if current.lower() == mid.lower():
        gemini[slot] = repl
        switched = True

    new_config = save_config({"gemini": gemini}, existing=config)
    logger.info(
        "Learned retired Gemini model %s → %s (slot %s switched=%s)",
        mid,
        repl or "(cleared)",
        slot,
        switched,
    )
    msg = (
        f'Gemini model "{mid}" is retired or unavailable for this API key. '
        f"It was removed from the picker"
        + (
            f' and {modality} was switched to "{repl}"'
            if switched and repl
            else (f" and {modality} was cleared" if switched else "")
        )
        + ". Open Settings → Models to confirm or choose another model."
    )
    return {
        "retired": mid,
        "replacement": repl,
        "modality": modality,
        "switched": switched,
        "message": msg,
        "config": new_config,
    }


# Empty: the app never renders a static list of models; it always fetches Google's live catalog.
SUGGESTED_GEMINI_MODELS: list[dict[str, str]] = []


def _gemini_model_id(name: str | None) -> str:
    raw = (name or "").strip()
    if raw.startswith("models/"):
        raw = raw[len("models/") :]
    return raw


def _gemini_model_notes(model_id: str, description: str | None = None) -> str:
    mid = model_id.lower()
    if "flash-lite" in mid or "flashlite" in mid:
        return "Fastest / cheapest Flash variant"
    if "lyria" in mid:
        if "clip" in mid:
            return "30-second music clips"
        if "3.5" in mid or "pro" in mid:
            return "Full-length songs (Lyria)"
        return "Music generation (Lyria)"
    if "flash" in mid and "pro" not in mid:
        if "2.5" in mid:
            return "Best balance — recommended with Search + two-pass"
        return "Fast Flash model"
    if "pro" in mid:
        return "Higher quality — good for accuracy"
    desc = (description or "").strip()
    if desc and len(desc) < 80:
        return desc
    return "Available for your API key"


def _gemini_model_label(model_id: str, display_name: str | None = None) -> str:
    if display_name and display_name.strip():
        return display_name.strip()
    # gemini-2.5-flash → Gemini 2.5 Flash
    parts = model_id.replace("_", "-").split("-")
    titled = " ".join(p.upper() if p in {"tts", "it"} else p.capitalize() for p in parts)
    return titled.replace("Gemini", "Gemini", 1)


# Tokens matched against the model id only — non-studio surfaces to skip.
_GEMINI_ID_SKIP_TOKENS: tuple[str, ...] = (
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

# Phrases matched against display name + description (not bare "video"/"image").
_GEMINI_SKIP_PHRASES: tuple[str, ...] = (
    "text-to-speech",
    "text to speech",
    "native audio",
    "audio output",
    "speech synthesis",
)


def _is_studio_gemini_model(
    model_id: str,
    *,
    display_name: str | None = None,
    description: str | None = None,
    supported_actions: list[str] | None = None,
    retired_aliases: dict[str, str] | None = None,
) -> bool:
    """True for Gemini text / image / video / audio models usable in the studio."""
    mid = _gemini_model_id(model_id).lower().rstrip("/")
    if not mid:
        return False
    # Drop shut-down / learned-retired ids even if Google still lists them
    aliases = retired_aliases if retired_aliases is not None else GEMINI_RETIRED_MODEL_ALIASES
    if mid in {k.lower() for k in aliases}:
        return False
    # Allow imagen / veo / lyria even without "gemini" in the id
    modality = classify_model_modality(
        mid, display_name=display_name, description=description
    )
    if modality is None:
        return False
    if "gemini" not in mid and modality == "text":
        return False

    for token in _GEMINI_ID_SKIP_TOKENS:
        if token in mid:
            return False

    if modality == "text":
        meta = f"{display_name or ''} {description or ''}".lower()
        for phrase in _GEMINI_SKIP_PHRASES:
            if phrase in meta:
                return False

    actions = [str(a).lower() for a in (supported_actions or [])]
    if actions and modality == "text":
        joined = "".join(actions).replace("_", "")
        # Some listings omit actions; only enforce when present
        if "generatecontent" not in joined and "predict" not in joined:
            # video/image may use other action names — already classified
            if modality == "text":
                return False

    return True


def _is_text_generation_gemini_model(
    model_id: str,
    *,
    display_name: str | None = None,
    description: str | None = None,
    supported_actions: list[str] | None = None,
) -> bool:
    """True only for text-modality Gemini models (tests / callers)."""
    if not _is_studio_gemini_model(
        model_id,
        display_name=display_name,
        description=description,
        supported_actions=supported_actions,
    ):
        return False
    return (
        classify_model_modality(
            model_id, display_name=display_name, description=description
        )
        == "text"
    )


def list_available_gemini_models(
    api_key: str,
    *,
    retired_aliases: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Query Google for text/image/video/audio models available to this API key."""
    key = (api_key or "").strip()
    if not key:
        raise RuntimeError("Gemini API key required to list available models.")

    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed. Run:\n  python -m pip install google-genai"
        ) from exc

    aliases = retired_aliases if retired_aliases is not None else GEMINI_RETIRED_MODEL_ALIASES
    client = genai.Client(api_key=key)
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    for model in client.models.list():
        model_id = _gemini_model_id(getattr(model, "name", None))
        if not model_id or model_id in seen:
            continue
        display = getattr(model, "display_name", None)
        description = getattr(model, "description", None)
        actions = list(getattr(model, "supported_actions", None) or [])
        if not _is_studio_gemini_model(
            model_id,
            display_name=display,
            description=description,
            supported_actions=actions,
            retired_aliases=aliases,
        ):
            continue
        modality = classify_model_modality(
            model_id, display_name=display, description=description
        ) or "text"
        seen.add(model_id)
        out.append(
            {
                "repo_id": model_id,
                "label": _gemini_model_label(model_id, display),
                "notes": _gemini_model_notes(model_id, description),
                "modality": modality,
            }
        )

    def sort_key(item: dict[str, str]) -> tuple:
        mid = item["repo_id"].lower()
        modality = item.get("modality") or "text"
        mod_tier = {"text": 0, "image": 1, "video": 2, "audio": 3}.get(modality, 9)
        tier = 50
        if "2.5-flash" in mid and "lite" not in mid and "image" not in mid:
            tier = 0
        elif "2.5-pro" in mid and "image" not in mid:
            tier = 1
        elif "flash-latest" in mid or mid.endswith("flash"):
            tier = 2
        elif "pro" in mid:
            tier = 3
        elif "imagen" in mid or "flash-image" in mid or "image" in mid:
            tier = 10
        elif "veo" in mid:
            tier = 20
        elif "lyria" in mid:
            tier = 30
        elif "exp" in mid or "preview" in mid:
            tier = 80
        return (mod_tier, tier, mid)

    out.sort(key=sort_key)
    if not out:
        raise RuntimeError(
            "No Gemini studio models were returned for this API key."
        )
    return out


def normalize_gemini_model(
    model_name: str | None,
    *,
    retired_aliases: dict[str, str] | None = None,
) -> str:
    """Strip models/ prefix and remap/clear shut-down Gemini ids."""
    name = _gemini_model_id(model_name)
    if not name:
        return ""
    aliases = retired_aliases if retired_aliases is not None else GEMINI_RETIRED_MODEL_ALIASES
    remapped = aliases.get(name) or aliases.get(name.lower())
    if remapped:
        if remapped == RETIRED_SENTINEL:
            logger.info("Clearing retired Gemini model %s", name)
            return ""
        logger.info("Remapping retired Gemini model %s → %s", name, remapped)
        return remapped
    return name


def resolve_gemini_model_for_modality(
    gemini_cfg: dict[str, Any] | None, modality: str
) -> str:
    """Pick the configured model id for text / image / video / audio (empty if unset)."""
    cfg = gemini_cfg or {}
    aliases = merged_retired_aliases(cfg)
    mod = (modality or "text").lower().strip()
    if mod == "image":
        raw = (cfg.get("image_model") or "").strip()
    elif mod == "video":
        raw = (cfg.get("video_model") or "").strip()
    elif mod == "audio":
        raw = (cfg.get("audio_model") or "").strip()
    else:
        raw = (cfg.get("text_model") or "").strip()
    return normalize_gemini_model(raw, retired_aliases=aliases)


def ensure_gemini_model_for_modality(
    gemini_cfg: dict[str, Any] | None, modality: str
) -> str:
    """Return configured model for ``modality``, or dynamically pick one from Google's live catalog."""
    cfg = dict(gemini_cfg or {})
    mod = (modality or "text").lower().strip()
    chosen = resolve_gemini_model_for_modality(cfg, mod)
    if chosen and (mod == "text" or (classify_model_modality(chosen) or "text") == mod):
        return chosen
    if resolve_api_key(cfg):
        try:
            from .recommend_models import recommend_models_for_config

            rec = recommend_models_for_config({"gemini": cfg}, "balanced")
            live_pick = _gemini_model_id((rec.get("picks") or {}).get(mod) or "")
            if live_pick:
                return live_pick
        except Exception:  # noqa: BLE001
            logger.debug("On-demand live model lookup failed for %s", mod, exc_info=True)
    raise RuntimeError(
        f"No Gemini {mod} model is selected. Open Settings → Models to choose your models."
    )


def resolve_api_key(gemini_cfg: dict[str, Any] | None = None) -> str | None:
    gemini_cfg = gemini_cfg or {}
    key = (gemini_cfg.get("api_key") or "").strip()
    return key or None


def _extract_grounding_sources(response: Any) -> list[dict[str, str]]:
    """Best-effort extraction of web citations from Gemini grounding metadata."""
    sources: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(title: str | None, url: str | None) -> None:
        if not url:
            return
        key = url.strip()
        if not key or key in seen:
            return
        seen.add(key)
        sources.append({"title": (title or url).strip(), "url": key})

    try:
        cands = getattr(response, "candidates", None) or []
        if not cands:
            return sources
        meta = getattr(cands[0], "grounding_metadata", None)
        if not meta:
            return sources

        for chunk in getattr(meta, "grounding_chunks", None) or []:
            web = getattr(chunk, "web", None)
            if web and getattr(web, "uri", None):
                add(getattr(web, "title", None), web.uri)

        # Some responses only populate the search entry-point HTML
        entry = getattr(meta, "search_entry_point", None)
        html = getattr(entry, "rendered_content", None) if entry else None
        if isinstance(html, str) and html:
            for href, label in re.findall(
                r'href="([^"]+)"[^>]*>([^<]*)</a>', html, flags=re.IGNORECASE
            ):
                add(label or href, href)

        # Last resort: expose the queries that were searched
        if not sources:
            from urllib.parse import quote_plus

            for query in getattr(meta, "web_search_queries", None) or []:
                q = str(query).strip()
                if q:
                    add(f"Search: {q}", f"https://www.google.com/search?q={quote_plus(q)}")
    except Exception:  # noqa: BLE001
        logger.debug("Could not parse grounding metadata", exc_info=True)

    return sources


def _record_search_enrichment_meta(
    model_info: dict[str, Any],
    meta: dict[str, Any],
) -> None:
    if meta.get("ocrImageCount"):
        model_info["ocr_search_images"] = True
        model_info["ocrImageCount"] = meta["ocrImageCount"]
        model_info["ocrImageUrls"] = list(meta.get("ocrImageUrls") or [])
    if meta.get("youtubeCaptionCount"):
        model_info["youtube_search_captions"] = True
        model_info["youtubeCaptionCount"] = meta["youtubeCaptionCount"]
        model_info["youtubeUrls"] = list(meta.get("youtubeUrls") or [])


def _build_enrichment_refinement_prompt(
    user_prompt: str,
    draft: str,
    enrichment_block: str,
) -> str:
    return (
        "You are refining a search-grounded answer with additional extracted material.\n"
        "Incorporate the draft and the extracted material faithfully. "
        "Do not invent facts, URLs, or captions that are not supported below.\n\n"
        f"USER REQUEST:\n{user_prompt.strip()}\n\n"
        f"SEARCH-GROUNDED DRAFT:\n{draft.strip()}\n\n"
        f"ADDITIONAL EXTRACTED MATERIAL:\n{enrichment_block.strip()}\n"
    )


def _two_pass_enabled(gemini_cfg: dict[str, Any], *, use_search: bool) -> bool:
    """Two-pass verify defaults on whenever Google Search grounding is enabled."""
    if not use_search:
        return False
    flag = gemini_cfg.get("two_pass_verify")
    if flag is None:
        return True
    return bool(flag)


def generate_with_gemini(
    game: str,
    platform: str,
    creation_type: str,
    *,
    gemini_cfg: dict[str, Any],
    system_extra: str = "",
    creation_description: str = "",
    progress: ProgressCallback | None = None,
    exact_title: bool = False,
    basis_media: dict[str, Any] | None = None,
    forced_modality: str | None = None,
    cancel_event: Any = None,
    tool_aliases: list[str] | None = None,
    search_query: str | None = None,
) -> dict[str, Any]:
    """Call Gemini; prompt intent (or forced modality / media basis) selects the slot."""
    from .modality import infer_prompt_modality

    cfg = dict(gemini_cfg or {})
    prompt_text = (creation_description or "").strip() or (game or "").strip()
    modality = (forced_modality or "").strip().lower() or infer_prompt_modality(
        prompt_text
    ) or "text"
    if basis_media and modality not in {"image", "video", "audio"}:
        if basis_media.get("extracted_layout"):
            modality = "text"
        else:
            modality = str(basis_media.get("modality") or "image")
    model_name = resolve_gemini_model_for_modality(cfg, modality)

    if modality == "image":
        from .gemini_media import generate_image_with_gemini

        return generate_image_with_gemini(
            prompt_text,
            gemini_cfg=cfg,
            progress=progress,
            basis_media=basis_media,
            cancel_event=cancel_event,
        )
    if modality == "video":
        from .gemini_media import generate_video_with_gemini

        return generate_video_with_gemini(
            prompt_text,
            gemini_cfg=cfg,
            progress=progress,
            basis_media=basis_media,
            cancel_event=cancel_event,
        )
    if modality == "audio":
        from .gemini_audio import generate_audio_with_gemini

        return generate_audio_with_gemini(
            prompt_text,
            gemini_cfg=cfg,
            progress=progress,
            basis_media=basis_media,
            cancel_event=cancel_event,
        )

    return _generate_text_with_gemini(
        game,
        platform,
        creation_type,
        gemini_cfg=cfg,
        system_extra=system_extra,
        creation_description=creation_description,
        progress=progress,
        exact_title=exact_title,
        prompt_text=prompt_text,
        model_name=model_name,
        cancel_event=cancel_event,
        tool_aliases=tool_aliases,
        search_query=search_query,
        basis_media=basis_media,
    )


def _generate_text_with_gemini(
    game: str,
    platform: str,
    creation_type: str,
    *,
    gemini_cfg: dict[str, Any],
    system_extra: str = "",
    creation_description: str = "",
    progress: ProgressCallback | None = None,
    exact_title: bool = False,
    prompt_text: str = "",
    model_name: str = DEFAULT_GEMINI_TEXT_MODEL,
    cancel_event: Any = None,
    tool_aliases: list[str] | None = None,
    search_query: str | None = None,
    basis_media: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Text generation path (freeform Prompt or classic structured document)."""

    def emit(message: str, percent: float | None = None, **extra: Any) -> None:
        if not progress:
            return
        from .cancellation import GenerationCancelled

        payload: dict[str, Any] = {
            "message": message,
            "phase": "generate",
            "title": extra.pop("title", None) or "Generating text",
        }
        if percent is not None:
            payload["percent"] = percent
        payload.update(extra)
        try:
            progress(payload)
        except GenerationCancelled:
            raise
        except Exception:  # noqa: BLE001
            pass

    api_key = resolve_api_key(gemini_cfg)
    if not api_key:
        raise RuntimeError(
            "Gemini API key missing. Paste your key in Settings → AI Model (Gemini)."
        )
    model_name = normalize_gemini_model(model_name) or ensure_gemini_model_for_modality(
        gemini_cfg, "text"
    )

    from .gemini_tools import normalize_tool_aliases

    selected_tools = normalize_tool_aliases(tool_aliases)
    use_tools = bool(selected_tools)

    use_search = bool(gemini_cfg.get("google_search", True))
    temperature = float(
        gemini_cfg.get("temperature") if gemini_cfg.get("temperature") is not None else 0.0
    )
    generic = is_generic_studio_request(game, platform, creation_type)
    use_search = bool(gemini_cfg.get("google_search", True))
    two_pass = _two_pass_enabled(gemini_cfg, use_search=bool(use_search)) and not generic

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed. Run:\n  python -m pip install google-genai"
        ) from exc

    emit(f"Contacting Gemini ({model_name})…", percent=10)
    client = genai.Client(api_key=api_key)

    grounding_sources: list[dict[str, str]] = []
    search_used = False
    enrich_meta: dict[str, Any] = {}
    search_enrichment_appendix = ""

    def _text_user_contents(prompt: str, *, attach_basis: bool) -> Any:
        raw = (basis_media or {}).get("bytes") if basis_media else None
        mime = str((basis_media or {}).get("mime_type") or "image/png").lower()
        if (
            not attach_basis
            or not basis_media
            or not basis_media.get("extracted_layout")
            or not raw
            or not mime.startswith("image/")
        ):
            return prompt
        return [
            types.Part.from_bytes(data=bytes(raw), mime_type=mime),
            types.Part.from_text(text=prompt),
        ]

    def _call(
        prompt: str,
        *,
        with_search: bool,
        call_temperature: float,
        json_mime: bool,
        with_url_context: bool = False,
        attach_basis: bool = True,
    ) -> str:
        nonlocal grounding_sources
        config_kwargs: dict[str, Any] = {
            "temperature": call_temperature,
        }
        tools: list[Any] = []
        if with_search:
            tools.append(types.Tool(google_search=types.GoogleSearch()))
        if with_url_context:
            # Lets the model open promising pages and extract full tables (when fetch works).
            tools.append(types.Tool(url_context=types.UrlContext()))
        if tools:
            config_kwargs["tools"] = tools
        elif json_mime:
            config_kwargs["response_mime_type"] = "application/json"

        from .cancellation import run_cancellable

        response = run_cancellable(
            lambda: client.models.generate_content(
                model=model_name,
                contents=_text_user_contents(prompt, attach_basis=attach_basis),
                config=types.GenerateContentConfig(**config_kwargs),
            ),
            cancel_event,
        )
        if with_search:
            grounding_sources = _extract_grounding_sources(response)
        return (response.text or "").strip()

    def _call_with_tools(
        prompt: str,
        *,
        call_temperature: float,
        with_search: bool,
    ) -> str:
        nonlocal grounding_sources, search_used
        from .cancellation import run_cancellable
        from .gemini_tools import (
            MAX_TOOL_ITERATIONS,
            execute_tool,
            extract_function_calls,
            response_text,
            tools_config_for,
        )

        tools = tools_config_for(selected_tools, with_search=with_search)
        if not tools:
            raise RuntimeError("No valid Gemini tools were selected.")

        config_kwargs: dict[str, Any] = {
            "temperature": call_temperature,
            "tools": tools,
        }
        if with_search:
            # Required to combine Google Search (server-side) with function calling.
            config_kwargs["tool_config"] = types.ToolConfig(
                include_server_side_tool_invocations=True,
            )

        config = types.GenerateContentConfig(**config_kwargs)
        user_parts = _text_user_contents(prompt, attach_basis=True)
        if isinstance(user_parts, str):
            parts = [types.Part.from_text(text=user_parts)]
        else:
            parts = user_parts
        contents: list[Any] = [
            types.Content(
                role="user",
                parts=parts,
            )
        ]

        for step in range(MAX_TOOL_ITERATIONS):
            emit(
                f"Gemini tools (step {step + 1}/{MAX_TOOL_ITERATIONS})…",
                percent=30 + min(50, step * 5),
                title="Using tools",
            )
            response = run_cancellable(
                lambda c=contents: client.models.generate_content(
                    model=model_name,
                    contents=c,
                    config=config,
                ),
                cancel_event,
            )
            if with_search:
                found = _extract_grounding_sources(response)
                if found:
                    # Prefer latest non-empty grounding; keep first if later turns omit it.
                    grounding_sources = found
                    search_used = True

            calls = extract_function_calls(response)
            if not calls:
                text = response_text(response)
                if text:
                    return text
                raise RuntimeError("Gemini returned an empty response.")

            model_content = None
            try:
                cands = getattr(response, "candidates", None) or []
                if cands:
                    model_content = getattr(cands[0], "content", None)
            except Exception:  # noqa: BLE001
                model_content = None
            if model_content is not None:
                contents.append(model_content)
            else:
                # Reconstruct function_call parts if content is missing
                fc_parts = []
                for name, args in calls:
                    fc_parts.append(
                        types.Part.from_function_call(name=name, args=args)
                    )
                contents.append(types.Content(role="model", parts=fc_parts))

            response_parts = []
            for name, args in calls:
                emit(f"Running tool {name}…", percent=None, title="Using tools")
                result = execute_tool(name, args)
                response_parts.append(
                    types.Part.from_function_response(name=name, response=result)
                )
            contents.append(types.Content(role="user", parts=response_parts))

        raise RuntimeError(
            f"Gemini tool loop exceeded {MAX_TOOL_ITERATIONS} iterations."
        )

    if generic:
        emit("Calling Gemini…", percent=40)
        try:
            if use_tools:
                research_context = ""
                # Search-first: Google Search alone, then file tools with that brief.
                # Combining Search + function calling lets the model skip Search and
                # invent write_json payloads; a dedicated research pass forces grounding.
                if use_search:
                    research_prompt = (search_query or "").strip()
                    if research_prompt:
                        emit("Google Search research…", percent=25, title="Searching")
                        try:
                            # Slightly warmer than 0 helps recall; keep user temp if already higher.
                            research_temp = max(float(temperature), 0.4)
                            research_context = _call(
                                build_tools_research_prompt(
                                    research_prompt, system_extra=system_extra
                                ),
                                with_search=True,
                                with_url_context=True,
                                call_temperature=research_temp,
                                json_mime=False,
                                attach_basis=False,
                            )
                            if grounding_sources:
                                search_used = True
                                # Append explicit citations so the tool pass cannot "lose" URLs.
                                cite_lines = []
                                for src in grounding_sources:
                                    title = (src.get("title") or "").strip() or "source"
                                    url = (src.get("url") or "").strip()
                                    if url:
                                        cite_lines.append(f"- {title}: {url}")
                                if cite_lines:
                                    research_context = (
                                        (research_context or "").rstrip()
                                        + "\n\nCITED SOURCES FROM GOOGLE SEARCH:\n"
                                        + "\n".join(cite_lines)
                                        + "\n"
                                    )
                            elif research_context:
                                # Search ran even if citation metadata was sparse.
                                search_used = True

                            if grounding_sources and (research_context or "").strip():
                                from .search_enrichment import apply_search_enrichment

                                research_context, appended, enrich_meta = apply_search_enrichment(
                                    research_context,
                                    grounding_sources=grounding_sources,
                                    gemini_cfg=gemini_cfg,
                                    progress=progress,
                                    cancel_event=cancel_event,
                                )
                                if appended:
                                    search_enrichment_appendix = appended
                        except Exception as research_err:
                            from .cancellation import GenerationCancelled

                            if isinstance(research_err, GenerationCancelled):
                                raise
                            logger.warning(
                                "Tools research search failed; continuing with tools only: %s",
                                research_err,
                            )
                            research_context = ""

                response_text = _call_with_tools(
                    build_general_text_prompt(
                        prompt_text,
                        system_extra=system_extra,
                        tool_aliases=selected_tools,
                        with_search=False,
                        research_context=research_context,
                    ),
                    call_temperature=temperature,
                    # Research already done; keep the tool loop on file tools only.
                    with_search=False,
                )
            else:
                if use_search:
                    from .search_enrichment import apply_search_enrichment

                    emit("Google Search grounding…", percent=25, title="Searching")
                    draft = _call(
                        build_general_text_prompt(
                            prompt_text,
                            system_extra=system_extra,
                            with_search=True,
                        ),
                        with_search=True,
                        with_url_context=True,
                        call_temperature=temperature,
                        json_mime=False,
                    )
                    search_used = True
                    response_text = draft
                    if grounding_sources:
                        _, appended, enrich_meta = apply_search_enrichment(
                            draft,
                            grounding_sources=grounding_sources,
                            gemini_cfg=gemini_cfg,
                            progress=progress,
                            cancel_event=cancel_event,
                        )
                        if appended:
                            search_enrichment_appendix = appended
                            response_text = _call(
                                _build_enrichment_refinement_prompt(
                                    prompt_text, draft, appended
                                ),
                                with_search=False,
                                call_temperature=temperature,
                                json_mime=False,
                            )
                else:
                    response_text = _call(
                        build_general_text_prompt(prompt_text, system_extra=system_extra),
                        with_search=False,
                        call_temperature=temperature,
                        json_mime=False,
                    )
        except Exception as exc:
            from .cancellation import GenerationCancelled

            if isinstance(exc, GenerationCancelled):
                raise
            raise RuntimeError(f"Gemini API error: {exc}") from exc
        if not response_text:
            raise RuntimeError("Gemini returned an empty response.")
        emit("Formatting response…", percent=90)
        model_info: dict[str, Any] = {
            "provider": "gemini",
            "repo_id": model_name,
            "modality": "text",
            "temperature": temperature,
            "google_search": bool(use_search and search_used),
            "two_pass_verify": False,
            "use_tools": bool(use_tools),
        }
        if use_tools:
            model_info["tools"] = list(selected_tools)
            if use_search:
                model_info["search_first"] = True
        _record_search_enrichment_meta(model_info, enrich_meta)
        creation = build_text_creation_from_plain(
            response_text,
            prompt=prompt_text,
            model_info=model_info,
        )
        if grounding_sources:
            creation["groundingSources"] = grounding_sources
        brief_source = ""
        if use_tools and use_search and (research_context or "").strip():
            brief_source = research_context.strip()
        elif use_search and search_enrichment_appendix:
            brief_source = search_enrichment_appendix
        if brief_source:
            brief = brief_source
            if len(brief) > 12000:
                brief = brief[:12000] + "\n…[truncated]"
            creation["researchBrief"] = brief
        return creation

    if two_pass:
        pass1_prompt = build_search_extract_prompt(
            game,
            platform,
            creation_type,
            system_extra=system_extra,
            creation_description=creation_description,
            exact_title=exact_title,
        )
    else:
        pass1_prompt = build_prompt(
            game,
            platform,
            creation_type,
            system_extra=system_extra,
            creation_description=creation_description,
            with_web_search=bool(use_search),
            exact_title=exact_title,
        )

    response_text = ""
    try:
        if use_search:
            emit(
                "Pass 1: Gemini + Google Search (extract)…"
                if two_pass
                else "Gemini + Google Search grounding…",
                percent=30,
                title="Generating document",
            )
            try:
                response_text = _call(
                    pass1_prompt,
                    with_search=True,
                    call_temperature=temperature,
                    json_mime=False,
                )
                search_used = True
                if grounding_sources:
                    from .search_enrichment import apply_search_enrichment

                    _, appended, enrich_meta = apply_search_enrichment(
                        response_text,
                        grounding_sources=grounding_sources,
                        gemini_cfg=gemini_cfg,
                        progress=progress,
                        cancel_event=cancel_event,
                    )
                    if appended:
                        search_enrichment_appendix = appended
            except Exception as search_err:
                from .cancellation import GenerationCancelled

                if isinstance(search_err, GenerationCancelled):
                    raise
                logger.warning(
                    "Gemini search-grounded call failed; retrying without search: %s",
                    search_err,
                )
                emit("Search grounding unavailable — using direct Gemini…", percent=45)
                two_pass = False
                response_text = _call(
                    build_prompt(
                        game,
                        platform,
                        creation_type,
                        system_extra=system_extra,
                        creation_description=creation_description,
                        with_web_search=False,
                        exact_title=exact_title,
                    ),
                    with_search=False,
                    call_temperature=temperature,
                    json_mime=True,
                )
                search_used = False
        else:
            emit("Calling Gemini…", percent=40, title="Generating document")
            response_text = _call(
                pass1_prompt,
                with_search=False,
                call_temperature=temperature,
                json_mime=True,
            )
    except Exception as exc:
        from .cancellation import GenerationCancelled

        if isinstance(exc, GenerationCancelled):
            raise
        raise RuntimeError(f"Gemini API error: {exc}") from exc

    if not response_text:
        raise RuntimeError("Gemini returned an empty response.")

    pass1_parsed = extract_json_object(response_text)
    if is_ambiguous(pass1_parsed) or is_game_not_found(pass1_parsed):
        emit("Parsing Gemini JSON…", percent=90, title="Generating document")
        return finalize_creation(
            response_text,
            game,
            platform,
            creation_type,
            model_info={
                "provider": "gemini",
                "repo_id": model_name,
                "modality": "text",
                "temperature": temperature,
                "google_search": bool(search_used),
                "two_pass_verify": False,
            },
            grounding_sources=grounding_sources or None,
            exact_title=exact_title,
            prompt=prompt_text,
        )

    verified = False
    if two_pass and isinstance(pass1_parsed, dict):
        snippets = normalize_source_snippets(pass1_parsed.get("sourceSnippets"))
        if not snippets:
            logger.warning(
                "Pass 1 returned no sourceSnippets — skipping verification pass."
            )
            emit("Pass 1 had no snippets — skipping verification…", percent=75)
        else:
            emit("Pass 2: Gemini verification (temperature 0)…", percent=65)
            verify_prompt = build_verification_prompt(
                game,
                platform,
                creation_type,
                candidate_document=pass1_parsed,
                source_snippets=snippets,
                creation_description=creation_description,
                system_extra=(
                    (system_extra + "\n\nADDITIONAL EXTRACTED SEARCH MATERIAL:\n" + search_enrichment_appendix).strip()
                    if search_enrichment_appendix
                    else system_extra
                ),
            )
            try:
                verified_text = _call(
                    verify_prompt,
                    with_search=False,
                    call_temperature=0.0,
                    json_mime=True,
                )
            except Exception as verify_err:
                from .cancellation import GenerationCancelled

                if isinstance(verify_err, GenerationCancelled):
                    raise
                logger.warning(
                    "Pass 2 verification failed; using Pass 1 output: %s", verify_err
                )
                emit("Verification unavailable — using Pass 1 extract…", percent=80)
                verified_text = ""

            if verified_text:
                verified_parsed = extract_json_object(verified_text)
                if (
                    verified_parsed
                    and not is_ambiguous(verified_parsed)
                    and not is_game_not_found(verified_parsed)
                    and str(verified_parsed.get("game") or "").strip()
                ):
                    if not normalize_source_snippets(verified_parsed.get("sourceSnippets")):
                        verified_parsed["sourceSnippets"] = snippets
                    response_text = json.dumps(verified_parsed, ensure_ascii=False)
                    verified = True
                else:
                    logger.warning(
                        "Pass 2 returned unusable JSON — keeping Pass 1 candidate."
                    )

    emit("Parsing Gemini JSON…", percent=90, title="Generating document")
    model_info = {
        "provider": "gemini",
        "repo_id": model_name,
        "modality": "text",
        "temperature": temperature,
        "google_search": bool(search_used),
        "two_pass_verify": bool(verified),
    }
    _record_search_enrichment_meta(model_info, enrich_meta)
    return finalize_creation(
        response_text,
        game,
        platform,
        creation_type,
        model_info=model_info,
        grounding_sources=grounding_sources or None,
        exact_title=exact_title,
        prompt=prompt_text,
    )
