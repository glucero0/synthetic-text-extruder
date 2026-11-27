"""Self-healing Gemini retired-model detection and live replacement persistence."""

from __future__ import annotations

from synthetic_text_extruder.gemini_provider import (
    SUGGESTED_GEMINI_MODELS,
    extract_model_from_gemini_error,
    is_retired_gemini_error,
    learn_retired_gemini_model,
    merged_retired_aliases,
    normalize_gemini_model,
)


def test_detect_retired_404_message():
    err = (
        "Gemini API error: 404 NOT_FOUND. {'error': {'code': 404, "
        "'message': 'This model models/gemini-2.5-flash-lite is no longer "
        "available to new users. Please update your code to use a newer model "
        "for the latest features and improvements.', 'status': 'NOT_FOUND'}}"
    )
    assert is_retired_gemini_error(err)
    assert extract_model_from_gemini_error(err) == "gemini-2.5-flash-lite"


def test_detect_ignores_unrelated_errors():
    assert not is_retired_gemini_error("HTTP 400: bad request")
    assert not is_retired_gemini_error("network timeout")


def test_learn_retired_picks_live_replacement_or_clears_slot(tmp_path, monkeypatch):
    from synthetic_text_extruder import config as config_mod

    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(
        "synthetic_text_extruder.gemini_provider.list_available_gemini_models",
        lambda _key, retired_aliases=None: [
            {"repo_id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash", "modality": "text"},
            {"repo_id": "veo-3.1-generate-preview", "label": "Veo 3.1", "modality": "video"},
        ],
    )
    cfg = {
        "backend": {"provider": "gemini"},
        "gemini": {
            "api_key": "test-key",
            "text_model": "gemini-mystery-flash",
            "image_model": "gemini-2.5-flash-image",
            "video_model": "veo-2.0-generate-001",
            "retired_model_aliases": {},
        },
        "ui": {},
        "paths": {"archives": str(tmp_path / "archives.json")},
        "prompt": {},
    }

    info = learn_retired_gemini_model(cfg, "gemini-mystery-flash")
    assert info["retired"] == "gemini-mystery-flash"
    assert info["switched"] is True
    assert info["replacement"] == "gemini-3.5-flash"
    assert info["config"]["gemini"]["text_model"] == "gemini-3.5-flash"
    assert (
        info["config"]["gemini"]["retired_model_aliases"]["gemini-mystery-flash"]
        == "gemini-3.5-flash"
    )

    aliases = merged_retired_aliases(info["config"]["gemini"])
    assert (
        normalize_gemini_model("gemini-mystery-flash", retired_aliases=aliases)
        == "gemini-3.5-flash"
    )


def test_merged_aliases_learned_override_builtin():
    cfg = {
        "retired_model_aliases": {
            "gemini-2.5-flash-lite": "gemini-3.5-flash-lite",
        }
    }
    aliases = merged_retired_aliases(cfg)
    assert aliases["gemini-2.5-flash-lite"] == "gemini-3.5-flash-lite"


def test_no_static_suggested_models_list():
    assert SUGGESTED_GEMINI_MODELS == []


def test_bootstrap_never_returns_static_models_and_keeps_saved_slots(tmp_path, monkeypatch):
    import synthetic_text_extruder.api as api_mod
    from synthetic_text_extruder.api import Api

    cfg = {
        "backend": {"provider": "gemini"},
        "gemini": {
            "text_model": "gemini-3.5-flash",
            "image_model": "gemini-3.1-flash-image-preview",
            "video_model": "veo-3.1-fast-generate-preview",
            "retired_model_aliases": {"gemini-mystery-flash": "gemini-3.5-flash"},
        },
        "ui": {},
        "paths": {"archives": str(tmp_path / "archives.json")},
        "prompt": {},
    }
    monkeypatch.setattr(api_mod, "load_config", lambda: cfg)
    api = Api()
    api.config = cfg
    boot = api.get_bootstrap()
    assert "gemini-mystery-flash" in boot["retiredGeminiModels"]
    assert boot["suggestedGeminiModels"] == []
    assert boot["config"]["gemini"]["video_model"] == "veo-3.1-fast-generate-preview"
