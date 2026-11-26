"""Runtime platform detection and capability flags (desktop vs. Android)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

PLATFORM_ENV_VAR = "SYNTHETIC_TEXT_EXTRUDER_PLATFORM"
DATA_DIR_ENV_VAR = "SYNTHETIC_TEXT_EXTRUDER_DATA_DIR"
WORKSPACE_DIR_ENV_VAR = "SYNTHETIC_TEXT_EXTRUDER_WORKSPACE_DIR"


def current_platform() -> str:
    """Return ``'android'`` when hosted in the Android shell, else ``'desktop'``."""
    raw = (os.environ.get(PLATFORM_ENV_VAR) or "").strip().lower()
    if raw == "android" or os.environ.get("ANDROID_ARGUMENT") or os.environ.get("ANDROID_PRIVATE"):
        return "android"
    return "desktop"


def is_android() -> bool:
    return current_platform() == "android"


def configured_data_dir() -> Path | None:
    """Return an explicit writable data root override when configured via env."""
    raw = (os.environ.get(DATA_DIR_ENV_VAR) or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def configured_workspace_dir() -> Path | None:
    """Return the Android-scoped folder for local file tools, if configured."""
    raw = (os.environ.get(WORKSPACE_DIR_ENV_VAR) or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def platform_capabilities() -> dict[str, Any]:
    """Capability profile exposed to the web UI during bootstrap."""
    android = is_android()
    return {
        "platform": "android" if android else "desktop",
        "isAndroid": android,
        "videoEditor": not android,
        "ffmpeg": not android,
        "powershell": not android,
        "nativeFileDialogs": not android,
        "oauthTokenImport": True,
        "oauthClientSignIn": True,
    }
