"""Gemini Lyria music generation via the Interactions API."""

from __future__ import annotations

import base64
import logging
import uuid
from typing import Any, Callable

from .creation_utils import build_media_creation, title_from_prompt
from .media_store import write_media_bytes
from .modality import classify_model_modality

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[Any], None]

# Current Interactions full-song id plus the older Pro preview id.
_LYRIA_FULL_SONG_IDS: tuple[str, ...] = ("lyria-3.5", "lyria-3-pro-preview")


def lyria_model_candidates(model_name: str) -> list[str]:
    """Return the requested Lyria id, then a sibling full-song id if needed."""
    mid = (model_name or "").strip()
    if mid.startswith("models/"):
        mid = mid[len("models/") :]
    out: list[str] = []
    if mid:
        out.append(mid)
    low = mid.lower()
    if low in {m.lower() for m in _LYRIA_FULL_SONG_IDS} or "pro" in low:
        for alt in _LYRIA_FULL_SONG_IDS:
            if alt.lower() not in {x.lower() for x in out}:
                out.append(alt)
    return out or ["lyria-3-clip-preview"]


def is_lyria_policy_block(exc: BaseException | str) -> bool:
    text = str(exc or "").lower()
    return (
        "content_blocked" in text
        or "unspecified policy" in text
        or "request blocked" in text
        or "blocked for an unspecified policy" in text
    )


def is_lyria_model_unavailable(exc: BaseException | str) -> bool:
    text = str(exc or "").lower()
    return (
        "not_found" in text
        or "not found" in text
        or "not available" in text
        or ("404" in text and "model" in text)
    )


def is_lyria_modality_schema_error(exc: BaseException | str) -> bool:
    """True when Interactions rejects response_modalities (e.g. uppercase AUDIO)."""
    text = str(exc or "").lower()
    if "response_modalities" in text:
        return True
    if "invalid_request" not in text:
        return False
    unsupported = (
        "not supported" in text
        or "unsupported" in text
        or "supported values" in text
    )
    mentions_audio = "'audio'" in text or '"audio"' in text
    return unsupported and (mentions_audio or "modalit" in text)


def lyria_user_error(exc: BaseException | str, *, model_name: str = "") -> str:
    """Turn SDK / policy failures into a Studio-facing message."""
    mid = (model_name or "").strip() or "Lyria"
    if is_lyria_modality_schema_error(exc):
        return (
            f"Lyria rejected this request format ({mid}). "
            "The music API did not accept the app’s audio output settings. "
            "Try Settings → Refresh the Audio picker, or "
            "python -m pip install -U google-genai, then retry."
        )
    if is_lyria_policy_block(exc):
        return (
            f"Lyria blocked this request ({mid}). Google’s music safety filters "
            "rejected the prompt or the generated vocals — this is stricter on "
            "full-length Pro / 3.5 songs than on 30-second Clip. Avoid artist "
            "names, copyrighted lyrics, or sounding like a specific performer. "
            "Try a more original description, an instrumental-only prompt, or "
            "Settings → Audio model → Lyria 3 Clip."
        )
    if is_lyria_model_unavailable(exc):
        return (
            f'Lyria model "{mid}" is not available for this API key. '
            "Open Settings, Refresh the Audio picker, and choose "
            "lyria-3.5 (full songs) or lyria-3-clip-preview (30 seconds)."
        )
    return f"Gemini music generation error: {exc}"


def _emit(
    progress: ProgressCallback | None,
    message: str,
    *,
    percent: float | None = None,
    title: str = "Generating music",
) -> None:
    if not progress:
        return
    from .cancellation import GenerationCancelled

    payload: dict[str, Any] = {
        "message": message,
        "phase": "generate",
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


def _attr_or_key(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        for name in names:
            if name in obj and obj[name] is not None:
                return obj[name]
        return default
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _decode_audio_payload(data: Any) -> bytes | None:
    if data is None:
        return None
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, str):
        try:
            return base64.b64decode(data)
        except Exception:  # noqa: BLE001
            return None
    return None


def _block_type(block: Any) -> str:
    return str(_attr_or_key(block, "type", default="") or "").strip().lower()


def _iter_content_blocks(interaction: Any) -> list[Any]:
    blocks: list[Any] = []
    for step in _attr_or_key(interaction, "steps", default=None) or []:
        step_type = str(_attr_or_key(step, "type", default="") or "").strip().lower()
        if step_type and step_type not in {"model_output", "output"}:
            continue
        for block in _attr_or_key(step, "content", default=None) or []:
            blocks.append(block)
    for block in _attr_or_key(interaction, "outputs", "output", default=None) or []:
        if isinstance(block, (dict, object)):
            blocks.append(block)
    return blocks


def extract_lyria_output(interaction: Any) -> tuple[bytes | None, str, str]:
    """Return (audio_bytes, mime_type, lyrics) from an Interactions response."""
    mime_type = "audio/mpeg"
    audio_bytes: bytes | None = None
    lyrics_parts: list[str] = []

    generated = _attr_or_key(interaction, "output_audio", "outputAudio")
    if generated is not None:
        data = generated
        if not isinstance(generated, (bytes, bytearray, str)):
            data = _attr_or_key(generated, "data")
            mime_type = (
                str(
                    _attr_or_key(generated, "mime_type", "mimeType", default="") or ""
                ).strip()
                or mime_type
            )
        audio_bytes = _decode_audio_payload(data)

    text = _attr_or_key(interaction, "output_text", "outputText")
    if text:
        lyrics_parts.append(str(text))

    for block in _iter_content_blocks(interaction):
        btype = _block_type(block)
        if btype == "audio":
            decoded = _decode_audio_payload(_attr_or_key(block, "data"))
            if decoded:
                audio_bytes = decoded
            block_mime = str(
                _attr_or_key(block, "mime_type", "mimeType", default="") or ""
            ).strip()
            if block_mime:
                mime_type = block_mime
        elif btype in {"text", ""}:
            piece = _attr_or_key(block, "text")
            if piece:
                lyrics_parts.append(str(piece))

    seen: set[str] = set()
    unique_lyrics: list[str] = []
    for part in lyrics_parts:
        cleaned = part.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique_lyrics.append(cleaned)
    return audio_bytes, mime_type or "audio/mpeg", "\n\n".join(unique_lyrics)


def generate_audio_with_gemini(
    prompt: str,
    *,
    gemini_cfg: dict[str, Any],
    resolve_api_key: Callable[[dict[str, Any] | None], str | None] | None = None,
    normalize_model: Callable[[str | None], str] | None = None,
    progress: ProgressCallback | None = None,
    basis_media: dict[str, Any] | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """Generate music via Lyria and store under media/ as MP3 or WAV."""
    from .cancellation import run_cancellable
    from .gemini_provider import DEFAULT_GEMINI_AUDIO_MODEL
    from .gemini_provider import normalize_gemini_model as _ngm
    from .gemini_provider import resolve_api_key as _rak

    resolve_api_key = resolve_api_key or _rak
    normalize_model = normalize_model or _ngm

    api_key = resolve_api_key(gemini_cfg)
    if not api_key:
        raise RuntimeError(
            "Gemini API key missing. Paste your key in Settings → AI Model (Gemini)."
        )
    prompt = (prompt or "").strip()
    if not prompt:
        raise RuntimeError("Enter a prompt to generate music.")

    model_name = normalize_model(gemini_cfg.get("audio_model"))
    if (classify_model_modality(model_name) or "text") != "audio":
        model_name = DEFAULT_GEMINI_AUDIO_MODEL
    candidates = lyria_model_candidates(model_name)

    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed. Run:\n  python -m pip install google-genai"
        ) from exc

    _emit(
        progress,
        f"Contacting Lyria ({candidates[0]})…",
        percent=15,
        title="Generating music",
    )
    logger.info("Lyria generate: models=%s prompt_chars=%s", candidates, len(prompt))
    client = genai.Client(api_key=api_key)

    basis_bytes = (basis_media or {}).get("bytes") if basis_media else None
    basis_mime = str((basis_media or {}).get("mime_type") or "image/png")
    use_image = bool(basis_bytes) and basis_mime.lower().startswith("image/")

    interaction_input: Any
    if use_image:
        image_b64 = base64.b64encode(bytes(basis_bytes)).decode("ascii")
        interaction_input = [
            {"type": "text", "text": prompt},
            {
                "type": "image",
                "mime_type": basis_mime,
                "data": image_b64,
            },
        ]
    else:
        interaction_input = prompt

    interactions = getattr(client, "interactions", None)
    if interactions is None or not hasattr(interactions, "create"):
        raise RuntimeError(
            "This google-genai version has no Interactions API. "
            "Upgrade with: python -m pip install -U google-genai"
        )

    def _create(candidate: str) -> Any:
        kwargs: dict[str, Any] = {
            "model": candidate,
            "input": interaction_input,
        }
        extra_attempts: list[dict[str, Any]] = [
            {"response_modalities": ["audio", "text"], "timeout": 300},
            {"response_modalities": ["audio", "text"]},
            {"timeout": 300},
            {},
        ]
        last_schema_exc: Exception | None = None
        skip_modalities = False
        for extra in extra_attempts:
            if skip_modalities and extra.get("response_modalities"):
                continue
            try:
                return interactions.create(**kwargs, **extra)
            except TypeError as exc:
                last_schema_exc = exc
                continue
            except Exception as exc:
                if extra.get("response_modalities") and is_lyria_modality_schema_error(
                    exc
                ):
                    logger.warning(
                        "Lyria rejected response_modalities (%s); retrying without it",
                        exc,
                    )
                    skip_modalities = True
                    last_schema_exc = exc
                    continue
                raise
        if last_schema_exc:
            raise last_schema_exc
        return interactions.create(**kwargs)

    interaction = None
    used_model = candidates[0]
    last_exc: Exception | None = None
    try:
        for index, candidate in enumerate(candidates):
            used_model = candidate
            _emit(
                progress,
                (
                    "Composing from image…"
                    if use_image
                    else f"Composing music ({candidate})…"
                ),
                percent=40 + min(20, index * 10),
                title="Generating music",
            )
            try:
                interaction = run_cancellable(
                    lambda model=candidate: _create(model),
                    cancel_event,
                )
                model_name = candidate
                break
            except Exception as exc:
                from .cancellation import GenerationCancelled

                if isinstance(exc, GenerationCancelled):
                    raise
                last_exc = exc
                retryable = is_lyria_policy_block(exc) or is_lyria_model_unavailable(
                    exc
                )
                if retryable and index + 1 < len(candidates):
                    nxt = candidates[index + 1]
                    logger.warning(
                        "Lyria %s failed (%s); retrying %s",
                        candidate,
                        exc,
                        nxt,
                    )
                    _emit(
                        progress,
                        f"{candidate} was blocked or unavailable — trying {nxt}…",
                        percent=50,
                        title="Generating music",
                    )
                    continue
                raise RuntimeError(lyria_user_error(exc, model_name=candidate)) from exc
    except Exception as exc:
        from .cancellation import GenerationCancelled

        if isinstance(exc, GenerationCancelled):
            raise
        if isinstance(exc, RuntimeError) and str(exc).startswith(
            ("Lyria", "Gemini music")
        ):
            raise
        raise RuntimeError(
            lyria_user_error(last_exc or exc, model_name=used_model)
        ) from exc

    if interaction is None:
        raise RuntimeError(
            lyria_user_error(last_exc or "Lyria returned no response.", model_name=used_model)
        )

    audio_bytes, mime_type, lyrics = extract_lyria_output(interaction)
    if not audio_bytes:
        raise RuntimeError("Lyria returned no audio data.")

    _emit(progress, "Saving track…", percent=90, title="Generating music")
    creation_id = f"doc_{uuid.uuid4().hex[:10]}"
    stored = write_media_bytes(
        creation_id, audio_bytes, mime_type=mime_type or "audio/mpeg"
    )
    return build_media_creation(
        modality="audio",
        prompt=prompt,
        media_path=stored["mediaPath"],
        mime_type=stored["mimeType"],
        title=title_from_prompt(prompt),
        model_info={
            "provider": "gemini",
            "repo_id": model_name,
            "modality": "audio",
            "basis": bool(use_image),
        },
        creation_id=creation_id,
        lyrics=lyrics or None,
    )
