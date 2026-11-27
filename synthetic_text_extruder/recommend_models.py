"""Recommend Text / Image / Video / Audio models from Google's live catalog."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

CRITERIA = ("economical", "balanced", "quality")

_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?")


def normalize_criteria(value: str | None) -> str:
    raw = (value or "").strip().lower()
    aliases = {
        "economical": "economical",
        "economy": "economical",
        "budget": "economical",
        "cheap": "economical",
        "cheapest": "economical",
        "free": "economical",
        "best free": "economical",
        "best_free": "economical",
        "best-free": "economical",
        "lowest cost": "economical",
        "balanced": "balanced",
        "balance": "balanced",
        "recommended": "balanced",
        "everyday": "balanced",
        "quality": "quality",
        "maximum quality": "quality",
        "maximum_quality": "quality",
        "highest quality": "quality",
        "highest_quality": "quality",
        "premium": "quality",
        "best": "quality",
    }
    out = aliases.get(raw) or aliases.get(raw.replace(" ", "_"))
    if out not in CRITERIA:
        raise ValueError(
            "criteria must be one of: economical, balanced, quality (maximum quality)."
        )
    return out


def _extract_version(model_id: str) -> tuple[int, int]:
    """Extract highest (major, minor) generation version token from a model id."""
    best = (0, 0)
    for m in _VERSION_RE.finditer(model_id or ""):
        maj = int(m.group(1))
        # Ignore 8-digit date stamps like 20250617 or 3-digit revision suffixes like 001
        if maj > 20 or (m.group(2) is None and len(m.group(1)) >= 3):
            continue
        minor = int(m.group(2)) if m.group(2) is not None else 0
        if (maj, minor) > best:
            best = (maj, minor)
    return best


def _score_live_model(item: dict[str, str], modality: str, criteria: str) -> tuple:
    """Return a comparable tuple (higher is better) for dynamic live model selection."""
    mid = str(item.get("repo_id") or "").strip().lower()
    ver = _extract_version(mid)
    is_lite = "lite" in mid or "nano" in mid
    is_fast = "fast" in mid
    is_clip = "clip" in mid
    is_flash = "flash" in mid and not is_lite
    is_pro = "pro" in mid
    is_ultra = "ultra" in mid
    is_exp = "-exp" in mid or mid.endswith("exp")
    is_latest_alias = mid.endswith("-latest")
    stability = 0 if is_exp else (1 if is_latest_alias else 2)

    if criteria == "economical":
        if modality == "text":
            tier = 3 if is_lite else (2 if is_flash else (1 if not is_pro and not is_ultra else 0))
        elif modality == "image":
            tier = 3 if (is_fast or is_lite or "flash-image" in mid) else (2 if not is_ultra and not is_pro else 1)
        elif modality == "video":
            tier = 3 if is_fast else (2 if not is_ultra and not is_pro else 1)
        else:  # audio
            tier = 3 if (is_clip or is_lite or is_fast) else 2
        return (tier, ver, stability, mid)

    if criteria == "quality":
        if modality == "text":
            tier = 4 if is_ultra else (3 if is_pro else (2 if is_flash else 1))
        elif modality == "image":
            tier = 4 if is_ultra else (3 if (is_pro or "imagen" in mid) else (2 if "flash-image" in mid else 1))
        elif modality == "video":
            tier = 4 if is_ultra else (3 if not is_fast else 2)
        else:  # audio
            tier = 3 if not is_clip else 1
        return (ver if modality in {"image", "video"} else (tier,), tier, ver, stability, mid)

    # balanced
    if modality == "text":
        tier = 4 if (is_flash and not is_pro) else (3 if is_pro else (2 if is_lite else 1))
    elif modality == "image":
        tier = 4 if ("flash-image" in mid and not is_ultra) else (3 if not is_ultra else 2)
    elif modality == "video":
        tier = 4 if (not is_fast and not is_ultra) else (3 if is_fast else 2)
    else:  # audio
        tier = 3 if not is_clip else 2
    return (tier, ver, stability, mid)


def _by_modality(models: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {
        "text": [],
        "image": [],
        "video": [],
        "audio": [],
    }
    for item in models:
        mod = str(item.get("modality") or "text").lower()
        if mod in out:
            out[mod].append(item)
    return out


def _pick_from_prefs(
    available: list[dict[str, str]],
    prefs: tuple[str, ...],
) -> dict[str, str] | None:
    ids = {str(m.get("repo_id") or "").strip(): m for m in available}
    lower_map = {k.lower(): v for k, v in ids.items()}
    for pref in prefs:
        if pref in ids:
            return ids[pref]
        hit = lower_map.get(pref.lower())
        if hit:
            return hit
        for mid, row in ids.items():
            if pref.lower() in mid.lower():
                return row
    return available[0] if available else None


def _pick_best_live_model(
    available: list[dict[str, str]],
    modality: str,
    criteria: str,
) -> dict[str, str] | None:
    if not available:
        return None
    return max(available, key=lambda item: _score_live_model(item, modality, criteria))


def recommend_models_for_config(
    config: dict[str, Any],
    criteria: str,
    *,
    provider: str | None = None,
    live_models: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Fetch Gemini's live catalog and pick Text / Image / Video / Audio models dynamically.

    Never falls back to a static list of models.
    """
    from .gemini_provider import (
        list_available_gemini_models,
        merged_retired_aliases,
        normalize_gemini_model,
        resolve_api_key,
    )

    crit = normalize_criteria(criteria)
    _ = provider
    gemini_cfg = (config or {}).get("gemini") or {}
    aliases = merged_retired_aliases(gemini_cfg)

    if live_models is not None:
        models = [
            m
            for m in live_models
            if (m.get("repo_id") or "").lower() not in {k.lower() for k in aliases}
        ]
    else:
        key = resolve_api_key(gemini_cfg)
        if not key:
            return {
                "ok": False,
                "provider": "gemini",
                "criteria": crit,
                "error": "Save your Gemini API key first so the app can fetch Google's live model catalog.",
                "models": [],
                "picks": {},
                "labels": {},
                "availableModalities": [],
            }
        models = list_available_gemini_models(key, retired_aliases=aliases)

    buckets = _by_modality(models)
    available_modalities = [mod for mod in ("text", "image", "video", "audio") if buckets[mod]]
    picks: dict[str, str] = {}
    labels: dict[str, str] = {}
    for mod in ("text", "image", "video", "audio"):
        row = _pick_best_live_model(buckets[mod], mod, crit)
        mid = normalize_gemini_model(
            (row or {}).get("repo_id") or "",
            retired_aliases=aliases,
        )
        picks[mod] = mid
        labels[mod] = str((row or {}).get("label") or mid) if mid else ""

    return {
        "ok": True,
        "provider": "gemini",
        "criteria": crit,
        "source": "live",
        "picks": picks,
        "labels": labels,
        "models": models,
        "availableModalities": available_modalities,
        "message": _summary_message("Gemini", crit, labels),
    }


def _summary_message(provider: str, criteria: str, labels: dict[str, str]) -> str:
    pretty = {
        "economical": "Economical",
        "balanced": "Balanced",
        "quality": "Maximum quality",
    }.get(criteria, criteria)
    return (
        f"{provider} · {pretty}: "
        f"text {labels.get('text') or '—'}, "
        f"image {labels.get('image') or '—'}, "
        f"video {labels.get('video') or '—'}"
        + (
            f", audio {labels.get('audio') or '—'}"
            if labels.get("audio")
            else ""
        )
    )
