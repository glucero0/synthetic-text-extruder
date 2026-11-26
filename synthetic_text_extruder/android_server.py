"""Embedded localhost HTTP + JSON-RPC server for the Android WebView shell."""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import webbrowser
from collections.abc import Callable
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Android's OpenSSL 3.0 build omits the legacy provider module; tell
# `cryptography` not to abort on import when google-auth loads it.
os.environ.setdefault("CRYPTOGRAPHY_OPENSSL_NO_LEGACY", "1")

logger = logging.getLogger(__name__)

_RPC_BLOCKLIST = frozenset({"set_window", "set_ui_origin"})
_server_lock = threading.Lock()
_active_server: ThreadingHTTPServer | None = None
_active_api: Any = None
_active_origin: str | None = None
_active_token: str | None = None


class _AndroidWebBrowser(webbrowser.BaseBrowser):
    """Route Python webbrowser.open() (used by Google OAuth) to Android Custom Tabs."""

    def __init__(self, opener: Callable[[str], Any]) -> None:
        super().__init__("android-custom-tab")
        self._opener = opener

    def open(self, url: str, new: int = 0, autoraise: bool = True) -> bool:
        try:
            if hasattr(self._opener, "openUrl"):
                self._opener.openUrl(str(url))
            else:
                self._opener(str(url))
            return True
        except Exception:  # noqa: BLE001
            logger.exception("Android browser opener failed for %s", url)
            return False


def register_android_browser_opener(opener: Callable[[str], Any]) -> None:
    """Register a Kotlin/Java URL opener as Python's preferred webbrowser."""
    webbrowser.register(
        "android-custom-tab",
        None,
        _AndroidWebBrowser(opener),
        preferred=True,
    )


def _make_handler(api_bridge: Any, token: str):
    from .app import UI_DIR, _AppRequestHandler

    class _AndroidRequestHandler(_AppRequestHandler):
        ui_root: Path = UI_DIR

        def _authorized_rpc(self) -> bool:
            got = (self.headers.get("X-STE-Token") or "").strip()
            return bool(token) and secrets.compare_digest(got, token)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path).path
            if parsed in ("/", "/index.html"):
                index_file = (self.ui_root / "index.html").resolve()
                if not index_file.is_file():
                    self.send_error(404, "index.html not found")
                    return
                html = index_file.read_text(encoding="utf-8")
                boot_script = (
                    "<script>"
                    f"window.__STE_ANDROID_TOKEN__={json.dumps(token)};"
                    "window.__STE_PLATFORM__='android';"
                    "</script>"
                )
                if "</head>" in html:
                    html = html.replace("</head>", f"  {boot_script}\n</head>", 1)
                else:
                    html = boot_script + html
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path).path
            if not parsed.startswith("/api/rpc/"):
                super().do_POST()
                return
            if not self._authorized_rpc():
                self._send_json(403, {"ok": False, "error": "Unauthorized RPC request"})
                return
            method_name = parsed[len("/api/rpc/") :].strip("/")
            if (
                not method_name
                or method_name.startswith("_")
                or method_name in _RPC_BLOCKLIST
            ):
                self._send_json(404, {"ok": False, "error": f"Unknown API method: {method_name}"})
                return
            method = getattr(api_bridge, method_name, None)
            if not callable(method):
                self._send_json(404, {"ok": False, "error": f"Unknown API method: {method_name}"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length < 0 or length > 80 * 1024 * 1024:
                self._send_json(400, {"ok": False, "error": "Invalid payload size"})
                return
            try:
                raw = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(raw.decode("utf-8")) if raw else {}
                if not isinstance(payload, dict):
                    raise ValueError("Expected JSON object")
                args = payload.get("args") or []
                kwargs = payload.get("kwargs") or {}
                if not isinstance(args, list) or not isinstance(kwargs, dict):
                    raise ValueError("Invalid args/kwargs payload")
                result = method(*args, **kwargs)
                self._send_json(200, {"ok": True, "result": result})
            except Exception as exc:  # noqa: BLE001
                logger.exception("Android RPC %s failed", method_name)
                self._send_json(500, {"ok": False, "error": str(exc)})

    return _AndroidRequestHandler


def start_android_server(
    data_dir: str,
    browser_opener: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """
    Start (or reuse) the embedded localhost HTTP + RPC server for Android WebView.

    Must be called with the app's private writable ``filesDir`` path.
    """
    global _active_server, _active_api, _active_origin, _active_token

    with _server_lock:
        if browser_opener is not None:
            register_android_browser_opener(browser_opener)
        if _active_server is not None and _active_origin and _active_token:
            return {
                "ok": True,
                "origin": _active_origin,
                "url": f"{_active_origin}/index.html",
                "token": _active_token,
            }

        os.environ["SYNTHETIC_TEXT_EXTRUDER_PLATFORM"] = "android"
        if data_dir:
            root = Path(data_dir).expanduser().resolve()
            root.mkdir(parents=True, exist_ok=True)
            os.environ["SYNTHETIC_TEXT_EXTRUDER_DATA_DIR"] = str(root)

        from . import app as app_mod
        from .api import Api
        from .config import load_config
        from .media_store import media_dir

        cfg = load_config()
        token = secrets.token_urlsafe(24)
        api = Api()
        handler_cls = _make_handler(api, token)
        app_mod._api_bridge = api
        app_mod.set_media_http_root(media_dir(cfg))
        handler_cls.media_root = app_mod._AppRequestHandler.media_root
        handler_cls.fallback_media_root = app_mod._AppRequestHandler.fallback_media_root

        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        port = server.server_address[1]
        origin = f"http://127.0.0.1:{port}"
        api.set_ui_origin(origin)
        threading.Thread(
            target=server.serve_forever,
            name="ste-android-http",
            daemon=True,
        ).start()

        _active_server = server
        _active_api = api
        _active_origin = origin
        _active_token = token
        logger.info("Android embedded server ready at %s", origin)
        return {
            "ok": True,
            "origin": origin,
            "url": f"{origin}/index.html",
            "port": port,
            "token": token,
        }


def stop_android_server() -> None:
    """Cleanly stop the embedded localhost server."""
    global _active_server, _active_api, _active_origin, _active_token

    with _server_lock:
        if _active_server is not None:
            try:
                _active_server.shutdown()
                _active_server.server_close()
            except Exception:  # noqa: BLE001
                logger.debug("Error closing Android HTTP server", exc_info=True)
        _active_server = None
        _active_api = None
        _active_origin = None
        _active_token = None


def active_jobs_summary() -> dict[str, Any]:
    """Return active background job count and latest progress message for Android notifications."""
    api = _active_api
    if api is None:
        return {"active": 0, "message": ""}
    with api._jobs_lock:
        running = [
            dict(j)
            for j in api._jobs.values()
            if str(j.get("status") or "").lower() in {"queued", "running"}
        ]
    if not running:
        return {"active": 0, "message": ""}
    latest = running[-1]
    return {
        "active": len(running),
        "jobId": str(latest.get("id") or ""),
        "message": str(latest.get("message") or "Generating…"),
        "percent": latest.get("percent"),
    }


def cancel_active_jobs() -> int:
    """Cancel any currently running jobs (invoked from Android notification Cancel action)."""
    api = _active_api
    if api is None:
        return 0
    with api._jobs_lock:
        running_ids = [
            str(jid)
            for jid, j in api._jobs.items()
            if str(j.get("status") or "").lower() in {"queued", "running"}
        ]
    for jid in running_ids:
        try:
            api.cancel_job(jid)
        except Exception:  # noqa: BLE001
            logger.debug("Failed cancelling job %s", jid, exc_info=True)
    return len(running_ids)
