"""Configuration loading and persistence."""

from __future__ import annotations

import copy
import os
import threading
import uuid
from pathlib import Path
from typing import Any

import yaml

from .platform_env import configured_data_dir

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = configured_data_dir() or PACKAGE_ROOT.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
EXAMPLE_CONFIG_PATH = PACKAGE_ROOT.parent / "config.example.yaml"

_INITIAL_PROJECT_ROOT = PROJECT_ROOT
_INITIAL_CONFIG_PATH = DEFAULT_CONFIG_PATH
_CONFIG_LOCK = threading.RLock()

# Model slots start empty until selected via live catalog / tier recommendation.
DEFAULT_GEMINI_TEXT_MODEL = ""
DEFAULT_GEMINI_IMAGE_MODEL = ""
DEFAULT_GEMINI_VIDEO_MODEL = ""
DEFAULT_GEMINI_AUDIO_MODEL = ""

_DEPRECATED_BACKENDS = frozenset(
    {
        "openrouter",
        "open-router",
        "or",
        "huggingface",
        "hf",
        "local",
        "phi",
    }
)

DEFAULTS: dict[str, Any] = {
    "backend": {
        "provider": "gemini",
    },
    "gemini": {
        "text_model": "",
        "image_model": "",
        "video_model": "",
        "audio_model": "",
        "audio_unavailable": False,
        "api_key": None,  # set via Control Panel → saved in config.yaml
        "google_search": True,
        # When google_search is on: Pass 1 extract + Pass 2 verify at temperature 0
        "two_pass_verify": True,
        # Local file tools via Gemini function calling (can combine with google_search)
        "use_tools": False,
        # When google_search is on: OCR images / YouTube captions from cited search results
        "ocr_search_images": True,
        "youtube_search_captions": True,
        "temperature": 0.0,
        # Runtime-learned: { "old-model-id": "replacement-id" } merged with built-ins
        "retired_model_aliases": {},
    },
    "prompt": {
        # Appended to generation prompts (Control Panel → Extra system instructions).
        # Not used by the Studio job classifier (report vs video vs extract).
        "extra_instructions": "",
    },
    "ui": {
        "sound_enabled": True,
        "sound_volume": 100,
        "crt_enabled": False,
        "ui_scale": 1.0,
        "ui_font": "inter",
        "ui_font_size": 13,
        "app_theme": "light",
        "custom_theme": {
            "desktop_color": "#008080",
            "window_color": "#c0c0c0",
            "title_color": "#000080",
            "text_color": "#222222",
            "font": "sans",
        },
        "window_width": 1280,
        "window_height": 800,
        "studio_basis_width": 280,
        "lineage_pane_width": 360,
        "title": "Synthetic Text Extruder",
    },
    "paths": {
        # Relative paths resolve against the project root
        "archives": "archives.json",
        "media": "media",
        "exports": "exports",
        "prompts": "prompts.json",
    },
    "google_workspace": {
        # OAuth client JSON from Google Cloud (Desktop app) — set via Control Panel
        "credentials_path": None,
        # Authorized-user token (gitignored). Default path keeps older Gmail tokens.
        "token_path": ".synthetic-text-extruder/google_workspace_token.json",
    },
}

STUDIO_BASIS_WIDTH_MIN = 160
STUDIO_BASIS_WIDTH_MAX = 1200
STUDIO_BASIS_WIDTH_DEFAULT = 280
LINEAGE_PANE_WIDTH_MIN = 220
LINEAGE_PANE_WIDTH_MAX = 900
LINEAGE_PANE_WIDTH_DEFAULT = 360
UI_FONT_SIZE_MIN = 11
UI_FONT_SIZE_MAX = 22
UI_FONT_SIZE_DEFAULT = 13


def _active_project_root() -> Path:
    if PROJECT_ROOT != _INITIAL_PROJECT_ROOT:
        return PROJECT_ROOT
    return configured_data_dir() or PROJECT_ROOT


def _active_config_path() -> Path:
    if DEFAULT_CONFIG_PATH != _INITIAL_CONFIG_PATH:
        return DEFAULT_CONFIG_PATH
    return _active_project_root() / "config.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def expand_path(path_str: str) -> Path:
    """Resolve ~ and relative paths (relative → project root)."""
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = _active_project_root() / p
    return p.resolve()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config at {path} must be a mapping")
    return data


def _coerce_gemini_backend(cfg: dict[str, Any]) -> None:
    """Ignore retired OpenRouter / Hugging Face backends from older config files."""
    backend = cfg.setdefault("backend", {})
    if not isinstance(backend, dict):
        cfg["backend"] = {"provider": "gemini"}
        return
    prov = str(backend.get("provider") or "gemini").lower().strip()
    if prov in _DEPRECATED_BACKENDS or prov not in ("gemini", "google", "google-gemini"):
        backend["provider"] = "gemini"
    else:
        backend["provider"] = "gemini"
    cfg.pop("openrouter", None)
    cfg.pop("huggingface", None)


def normalize_gemini_cfg(section: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize Gemini keys and clear/remap shut-down model ids without hardcoded defaults."""
    from .gemini_provider import (
        learned_retired_aliases,
        merged_retired_aliases,
        normalize_gemini_model,
    )

    out = dict(section or {})
    raw_key = (out.get("api_key") or "").strip()
    out["api_key"] = raw_key or None
    aliases = merged_retired_aliases(out)
    for slot in ("text_model", "image_model", "video_model", "audio_model"):
        raw_val = str(out.get(slot) or "").strip()
        out[slot] = normalize_gemini_model(raw_val, retired_aliases=aliases) if raw_val else ""
    out["audio_unavailable"] = bool(out.get("audio_unavailable", False))
    out["retired_model_aliases"] = learned_retired_aliases(out)
    return out


def load_config() -> dict[str, Any]:
    """Merge defaults ← config.yaml ← optional config.local.yaml (thread-safe)."""
    with _CONFIG_LOCK:
        cfg = copy.deepcopy(DEFAULTS)
        cfg_path = _active_config_path()
        local_path = cfg_path.parent / "config.local.yaml"

        for path in (cfg_path, local_path):
            cfg = _deep_merge(cfg, _load_yaml(path))

        _coerce_gemini_backend(cfg)
        cfg["gemini"] = normalize_gemini_cfg(cfg.get("gemini"))
        cfg["google_workspace"] = normalize_google_workspace_cfg(cfg)

        paths = cfg.setdefault("paths", {})
        if not paths.get("archives"):
            paths["archives"] = DEFAULTS["paths"]["archives"]
        paths["media"] = normalize_media_folder(paths.get("media"))
        paths["exports"] = normalize_exports_folder(paths.get("exports"))
        if not paths.get("prompts"):
            paths["prompts"] = DEFAULTS["paths"]["prompts"]
        ui = cfg.setdefault("ui", {})
        if isinstance(ui, dict):
            ui["studio_basis_width"] = normalize_studio_basis_width(
                ui.get("studio_basis_width")
            )
            ui["lineage_pane_width"] = normalize_lineage_pane_width(
                ui.get("lineage_pane_width")
            )
            ui["ui_font_size"] = normalize_ui_font_size(ui.get("ui_font_size"))
        return cfg


def is_legacy_gmail_token_path(rel: str) -> bool:
    """True for gmail_token.json even when the path uses Windows backslashes."""
    return Path(str(rel).replace("\\", "/")).name == "gmail_token.json"


def is_legacy_app_token_path(rel: str) -> bool:
    """True for tokens stored under the pre-rename app folder."""
    posix = Path(str(rel).replace("\\", "/")).as_posix()
    return posix == ".retro-98-ai-creator" or posix.startswith(".retro-98-ai-creator/")


def _is_bogus_credentials_path(raw: str | None) -> bool:
    text = str(raw or "").strip()
    if not text:
        return False
    if text == "Stored in app vault":
        return True
    name = Path(text.replace("\\", "/")).name.lower()
    return name in {"google_workspace_token.json", "gmail_token.json"}


def normalize_google_workspace_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Prefer google_workspace; copy leftover gmail: keys if needed."""
    cfg = cfg or {}
    workspace = dict(cfg.get("google_workspace") or {})
    legacy = dict(cfg.get("gmail") or {})
    if not (workspace.get("credentials_path") or "").strip() and (
        legacy.get("credentials_path") or ""
    ).strip():
        workspace["credentials_path"] = legacy.get("credentials_path")
    if not (workspace.get("token_path") or "").strip() and (
        legacy.get("token_path") or ""
    ).strip():
        workspace["token_path"] = legacy.get("token_path")
    workspace.setdefault(
        "token_path", DEFAULTS["google_workspace"]["token_path"]
    )
    token_rel = str(workspace.get("token_path") or "")
    if is_legacy_gmail_token_path(token_rel) or is_legacy_app_token_path(token_rel):
        workspace["token_path"] = DEFAULTS["google_workspace"]["token_path"]
    cred_raw = workspace.get("credentials_path")
    if cred_raw == "" or _is_bogus_credentials_path(cred_raw):
        default_client = expand_path(".synthetic-text-extruder/google_oauth_client.json")
        workspace["credentials_path"] = (
            ".synthetic-text-extruder/google_oauth_client.json"
            if default_client.is_file()
            else None
        )
    return workspace


def _apply_api_key_update(updates: dict[str, Any], section: str) -> None:
    """Blank api_key fields mean keep the existing key (do not clear)."""
    section_updates = updates.get(section)
    if not isinstance(section_updates, dict):
        return
    incoming = (section_updates.get("api_key") or "").strip()
    section_updates = dict(section_updates)
    if incoming:
        section_updates["api_key"] = incoming
    else:
        section_updates.pop("api_key", None)
    updates[section] = section_updates


def save_config(updates: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Atomically persist Control Panel changes to config.yaml (thread-safe)."""
    with _CONFIG_LOCK:
        cfg_path = _active_config_path()
        if cfg_path.is_file():
            disk_cfg = load_config()
            if existing:
                # Start from existing, then overlay disk_cfg so a stale in-memory
                # snapshot on another thread never wipes a saved API key or setting.
                current = _deep_merge(copy.deepcopy(existing), disk_cfg)
                if not current.get("gemini", {}).get("api_key") and (
                    (existing.get("gemini") or {}).get("api_key")
                ):
                    current["gemini"]["api_key"] = existing["gemini"]["api_key"]
            else:
                current = disk_cfg
        else:
            current = copy.deepcopy(existing) if existing else load_config()

        updates_copy = copy.deepcopy(updates)
        _apply_api_key_update(updates_copy, "gemini")
        # Prevent a blank/token-path credentials_path from wiping an imported client JSON
        gw_upd = updates_copy.get("google_workspace")
        if isinstance(gw_upd, dict) and "credentials_path" in gw_upd:
            raw_cred = gw_upd.get("credentials_path")
            if _is_bogus_credentials_path(raw_cred):
                gw_upd = dict(gw_upd)
                gw_upd.pop("credentials_path", None)
                updates_copy["google_workspace"] = gw_upd

        merged = _deep_merge(current, updates_copy)
        _coerce_gemini_backend(merged)
        paths = merged.setdefault("paths", {})
        paths.pop("media_resolved", None)
        paths.pop("exports_resolved", None)
        paths["media"] = normalize_media_folder(paths.get("media"))
        paths["exports"] = normalize_exports_folder(paths.get("exports"))
        ui_out = dict(merged.get("ui") or {})
        ui_out["studio_basis_width"] = normalize_studio_basis_width(
            ui_out.get("studio_basis_width")
        )
        ui_out["lineage_pane_width"] = normalize_lineage_pane_width(
            ui_out.get("lineage_pane_width")
        )
        ui_out["ui_font_size"] = normalize_ui_font_size(ui_out.get("ui_font_size"))

        gemini_out = normalize_gemini_cfg(merged.get("gemini") or {})
        prompt_out = dict(merged.get("prompt") or {})
        prompt_out.setdefault("extra_instructions", "")
        workspace_out = normalize_google_workspace_cfg(merged)

        to_write = {
            "backend": {"provider": "gemini"},
            "gemini": gemini_out,
            "prompt": prompt_out,
            "google_workspace": workspace_out,
            "ui": ui_out,
            "paths": {
                "archives": paths.get("archives") or DEFAULTS["paths"]["archives"],
                "media": paths.get("media") or DEFAULTS["paths"]["media"],
                "exports": paths.get("exports") or DEFAULTS["paths"]["exports"],
                "prompts": paths.get("prompts") or DEFAULTS["paths"]["prompts"],
            },
        }
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cfg_path.with_name(f".{cfg_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as fh:
                yaml.safe_dump(to_write, fh, default_flow_style=False, sort_keys=False)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            os.replace(tmp_path, cfg_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

        merged["backend"] = {"provider": "gemini"}
        merged["gemini"] = gemini_out
        merged["prompt"] = prompt_out
        merged["google_workspace"] = workspace_out
        merged.pop("gmail", None)
        merged.pop("openrouter", None)
        merged.pop("huggingface", None)
        merged["ui"] = ui_out
        return merged


def normalize_ui_font_size(raw: Any) -> int:
    """Clamp Appearance UI font size (px) for config I/O."""
    try:
        value = int(round(float(raw)))
    except (TypeError, ValueError):
        return UI_FONT_SIZE_DEFAULT
    return max(UI_FONT_SIZE_MIN, min(UI_FONT_SIZE_MAX, value))


def normalize_studio_basis_width(raw: Any) -> int:
    """Clamp Creation Studio Media basis pane width (px) for config I/O."""
    try:
        value = int(round(float(raw)))
    except (TypeError, ValueError):
        return STUDIO_BASIS_WIDTH_DEFAULT
    return max(STUDIO_BASIS_WIDTH_MIN, min(STUDIO_BASIS_WIDTH_MAX, value))


def normalize_lineage_pane_width(raw: Any) -> int:
    """Clamp Lineage viewer pane width (px) for config I/O."""
    try:
        value = int(round(float(raw)))
    except (TypeError, ValueError):
        return LINEAGE_PANE_WIDTH_DEFAULT
    return max(LINEAGE_PANE_WIDTH_MIN, min(LINEAGE_PANE_WIDTH_MAX, value))


def _normalize_project_folder(raw: str | None, default: str) -> str:
    """Return a portable default folder name or an absolute folder path."""
    root = _active_project_root()
    text = str(raw or "").strip() or default
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        resolved = path.resolve()
    except OSError:
        return text
    default_resolved = (root / default).resolve()
    if resolved == default_resolved:
        return default
    return str(resolved)


def normalize_media_folder(raw: str | None) -> str:
    """Return a portable default (`media`) or an absolute folder path."""
    return _normalize_project_folder(raw, DEFAULTS["paths"]["media"])


def normalize_exports_folder(raw: str | None) -> str:
    """Return a portable default (`exports`) or an absolute folder path."""
    return _normalize_project_folder(raw, DEFAULTS["paths"]["exports"])


def archives_path(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    return expand_path(cfg["paths"]["archives"])


def media_path(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    return expand_path(
        normalize_media_folder((cfg.get("paths") or {}).get("media"))
    )


def exports_path(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    return expand_path(
        normalize_exports_folder((cfg.get("paths") or {}).get("exports"))
    )


def prompts_path(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg or load_config()
    return expand_path(cfg["paths"].get("prompts") or DEFAULTS["paths"]["prompts"])
