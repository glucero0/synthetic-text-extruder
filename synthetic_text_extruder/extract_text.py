"""Extract readable text from image (OCR) or video (audio transcription)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[Any], None]

OCR_PROMPT = (
    "Extract all readable text from this image. Preserve reading order and line breaks "
    "where helpful. If there is no readable text, reply with exactly: (no text found). "
    "Do not describe the image; output only the extracted text."
)

TRANSCRIPT_PROMPT = (
    "Transcribe all spoken words from this audio as plain text. Include punctuation "
    "and paragraph breaks where natural. If there is no speech, reply with exactly: "
    "(no speech found). Do not describe the audio; output only the transcript."
)

VIDEO_FALLBACK_PROMPT = (
    "This video has little or no usable audio. Extract any on-screen text you can read, "
    "and briefly note spoken words if any are audible. If nothing is readable or spoken, "
    "reply with exactly: (no text found). Prefer plain text over description."
)

# Inline multimodal payloads stay reasonable for API requests.
MAX_INLINE_BYTES = 18 * 1024 * 1024


def _emit(
    progress: ProgressCallback | None,
    message: str,
    *,
    percent: float | None = None,
    title: str = "Extracting text",
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


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def clear_extraction_fields(creation: dict[str, Any]) -> dict[str, Any]:
    """Drop cached OCR/transcript fields after media is replaced."""
    out = dict(creation)
    meta = dict(out.get("meta") or {})
    for key in (
        "extractedText",
        "extractionKind",
        "extractedAt",
        "extractionModel",
        "extractionProvider",
    ):
        meta.pop(key, None)
    out["meta"] = meta
    return out


def apply_extraction_fields(
    creation: dict[str, Any],
    *,
    text: str,
    kind: str,
    model: str,
    provider: str,
) -> dict[str, Any]:
    out = dict(creation)
    meta = dict(out.get("meta") or {})
    meta["extractedText"] = text
    meta["extractionKind"] = kind
    meta["extractedAt"] = _utcnow_iso()
    meta["extractionModel"] = model
    meta["extractionProvider"] = provider
    meta["studioJob"] = "extract"
    out["meta"] = meta
    return out


def get_extracted_text(creation: dict[str, Any] | None) -> str:
    if not creation:
        return ""
    meta = creation.get("meta") or {}
    return str(meta.get("extractedText") or "").strip()


def extract_text_from_creation(
    creation: dict[str, Any],
    *,
    config: dict[str, Any],
    media_path: Any,
    progress: ProgressCallback | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """Run OCR or transcription and return updated creation (not yet persisted)."""
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
        raise RuntimeError("Extract Text is only available for image and video creations.")

    model_id, provider = _active_model_and_provider(config)
    if provider != "gemini":
        raise RuntimeError(
            "Extract Text requires Gemini. Paste a Gemini API key in Settings."
        )

    path = media_path
    if path is None:
        raise RuntimeError("Media file is missing on disk.")

    raise_if_cancelled(_cancelled)

    if modality == "image":
        raw = path.read_bytes() if hasattr(path, "read_bytes") else bytes(path)
        image_mime = mime if mime.startswith("image/") else "image/png"
        _emit(progress, "Running OCR…", percent=35, title="Extracting text")
        text, used_model = _extract_image(
            raw,
            mime_type=image_mime,
            config=config,
            model_id=model_id,
            progress=progress,
            cancel_check=_cancelled,
            cancel_event=cancel_event,
        )
        kind = "ocr"
    else:
        text, used_model, kind = _extract_video(
            path,
            mime_type=mime if mime.startswith("video/") else "video/mp4",
            config=config,
            model_id=model_id,
            progress=progress,
            cancel_check=_cancelled,
            cancel_event=cancel_event,
        )

    raise_if_cancelled(_cancelled)
    text = (text or "").strip()
    if not text:
        text = "(no text found)" if kind == "ocr" else "(no speech found)"

    _emit(progress, "Saving extracted text…", percent=90, title="Extracting text")
    return apply_extraction_fields(
        creation,
        text=text,
        kind=kind,
        model=used_model,
        provider=provider,
    )


def ocr_image_bytes(
    raw: bytes,
    *,
    mime_type: str = "image/png",
    config: dict[str, Any],
    progress: ProgressCallback | None = None,
    cancel_event: Any = None,
) -> tuple[str, str]:
    """OCR image bytes via the configured multimodal provider (Gemini)."""
    from .cancellation import raise_if_cancelled
    from .generator import _active_model_and_provider

    def _cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    raise_if_cancelled(_cancelled)
    model_id, provider = _active_model_and_provider(config)
    if provider != "gemini":
        raise RuntimeError(
            "Search image OCR requires a Gemini API key. Paste it in Settings."
        )
    return _extract_image(
        raw,
        mime_type=mime_type,
        config=config,
        model_id=model_id,
        progress=progress,
        cancel_check=_cancelled,
        cancel_event=cancel_event,
    )


def _extract_image(
    raw: bytes,
    *,
    mime_type: str,
    config: dict[str, Any],
    model_id: str,
    progress: ProgressCallback | None,
    cancel_check: Callable[[], bool],
    cancel_event: Any = None,
) -> tuple[str, str]:
    from .cancellation import raise_if_cancelled

    raise_if_cancelled(cancel_check)
    return _gemini_multimodal(
        raw,
        mime_type=mime_type,
        prompt=OCR_PROMPT,
        config=config,
        model_id=model_id,
        progress=progress,
        cancel_check=cancel_check,
        cancel_event=cancel_event,
    )


def _extract_video(
    path: Any,
    *,
    mime_type: str,
    config: dict[str, Any],
    model_id: str,
    progress: ProgressCallback | None,
    cancel_check: Callable[[], bool],
    cancel_event: Any = None,
) -> tuple[str, str, str]:
    from .cancellation import raise_if_cancelled
    from .video_edit import (
        FfmpegNotFoundError,
        extract_audio_mp3,
        video_has_audio_stream,
    )

    raise_if_cancelled(cancel_check)
    _emit(progress, "Checking video audio…", percent=20, title="Transcribing")

    try:
        has_audio = video_has_audio_stream(path)
    except FfmpegNotFoundError as exc:
        raise RuntimeError(str(exc)) from exc

    if has_audio:
        _emit(progress, "Extracting audio…", percent=30, title="Transcribing")
        try:
            audio = extract_audio_mp3(path, max_seconds=600)
        except FfmpegNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Audio extract failed, falling back to video: %s", exc)
            audio = b""
        raise_if_cancelled(cancel_check)
        if audio and len(audio) <= MAX_INLINE_BYTES:
            _emit(progress, "Transcribing audio…", percent=45, title="Transcribing")
            text, model = _gemini_multimodal(
                audio,
                mime_type="audio/mpeg",
                prompt=TRANSCRIPT_PROMPT,
                config=config,
                model_id=model_id,
                progress=progress,
                cancel_check=cancel_check,
                cancel_event=cancel_event,
            )
            return text, model, "transcript"

    # Silent / oversized audio: send a short video clip for on-screen text.
    _emit(progress, "Reading video for on-screen text…", percent=40, title="Extracting text")
    from .video_edit import extract_video_clip_bytes

    clip = extract_video_clip_bytes(path, max_seconds=90)
    raise_if_cancelled(cancel_check)
    if len(clip) > MAX_INLINE_BYTES:
        raise RuntimeError(
            "Video is too large to analyze without audio. "
            "Trim it in Video Editor, or use a clip with a spoken track."
        )
    text, model = _gemini_multimodal(
        clip,
        mime_type="video/mp4",
        prompt=VIDEO_FALLBACK_PROMPT,
        config=config,
        model_id=model_id,
        progress=progress,
        cancel_check=cancel_check,
        cancel_event=cancel_event,
    )
    return text, model, "ocr" if not has_audio else "transcript"


def _gemini_multimodal(
    data: bytes,
    *,
    mime_type: str,
    prompt: str,
    config: dict[str, Any],
    model_id: str,
    progress: ProgressCallback | None,
    cancel_check: Callable[[], bool],
    cancel_event: Any = None,
) -> tuple[str, str]:
    from .cancellation import raise_if_cancelled, run_cancellable
    from .gemini_provider import normalize_gemini_model, resolve_api_key

    raise_if_cancelled(cancel_check)
    gemini_cfg = config.get("gemini") or {}
    api_key = resolve_api_key(gemini_cfg)
    if not api_key:
        raise RuntimeError(
            "Gemini API key missing. Paste your key in Settings → AI Model (Gemini)."
        )
    model_name = normalize_gemini_model(model_id or gemini_cfg.get("text_model"))

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed. Run:\n  pip install google-genai"
        ) from exc

    _emit(progress, f"Contacting Gemini ({model_name})…", percent=55)
    client = genai.Client(api_key=api_key)
    raise_if_cancelled(cancel_check)
    uploaded = None
    try:
        media_part, uploaded = _gemini_media_part(
            client, types, data=data, mime_type=mime_type, cancel_check=cancel_check
        )
        response = run_cancellable(
            lambda: client.models.generate_content(
                model=model_name,
                contents=[media_part, prompt],
                config=types.GenerateContentConfig(temperature=0.0),
            ),
            cancel_event,
        )
    except Exception as exc:  # noqa: BLE001
        from .cancellation import GenerationCancelled

        if isinstance(exc, GenerationCancelled):
            raise
        raise RuntimeError(f"Gemini Extract Text failed: {exc}") from exc
    finally:
        if uploaded is not None:
            try:
                name = getattr(uploaded, "name", None)
                if name:
                    client.files.delete(name=name)
            except Exception:  # noqa: BLE001
                logger.debug("Could not delete Gemini uploaded file", exc_info=True)

    raise_if_cancelled(cancel_check)
    text = _gemini_response_text(response)
    return text, model_name


def gemini_text_prompt(
    prompt: str,
    *,
    config: dict[str, Any],
    model_id: str,
    progress: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
    cancel_event: Any = None,
) -> tuple[str, str]:
    """Plain-text Gemini call (no media part)."""
    from .cancellation import raise_if_cancelled, run_cancellable
    from .gemini_provider import normalize_gemini_model, resolve_api_key

    def _cancelled() -> bool:
        if cancel_check:
            return bool(cancel_check())
        return bool(cancel_event is not None and cancel_event.is_set())

    raise_if_cancelled(_cancelled)
    gemini_cfg = config.get("gemini") or {}
    api_key = resolve_api_key(gemini_cfg)
    if not api_key:
        raise RuntimeError(
            "Gemini API key missing. Paste your key in Settings → AI Model (Gemini)."
        )
    model_name = normalize_gemini_model(model_id or gemini_cfg.get("text_model"))
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed. Run:\n  pip install google-genai"
        ) from exc
    _emit(progress, f"Contacting Gemini ({model_name})…", percent=55)
    client = genai.Client(api_key=api_key)
    response = run_cancellable(
        lambda: client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2),
        ),
        cancel_event,
    )
    return _gemini_response_text(response), model_name


def _gemini_media_part(
    client: Any,
    types: Any,
    *,
    data: bytes,
    mime_type: str,
    cancel_check: Callable[[], bool],
) -> tuple[Any, Any]:
    """Inline bytes when small; Gemini Files API upload when over the inline cap."""
    from .cancellation import raise_if_cancelled

    raise_if_cancelled(cancel_check)
    mime = (mime_type or "application/octet-stream").split(";", 1)[0].strip()
    if len(data) <= MAX_INLINE_BYTES:
        return types.Part.from_bytes(data=data, mime_type=mime), None

    import tempfile
    import time

    suffix = _suffix_for_mime(mime)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(data)
            tmp_path = handle.name
        uploaded = client.files.upload(file=tmp_path, config={"mime_type": mime})
        deadline = time.monotonic() + 120
        state = str(getattr(getattr(uploaded, "state", None), "name", "") or "")
        while state in {"PROCESSING", "STATE_UNSPECIFIED", ""}:
            raise_if_cancelled(cancel_check)
            if time.monotonic() > deadline:
                break
            time.sleep(0.4)
            name = getattr(uploaded, "name", None)
            if not name:
                break
            uploaded = client.files.get(name=name)
            state = str(getattr(getattr(uploaded, "state", None), "name", "") or "")
        if state and state not in {"ACTIVE", "STATE_UNSPECIFIED", ""}:
            raise RuntimeError(f"Gemini file upload ended in state {state}.")
        return uploaded, uploaded
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass


def _suffix_for_mime(mime: str) -> str:
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "application/pdf": ".pdf",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "text/plain": ".txt",
    }
    return mapping.get((mime or "").lower(), ".bin")


def _gemini_response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text).strip()
    parts: list[str] = []
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            t = getattr(part, "text", None)
            if t:
                parts.append(str(t))
    return "\n".join(parts).strip()
