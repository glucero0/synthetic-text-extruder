"""Gemini image and video generation helpers."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from .creation_utils import build_media_creation, title_from_prompt
from .media_store import write_media_bytes
from .modality import classify_model_modality

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[Any], None]


def _emit(
    progress: ProgressCallback | None,
    message: str,
    *,
    percent: float | None = None,
    title: str = "Generating",
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


def generate_image_with_gemini(
    prompt: str,
    *,
    gemini_cfg: dict[str, Any],
    resolve_api_key: Callable[[dict[str, Any] | None], str | None] | None = None,
    normalize_model: Callable[[str | None], str] | None = None,
    progress: ProgressCallback | None = None,
    basis_media: dict[str, Any] | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """Generate an image via Gemini image models and store under media/."""
    from .cancellation import run_cancellable
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
        raise RuntimeError("Enter a prompt to generate an image.")

    model_name = normalize_model(gemini_cfg.get("image_model"))
    if (classify_model_modality(model_name) or "text") != "image":
        from .gemini_provider import DEFAULT_GEMINI_IMAGE_MODEL

        model_name = DEFAULT_GEMINI_IMAGE_MODEL

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed. Run:\n  pip install google-genai"
        ) from exc

    _emit(progress, f"Contacting Gemini image model ({model_name})…", percent=15, title="Generating image")
    client = genai.Client(api_key=api_key)

    image_bytes: bytes | None = None
    mime_type = "image/png"
    basis_bytes = (basis_media or {}).get("bytes") if basis_media else None
    basis_mime = str((basis_media or {}).get("mime_type") or "image/png")
    reference_parts: list[tuple[bytes, str]] = []
    raw_refs = (basis_media or {}).get("reference_media") if basis_media else None
    if isinstance(raw_refs, list):
        for item in raw_refs:
            if not isinstance(item, dict):
                continue
            data = item.get("bytes")
            if not data:
                continue
            mime = str(item.get("mime_type") or "image/png")
            reference_parts.append((bytes(data), mime))

    try:
        if "imagen" not in model_name.lower():
            has_refs = bool(basis_bytes or reference_parts)
            _emit(
                progress,
                "Generating image from basis…" if has_refs else "Generating image…",
                percent=40,
                title="Generating image",
            )
            contents: list[Any]
            if has_refs:
                if reference_parts and basis_bytes:
                    edit_prompt = (
                        "Using the provided reference images as lineage context. "
                        "The last image is the current basis to edit; earlier images "
                        "are ancestors from the same chain. Create a new image. "
                        "Follow this instruction:\n" + prompt
                    )
                else:
                    edit_prompt = (
                        "Using the provided reference image as the basis, create a new image. "
                        "Follow this instruction:\n" + prompt
                    )
                contents = [
                    types.Part.from_bytes(data=data, mime_type=mime)
                    for data, mime in reference_parts
                ]
                if basis_bytes:
                    contents.append(
                        types.Part.from_bytes(
                            data=bytes(basis_bytes), mime_type=basis_mime
                        )
                    )
                contents.append(edit_prompt)
            else:
                contents = [prompt]
            response = run_cancellable(
                lambda: client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_modalities=["TEXT", "IMAGE"],
                    ),
                ),
                cancel_event,
            )
            for cand in getattr(response, "candidates", None) or []:
                content = getattr(cand, "content", None)
                for part in getattr(content, "parts", None) or []:
                    inline = getattr(part, "inline_data", None)
                    if inline and getattr(inline, "data", None):
                        data = inline.data
                        if isinstance(data, str):
                            import base64

                            image_bytes = base64.b64decode(data)
                        else:
                            image_bytes = bytes(data)
                        mime_type = getattr(inline, "mime_type", None) or "image/png"
                        break
                if image_bytes:
                    break
        else:
            if basis_bytes or reference_parts:
                raise RuntimeError(
                    "Imagen models in this app do not accept a Studio media basis. "
                    "Switch the Gemini Image model to a Flash Image model, or Clear basis."
                )
            _emit(progress, "Generating image (Imagen)…", percent=40, title="Generating image")
            response = run_cancellable(
                lambda: client.models.generate_images(
                    model=model_name,
                    prompt=prompt,
                    config=types.GenerateImagesConfig(number_of_images=1),
                ),
                cancel_event,
            )
            for generated in getattr(response, "generated_images", None) or []:
                img = getattr(generated, "image", None)
                if img is None:
                    continue
                data = getattr(img, "image_bytes", None) or getattr(img, "data", None)
                if data:
                    image_bytes = bytes(data)
                    mime_type = getattr(img, "mime_type", None) or "image/png"
                    break
    except Exception as exc:
        from .cancellation import GenerationCancelled

        if isinstance(exc, GenerationCancelled):
            raise
        raise RuntimeError(f"Gemini image generation error: {exc}") from exc

    if not image_bytes:
        raise RuntimeError("Gemini returned no image data.")

    _emit(progress, "Saving image…", percent=85, title="Generating image")
    creation_id = f"doc_{uuid.uuid4().hex[:10]}"
    stored = write_media_bytes(creation_id, image_bytes, mime_type=mime_type)
    return build_media_creation(
        modality="image",
        prompt=prompt,
        media_path=stored["mediaPath"],
        mime_type=stored["mimeType"],
        title=title_from_prompt(prompt),
        model_info={
            "provider": "gemini",
            "repo_id": model_name,
            "modality": "image",
            "basis": bool(basis_bytes),
        },
        creation_id=creation_id,
    )


def generate_video_with_gemini(
    prompt: str,
    *,
    gemini_cfg: dict[str, Any],
    resolve_api_key: Callable[[dict[str, Any] | None], str | None] | None = None,
    normalize_model: Callable[[str | None], str] | None = None,
    progress: ProgressCallback | None = None,
    basis_media: dict[str, Any] | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """Generate a video via Veo and store under media/ as MP4 when possible."""
    from .cancellation import run_cancellable
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
        raise RuntimeError("Enter a prompt to generate a video.")

    model_name = normalize_model(gemini_cfg.get("video_model"))
    if (classify_model_modality(model_name) or "text") != "video":
        from .gemini_provider import DEFAULT_GEMINI_VIDEO_MODEL

        model_name = DEFAULT_GEMINI_VIDEO_MODEL

    try:
        import time

        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed. Run:\n  pip install google-genai"
        ) from exc

    _emit(progress, f"Contacting Veo ({model_name})…", percent=10, title="Generating video")
    client = genai.Client(api_key=api_key)

    basis_bytes = (basis_media or {}).get("bytes") if basis_media else None
    basis_mime = str((basis_media or {}).get("mime_type") or "image/png")

    try:
        _emit(
            progress,
            "Starting video generation from basis…"
            if basis_bytes
            else "Starting video generation (this can take a few minutes)…",
            percent=25,
            title="Generating video",
        )
        gen_kwargs: dict[str, Any] = {
            "model": model_name,
            "prompt": prompt,
            "config": types.GenerateVideosConfig(number_of_videos=1),
        }
        if basis_bytes:
            # Image-to-video (video basis is reduced to a reference frame upstream)
            gen_kwargs["image"] = types.Image(
                image_bytes=bytes(basis_bytes),
                mime_type=basis_mime,
            )

        def _start_videos() -> Any:
            try:
                return client.models.generate_videos(**gen_kwargs)
            except TypeError:
                if not basis_bytes:
                    raise
                # Older SDKs: retry without typed Image kwargs
                return client.models.generate_videos(
                    model=model_name,
                    prompt=prompt,
                    image=bytes(basis_bytes),
                    config=types.GenerateVideosConfig(number_of_videos=1),
                )

        operation = run_cancellable(_start_videos, cancel_event)
        waited = 0
        while not getattr(operation, "done", False):
            # 1s ticks so Cancel is noticed quickly (progress raises GenerationCancelled).
            time.sleep(1)
            waited += 1
            pct = min(85, 25 + waited // 4)
            _emit(
                progress,
                f"Rendering video… ({waited}s)",
                percent=pct,
                title="Generating video",
            )
            if waited % 8 == 0:
                operation = client.operations.get(operation)
            elif getattr(operation, "done", False):
                break
        if not getattr(operation, "done", False):
            operation = client.operations.get(operation)

        result = getattr(operation, "response", None) or getattr(operation, "result", None)
        generated = None
        if result is not None:
            videos = getattr(result, "generated_videos", None) or []
            if videos:
                generated = videos[0]
        if generated is None:
            raise RuntimeError("Veo returned no video.")

        video_obj = getattr(generated, "video", None) or generated
        video_bytes: bytes | None = None
        mime_type = "video/mp4"

        uri = getattr(video_obj, "uri", None)
        files = getattr(client, "files", None)
        if uri and files is not None and hasattr(files, "download"):
            _emit(progress, "Downloading video…", percent=90, title="Generating video")
            try:
                downloaded = files.download(file=video_obj)
                if isinstance(downloaded, (bytes, bytearray)):
                    video_bytes = bytes(downloaded)
            except Exception:  # noqa: BLE001
                logger.debug("client.files.download failed", exc_info=True)

        if video_bytes is None:
            data = getattr(video_obj, "video_bytes", None) or getattr(video_obj, "data", None)
            if data:
                video_bytes = bytes(data)

        if video_bytes is None and uri:
            import urllib.request

            _emit(progress, "Fetching video file…", percent=90, title="Generating video")
            req = urllib.request.Request(str(uri))
            with urllib.request.urlopen(req, timeout=300) as resp:
                video_bytes = resp.read()
                mime_type = resp.headers.get_content_type() or "video/mp4"

        if not video_bytes:
            raise RuntimeError("Could not download Veo video bytes.")
    except Exception as exc:
        from .cancellation import GenerationCancelled

        if isinstance(exc, GenerationCancelled):
            raise
        raise RuntimeError(f"Gemini video generation error: {exc}") from exc

    _emit(progress, "Saving video…", percent=95, title="Generating video")
    creation_id = f"doc_{uuid.uuid4().hex[:10]}"
    stored = write_media_bytes(creation_id, video_bytes, mime_type=mime_type or "video/mp4")
    return build_media_creation(
        modality="video",
        prompt=prompt,
        media_path=stored["mediaPath"],
        mime_type=stored["mimeType"],
        title=title_from_prompt(prompt),
        model_info={
            "provider": "gemini",
            "repo_id": model_name,
            "modality": "video",
        },
        creation_id=creation_id,
    )
