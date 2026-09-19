"""API media replace / edit export / import (mocked dialogs & ffmpeg)."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from synthetic_text_extruder.api import Api, _safe_dialog_save_path
from synthetic_text_extruder.creation_utils import build_media_creation
from synthetic_text_extruder.storage import ArchiveStore


def _api_with_tmp_store(tmp_path, monkeypatch) -> Api:
    api = Api()
    api.config = {
        "paths": {"archives": str(tmp_path / "archives.json"), "media": "media"},
    }
    api.store = ArchiveStore(path=tmp_path / "archives.json")
    monkeypatch.setattr(
        "synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path
    )
    monkeypatch.setattr(
        "synthetic_text_extruder.media_store.load_config",
        lambda: api.config,
    )
    return api


def test_replace_creation_media_writes_image(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    creation = build_media_creation(
        modality="image",
        prompt="test",
        media_path="media/doc_img1.png",
        mime_type="image/png",
        title="Shot",
        creation_id="doc_img1",
    )
    api.store.upsert(creation)
    # Seed original media file path used by record (optional)
    (tmp_path / "media").mkdir(parents=True, exist_ok=True)

    png = base64.b64encode(b"\x89PNG\r\n\x1a\nedited").decode("ascii")
    res = api.replace_creation_media(
        "doc_img1",
        f"data:image/png;base64,{png}",
        "image/png",
    )
    assert res["ok"] is True
    saved = res["creation"]
    assert saved["id"] == "doc_img1"
    assert saved["modality"] == "image"
    assert saved.get("mediaPath")
    media_file = tmp_path / saved["mediaPath"]
    assert media_file.is_file()
    assert b"edited" in media_file.read_bytes()


def test_replace_creation_media_rejects_non_image(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    video = build_media_creation(
        modality="video",
        prompt="clip",
        media_path="media/doc_v1.mp4",
        mime_type="video/mp4",
        title="Clip",
        creation_id="doc_v1",
    )
    api.store.upsert(video)
    res = api.replace_creation_media("doc_v1", base64.b64encode(b"x").decode(), "image/png")
    assert res["ok"] is False
    assert "image" in (res.get("error") or "").lower()


def test_replace_creation_media_missing_id(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    assert api.replace_creation_media("", "aaaa")["ok"] is False
    assert api.replace_creation_media("missing", "aaaa")["ok"] is False


def test_edit_video_overwrites_media(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    (tmp_path / "media").mkdir(parents=True, exist_ok=True)
    src = tmp_path / "media" / "doc_vid.mp4"
    src.write_bytes(b"source-bytes")
    creation = build_media_creation(
        modality="video",
        prompt="vid",
        media_path="media/doc_vid.mp4",
        mime_type="video/mp4",
        title="Vid",
        creation_id="doc_vid",
    )
    api.store.upsert(creation)

    rendered = tmp_path / "rendered.mp4"
    rendered.write_bytes(b"edited-video-bytes")

    def fake_render(creation_id, ops=None):
        assert creation_id == "doc_vid"
        assert ops and ops.get("segments")
        return None, rendered, creation

    monkeypatch.setattr(api, "_render_edited_video", fake_render)
    res = api.edit_video(
        "doc_vid",
        {"segments": [{"start": 0, "end": 1}], "filters": {"brightness": 5}},
    )
    assert res["ok"] is True
    assert res["creation"]["id"] == "doc_vid"
    out = tmp_path / res["creation"]["mediaPath"]
    assert out.read_bytes() == b"edited-video-bytes"
    assert not rendered.exists()  # cleaned up in finally


def test_export_edited_video_save_dialog(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    creation = build_media_creation(
        modality="video",
        prompt="vid",
        media_path="media/doc_exp.mp4",
        mime_type="video/mp4",
        title="Export Me",
        creation_id="doc_exp",
    )
    api.store.upsert(creation)
    rendered = tmp_path / "rendered_export.mp4"
    rendered.write_bytes(b"export-bytes")
    dest = tmp_path / "user_save.mp4"

    monkeypatch.setattr(
        api,
        "_render_edited_video",
        lambda creation_id, ops=None: (None, rendered, creation),
    )
    win = MagicMock()
    win.create_file_dialog.return_value = str(dest)
    api._window = win

    res = api.export_edited_video(
        "doc_exp", {"segments": [{"start": 0, "end": 2}]}
    )
    assert res["ok"] is True
    assert Path(res["path"]) == dest
    assert dest.read_bytes() == b"export-bytes"


def test_export_edited_video_cancelled(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    creation = build_media_creation(
        modality="video",
        prompt="vid",
        media_path="media/doc_exp2.mp4",
        mime_type="video/mp4",
        title="Clip",
        creation_id="doc_exp2",
    )
    api.store.upsert(creation)
    rendered = tmp_path / "rendered_cancel.mp4"
    rendered.write_bytes(b"x")
    monkeypatch.setattr(
        api,
        "_render_edited_video",
        lambda creation_id, ops=None: (None, rendered, creation),
    )
    win = MagicMock()
    win.create_file_dialog.return_value = None
    api._window = win
    res = api.export_edited_video("doc_exp2", {"segments": [{"start": 0, "end": 1}]})
    assert res.get("cancelled") is True


def test_import_media_file_image(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    src = tmp_path / "photo.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\nhello")
    win = MagicMock()
    win.create_file_dialog.return_value = str(src)
    api._window = win

    res = api.import_media_file("image")
    assert res["ok"] is True
    assert res["modality"] == "image"
    c = res["creation"]
    assert c["modality"] == "image"
    assert c["title"] == "photo"
    assert "Imported from photo.png" in c["prompt"]
    media = tmp_path / c["mediaPath"]
    assert media.read_bytes().startswith(b"\x89PNG")


def test_import_media_file_cancelled(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    win = MagicMock()
    win.create_file_dialog.return_value = None
    api._window = win
    res = api.import_media_file("video")
    assert res.get("cancelled") is True


def test_import_text_file_into_prompt(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    src = tmp_path / "notes.txt"
    src.write_text("Hello studio basis", encoding="utf-8")
    win = MagicMock()
    win.create_file_dialog.return_value = str(src)
    api._window = win

    res = api.import_text_file(False)
    assert res["ok"] is True
    assert res["text"] == "Hello studio basis"
    assert "creation" not in res

    res2 = api.import_text_file(True)
    assert res2["ok"] is True
    assert res2["creation"]["modality"] == "text"
    assert "Hello studio basis" in res2["creation"]["sections"][0]["content"]


def test_modality_for_path_detects_supported_types(tmp_path):
    from synthetic_text_extruder.media_store import modality_for_path

    assert modality_for_path(tmp_path / "notes.txt") == "text"
    assert modality_for_path(tmp_path / "readme.markdown") == "text"
    assert modality_for_path(tmp_path / "shot.png") == "image"
    assert modality_for_path(tmp_path / "clip.mp4") == "video"
    assert modality_for_path(tmp_path / "song.mp3") == "audio"
    assert modality_for_path(tmp_path / "secret.pdf") == "pdf"
    assert modality_for_path(tmp_path / "app.exe") is None


def test_open_viewer_file_image(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    src = tmp_path / "ui.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\nlayout")
    win = MagicMock()
    win.create_file_dialog.return_value = str(src)
    api._window = win

    res = api.open_viewer_file()
    assert res["ok"] is True
    assert res["modality"] == "image"
    assert res["creation"]["modality"] == "image"
    assert res["creation"]["title"] == "ui"


def test_open_viewer_file_text(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    src = tmp_path / "doc.md"
    src.write_text("# Hello", encoding="utf-8")
    win = MagicMock()
    win.create_file_dialog.return_value = str(src)
    api._window = win

    res = api.open_viewer_file()
    assert res["ok"] is True
    assert res["modality"] == "text"
    assert res["creation"]["modality"] == "text"
    assert "# Hello" in res["creation"]["sections"][0]["content"]


def test_open_viewer_file_pdf(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    src = tmp_path / "brief.pdf"
    src.write_bytes(b"%PDF-1.4")
    win = MagicMock()
    win.create_file_dialog.return_value = str(src)
    api._window = win

    res = api.open_viewer_file()
    assert res["ok"] is True
    assert res["modality"] == "pdf"
    assert res["creation"]["modality"] == "pdf"
    assert res["creation"]["mimeType"] == "application/pdf"


def test_open_viewer_file_rejects_unsupported(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    src = tmp_path / "payload.exe"
    src.write_bytes(b"%PDF-1.4")
    win = MagicMock()
    win.create_file_dialog.return_value = str(src)
    api._window = win

    res = api.open_viewer_file()
    assert res["ok"] is False
    assert "text" in (res.get("error") or "").lower()


def test_open_viewer_file_cancelled(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    win = MagicMock()
    win.create_file_dialog.return_value = None
    api._window = win
    res = api.open_viewer_file()
    assert res.get("cancelled") is True


def test_duplicate_image_copies_media(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    (tmp_path / "media").mkdir(parents=True, exist_ok=True)
    src = tmp_path / "media" / "doc_dup.png"
    src.write_bytes(b"image-bytes")
    creation = build_media_creation(
        modality="image",
        prompt="orig",
        media_path="media/doc_dup.png",
        mime_type="image/png",
        title="Original",
        creation_id="doc_dup",
    )
    api.store.upsert(creation)
    res = api.duplicate_creation("doc_dup")
    assert res["ok"] is True
    copy = res["creation"]
    assert copy["id"] != "doc_dup"
    assert "(copy)" in copy["title"]
    assert (tmp_path / copy["mediaPath"]).read_bytes() == b"image-bytes"


def test_get_media_payload_image_includes_file_url(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    api._ui_origin = "http://127.0.0.1:8765"
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    img_path = media_dir / "doc_basis.png"
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    img_path.write_bytes(png)
    creation = build_media_creation(
        modality="image",
        prompt="basis",
        media_path="media/doc_basis.png",
        mime_type="image/png",
        title="Basis",
        creation_id="doc_basis",
    )
    api.store.upsert(creation)
    res = api.get_media_payload(creation)
    assert res["ok"] is True
    assert res["modality"] == "image"
    assert res.get("fileUrl") == "http://127.0.0.1:8765/media/doc_basis.png"
    assert str(res.get("dataUrl") or "").startswith("data:image/")


def test_save_binary_file_dialog_forces_png_and_pdf_extension(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    png_bytes = b"\x89PNG\r\n\x1a\n"
    png_b64 = base64.b64encode(png_bytes).decode("ascii")

    class _Win:
        def __init__(self, dest: Path):
            self.dest = dest

        def create_file_dialog(self, *_args, **_kwargs):
            return str(self.dest)

    dest = tmp_path / "from-viewer"
    api._window = _Win(dest)
    res = api.save_binary_file_dialog("poster.png", png_b64)
    assert res["ok"] is True
    assert Path(res["path"]).name == "from-viewer.png"
    assert Path(res["path"]).read_bytes() == png_bytes

    dest2 = tmp_path / "report.txt"
    api._window = _Win(dest2)
    res = api.save_binary_file_dialog("report.pdf", base64.b64encode(b"%PDF").decode("ascii"))
    assert res["ok"] is True
    assert Path(res["path"]).suffix == ".pdf"
    assert Path(res["path"]).read_bytes() == b"%PDF"


def test_safe_dialog_save_path_stays_in_parent(tmp_path):
    dest = _safe_dialog_save_path(str(tmp_path / "shot"), ".png")
    assert dest.parent == tmp_path.resolve()
    assert dest.name == "shot.png"


def test_safe_dialog_save_path_rejects_parent_escape(tmp_path):
    with pytest.raises(ValueError):
        _safe_dialog_save_path(str(tmp_path / ".." / "outside.png"), ".png")

    class _Win:
        def create_file_dialog(self, *_args, **_kwargs):
            return str(tmp_path / ".." / "escape")

    api = Api()
    api._window = _Win()
    res = api.save_binary_file_dialog(
        "x.png", base64.b64encode(b"\x89PNG").decode("ascii")
    )
    assert res["ok"] is False
    assert "Invalid" in (res.get("error") or "")


def test_export_creation_media_forces_mp4_extension(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    src = media_dir / "clip.mp4"
    src.write_bytes(b"ftypisom")
    creation = build_media_creation(
        modality="video",
        prompt="clip",
        media_path="media/clip.mp4",
        mime_type="video/mp4",
        title="Clip",
        creation_id="clip1",
    )
    api.store.upsert(creation)

    dest = tmp_path / "exported"
    class _Win:
        def create_file_dialog(self, *_args, **_kwargs):
            return str(dest)

    api._window = _Win()
    res = api.export_creation_media(creation)
    assert res["ok"] is True
    assert Path(res["path"]).name == "exported.mp4"
    assert Path(res["path"]).read_bytes() == b"ftypisom"


def test_export_creation_media_forces_mp3_extension(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    src = media_dir / "song.wav"
    src.write_bytes(b"ID3song")
    creation = build_media_creation(
        modality="audio",
        prompt="A lofi beat",
        media_path="media/song.wav",
        mime_type="audio/wav",
        title="Song",
        creation_id="song1",
    )
    api.store.upsert(creation)

    dest = tmp_path / "exported"
    captured: dict[str, object] = {}

    class _Win:
        def create_file_dialog(self, *_args, **kwargs):
            captured.update(kwargs)
            return str(dest)

    api._window = _Win()
    res = api.export_creation_media(creation)
    assert res["ok"] is True
    assert Path(res["path"]).name == "exported.mp3"
    assert Path(res["path"]).read_bytes() == b"ID3song"
    assert str(captured.get("save_filename") or "").endswith(".mp3")
    types = captured.get("file_types") or ()
    assert any("*.mp3" in str(item) for item in types)


def test_export_creation_media_uses_embedding_filename(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    src = media_dir / "fox.png"
    src.write_bytes(b"\x89PNG")
    prompt = "cinematic wide shot of a red fox in snow at dawn, photorealistic"
    creation = build_media_creation(
        modality="image",
        prompt=prompt,
        media_path="media/fox.png",
        mime_type="image/png",
        title=prompt,
        creation_id="fox1",
    )
    api.store.upsert(creation)
    api.config["gemini"] = {"api_key": "test-key"}

    monkeypatch.setattr(
        "synthetic_text_extruder.embedding_filename.suggest_filename_for_creation",
        lambda *args, **kwargs: "red-fox-snow-dawn",
    )

    captured: dict[str, object] = {}

    class _Win:
        def create_file_dialog(self, *_args, **kwargs):
            captured.update(kwargs)
            return str(tmp_path / "out")

    api._window = _Win()
    res = api.export_creation_media(creation)
    assert res["ok"] is True
    assert captured.get("save_filename") == "red-fox-snow-dawn.png"
    stored = next(c for c in api.store.load() if c.get("id") == "fox1")
    assert stored.get("meta", {}).get("embeddingFilename") == "red-fox-snow-dawn"


def test_suggest_media_filename_api(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    creation = build_media_creation(
        modality="image",
        prompt="a lighthouse at dusk",
        media_path="media/x.png",
        mime_type="image/png",
        title="Harbor dusk",
        creation_id="light1",
    )
    api.store.upsert(creation)
    res = api.suggest_media_filename(creation)
    assert res["ok"] is True
    assert res["filename"] == "harbor-dusk"


def test_pick_media_folder_mocked_dialog(tmp_path):
    api = Api()
    api.config = {"paths": {"media": "media"}}
    chosen = tmp_path / "picked-media"
    chosen.mkdir()
    win = MagicMock()
    win.create_file_dialog.return_value = str(chosen)
    api._window = win
    res = api.pick_media_folder()
    assert res["ok"] is True
    assert Path(res["path"]) == chosen.resolve()
    win.create_file_dialog.assert_called()


def test_pick_media_folder_cancelled():
    api = Api()
    api.config = {"paths": {"media": "media"}}
    win = MagicMock()
    win.create_file_dialog.return_value = None
    api._window = win
    res = api.pick_media_folder()
    assert res.get("cancelled") is True
    assert res.get("ok") is False


def test_relocate_media_files_moves_and_updates_archive(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    old = tmp_path / "media"
    old.mkdir(parents=True, exist_ok=True)
    src = old / "doc_mv.png"
    src.write_bytes(b"img-bytes")
    (old / "archives.json").write_text("[]", encoding="utf-8")
    (old / "notes.txt").write_text("leave me", encoding="utf-8")
    creation = build_media_creation(
        modality="image",
        prompt="move me",
        media_path="media/doc_mv.png",
        mime_type="image/png",
        title="Move",
        creation_id="doc_mv",
    )
    api.store.upsert(creation)
    custom = tmp_path / "new-media"
    api.config["paths"]["media"] = str(custom.resolve())

    res = api.relocate_media_files(str(old.resolve()))
    assert res["ok"] is True
    assert res["moved"] == 1
    assert res["updated"] == 1
    assert not src.exists()
    assert (old / "archives.json").is_file()
    assert (old / "notes.txt").read_text(encoding="utf-8") == "leave me"
    item = next(c for c in api.store.load() if c["id"] == "doc_mv")
    new_path = Path(item["mediaPath"])
    if not new_path.is_absolute():
        new_path = tmp_path / new_path
    assert new_path.is_file()
    assert new_path.read_bytes() == b"img-bytes"
    assert new_path.parent == custom.resolve()


def test_relocate_media_collision_uses_unique_name(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    old = tmp_path / "media"
    old.mkdir(parents=True, exist_ok=True)
    (old / "doc_col.png").write_bytes(b"old-bytes")
    custom = tmp_path / "new-media"
    custom.mkdir()
    (custom / "doc_col.png").write_bytes(b"already-there")
    creation = build_media_creation(
        modality="image",
        prompt="collide",
        media_path="media/doc_col.png",
        mime_type="image/png",
        title="Collide",
        creation_id="doc_col",
    )
    api.store.upsert(creation)
    api.config["paths"]["media"] = str(custom.resolve())

    res = api.relocate_media_files(str(old.resolve()))
    assert res["ok"] is True
    item = next(c for c in api.store.load() if c["id"] == "doc_col")
    new_path = Path(item["mediaPath"])
    if not new_path.is_absolute():
        new_path = tmp_path / new_path
    assert new_path.name != "doc_col.png"
    assert new_path.read_bytes() == b"old-bytes"
    assert (custom / "doc_col.png").read_bytes() == b"already-there"


def test_save_settings_offers_move_decline_leaves_files(tmp_path, monkeypatch):
    import copy

    from synthetic_text_extruder.config import DEFAULTS

    api = _api_with_tmp_store(tmp_path, monkeypatch)
    dest_cfg = tmp_path / "config.yaml"
    monkeypatch.setattr("synthetic_text_extruder.config.DEFAULT_CONFIG_PATH", dest_cfg)
    old = tmp_path / "media"
    old.mkdir(parents=True, exist_ok=True)
    leftover = old / "doc_stay.png"
    leftover.write_bytes(b"stay")
    creation = build_media_creation(
        modality="image",
        prompt="stay",
        media_path="media/doc_stay.png",
        mime_type="image/png",
        title="Stay",
        creation_id="doc_stay",
    )
    api.store.upsert(creation)
    existing = copy.deepcopy(DEFAULTS)
    existing["paths"]["archives"] = str(tmp_path / "archives.json")
    existing["paths"]["media"] = "media"
    api.config = existing
    custom = (tmp_path / "elsewhere").resolve()

    res = api.save_settings({"paths": {"media": str(custom)}})
    assert res["ok"] is True
    offer = res.get("mediaMove") or {}
    assert offer.get("offered") is True
    assert offer.get("count", 0) >= 1
    assert leftover.is_file()
    assert leftover.read_bytes() == b"stay"
    item = next(c for c in api.store.load() if c["id"] == "doc_stay")
    assert item["mediaPath"] == "media/doc_stay.png"

