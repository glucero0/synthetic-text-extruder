"""Tests for Studio text extract / transcription helpers and API."""

from __future__ import annotations

import base64
import threading

import pytest

from synthetic_text_extruder.api import Api
from synthetic_text_extruder.creation_utils import (
    build_media_creation,
    build_text_creation_from_plain,
)
from synthetic_text_extruder.extract_text import (
    apply_extraction_fields,
    clear_extraction_fields,
    get_extracted_text,
)
from synthetic_text_extruder.storage import ArchiveStore


def _api_with_tmp_store(tmp_path, monkeypatch) -> Api:
    api = Api()
    api.config = {
        "backend": {"provider": "gemini"},
        "gemini": {"text_model": "gemini-2.5-flash", "api_key": "test-key"},
        "paths": {"archives": str(tmp_path / "archives.json"), "media": "media"},
    }
    api.store = ArchiveStore(path=tmp_path / "archives.json")
    monkeypatch.setattr("synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "synthetic_text_extruder.media_store.load_config",
        lambda: api.config,
    )
    return api


def _wait_job(api: Api, job_id: str, timeout_s: float = 5.0) -> dict:
    steps = max(1, int(timeout_s / 0.05))
    for _ in range(steps):
        job = api.get_job(job_id)
        if job.get("status") in ("done", "error", "cancelled", "missing"):
            return job
        threading.Event().wait(0.05)
    return api.get_job(job_id)


def test_clear_and_apply_extraction_fields():
    creation = build_media_creation(
        modality="image",
        prompt="sign",
        media_path="media/a.png",
        mime_type="image/png",
        title="Sign",
        creation_id="doc_a",
    )
    updated = apply_extraction_fields(
        creation,
        text="HELLO",
        kind="ocr",
        model="gemini-2.5-flash",
        provider="gemini",
    )
    assert get_extracted_text(updated) == "HELLO"
    assert updated["meta"]["extractionKind"] == "ocr"
    assert updated["meta"]["extractionModel"] == "gemini-2.5-flash"

    cleared = clear_extraction_fields(updated)
    assert get_extracted_text(cleared) == ""
    assert "extractionKind" not in (cleared.get("meta") or {})


def test_export_creation_txt_uses_extracted_for_media(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    creation = build_media_creation(
        modality="image",
        prompt="sign",
        media_path="media/a.png",
        mime_type="image/png",
        title="Sign",
        creation_id="doc_a",
    )
    with pytest.raises(RuntimeError, match="extract the text"):
        api.export_creation_txt(creation)

    creation = apply_extraction_fields(
        creation,
        text="HELLO WORLD",
        kind="ocr",
        model="m",
        provider="gemini",
    )
    out = api.export_creation_txt(creation)
    assert "HELLO WORLD" in out


def test_replace_creation_media_clears_extracted_text(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    (tmp_path / "media").mkdir(parents=True, exist_ok=True)
    creation = build_media_creation(
        modality="image",
        prompt="sign",
        media_path="media/doc_img1.png",
        mime_type="image/png",
        title="Shot",
        creation_id="doc_img1",
    )
    creation = apply_extraction_fields(
        creation, text="OLD", kind="ocr", model="m", provider="gemini"
    )
    api.store.upsert(creation)

    png = base64.b64encode(b"\x89PNG\r\n\x1a\nedited").decode("ascii")
    res = api.replace_creation_media(
        "doc_img1",
        f"data:image/png;base64,{png}",
        "image/png",
    )
    assert res["ok"] is True
    assert get_extracted_text(res["creation"]) == ""


def test_extract_creation_text_rejects_text_doc(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    text_doc = {
        "id": "doc_t1",
        "modality": "text",
        "title": "Note",
        "overview": "hello",
        "sections": [{"title": "Response", "content": "hello"}],
    }
    api.store.upsert(text_doc)
    res = api.extract_creation_text("doc_t1")
    assert res["ok"] is False
    assert "image or video" in (res.get("error") or "").lower()


def test_extract_creation_text_job_persists(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "doc_img2.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    creation = build_media_creation(
        modality="image",
        prompt="sign",
        media_path="media/doc_img2.png",
        mime_type="image/png",
        title="Shot",
        creation_id="doc_img2",
    )
    api.store.upsert(creation)

    def fake_extract(creation, *, config, media_path, progress=None, cancel_event=None):
        return apply_extraction_fields(
            creation,
            text="OCR RESULT",
            kind="ocr",
            model="gemini-2.5-flash",
            provider="gemini",
        )

    monkeypatch.setattr(
        "synthetic_text_extruder.extract_text.extract_text_from_creation",
        fake_extract,
    )

    res = api.extract_creation_text("doc_img2")
    assert res["ok"] is True
    job = _wait_job(api, res["job_id"])
    assert job["status"] == "done", job
    assert get_extracted_text(job["result"]) == "OCR RESULT"
    stored = next(c for c in api.store.load() if c["id"] == "doc_img2")
    assert get_extracted_text(stored) == "OCR RESULT"


def test_create_creation_extract_text_from_studio_prompt(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "doc_studio_ocr.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    creation = build_media_creation(
        modality="image",
        prompt="sign",
        media_path="media/doc_studio_ocr.png",
        mime_type="image/png",
        title="Shot",
        creation_id="doc_studio_ocr",
    )
    api.store.upsert(creation)

    def fake_extract(creation, *, config, media_path, progress=None, cancel_event=None):
        return apply_extraction_fields(
            creation,
            text="OCR FROM STUDIO",
            kind="ocr",
            model="gemini-2.5-flash",
            provider="gemini",
        )

    monkeypatch.setattr(
        "synthetic_text_extruder.extract_text.extract_text_from_creation",
        fake_extract,
    )

    res = api.create_creation(
        "Prompt",
        "General",
        "Custom",
        True,
        "extract the text",
        "doc_studio_ocr",
    )
    assert res["ok"] is True, res
    job = _wait_job(api, res["job_id"])
    assert job["status"] == "done", job
    assert job["result"]["id"] == "doc_studio_ocr"
    assert get_extracted_text(job["result"]) == "OCR FROM STUDIO"
    assert job["result"]["meta"]["studioJob"] == "extract"
    stored = next(c for c in api.store.load() if c["id"] == "doc_studio_ocr")
    assert get_extracted_text(stored) == "OCR FROM STUDIO"


def test_create_creation_extract_named_image_not_last_visual(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "doc_toast.png").write_bytes(b"\x89PNG\r\n\x1a\ntoast")
    (media_dir / "doc_later.png").write_bytes(b"\x89PNG\r\n\x1a\nlater")
    toaster = build_media_creation(
        modality="image",
        prompt="a toaster on fire",
        media_path="media/doc_toast.png",
        mime_type="image/png",
        title="a toaster on fire",
        creation_id="doc_toast",
    )
    later = build_media_creation(
        modality="image",
        prompt="harbor",
        media_path="media/doc_later.png",
        mime_type="image/png",
        title="harbor",
        creation_id="doc_later",
    )
    notes = build_text_creation_from_plain("Notes", prompt="notes", title="Notes")
    notes["id"] = "doc_notes"
    api.store.upsert(toaster)
    api.store.upsert(later)
    api.store.upsert(notes)

    seen = {}

    def fake_extract(creation, *, config, media_path, progress=None, cancel_event=None):
        seen["id"] = creation.get("id")
        return apply_extraction_fields(
            creation,
            text="TOASTER OCR",
            kind="ocr",
            model="gemini-2.5-flash",
            provider="gemini",
        )

    monkeypatch.setattr(
        "synthetic_text_extruder.extract_text.extract_text_from_creation",
        fake_extract,
    )
    res = api.create_creation(
        "Prompt",
        "General",
        "Custom",
        True,
        'extract the text from the image "a toaster on fire"',
        "doc_later",
        [],
        "",
        ["doc_toast", "doc_notes", "doc_later"],
    )
    assert res["ok"] is True, res
    job = _wait_job(api, res["job_id"])
    assert job["status"] == "done", job
    assert seen.get("id") == "doc_toast"
    assert job["result"]["id"] == "doc_toast"
    assert get_extracted_text(job["result"]) == "TOASTER OCR"


def test_create_creation_extract_unknown_quoted_source_errors(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    img = build_media_creation(
        modality="image",
        prompt="harbor",
        media_path="media/h.png",
        mime_type="image/png",
        title="harbor",
        creation_id="doc_later",
    )
    api.store.upsert(img)
    res = api.create_creation(
        "Prompt",
        "General",
        "Custom",
        True,
        'extract the text from the image "a toaster on fire"',
        "doc_later",
        [],
        "",
        ["doc_later"],
    )
    assert res["ok"] is False
    assert "toaster on fire" in (res.get("error") or "")


def test_create_creation_transcribe_from_studio_prompt(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "doc_studio_talk.mp4").write_bytes(b"fake-mp4")
    creation = build_media_creation(
        modality="video",
        prompt="talk",
        media_path="media/doc_studio_talk.mp4",
        mime_type="video/mp4",
        title="Talk",
        creation_id="doc_studio_talk",
    )
    api.store.upsert(creation)

    def fake_extract(creation, *, config, media_path, progress=None, cancel_event=None):
        return apply_extraction_fields(
            creation,
            text="HELLO FROM THE CLIP",
            kind="transcript",
            model="gemini-2.5-flash",
            provider="gemini",
        )

    monkeypatch.setattr(
        "synthetic_text_extruder.extract_text.extract_text_from_creation",
        fake_extract,
    )
    monkeypatch.setattr(
        "synthetic_text_extruder.video_edit.extract_video_frame_png",
        lambda *a, **k: b"\x89PNG\r\n\x1a\nframe",
    )

    res = api.create_creation(
        "Prompt",
        "General",
        "Custom",
        True,
        "transcribe this video",
        "doc_studio_talk",
    )
    assert res["ok"] is True, res
    job = _wait_job(api, res["job_id"])
    assert job["status"] == "done", job
    assert get_extracted_text(job["result"]) == "HELLO FROM THE CLIP"
    assert job["result"]["meta"]["extractionKind"] == "transcript"


def test_generate_creation_extract_text_requires_basis():
    from synthetic_text_extruder.generator import generate_creation

    try:
        generate_creation(
            game="Prompt",
            platform="General",
            creation_type="Custom",
            config={
                "backend": {"provider": "gemini"},
                "gemini": {"text_model": "gemini-2.5-flash", "api_key": "test-key"},
            },
            exact_title=True,
            creation_description="extract the text",
        )
    except RuntimeError as exc:
        assert "Studio basis" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when no media basis")
