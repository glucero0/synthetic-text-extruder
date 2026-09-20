"""Studio CREATE job classifier: policy prompt + JSON Gemini call + regex fallback."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .creation_utils import extract_json_object
from .modality import (
    infer_layout_extract_intent,
    infer_text_extract_intent,
    resolve_generation_modality,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[Any], None]

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_POLICY_PATH = _PROMPTS_DIR / "studio_router.md"
_FIXTURES_PATH = _PROMPTS_DIR / "studio_router.fixtures.json"

JOB_KINDS = frozenset(
    {
        "report",
        "layout_extract",
        "text_extract",
        "collection",
        "video",
        "image",
        "audio",
        "text",
    }
)
COLLECTION_KINDS = frozenset(
    {
        "magazine",
        "flipbook",
        "contact_sheet",
        "filters",
        "ocr",
        "assemble_pdf",
        "generic_map",
        "report",
    }
)
MEDIA_JOBS = frozenset({"video", "image", "audio"})
TEXT_JOBS = frozenset(
    {"report", "layout_extract", "text_extract", "collection", "text"}
)


def load_studio_router_prompt() -> str:
    return _POLICY_PATH.read_text(encoding="utf-8")


def load_studio_router_fixtures() -> list[dict[str, Any]]:
    raw = json.loads(_FIXTURES_PATH.read_text(encoding="utf-8"))
    items = raw.get("fixtures") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def source_inventory(sources: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Small JSON inventory for the classifier (no file bytes)."""
    from .collection_jobs import is_collection_creation
    from .lineage import derived_from_edges
    from .studio_sources import creation_source_modality, original_filename_for_creation

    items: list[dict[str, Any]] = []
    has_collection = False
    for src in sources or []:
        if not isinstance(src, dict):
            continue
        is_col = is_collection_creation(src)
        if is_col:
            has_collection = True
        title = str(src.get("title") or src.get("game") or "").strip()
        filename = original_filename_for_creation(src)
        row: dict[str, Any] = {
            "id": str(src.get("id") or ""),
            "title": title,
            "filename": filename,
            "modality": creation_source_modality(src),
            "isCollection": is_col,
        }
        edges = derived_from_edges(src)
        if edges:
            row["derivedFrom"] = [{"id": e["id"], "role": e["role"]} for e in edges]
        items.append(row)
    return {
        "count": len(items),
        "hasCollection": has_collection,
        "items": items,
    }


def sources_from_fixture(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn a fixture inventory row into source dicts the regex fallback understands."""
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(entry.get("sources") or []):
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("id") or f"doc_{i}")
        item: dict[str, Any] = {
            "id": sid,
            "modality": str(raw.get("modality") or "text"),
            "title": str(raw.get("title") or sid),
        }
        meta: dict[str, Any] = {}
        filename = str(raw.get("filename") or "").strip()
        if filename:
            meta["originalFilename"] = filename
        if raw.get("isCollection"):
            meta["collection"] = {
                "memberIds": [f"{sid}_m0"],
                "members": [{"id": f"{sid}_m0", "modality": "image"}],
            }
        if meta:
            item["meta"] = meta
        derived = raw.get("derivedFrom")
        if isinstance(derived, list) and derived:
            item["derivedFrom"] = derived
        out.append(item)
    return out


def build_router_user_message(prompt: str, inventory: dict[str, Any]) -> str:
    body = (prompt or "").strip()
    return (
        "Classify this Studio CREATE request. Return ONLY the JSON object.\n\n"
        f"User prompt:\n{body or '(empty)'}\n\n"
        "Source inventory (JSON):\n"
        f"{json.dumps(inventory, ensure_ascii=False, indent=2)}\n"
    )


def build_router_model_prompt(prompt: str, inventory: dict[str, Any]) -> str:
    policy = load_studio_router_prompt()
    return f"{policy.strip()}\n\n---\n\n{build_router_user_message(prompt, inventory)}"


def parse_router_payload(raw: str | None) -> dict[str, Any] | None:
    """Validate classifier JSON. Returns a normalized job dict or None."""
    if not (raw or "").strip():
        return None
    data = extract_json_object(raw)
    if not data:
        return None
    job = str(data.get("job") or "").strip().lower()
    if job not in JOB_KINDS:
        return None
    kind = str(data.get("collectionKind") or data.get("collection_kind") or "").strip().lower()
    if job == "collection":
        if kind not in COLLECTION_KINDS:
            return None
    else:
        kind = ""
    if job in MEDIA_JOBS:
        modality = job
    elif job in TEXT_JOBS:
        modality = "text"
    else:
        modality = "text"
    reason = str(data.get("reason") or "").strip()
    return {
        "job": job,
        "collectionKind": kind,
        "modality": modality,
        "reason": reason,
        "source": "llm",
    }


def fallback_classify(
    prompt: str,
    sources: list[dict[str, Any]] | None,
    *,
    basis_modality: str | None = None,
    layout_basis: bool = False,
) -> dict[str, Any]:
    """Regex / heuristic path used when Gemini is unavailable or returns junk."""
    from .collection_jobs import (
        is_collection_creation,
        plan_collection_job,
        wants_collection_job,
    )
    from .lineage import extra_sources_are_lineage_context
    from .studio_sources import (
        creation_source_modality,
        last_visual_source,
        wants_source_report,
    )

    items = [s for s in (sources or []) if isinstance(s, dict)]
    text = prompt or ""
    if not basis_modality and extra_sources_are_lineage_context(items):
        visual = last_visual_source(items)
        guessed = creation_source_modality(visual) if visual else ""
        if guessed in {"image", "video"}:
            basis_modality = guessed
    if wants_collection_job(text, items):
        has_col = any(is_collection_creation(s) for s in items)
        plan = plan_collection_job(text, has_collection=has_col)
        kind = str(plan.get("kind") or "generic_map")
        if kind not in COLLECTION_KINDS:
            kind = "generic_map"
        return {
            "job": "collection",
            "collectionKind": kind,
            "modality": "text",
            "reason": "regex collection",
            "source": "fallback",
        }

    report = wants_source_report(text, items)
    if not report and infer_layout_extract_intent(text):
        return {
            "job": "layout_extract",
            "collectionKind": "",
            "modality": "text",
            "reason": "regex layout extract",
            "source": "fallback",
        }
    if not report and infer_text_extract_intent(text):
        return {
            "job": "text_extract",
            "collectionKind": "",
            "modality": "text",
            "reason": "regex text extract",
            "source": "fallback",
        }
    if report:
        return {
            "job": "report",
            "collectionKind": "",
            "modality": "text",
            "reason": "regex report",
            "source": "fallback",
        }

    forced = resolve_generation_modality(
        text,
        basis_modality=basis_modality,
        layout_basis=layout_basis,
    )
    if forced in {"video", "image", "audio"}:
        return {
            "job": forced,
            "collectionKind": "",
            "modality": forced,
            "reason": "regex media",
            "source": "fallback",
        }
    return {
        "job": "text",
        "collectionKind": "",
        "modality": "text",
        "reason": "regex text",
        "source": "fallback",
    }


def _accept_llm_job(
    parsed: dict[str, Any],
    prompt: str,
    sources: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Drop LLM answers that cannot be executed (no sources for a report, etc.)."""
    from .collection_jobs import is_collection_creation, wants_collection_job

    items = [s for s in (sources or []) if isinstance(s, dict)]
    job = parsed.get("job")
    if job == "report" and not items:
        return None
    if job == "collection":
        has_col = any(is_collection_creation(s) for s in items)
        if has_col or wants_collection_job(prompt, items):
            return parsed
        return None
    return parsed


def _call_gemini_router(
    prompt: str,
    *,
    config: dict[str, Any] | None,
    cancel_event: Any = None,
) -> str | None:
    """HTTP hop for the classifier. Isolated so tests can stub it without a network."""
    from .cancellation import GenerationCancelled, raise_if_cancelled, run_cancellable
    from .gemini_provider import resolve_api_key, resolve_gemini_model_for_modality

    gemini_cfg = (config or {}).get("gemini") or {}
    api_key = resolve_api_key(gemini_cfg)
    if not api_key:
        return None
    model_name = resolve_gemini_model_for_modality(gemini_cfg, "text")

    def _cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    raise_if_cancelled(_cancelled)
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.debug("google-genai missing; Studio router using regex fallback")
        return None

    try:
        http_options = None
        try:
            http_options = types.HttpOptions(timeout=20_000)
        except Exception:  # noqa: BLE001
            http_options = None
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if http_options is not None:
            client_kwargs["http_options"] = http_options
        client = genai.Client(**client_kwargs)
        response = run_cancellable(
            lambda: client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            ),
            cancel_event,
        )
    except GenerationCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.info("Studio router Gemini call failed (%s); using regex fallback", exc)
        return None
    return (getattr(response, "text", None) or "").strip() or None


def ask_gemini_router(
    prompt: str,
    sources: list[dict[str, Any]] | None,
    *,
    config: dict[str, Any] | None = None,
    cancel_event: Any = None,
) -> dict[str, Any] | None:
    """Ask Gemini to classify. Never receives Settings extra_instructions."""
    inventory = source_inventory(sources)
    model_prompt = build_router_model_prompt(prompt, inventory)
    raw = _call_gemini_router(model_prompt, config=config, cancel_event=cancel_event)
    parsed = parse_router_payload(raw)
    if not parsed:
        return None
    return _accept_llm_job(parsed, prompt, sources)


def classify_studio_job(
    prompt: str,
    sources: list[dict[str, Any]] | None,
    *,
    config: dict[str, Any] | None = None,
    basis_modality: str | None = None,
    layout_basis: bool = False,
    progress: ProgressCallback | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """
    Classify a Studio CREATE into a job kind.

    Tries the project policy prompt on the text model, then regex fallback.
    Does not pass Settings extra_instructions into the classifier.
    """
    from .cancellation import GenerationCancelled, raise_if_cancelled

    def _cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    raise_if_cancelled(_cancelled)
    _emit_progress(progress, "Classifying request…", percent=4)
    try:
        parsed = ask_gemini_router(
            prompt,
            sources,
            config=config,
            cancel_event=cancel_event,
        )
    except GenerationCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.info("Studio router failed (%s); using regex fallback", exc)
        parsed = None
    if parsed and parsed.get("job") in JOB_KINDS:
        return parsed
    return fallback_classify(
        prompt,
        sources,
        basis_modality=basis_modality,
        layout_basis=layout_basis,
    )


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
        "title": "Classifying request",
    }
    if percent is not None:
        payload["percent"] = percent
    try:
        progress(payload)
    except GenerationCancelled:
        raise
    except Exception:
        logger.debug("Studio router progress callback failed", exc_info=True)
