"""Shared Google OAuth for Gmail, Drive, Docs, Calendar, and Tasks tools."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import (
    expand_path,
    is_legacy_gmail_token_path,
    load_config,
    normalize_google_workspace_cfg,
)

logger = logging.getLogger(__name__)

GMAIL_MODIFY = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
DRIVE = "https://www.googleapis.com/auth/drive"
DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"
DOCUMENTS = "https://www.googleapis.com/auth/documents"
DOCUMENTS_READONLY = "https://www.googleapis.com/auth/documents.readonly"
CALENDAR = "https://www.googleapis.com/auth/calendar"
CALENDAR_EVENTS = "https://www.googleapis.com/auth/calendar.events"
TASKS = "https://www.googleapis.com/auth/tasks"
TASKS_READONLY = "https://www.googleapis.com/auth/tasks.readonly"

# One consent covers all official Google tools. drive.readonly finds existing
# files; drive.file lets the app create files it owns.
GOOGLE_SCOPES = [
    GMAIL_MODIFY,
    DRIVE_READONLY,
    DRIVE_FILE,
    DOCUMENTS,
    CALENDAR_EVENTS,
    TASKS,
]

SCOPE_SUPERSETS: dict[str, tuple[str, ...]] = {
    GMAIL_READONLY: (GMAIL_MODIFY, GMAIL_READONLY, "https://mail.google.com/"),
    GMAIL_MODIFY: (GMAIL_MODIFY, "https://mail.google.com/"),
    DRIVE_READONLY: (DRIVE, DRIVE_READONLY),
    DRIVE_FILE: (DRIVE, DRIVE_FILE),
    DOCUMENTS_READONLY: (DOCUMENTS, DOCUMENTS_READONLY),
    DOCUMENTS: (DOCUMENTS,),
    CALENDAR_EVENTS: (CALENDAR, CALENDAR_EVENTS),
    TASKS_READONLY: (TASKS, TASKS_READONLY),
    TASKS: (TASKS,),
}

SCOPE_PRODUCTS: list[tuple[str, tuple[str, ...]]] = [
    ("Gmail", (GMAIL_MODIFY, GMAIL_READONLY, "https://mail.google.com/")),
    ("Drive", (DRIVE, DRIVE_READONLY, DRIVE_FILE)),
    ("Docs", (DOCUMENTS, DOCUMENTS_READONLY)),
    ("Calendar", (CALENDAR, CALENDAR_EVENTS)),
    ("Tasks", (TASKS, TASKS_READONLY)),
]

DEFAULT_TOKEN_REL = ".synthetic-text-extruder/google_workspace_token.json"
PREVIOUS_TOKEN_REL = ".retro-98-ai-creator/google_workspace_token.json"
LEGACY_TOKEN_REL = ".retro-98-ai-creator/gmail_token.json"
CONNECT_HINT = (
    "Google Workspace is not authorized. Open Settings → Gemini → "
    "Google Workspace and click Connect Google Workspace after saving your "
    "OAuth client JSON path."
)


def _google_section(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    return normalize_google_workspace_cfg(cfg)


def token_path(cfg: dict[str, Any] | None = None) -> Path:
    section = _google_section(cfg)
    rel = (section.get("token_path") or DEFAULT_TOKEN_REL).strip() or DEFAULT_TOKEN_REL
    if is_legacy_gmail_token_path(rel):
        rel = DEFAULT_TOKEN_REL
    return expand_path(rel)


def _legacy_token_paths() -> list[Path]:
    return [expand_path(PREVIOUS_TOKEN_REL), expand_path(LEGACY_TOKEN_REL)]


def credentials_path(cfg: dict[str, Any] | None = None) -> Path | None:
    section = _google_section(cfg)
    raw = (section.get("credentials_path") or "").strip()
    if not raw:
        return None
    return expand_path(raw)


def granted_scopes(creds: Any | None) -> list[str]:
    if creds is None:
        return []
    raw = getattr(creds, "scopes", None) or []
    out: list[str] = []
    for item in raw:
        scope = str(item).strip()
        if scope and scope not in out:
            out.append(scope)
    return out


def has_scope(creds: Any | None, required: str) -> bool:
    granted = set(granted_scopes(creds))
    if required in granted:
        return True
    return any(alt in granted for alt in SCOPE_SUPERSETS.get(required, ()))


def granted_products(creds: Any | None) -> list[str]:
    granted = set(granted_scopes(creds))
    names: list[str] = []
    for name, scopes in SCOPE_PRODUCTS:
        if any(scope in granted for scope in scopes):
            names.append(name)
    return names


def missing_requested_scopes(creds: Any | None) -> list[str]:
    return [scope for scope in GOOGLE_SCOPES if not has_scope(creds, scope)]


def _load_stored_credentials(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        from google.oauth2.credentials import Credentials

        return Credentials.from_authorized_user_file(str(path), GOOGLE_SCOPES)
    except Exception as exc:  # noqa: BLE001
        logger.info("Could not load Google token: %s", exc)
        return None


def _save_credentials(creds: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json(), encoding="utf-8")


def _refresh_credentials(creds: Any) -> Any:
    from google.auth.transport.requests import Request

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def get_google_credentials(
    cfg: dict[str, Any] | None = None,
    *,
    required_scopes: list[str] | None = None,
) -> Any | None:
    """Return valid Google credentials, refreshing the token file when needed."""
    cfg = cfg or load_config()
    path = token_path(cfg)
    creds = _load_stored_credentials(path)
    if not creds and path == expand_path(DEFAULT_TOKEN_REL):
        for legacy in _legacy_token_paths():
            if legacy == path:
                continue
            creds = _load_stored_credentials(legacy)
            if creds and getattr(creds, "valid", False):
                _save_credentials(creds, path)
                break
    if not creds:
        return None
    if not creds.valid:
        if not getattr(creds, "refresh_token", None):
            logger.info("Google token expired and no refresh token is stored.")
            return None
        try:
            creds = _refresh_credentials(creds)
        except Exception as exc:  # noqa: BLE001
            logger.info("Google token refresh failed: %s", exc)
            return None
        if creds and creds.valid:
            _save_credentials(creds, path)
    if not (creds and creds.valid):
        return None
    for scope in required_scopes or []:
        if not has_scope(creds, scope):
            return None
    return creds


def google_auth_status(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Report whether Google OAuth is configured, authorized, and which scopes landed."""
    cfg = cfg or load_config()
    creds_path = credentials_path(cfg)
    path = token_path(cfg)
    stored = _load_stored_credentials(path)
    creds = get_google_credentials(cfg)
    granted = granted_scopes(creds or stored)
    return {
        "ok": True,
        "configured": creds_path is not None and creds_path.is_file(),
        "authorized": creds is not None,
        "has_refresh_token": bool(stored and getattr(stored, "refresh_token", None)),
        "credentials_path": str(creds_path) if creds_path else "",
        "token_path": str(path),
        "requested_scopes": list(GOOGLE_SCOPES),
        "granted_scopes": granted,
        "granted_products": granted_products(creds or stored) if granted else [],
        "missing_scopes": missing_requested_scopes(creds or stored) if granted else list(GOOGLE_SCOPES),
    }


def authorize_google(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Run the desktop OAuth flow (opens the system browser).

    Requires credentials_path in config pointing to a Google OAuth client JSON file.
    Requests Gmail, Drive, Docs, Calendar, and Tasks scopes on one token.
    """
    cfg = cfg or load_config()
    creds_path = credentials_path(cfg)
    if creds_path is None:
        return {
            "ok": False,
            "error": (
                "Google Workspace OAuth client JSON path is not set. Pick "
                "credentials in Settings → Gemini → Google Workspace, then connect."
            ),
        }
    if not creds_path.is_file():
        return {
            "ok": False,
            "error": f"Google Workspace credentials file not found: {creds_path}",
        }

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        return {
            "ok": False,
            "error": (
                "google-auth-oauthlib is not installed. "
                "Run: python -m pip install google-api-python-client google-auth-oauthlib"
            ),
        }

    path = token_path(cfg)
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), GOOGLE_SCOPES)
        creds = flow.run_local_server(
            port=0,
            open_browser=True,
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        if not getattr(creds, "refresh_token", None):
            logger.warning("Google authorization did not return a refresh token.")
        _save_credentials(creds, path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Google authorization failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    products = granted_products(creds)
    missing = missing_requested_scopes(creds)
    message = "Google Workspace authorized successfully."
    if products:
        message = f"Google Workspace authorized ({', '.join(products)})."
    if missing:
        message += " Reconnect if a product you need was not granted."

    return {
        "ok": True,
        "authorized": True,
        "token_path": str(path),
        "granted_scopes": granted_scopes(creds),
        "granted_products": products,
        "missing_scopes": missing,
        "message": message,
    }


def build_google_service(
    api_name: str,
    api_version: str,
    cfg: dict[str, Any] | None = None,
    *,
    required_scopes: list[str] | None = None,
) -> Any:
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "google-api-python-client is not installed. "
            "Run: python -m pip install google-api-python-client google-auth-oauthlib"
        ) from exc

    creds = get_google_credentials(cfg)
    if creds is None:
        raise RuntimeError(CONNECT_HINT)
    for scope in required_scopes or []:
        if not has_scope(creds, scope):
            raise RuntimeError(
                f"Google Workspace token is missing {scope}. Click "
                "Connect Google Workspace in Settings to grant the updated scopes."
            )
    return build(api_name, api_version, credentials=creds, cache_discovery=False)


# Backward-compatible names used by gmail_client and existing tests.
GMAIL_SCOPES = GOOGLE_SCOPES


def get_gmail_credentials(cfg: dict[str, Any] | None = None) -> Any | None:
    return get_google_credentials(cfg)


def gmail_auth_status(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    return google_auth_status(cfg)


def authorize_gmail(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    return authorize_google(cfg)
