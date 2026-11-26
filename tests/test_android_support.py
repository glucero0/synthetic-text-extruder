"""Tests for Android platform profile, dual OAuth JSON import, and HTTP RPC bridge."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request

from synthetic_text_extruder import android_server, config, gemini_tools, google_auth, platform_env
from synthetic_text_extruder.api import Api
from synthetic_text_extruder.storage import ArchiveStore


def test_platform_capabilities_desktop_vs_android(monkeypatch):
    monkeypatch.delenv(platform_env.PLATFORM_ENV_VAR, raising=False)
    monkeypatch.delenv("ANDROID_ARGUMENT", raising=False)
    monkeypatch.delenv("ANDROID_PRIVATE", raising=False)
    desk = platform_env.platform_capabilities()
    assert desk["platform"] == "desktop"
    assert desk["isAndroid"] is False
    assert desk["videoEditor"] is True
    assert desk["powershell"] is True

    monkeypatch.setenv(platform_env.PLATFORM_ENV_VAR, "android")
    mob = platform_env.platform_capabilities()
    assert mob["platform"] == "android"
    assert mob["isAndroid"] is True
    assert mob["videoEditor"] is False
    assert mob["powershell"] is False
    assert mob["oauthTokenImport"] is True
    assert mob["oauthClientSignIn"] is True


def test_android_hides_powershell_tool_and_scopes_relative_paths(monkeypatch, tmp_path):
    monkeypatch.setenv(platform_env.PLATFORM_ENV_VAR, "android")
    monkeypatch.setenv(platform_env.WORKSPACE_DIR_ENV_VAR, str(tmp_path / "ws"))

    aliases = [t["alias"] for t in gemini_tools.list_tool_catalog()]
    assert "execute_powershell" not in aliases
    assert "search_gmail" in aliases
    assert gemini_tools.normalize_tool_aliases(["execute_powershell", "write_text"]) == ["write_text"]

    write_res = gemini_tools.execute_tool("write_text", {"path": "notes.txt", "text": "hello phone"})
    assert write_res["ok"] is True
    read_res = gemini_tools.execute_tool("read_text", {"path": "notes.txt"})
    assert read_res["ok"] is True
    assert read_res["text"] == "hello phone"

    escape_res = gemini_tools.execute_tool("write_text", {"path": "../outside.txt", "text": "nope"})
    assert escape_res["ok"] is False


def test_classify_and_import_oauth_client_and_token_json(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")

    client_payload = {
        "installed": {
            "client_id": "12345.apps.googleusercontent.com",
            "client_secret": "secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    assert google_auth.classify_google_oauth_json(client_payload) == "client"
    res_client = google_auth.import_google_oauth_json(json.dumps(client_payload))
    assert res_client["ok"] is True
    assert res_client["kind"] == "client"
    assert (tmp_path / ".synthetic-text-extruder" / "google_oauth_client.json").is_file()

    token_payload = {
        "type": "authorized_user",
        "client_id": "12345.apps.googleusercontent.com",
        "client_secret": "secret",
        "refresh_token": "1//fake-refresh",
        "token": "ya29.fake-access",
        "scopes": list(google_auth.GOOGLE_SCOPES),
    }
    assert google_auth.classify_google_oauth_json(token_payload) == "token"

    class _FakeCreds:
        valid = True
        expired = False
        refresh_token = "1//fake-refresh"
        scopes = list(google_auth.GOOGLE_SCOPES)

    monkeypatch.setattr(google_auth, "_load_stored_credentials", lambda _p: _FakeCreds())
    res_tok = google_auth.import_google_oauth_json(json.dumps(token_payload))
    assert res_tok["ok"] is True
    assert res_tok["kind"] == "token"
    assert res_tok["authorized"] is True
    assert "Gmail" in res_tok["granted_products"]

    bad = google_auth.import_google_oauth_json('{"hello": "world"}')
    assert bad["ok"] is False

    cleared = google_auth.clear_google_credentials()
    assert cleared["ok"] is True
    assert not (tmp_path / ".synthetic-text-extruder" / "google_workspace_token.json").exists()
    assert not (tmp_path / ".synthetic-text-extruder" / "google_oauth_client.json").exists()


def test_api_import_uploaded_files_and_export_payload(monkeypatch, tmp_path):
    api = Api()
    api.config = {
        "backend": {"provider": "gemini"},
        "gemini": {"text_model": "gemini-2.5-flash", "api_key": "test-key"},
        "paths": {"archives": str(tmp_path / "archives.json"), "media": "media"},
    }
    api.store = ArchiveStore(path=tmp_path / "archives.json")
    monkeypatch.setattr("synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("synthetic_text_extruder.media_store.load_config", lambda: api.config)

    txt_b64 = base64.b64encode(b"Hello from Android picker").decode("ascii")
    res = api.import_uploaded_files(
        [{"name": "note.txt", "data_b64": txt_b64}],
        mode="sources",
        already=0,
    )
    assert res["ok"] is True
    assert len(res["creations"]) == 1
    assert "Hello from Android picker" in json.dumps(res["creations"][0])


def test_android_server_rpc_auth_and_html_injection(monkeypatch, tmp_path):
    monkeypatch.setenv(platform_env.PLATFORM_ENV_VAR, "android")
    monkeypatch.setenv(platform_env.DATA_DIR_ENV_VAR, str(tmp_path))
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr("synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path)
    android_server.stop_android_server()
    try:
        info = android_server.start_android_server(str(tmp_path))
        assert info["ok"] is True
        origin = info["origin"]
        token = info["token"]

        html = urllib.request.urlopen(f"{origin}/index.html", timeout=5).read().decode("utf-8")
        assert "__STE_ANDROID_TOKEN__" in html
        assert token in html

        # Unauthorized RPC must be rejected
        bad_req = urllib.request.Request(
            f"{origin}/api/rpc/ping",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(bad_req, timeout=5)
            raise AssertionError("Expected HTTP 403 for missing RPC token")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403

        # Authorized RPC returns ping ok
        ok_req = urllib.request.Request(
            f"{origin}/api/rpc/ping",
            data=b'{"args": []}',
            headers={"Content-Type": "application/json", "X-STE-Token": token},
            method="POST",
        )
        body = json.loads(urllib.request.urlopen(ok_req, timeout=5).read().decode("utf-8"))
        assert body["ok"] is True
        assert body["result"]["ok"] is True
    finally:
        android_server.stop_android_server()
