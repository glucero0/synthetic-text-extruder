"""Gemini modality model resolution (no hardcoded model defaults)."""

from synthetic_text_extruder.gemini_provider import (
    ensure_gemini_model_for_modality,
    resolve_gemini_model_for_modality,
)


def test_resolve_gemini_modality_slots():
    cfg = {
        "text_model": "gemini-2.5-pro",
        "image_model": "gemini-3.1-flash-image-preview",
        "video_model": "veo-3.1-generate-preview",
        "audio_model": "lyria-3.5",
    }
    assert resolve_gemini_model_for_modality(cfg, "text") == "gemini-2.5-pro"
    assert (
        resolve_gemini_model_for_modality(cfg, "image")
        == "gemini-3.1-flash-image-preview"
    )
    assert resolve_gemini_model_for_modality(cfg, "video") == "veo-3.1-generate-preview"
    assert resolve_gemini_model_for_modality(cfg, "audio") == "lyria-3.5"


def test_resolve_gemini_empty_when_unconfigured():
    assert resolve_gemini_model_for_modality({}, "text") == ""
    assert resolve_gemini_model_for_modality({}, "image") == ""
    assert resolve_gemini_model_for_modality({}, "video") == ""
    assert resolve_gemini_model_for_modality({}, "audio") == ""


def test_resolve_gemini_clears_retired_models_and_honors_learned_replacement():
    assert resolve_gemini_model_for_modality({"text_model": "gemini-2.0-flash-lite"}, "text") == ""
    assert resolve_gemini_model_for_modality({"video_model": "veo-2.0-generate-001"}, "video") == ""
    cfg_custom = {
        "text_model": "gemini-old-flash",
        "retired_model_aliases": {"gemini-old-flash": "gemini-3.5-flash"},
    }
    assert resolve_gemini_model_for_modality(cfg_custom, "text") == "gemini-3.5-flash"


def test_ensure_gemini_model_queries_live_catalog_when_slot_empty(monkeypatch):
    monkeypatch.setattr(
        "synthetic_text_extruder.gemini_provider.list_available_gemini_models",
        lambda _key, retired_aliases=None: [
            {"repo_id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash", "modality": "text"},
            {"repo_id": "veo-3.1-generate-preview", "label": "Veo 3.1", "modality": "video"},
        ],
    )
    assert ensure_gemini_model_for_modality({"api_key": "test-key"}, "text") == "gemini-3.5-flash"
    assert ensure_gemini_model_for_modality({"api_key": "test-key"}, "video") == "veo-3.1-generate-preview"
