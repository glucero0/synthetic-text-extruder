"""Tests for dynamic live-only Control Panel Recommend Models ranking."""

from __future__ import annotations

import pytest

from synthetic_text_extruder.recommend_models import (
    _by_modality,
    _pick_from_prefs,
    normalize_criteria,
    recommend_models_for_config,
)

LIVE_CATALOG_SAMPLE = [
    {"repo_id": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash-Lite", "modality": "text"},
    {"repo_id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash", "modality": "text"},
    {"repo_id": "gemini-3.5-pro", "label": "Gemini 3.5 Pro", "modality": "text"},
    {"repo_id": "gemini-2.5-flash-image", "label": "Gemini 2.5 Flash Image", "modality": "image"},
    {"repo_id": "imagen-4.0-generate-001", "label": "Imagen 4", "modality": "image"},
    {"repo_id": "veo-3.1-fast-generate-preview", "label": "Veo 3.1 Fast", "modality": "video"},
    {"repo_id": "veo-3.1-generate-preview", "label": "Veo 3.1", "modality": "video"},
    {"repo_id": "lyria-3-clip-preview", "label": "Lyria 3 Clip", "modality": "audio"},
    {"repo_id": "lyria-3.5", "label": "Lyria 3.5", "modality": "audio"},
]


def test_normalize_criteria_aliases():
    assert normalize_criteria("Economical") == "economical"
    assert normalize_criteria("cheapest") == "economical"
    assert normalize_criteria("best free") == "economical"
    assert normalize_criteria("Balanced") == "balanced"
    assert normalize_criteria("recommended") == "balanced"
    assert normalize_criteria("Maximum quality") == "quality"
    assert normalize_criteria("highest quality") == "quality"
    with pytest.raises(ValueError):
        normalize_criteria("nope")


def test_pick_from_prefs_prefers_listed_id():
    rows = [
        {"repo_id": "gemini-2.5-flash", "label": "Flash", "modality": "text"},
        {"repo_id": "gemini-3.1-flash-lite", "label": "Lite", "modality": "text"},
        {"repo_id": "gemini-2.5-pro", "label": "Pro", "modality": "text"},
    ]
    picked = _pick_from_prefs(rows, ("gemini-3.1-flash-lite", "gemini-2.5-flash"))
    assert picked["repo_id"] == "gemini-3.1-flash-lite"


def test_recommend_requires_api_key_never_static_fallback():
    cfg = {"backend": {"provider": "gemini"}, "gemini": {}}
    res = recommend_models_for_config(cfg, "balanced", provider="gemini")
    assert res["ok"] is False
    assert res["models"] == []


def test_recommend_gemini_dynamic_tiers_from_live_catalog(monkeypatch):
    monkeypatch.setattr(
        "synthetic_text_extruder.gemini_provider.list_available_gemini_models",
        lambda _key, retired_aliases=None: list(LIVE_CATALOG_SAMPLE),
    )
    cfg = {"backend": {"provider": "gemini"}, "gemini": {"api_key": "live-key"}}

    econ = recommend_models_for_config(cfg, "economical")
    assert econ["ok"] is True
    assert econ["picks"]["text"] == "gemini-3.1-flash-lite"
    assert econ["picks"]["video"] == "veo-3.1-fast-generate-preview"
    assert econ["picks"]["audio"] == "lyria-3-clip-preview"

    bal = recommend_models_for_config(cfg, "balanced")
    assert bal["ok"] is True
    assert bal["picks"]["text"] == "gemini-3.5-flash"
    assert bal["picks"]["video"] == "veo-3.1-generate-preview"
    mods = _by_modality(bal["models"])
    assert any(m["repo_id"] == bal["picks"]["text"] for m in mods["text"])

    qual = recommend_models_for_config(cfg, "quality", provider="openrouter")
    assert qual["ok"] is True
    assert qual["provider"] == "gemini"
    assert qual["picks"]["text"] == "gemini-3.5-pro"
    assert qual["picks"]["image"] == "imagen-4.0-generate-001"
    assert qual["picks"]["video"] == "veo-3.1-generate-preview"
    assert qual["picks"]["audio"] == "lyria-3.5"
