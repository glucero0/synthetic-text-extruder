"""Collection jobs: planner, folder collections, magazine PDF helpers."""

from __future__ import annotations

from pathlib import Path

from synthetic_text_extruder.api import Api
from synthetic_text_extruder.collection_jobs import (
    MAX_COLLECTION_ITEMS,
    build_collection_creation,
    expand_collection_members,
    is_collection_creation,
    plan_collection_job,
    wants_collection_job,
)
from synthetic_text_extruder.creation_utils import (
    build_media_creation,
)
from synthetic_text_extruder.document_reconstruct import (
    normalize_page_analysis,
    parse_page_analysis,
)
from synthetic_text_extruder.image_batch import parse_filters_from_prompt
from synthetic_text_extruder.pdf_build import article_pdf, images_to_pdf
from synthetic_text_extruder.storage import ArchiveStore
from synthetic_text_extruder.studio_sources import (
    MAX_SOURCES,
    list_source_files_in_folder,
    wants_source_report,
)


def _png_bytes() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 40, 40)).save(buf, format="PNG")
    return buf.getvalue()


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


def test_plan_collection_job_kinds():
    assert plan_collection_job("skip ads and reconstruct a magazine PDF")["kind"] == "magazine"
    assert plan_collection_job("make a flipbook")["kind"] == "flipbook"
    assert plan_collection_job("contact sheet of these")["kind"] == "contact_sheet"
    assert plan_collection_job("apply sepia and sharpen to every image")["kind"] == "filters"
    assert plan_collection_job("OCR every scan")["kind"] == "ocr"
    assert plan_collection_job("put them all in one PDF")["kind"] == "assemble_pdf"
    assert plan_collection_job("write a report", has_collection=True)["kind"] == "report"
    assert plan_collection_job("summarize", has_collection=True)["kind"] == "report"
    assert plan_collection_job("describe each photo", has_collection=True)["kind"] == "generic_map"


def test_wants_collection_job_does_not_steal_single_extract_or_report():
    img = {"id": "a", "modality": "image"}
    notes = {"id": "n", "modality": "text"}
    later = {"id": "b", "modality": "image"}
    assert wants_collection_job("extract the text", [img, notes]) is False
    assert wants_collection_job("write a report", [img, notes]) is False
    assert wants_source_report("write a report", [img, notes]) is True
    assert wants_collection_job("OCR every image", [img, later]) is True


def test_parse_filters_from_prompt():
    filt = parse_filters_from_prompt("grayscale and +20 contrast, sharpen")
    assert filt.get("grayscale") is True
    assert filt.get("contrast") == 20
    assert filt.get("sharpen") is True
    assert parse_filters_from_prompt("hello") == {}


def test_expand_collection_members_uses_snapshots():
    members = [
        build_media_creation(
            modality="image",
            prompt="p",
            media_path="media/a.png",
            mime_type="image/png",
            title="A",
            creation_id="doc_a",
        ),
        build_media_creation(
            modality="image",
            prompt="p",
            media_path="media/b.png",
            mime_type="image/png",
            title="B",
            creation_id="doc_b",
        ),
    ]
    col = build_collection_creation(members, folder_name="Scans")
    assert is_collection_creation(col)
    assert col["meta"]["collection"]["count"] == 2
    assert {e["id"] for e in col.get("derivedFrom") or []} == {"doc_a", "doc_b"}
    expanded = expand_collection_members([col])
    assert [c["id"] for c in expanded] == ["doc_a", "doc_b"]


def test_list_source_files_in_folder_recursive(tmp_path):
    folder = tmp_path / "bundle"
    nested = folder / "nested"
    nested.mkdir(parents=True)
    (folder / "shot.png").write_bytes(b"\x89PNG")
    (nested / "inner.txt").write_text("hi", encoding="utf-8")
    (nested / ".hidden.txt").write_text("no", encoding="utf-8")
    names = {p.name for p in list_source_files_in_folder(folder)}
    assert names == {"shot.png"}
    rec = {p.name for p in list_source_files_in_folder(folder, recursive=True)}
    assert rec == {"shot.png", "inner.txt"}


def test_import_overflow_becomes_collection(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    (tmp_path / "media").mkdir(parents=True, exist_ok=True)
    png = _png_bytes()
    paths = []
    for i in range(MAX_SOURCES + 2):
        p = tmp_path / f"p{i:02d}.png"
        p.write_bytes(png)
        paths.append(p)
    res = api._import_source_paths(paths, already=0, folder_name="MagazineScan")
    assert res["ok"] is True
    assert res.get("collection") is True
    assert len(res["creations"]) == 1
    col = res["creations"][0]
    assert is_collection_creation(col)
    assert col["meta"]["collection"]["count"] == MAX_SOURCES + 2


def test_import_source_paths_respects_empty_tray_cap(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    paths = []
    for i in range(3):
        p = tmp_path / f"n{i}.txt"
        p.write_text("x", encoding="utf-8")
        paths.append(p)
    res = api._import_source_paths(paths, already=MAX_SOURCES)
    assert res["ok"] is False
    assert "limited" in (res.get("error") or "").lower()


def test_import_overflow_with_one_slot_is_collection(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    paths = []
    for i in range(3):
        p = tmp_path / f"n{i}.txt"
        p.write_text("x", encoding="utf-8")
        paths.append(p)
    res = api._import_source_paths(paths, already=MAX_SOURCES - 1)
    assert res["ok"] is True
    assert res.get("collection") is True
    assert len(res["creations"]) == 1


def test_normalize_page_analysis_skips_ads():
    page = normalize_page_analysis(
        {
            "pageKind": "ad",
            "skipPage": False,
            "bodyText": "BUY NOW",
            "photos": [{"box": [0.1, 0.1, 0.2, 0.2], "caption": "x"}],
        }
    )
    assert page["skipPage"] is True
    assert page["photos"][0]["box"][0] == 0.1
    parsed = parse_page_analysis('{"pageKind":"editorial","skipPage":false,"bodyText":"Hello"}')
    assert parsed["bodyText"] == "Hello"


def test_article_pdf_and_images_pdf(tmp_path):
    png = tmp_path / "a.png"
    png.write_bytes(_png_bytes())
    stack = images_to_pdf([png], title="Stack")
    assert stack.startswith(b"%PDF")
    article = article_pdf(
        title="Harbor",
        sections=[
            {"heading": "One", "paragraphs": ["Calm water."], "photoPath": str(png), "photoCaption": "Still"},
        ],
        skipped_ads=[{"filename": "ad.png", "reason": "Full-page ad"}],
    )
    assert article.startswith(b"%PDF")


def test_generate_creation_routes_collection_job(monkeypatch):
    from synthetic_text_extruder.generator import generate_creation

    col = build_collection_creation(
        [
            build_media_creation(
                modality="image",
                prompt="p",
                media_path="media/a.png",
                mime_type="image/png",
                title="A",
                creation_id="doc_a",
            )
        ],
        folder_name="Scans",
    )
    called = {}

    def fake_run(sources, **kwargs):
        called["kind"] = True
        called["prompt"] = kwargs.get("prompt")
        return {"id": "doc_out", "modality": "text", "title": "ok"}

    monkeypatch.setattr(
        "synthetic_text_extruder.collection_jobs.run_collection_job", fake_run
    )
    result = generate_creation(
        "Prompt",
        "General",
        "Custom",
        {"gemini": {"text_model": "gemini-2.5-flash", "api_key": "x"}},
        creation_description="OCR every scan",
        source_creations=[col],
    )
    assert called["kind"] is True
    assert result["id"] == "doc_out"


def test_gemini_media_part_uploads_when_large(monkeypatch):
    from synthetic_text_extruder.extract_text import (
        MAX_INLINE_BYTES,
        _gemini_media_part,
    )

    class _Types:
        class Part:
            @staticmethod
            def from_bytes(**kwargs):
                return ("inline", kwargs.get("mime_type"))

    class _Uploaded:
        name = "files/abc"
        state = type("S", (), {"name": "ACTIVE"})()

    class _Files:
        def upload(self, **kwargs):
            return _Uploaded()

        def get(self, name):
            return _Uploaded()

        def delete(self, name):
            return None

    class _Client:
        files = _Files()

    part, uploaded = _gemini_media_part(
        _Client(),
        _Types,
        data=b"x" * (MAX_INLINE_BYTES + 10),
        mime_type="image/png",
        cancel_check=lambda: False,
    )
    assert uploaded is not None
    assert getattr(part, "name", None) == "files/abc"

    inline, none = _gemini_media_part(
        _Client(),
        _Types,
        data=b"small",
        mime_type="image/png",
        cancel_check=lambda: False,
    )
    assert none is None
    assert inline[0] == "inline"


def test_apply_still_filters_grayscale(tmp_path):
    from PIL import Image

    from synthetic_text_extruder.image_batch import apply_still_filters

    src = tmp_path / "in.png"
    dest = tmp_path / "out.png"
    Image.new("RGB", (12, 12), (200, 10, 10)).save(src)
    apply_still_filters(src, dest, {"grayscale": True})
    out = Image.open(dest)
    px = out.convert("RGB").getpixel((0, 0))
    assert px[0] == px[1] == px[2]


def test_crop_photo_boxes(tmp_path):
    from PIL import Image

    from synthetic_text_extruder.document_reconstruct import crop_photo_boxes

    src = tmp_path / "page.png"
    Image.new("RGB", (100, 100), (20, 80, 180)).save(src)
    crops = crop_photo_boxes(
        src,
        [{"box": [0.1, 0.1, 0.4, 0.4], "caption": "blue"}],
        dest_dir=tmp_path / "crops",
        stem="page",
    )
    assert len(crops) == 1
    assert Path(crops[0]["photoPath"]).is_file()


def test_max_collection_items_constant():
    assert MAX_COLLECTION_ITEMS >= 34
    assert MAX_COLLECTION_ITEMS > MAX_SOURCES
