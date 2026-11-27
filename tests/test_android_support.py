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
    assert mob["videoEditor"] is True
    assert mob["ffmpeg"] is True
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

    # Duplicate basenames from recursive folder upload preserve originalFilename
    dup_res = api.import_uploaded_files(
        [
            {"name": "scan.txt", "data_b64": base64.b64encode(b"page one").decode("ascii")},
            {"name": "scan.txt", "data_b64": base64.b64encode(b"page two").decode("ascii")},
        ],
        mode="sources",
        already=0,
        folder_name="Binder",
        recursive=True,
    )
    assert dup_res["ok"] is True
    assert len(dup_res["creations"]) == 2
    assert [c["meta"]["originalFilename"] for c in dup_res["creations"]] == ["scan.txt", "scan.txt"]


def test_android_server_picked_folder_flat_and_recursive(monkeypatch, tmp_path):
    monkeypatch.setenv(platform_env.PLATFORM_ENV_VAR, "android")
    monkeypatch.setenv(platform_env.DATA_DIR_ENV_VAR, str(tmp_path / "data"))
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path / "data")
    monkeypatch.setattr(config, "DEFAULT_CONFIG_PATH", tmp_path / "data" / "config.yaml")
    monkeypatch.setattr("synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path / "data")

    staged = tmp_path / "staged_tree"
    sub = staged / "chapter_1"
    hidden_sub = staged / ".secret"
    sub.mkdir(parents=True)
    hidden_sub.mkdir(parents=True)
    (staged / "root_note.txt").write_text("Top level note", encoding="utf-8")
    (staged / ".hidden.txt").write_text("Ignore me", encoding="utf-8")
    (sub / "nested_note.txt").write_text("Nested note", encoding="utf-8")
    (hidden_sub / "ignored.txt").write_text("Ignore hidden folder", encoding="utf-8")

    android_server.stop_android_server()
    try:
        info = android_server.start_android_server(str(tmp_path / "data"))
        assert info["ok"] is True
        origin = info["origin"]
        token = info["token"]

        # Arbitrary path import over HTTP RPC must be blocked
        blocked_req = urllib.request.Request(
            f"{origin}/api/rpc/import_staged_folder",
            data=json.dumps({"args": [str(staged)]}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-STE-Token": token},
            method="POST",
        )
        try:
            urllib.request.urlopen(blocked_req, timeout=5)
            raise AssertionError("Expected HTTP 404 for blocklisted import_staged_folder")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404

        # Non-recursive folder import only loads immediate supported files
        flat_res = json.loads(
            android_server.import_picked_folder_json(
                str(staged), folder_name="MyResearch", already=0, recursive=False
            )
        )
        assert flat_res["ok"] is True
        assert [c["meta"]["originalFilename"] for c in flat_res["creations"]] == ["root_note.txt"]

        # Recursive folder import includes subfolders while skipping hidden entries
        rec_res = json.loads(
            android_server.import_picked_folder_json(
                str(staged), folder_name="MyResearch", already=0, recursive=True
            )
        )
        assert rec_res["ok"] is True
        assert {c["meta"]["originalFilename"] for c in rec_res["creations"]} == {
            "root_note.txt",
            "nested_note.txt",
        }
    finally:
        android_server.stop_android_server()


def test_android_media3_bridge_video_features(monkeypatch, tmp_path):
    from synthetic_text_extruder import extract_text, video_edit

    fake_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
        b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    fake_m4a = b"\x00\x00\x00\x20ftypM4A " + b"x" * 64
    fake_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"v" * 80
    calls: list[tuple] = []

    class _FakeAndroidMediaBridge:
        @staticmethod
        def statusJson() -> str:
            return json.dumps(
                {
                    "ok": True,
                    "backend": "media3",
                    "ffmpeg": "androidx.media3.transformer",
                    "ffprobe": "android.media.MediaMetadataRetriever",
                    "ffmpegDecoder": True,
                    "version": "AndroidX Media3 1.8.0 (FFmpeg 6.1)",
                }
            )

        @staticmethod
        def probeVideoInfoJson(path: str) -> str:
            calls.append(("probe", path))
            return json.dumps(
                {
                    "duration": 12.5,
                    "width": 1280,
                    "height": 720,
                    "codec": "h264",
                    "size": 4096,
                    "hasAudio": True,
                }
            )

        @staticmethod
        def hasAudioStream(path: str) -> bool:
            calls.append(("hasAudio", path))
            return True

        @staticmethod
        def extractFramePng(path: str, at_seconds: float) -> bytes:
            calls.append(("frame", path, at_seconds))
            return fake_png

        @staticmethod
        def extractAudioM4a(path: str, max_seconds: float) -> bytes:
            calls.append(("audio", path, max_seconds))
            return fake_m4a

        @staticmethod
        def extractClipMp4(path: str, max_seconds: float) -> bytes:
            calls.append(("clip", path, max_seconds))
            return fake_mp4

        @staticmethod
        def applyEdits(src_path: str, dest_path: str, options_json: str) -> str:
            calls.append(("edit", src_path, dest_path, json.loads(options_json)))
            from pathlib import Path

            Path(dest_path).write_bytes(fake_mp4)
            return dest_path

        @staticmethod
        def concatVideos(paths_json: str, dest_path: str) -> str:
            calls.append(("concat", json.loads(paths_json), dest_path))
            from pathlib import Path

            Path(dest_path).write_bytes(fake_mp4)
            return dest_path

        @staticmethod
        def buildSlideshow(paths_json: str, dest_path: str, seconds: float) -> str:
            calls.append(("slideshow", json.loads(paths_json), dest_path, seconds))
            from pathlib import Path

            Path(dest_path).write_bytes(fake_mp4)
            return dest_path

    monkeypatch.setattr(video_edit, "_android_media_bridge", lambda: _FakeAndroidMediaBridge)

    vid = tmp_path / "sample.mp4"
    vid.write_bytes(fake_mp4)
    vid2 = tmp_path / "sample2.mp4"
    vid2.write_bytes(fake_mp4)
    img1 = tmp_path / "a.png"
    img2 = tmp_path / "b.png"
    img1.write_bytes(fake_png)
    img2.write_bytes(fake_png)

    status = video_edit.ffmpeg_available()
    assert status["ok"] is True
    assert status["ffmpegDecoder"] is True

    frame = video_edit.extract_video_frame_png(vid, at_seconds=1.25)
    assert frame == fake_png

    info = video_edit.probe_video_info(vid)
    assert info["duration"] == 12.5
    assert info["width"] == 1280
    assert video_edit.probe_duration(vid) == 12.5
    assert video_edit.video_has_audio_stream(vid) is True

    audio_bytes, audio_mime = video_edit.extract_audio_track(vid, max_seconds=120)
    assert audio_bytes == fake_m4a
    assert audio_mime == "audio/mp4"

    clip_bytes = video_edit.extract_video_clip_bytes(vid, max_seconds=30)
    assert clip_bytes == fake_mp4

    # Multi-segment assembly routes in a single Media3 pass
    assembled = tmp_path / "assembled.mp4"
    video_edit.assemble_segments(
        vid,
        assembled,
        [{"start": 0.0, "end": 3.0}, {"start": 5.0, "end": 8.0}],
        filters={"grayscale": True},
        rotation=90,
    )
    assert assembled.read_bytes() == fake_mp4
    assert any(c[0] == "edit" and len(c[3]["segments"]) == 2 for c in calls)

    spliced = tmp_path / "spliced.mp4"
    video_edit.concat_videos([vid, vid2], spliced)
    assert spliced.read_bytes() == fake_mp4

    slideshow = tmp_path / "flipbook.mp4"
    video_edit.build_image_slideshow([img1, img2], slideshow, seconds_per_image=2.0)
    assert slideshow.read_bytes() == fake_mp4

    # Video transcription sends audio/mp4 extracted via AndroidMediaBridge to Gemini
    seen_mimes: list[str] = []

    def _fake_multimodal(_data, *, mime_type, **_kwargs):
        seen_mimes.append(mime_type)
        return "Transcribed speech from Android video", "gemini-2.5-flash"

    monkeypatch.setattr(extract_text, "_gemini_multimodal", _fake_multimodal)
    transcript, _model, kind = extract_text._extract_video(
        vid,
        mime_type="video/mp4",
        config={},
        model_id="gemini-2.5-flash",
        progress=None,
        cancel_check=lambda: False,
    )
    assert kind == "transcript"
    assert transcript == "Transcribed speech from Android video"
    assert seen_mimes == ["audio/mp4"]

    # Android Video Editor Save As export helper returns base64 MP4
    api = Api()
    api.config = {
        "backend": {"provider": "gemini"},
        "gemini": {"text_model": "gemini-2.5-flash", "api_key": "test-key"},
        "paths": {"archives": str(tmp_path / "archives.json"), "media": str(tmp_path / "media")},
    }
    (tmp_path / "media").mkdir(parents=True, exist_ok=True)
    stored_vid = tmp_path / "media" / "clip.mp4"
    stored_vid.write_bytes(fake_mp4)
    api.store = ArchiveStore(path=tmp_path / "archives.json")
    api.store.upsert(
        {
            "id": "vid_1",
            "title": "Demo Clip",
            "modality": "video",
            "mediaPath": str(stored_vid),
            "mimeType": "video/mp4",
        }
    )
    monkeypatch.setattr("synthetic_text_extruder.media_store.load_config", lambda: api.config)
    exp = api.prepare_edited_video_export("vid_1", {"filters": {"grayscale": True}})
    assert exp["ok"] is True
    assert exp["mimeType"] == "video/mp4"
    assert exp["filename"].endswith(".mp4")
    assert base64.b64decode(exp["base64"]) == fake_mp4


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
