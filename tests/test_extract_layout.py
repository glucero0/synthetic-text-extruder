"""Tests for Studio layout-extract helpers and API."""

from __future__ import annotations

import base64
import threading
from struct import pack

from synthetic_text_extruder.api import Api
from synthetic_text_extruder.creation_utils import build_media_creation
from synthetic_text_extruder.extract_layout import (
    apply_layout_fields,
    clear_layout_fields,
    format_layout_basis_prompt,
    get_extracted_layout,
    image_size_from_bytes,
    normalize_layout,
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


def test_image_size_from_png_ihdr():
    raw = (
        b"\x89PNG\r\n\x1a\n"
        + pack(">I", 13)
        + b"IHDR"
        + pack(">II", 320, 240)
        + b"\x00\x00\x00\x00"
    )
    assert image_size_from_bytes(raw) == (320, 240)


def test_normalize_layout_clamps_types_and_flags():
    layout = normalize_layout(
        {
            "isUi": True,
            "confidence": 1.4,
            "width": 200,
            "height": 100,
            "elements": [
                {
                    "id": "win",
                    "type": "dialog",
                    "label": "Save",
                    "box": {"x": 10, "y": 10, "w": 80, "h": 40},
                    "parentId": "missing",
                },
                {
                    "id": "ok",
                    "type": "button",
                    "label": "",
                    "box": {"x": 20, "y": 20, "w": 30, "h": 16},
                    "parentId": "win",
                },
                {
                    "id": "gone",
                    "type": "button",
                    "box": {"x": 0, "y": 0, "w": 0, "h": 10},
                },
            ],
            "flags": [{"code": "made_up", "elementId": "ok"}],
        },
        image_size=(200, 100),
    )
    assert layout["confidence"] == 1.0
    assert layout["width"] == 200
    assert layout["height"] == 100
    by_id = {el["id"]: el for el in layout["elements"]}
    assert "gone" not in by_id
    assert by_id["win"]["type"] == "other"
    assert by_id["win"]["parentId"] is None
    assert by_id["ok"]["parentId"] == "win"
    codes = {(f["code"], f["elementId"]) for f in layout["flags"]}
    assert ("made_up", "ok") not in codes
    assert ("unlabeled_control", "ok") in codes


def test_normalize_layout_overflow_and_parent_flags():
    layout = normalize_layout(
        {
            "isUi": True,
            "confidence": 0.9,
            "elements": [
                {
                    "id": "win",
                    "type": "window",
                    "label": "App",
                    "box": {"x": 0, "y": 0, "w": 80, "h": 80},
                },
                {
                    "id": "btn",
                    "type": "button",
                    "label": "OK",
                    "box": {"x": 70, "y": 10, "w": 40, "h": 20},
                    "parentId": "win",
                },
                {
                    "id": "edge",
                    "type": "image",
                    "label": "logo",
                    "box": {"x": 90, "y": 90, "w": 40, "h": 40},
                },
            ],
        },
        image_size=(100, 100),
    )
    codes = {(f["code"], f["elementId"]) for f in layout["flags"]}
    assert ("overflow_parent", "btn") in codes
    assert ("overlap_parent", "btn") in codes
    assert ("overflow", "edge") in codes
    edge = next(el for el in layout["elements"] if el["id"] == "edge")
    assert edge["box"]["x"] + edge["box"]["w"] <= 100
    assert edge["box"]["y"] + edge["box"]["h"] <= 100


def test_normalize_layout_not_ui():
    layout = normalize_layout({"isUi": False, "elements": []}, image_size=(64, 64))
    assert layout["isUi"] is False
    assert any(f["code"] == "not_ui" for f in layout["flags"])


def test_apply_and_clear_layout_fields():
    creation = build_media_creation(
        modality="image",
        prompt="dialog",
        media_path="media/a.png",
        mime_type="image/png",
        title="Shot",
        creation_id="doc_layout_a",
    )
    layout = normalize_layout(
        {
            "isUi": True,
            "elements": [
                {
                    "id": "e1",
                    "type": "button",
                    "label": "OK",
                    "box": {"x": 1, "y": 1, "w": 10, "h": 10},
                }
            ],
        },
        image_size=(32, 32),
    )
    updated = apply_layout_fields(
        creation,
        layout=layout,
        model="gemini-2.5-flash",
        provider="gemini",
        source="image",
    )
    stored = get_extracted_layout(updated)
    assert stored is not None
    assert stored["elements"][0]["label"] == "OK"
    assert updated["meta"]["layoutExtractionModel"] == "gemini-2.5-flash"
    assert updated["meta"]["layoutSource"] == "image"

    cleared = clear_layout_fields(updated)
    assert get_extracted_layout(cleared) is None
    assert "layoutExtractionModel" not in (cleared.get("meta") or {})


def test_extract_creation_layout_rejects_text_doc(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    text_doc = {
        "id": "doc_t_layout",
        "modality": "text",
        "title": "Note",
        "overview": "hello",
        "sections": [{"title": "Response", "content": "hello"}],
    }
    api.store.upsert(text_doc)
    res = api.extract_creation_layout("doc_t_layout")
    assert res["ok"] is False
    assert "image or video" in (res.get("error") or "").lower()


def test_extract_creation_layout_job_persists(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "doc_layout_img.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    creation = build_media_creation(
        modality="image",
        prompt="dialog",
        media_path="media/doc_layout_img.png",
        mime_type="image/png",
        title="Shot",
        creation_id="doc_layout_img",
    )
    api.store.upsert(creation)

    layout = {
        "isUi": True,
        "confidence": 0.8,
        "width": 100,
        "height": 80,
        "elements": [
            {
                "id": "e1",
                "type": "button",
                "label": "OK",
                "box": {"x": 4, "y": 4, "w": 20, "h": 12},
                "parentId": None,
            }
        ],
        "flags": [],
    }

    def fake_extract(creation, *, config, media_path, progress=None, cancel_event=None):
        return apply_layout_fields(
            creation,
            layout=layout,
            model="gemini-2.5-flash",
            provider="gemini",
            source="image",
        )

    monkeypatch.setattr(
        "synthetic_text_extruder.extract_layout.extract_layout_from_creation",
        fake_extract,
    )

    res = api.extract_creation_layout("doc_layout_img")
    assert res["ok"] is True
    job = _wait_job(api, res["job_id"])
    assert job["status"] == "done", job
    assert get_extracted_layout(job["result"])["elements"][0]["label"] == "OK"
    stored = next(c for c in api.store.load() if c["id"] == "doc_layout_img")
    assert get_extracted_layout(stored)["elements"][0]["id"] == "e1"


def test_create_creation_extract_layout_from_studio_prompt(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "doc_studio_extract.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00\x00\x00\x01\x00\x00\x00\x01" + b"\x00\x00\x00\x00"
    )
    creation = build_media_creation(
        modality="image",
        prompt="dialog",
        media_path="media/doc_studio_extract.png",
        mime_type="image/png",
        title="Shot",
        creation_id="doc_studio_extract",
    )
    api.store.upsert(creation)

    layout = {
        "isUi": True,
        "confidence": 0.8,
        "width": 100,
        "height": 80,
        "elements": [
            {
                "id": "e1",
                "type": "button",
                "label": "OK",
                "box": {"x": 4, "y": 4, "w": 20, "h": 12},
                "parentId": None,
            }
        ],
        "flags": [],
    }

    def fake_extract(raw, *, config, mime_type="image/png", progress=None, cancel_event=None):
        return layout, "gemini-2.5-flash"

    monkeypatch.setattr(
        "synthetic_text_extruder.extract_layout.extract_layout_from_image_bytes",
        fake_extract,
    )

    res = api.create_creation(
        "Prompt",
        "General",
        "Custom",
        True,
        "extract the layout",
        "doc_studio_extract",
    )
    assert res["ok"] is True, res
    job = _wait_job(api, res["job_id"])
    assert job["status"] == "done", job
    assert job["result"]["id"] == "doc_studio_extract"
    assert get_extracted_layout(job["result"])["elements"][0]["label"] == "OK"
    stored = next(c for c in api.store.load() if c["id"] == "doc_studio_extract")
    assert get_extracted_layout(stored)["elements"][0]["id"] == "e1"


def test_replace_creation_media_clears_layout(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    (tmp_path / "media").mkdir(parents=True, exist_ok=True)
    creation = build_media_creation(
        modality="image",
        prompt="dialog",
        media_path="media/doc_layout_replace.png",
        mime_type="image/png",
        title="Shot",
        creation_id="doc_layout_replace",
    )
    creation = apply_layout_fields(
        creation,
        layout={"isUi": True, "elements": [], "flags": []},
        model="m",
        provider="gemini",
        source="image",
    )
    api.store.upsert(creation)

    png = base64.b64encode(b"\x89PNG\r\n\x1a\nedited").decode("ascii")
    res = api.replace_creation_media(
        "doc_layout_replace",
        f"data:image/png;base64,{png}",
        "image/png",
    )
    assert res["ok"] is True
    assert get_extracted_layout(res["creation"]) is None


def test_format_layout_basis_prompt_appends_once():
    layout = {
        "isUi": True,
        "elements": [{"id": "e1", "type": "button", "label": "OK"}],
        "flags": [],
    }
    first = format_layout_basis_prompt(layout, existing="")
    assert "Layout JSON:" in first
    assert '"e1"' in first
    again = format_layout_basis_prompt(layout, existing=first)
    assert again == first
    combined = format_layout_basis_prompt(layout, existing="Make a Win32 clone")
    assert combined.startswith("Make a Win32 clone")
    assert "Layout JSON:" in combined


def test_resolve_basis_media_includes_extracted_layout(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    (tmp_path / "media").mkdir(parents=True, exist_ok=True)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + b"\x00\x00\x00\x01\x00\x00\x00\x01"
        + b"\x00\x00\x00\x00"
    )
    (tmp_path / "media" / "doc_layout_basis.png").write_bytes(png)
    creation = build_media_creation(
        modality="image",
        prompt="dialog",
        media_path="media/doc_layout_basis.png",
        mime_type="image/png",
        title="Shot",
        creation_id="doc_layout_basis",
    )
    layout = {"isUi": True, "elements": [], "flags": []}
    creation = apply_layout_fields(
        creation, layout=layout, model="m", provider="gemini", source="image"
    )
    api.store.upsert(creation)
    payload = api._resolve_basis_media("doc_layout_basis")
    assert payload["modality"] == "image"
    assert payload["extracted_layout"]["isUi"] is True
    assert payload["bytes"]
    assert payload["source_creation"]["id"] == "doc_layout_basis"


def test_generate_creation_extracts_layout_from_studio_basis(monkeypatch):
    from synthetic_text_extruder.generator import generate_creation

    source = build_media_creation(
        modality="image",
        prompt="dialog",
        media_path="media/shot.png",
        mime_type="image/png",
        title="Shot",
        creation_id="doc_studio_layout",
    )
    layout = {
        "isUi": True,
        "confidence": 0.9,
        "width": 100,
        "height": 80,
        "elements": [
            {
                "id": "ok",
                "type": "button",
                "label": "OK",
                "box": {"x": 4, "y": 4, "w": 20, "h": 12},
                "parentId": None,
            }
        ],
        "flags": [],
    }

    def fake_extract(raw, *, config, mime_type="image/png", progress=None, cancel_event=None):
        assert raw
        return layout, "gemini-2.5-flash"

    monkeypatch.setattr(
        "synthetic_text_extruder.extract_layout.extract_layout_from_image_bytes",
        fake_extract,
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("layout extract must not call generate_with_gemini")

    monkeypatch.setattr(
        "synthetic_text_extruder.gemini_provider.generate_with_gemini",
        fail_generate,
    )

    result = generate_creation(
        game="Prompt",
        platform="General",
        creation_type="Custom",
        config={
            "backend": {"provider": "gemini"},
            "gemini": {"text_model": "gemini-2.5-flash", "api_key": "test-key"},
        },
        exact_title=True,
        creation_description="extract the layout",
        basis_media={
            "modality": "image",
            "bytes": b"\x89PNG\r\n\x1a\nfake",
            "mime_type": "image/png",
            "creation_id": source["id"],
            "source_creation": source,
        },
    )
    assert result["id"] == "doc_studio_layout"
    assert result["modality"] == "image"
    stored = get_extracted_layout(result)
    assert stored["elements"][0]["label"] == "OK"
    assert result["meta"]["layoutExtractionModel"] == "gemini-2.5-flash"


def test_generate_creation_extract_layout_requires_basis():
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
            creation_description="extract the layout",
        )
    except RuntimeError as exc:
        assert "Studio basis" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when no media basis")
