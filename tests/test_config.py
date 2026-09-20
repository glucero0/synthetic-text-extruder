"""Basic config merge / defaults."""

import copy
from pathlib import Path

import yaml

from synthetic_text_extruder.config import (
    DEFAULTS,
    PROJECT_ROOT,
    archives_path,
    expand_path,
    is_legacy_app_token_path,
    is_legacy_gmail_token_path,
    load_config,
    normalize_exports_folder,
    normalize_google_workspace_cfg,
    normalize_lineage_pane_width,
    normalize_media_folder,
    normalize_studio_basis_width,
    normalize_ui_font_size,
    prompts_path,
    save_config,
)
from synthetic_text_extruder.creation_utils import extract_json_object
from synthetic_text_extruder.gemini_provider import normalize_gemini_model


def test_default_backend_is_gemini():
    assert DEFAULTS["backend"]["provider"] == "gemini"
    assert DEFAULTS["gemini"]["text_model"] == "gemini-2.5-flash"
    assert DEFAULTS["gemini"]["audio_model"] == "lyria-3-clip-preview"
    assert DEFAULTS["gemini"]["use_tools"] is False
    assert DEFAULTS["paths"]["exports"] == "exports"
    assert "openrouter" not in DEFAULTS
    assert "huggingface" not in DEFAULTS


def test_load_config_has_sections():
    cfg = load_config()
    assert "backend" in cfg
    assert cfg["backend"]["provider"] == "gemini"
    assert "gemini" in cfg
    assert "openrouter" not in cfg
    assert "huggingface" not in cfg
    assert "prompt" in cfg
    assert "google_workspace" in cfg
    assert "extra_instructions" in (cfg.get("prompt") or {})


def test_load_config_strips_deprecated_backends(tmp_path, monkeypatch):
    from synthetic_text_extruder import config as config_mod

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "backend:\n  provider: huggingface\n"
        "openrouter:\n  api_key: leftover\n"
        "huggingface:\n  text_model: microsoft/Phi-3.5-mini-instruct\n"
        "gemini:\n  text_model: gemini-2.5-flash\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
    cfg = load_config()
    assert cfg["backend"]["provider"] == "gemini"
    assert "openrouter" not in cfg
    assert "huggingface" not in cfg


def test_is_legacy_gmail_token_path_accepts_windows_separators():
    assert is_legacy_gmail_token_path(r"C:\data\gmail_token.json") is True
    assert is_legacy_gmail_token_path(".retro-98-ai-creator/gmail_token.json") is True
    assert is_legacy_gmail_token_path(
        ".retro-98-ai-creator/google_workspace_token.json"
    ) is False


def test_is_legacy_app_token_path():
    assert is_legacy_app_token_path(".retro-98-ai-creator/google_workspace_token.json")
    assert is_legacy_app_token_path(r".retro-98-ai-creator\gmail_token.json")
    assert is_legacy_app_token_path(".synthetic-text-extruder/google_workspace_token.json") is False


def test_normalize_google_workspace_reads_legacy_gmail():
    out = normalize_google_workspace_cfg(
        {
            "gmail": {
                "credentials_path": "C:/secrets/client.json",
                "token_path": ".retro-98-ai-creator/gmail_token.json",
            }
        }
    )
    assert out["credentials_path"] == "C:/secrets/client.json"
    assert out["token_path"] == ".synthetic-text-extruder/google_workspace_token.json"


def test_normalize_google_workspace_prefers_new_section():
    out = normalize_google_workspace_cfg(
        {
            "gmail": {"credentials_path": "C:/old.json"},
            "google_workspace": {"credentials_path": "C:/new.json"},
        }
    )
    assert out["credentials_path"] == "C:/new.json"


def test_archives_path_is_in_project():
    path = archives_path(load_config())
    assert path == (PROJECT_ROOT / "archives.json").resolve()


def test_prompts_path_is_in_project():
    path = prompts_path(load_config())
    assert path == (PROJECT_ROOT / "prompts.json").resolve()
    assert DEFAULTS["paths"]["prompts"] == "prompts.json"


def test_relative_expand_path_uses_project_root():
    assert expand_path("archives.json") == (PROJECT_ROOT / "archives.json").resolve()
    assert expand_path(str(Path.home() / "x.json")).is_absolute()


def test_normalize_media_folder_maps_project_media_to_portable():
    assert normalize_media_folder(None) == "media"
    assert normalize_media_folder("") == "media"
    assert normalize_media_folder("media") == "media"
    assert normalize_media_folder(str(PROJECT_ROOT / "media")) == "media"
    assert normalize_media_folder(str(PROJECT_ROOT / "media") + "/") == "media"


def test_normalize_exports_folder_maps_project_exports_to_portable():
    assert normalize_exports_folder(None) == "exports"
    assert normalize_exports_folder("") == "exports"
    assert normalize_exports_folder("exports") == "exports"
    assert normalize_exports_folder(str(PROJECT_ROOT / "exports")) == "exports"


def test_normalize_media_folder_keeps_other_absolute(tmp_path):
    other = (tmp_path / "custom-media").resolve()
    other.mkdir()
    assert normalize_media_folder(str(other)) == str(other)


def test_save_config_persists_gemini_api_key(tmp_path, monkeypatch):
    dest = tmp_path / "config.yaml"
    monkeypatch.setattr("synthetic_text_extruder.config.DEFAULT_CONFIG_PATH", dest)
    existing = copy.deepcopy(DEFAULTS)
    out = save_config({"gemini": {"api_key": "new-key-123"}}, existing=existing)
    assert out["gemini"]["api_key"] == "new-key-123"
    written = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert written["gemini"]["api_key"] == "new-key-123"

    out2 = save_config({"gemini": {"api_key": ""}}, existing=out)
    assert out2["gemini"]["api_key"] == "new-key-123"
    written2 = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert written2["gemini"]["api_key"] == "new-key-123"


def test_settings_html_exposes_gemini_api_key_fields():
    html = (PROJECT_ROOT / "synthetic_text_extruder" / "ui" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'id="gemini-key"' in html
    assert 'id="gemini-key-google"' in html
    assert 'id="btn-save-gemini-key"' in html
    assert 'id="btn-save-gemini-key-google"' in html


def test_settings_html_exposes_library_exports_and_lineage():
    html = (PROJECT_ROOT / "synthetic_text_extruder" / "ui" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'id="media-folder-path"' in html
    assert 'id="exports-folder-path"' in html
    assert 'id="win-lineage"' in html
    assert 'id="btn-show-lineage"' in html
    assert 'id="lineage-viewer-pane"' in html
    assert 'id="lineage-pane-splitter"' in html
    assert 'id="lineage-node-menu"' in html
    assert 'id="lineage-chain-menu"' in html
    assert 'id="lineage-search"' in html
    assert 'id="btn-lineage-open-viewer"' not in html
    assert "lineage.sqlite" in html
    assert "Library folder" in html
    assert "Exports folder" in html


def test_save_config_persists_paths_media(tmp_path, monkeypatch):
    dest = tmp_path / "config.yaml"
    monkeypatch.setattr("synthetic_text_extruder.config.DEFAULT_CONFIG_PATH", dest)
    custom = (tmp_path / "my-media").resolve()
    existing = copy.deepcopy(DEFAULTS)
    out = save_config(
        {"paths": {"media": str(custom), "media_resolved": "should-not-write"}},
        existing=existing,
    )
    assert out["paths"]["media"] == str(custom)
    assert "media_resolved" not in (out.get("paths") or {})
    written = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert written["paths"]["media"] == str(custom)
    assert "media_resolved" not in (written.get("paths") or {})

    out2 = save_config(
        {"paths": {"media": str(PROJECT_ROOT / "media")}},
        existing=existing,
    )
    written2 = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert out2["paths"]["media"] == "media"
    assert written2["paths"]["media"] == "media"


def test_save_config_persists_paths_exports(tmp_path, monkeypatch):
    dest = tmp_path / "config.yaml"
    monkeypatch.setattr("synthetic_text_extruder.config.DEFAULT_CONFIG_PATH", dest)
    custom = (tmp_path / "my-exports").resolve()
    existing = copy.deepcopy(DEFAULTS)
    out = save_config(
        {"paths": {"exports": str(custom), "exports_resolved": "should-not-write"}},
        existing=existing,
    )
    assert out["paths"]["exports"] == str(custom)
    assert "exports_resolved" not in (out.get("paths") or {})
    written = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert written["paths"]["exports"] == str(custom)
    assert "exports_resolved" not in (written.get("paths") or {})


def test_extract_json_still_works():
    assert extract_json_object('{"game": "Doom"}')["game"] == "Doom"


def test_normalize_gemini_model():
    assert normalize_gemini_model("gemini-2.5-flash") == "gemini-2.5-flash"
    assert normalize_gemini_model("") == "gemini-2.5-flash"
    assert normalize_gemini_model(None) == "gemini-2.5-flash"


def test_normalize_ui_font_size():
    assert normalize_ui_font_size(13) == 13
    assert normalize_ui_font_size(11) == 11
    assert normalize_ui_font_size(22) == 22
    assert normalize_ui_font_size(8) == 11
    assert normalize_ui_font_size(40) == 22
    assert normalize_ui_font_size("nope") == 13
    assert normalize_ui_font_size(None) == 13


def test_save_config_persists_ui_font_size(tmp_path, monkeypatch):
    dest = tmp_path / "config.yaml"
    monkeypatch.setattr("synthetic_text_extruder.config.DEFAULT_CONFIG_PATH", dest)
    existing = copy.deepcopy(DEFAULTS)
    out = save_config({"ui": {"ui_font_size": 16}}, existing=existing)
    assert out["ui"]["ui_font_size"] == 16
    written = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert written["ui"]["ui_font_size"] == 16

    out2 = save_config({"ui": {"ui_font_size": 3}}, existing=out)
    assert out2["ui"]["ui_font_size"] == 11


def test_normalize_studio_basis_width():
    assert normalize_studio_basis_width(440) == 440
    assert normalize_studio_basis_width(50) == 160
    assert normalize_studio_basis_width(9999) == 1200
    assert normalize_studio_basis_width("nope") == 280
    assert normalize_studio_basis_width(None) == 280


def test_save_config_persists_studio_basis_width(tmp_path, monkeypatch):
    dest = tmp_path / "config.yaml"
    monkeypatch.setattr("synthetic_text_extruder.config.DEFAULT_CONFIG_PATH", dest)
    existing = copy.deepcopy(DEFAULTS)
    out = save_config({"ui": {"studio_basis_width": 440}}, existing=existing)
    assert out["ui"]["studio_basis_width"] == 440
    written = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert written["ui"]["studio_basis_width"] == 440

    out2 = save_config({"ui": {"studio_basis_width": 12}}, existing=out)
    assert out2["ui"]["studio_basis_width"] == 160


def test_normalize_lineage_pane_width():
    assert normalize_lineage_pane_width(480) == 480
    assert normalize_lineage_pane_width(50) == 220
    assert normalize_lineage_pane_width(9999) == 900
    assert normalize_lineage_pane_width("nope") == 360
    assert normalize_lineage_pane_width(None) == 360


def test_save_config_persists_lineage_pane_width(tmp_path, monkeypatch):
    dest = tmp_path / "config.yaml"
    monkeypatch.setattr("synthetic_text_extruder.config.DEFAULT_CONFIG_PATH", dest)
    existing = copy.deepcopy(DEFAULTS)
    out = save_config({"ui": {"lineage_pane_width": 480}}, existing=existing)
    assert out["ui"]["lineage_pane_width"] == 480
    written = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert written["ui"]["lineage_pane_width"] == 480

    out2 = save_config({"ui": {"lineage_pane_width": 12}}, existing=out)
    assert out2["ui"]["lineage_pane_width"] == 220


def test_ui_app_theme_defaults():
    ui = DEFAULTS["ui"]
    assert ui["app_theme"] == "light"
    assert ui["ui_font"] == "inter"
    assert ui["ui_font_size"] == 13
    assert ui["studio_basis_width"] == 280
    assert ui["lineage_pane_width"] == 360
    custom = ui["custom_theme"]
    assert custom["desktop_color"] == "#008080"
    assert custom["window_color"] == "#c0c0c0"
    assert custom["title_color"] == "#000080"
    assert custom["text_color"] == "#222222"
    assert custom["font"] == "sans"


def test_load_config_preserves_app_theme_keys():
    cfg = load_config()
    ui = cfg.get("ui") or {}
    assert "app_theme" in ui
    assert "ui_font" in ui
    assert "ui_font_size" in ui
    assert ui["app_theme"] in {"light", "dark"} or isinstance(ui["app_theme"], str)
    custom = ui.get("custom_theme") or {}
    for key in (
        "desktop_color",
        "window_color",
        "title_color",
        "text_color",
        "font",
    ):
        assert key in custom
