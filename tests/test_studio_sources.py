"""Studio Sources gather/report routing and folder import helpers."""

from __future__ import annotations

import threading
from pathlib import Path

from synthetic_text_extruder.api import Api
from synthetic_text_extruder.creation_utils import (
    build_media_creation,
    build_text_creation_from_plain,
)
from synthetic_text_extruder.generator import generate_creation
from synthetic_text_extruder.storage import ArchiveStore
from synthetic_text_extruder.studio_sources import (
    MAX_SOURCES,
    creation_source_modality,
    gather_source_briefs,
    last_visual_source,
    list_source_files_in_folder,
    match_quoted_source,
    normalize_report_layout,
    snapshot_report_figures,
    wants_source_report,
)


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


def test_creation_source_modality_pdf_and_mime():
    assert creation_source_modality({"modality": "pdf"}) == "pdf"
    assert (
        creation_source_modality({"modality": "text", "mimeType": "application/pdf"})
        == "pdf"
    )
    assert creation_source_modality({"modality": "image"}) == "image"


def test_wants_source_report_two_sources_default():
    img = {"id": "a", "modality": "image"}
    pdf = {"id": "b", "modality": "pdf"}
    assert wants_source_report("write a report", [img, pdf]) is True
    assert wants_source_report("", [img, pdf]) is True
    assert wants_source_report("generate a video of the harbor", [img, pdf]) is False
    assert wants_source_report("create an image of both", [img, pdf]) is False
    report_prompt = (
        'create a report, include a summary of the video, "doc_1c9b1302da.mp4", '
        'the image, "doc_7b759c704e.jpg", and the story from '
        '"a_very_short_story_of_a_dog_being_rescued_by_a_family_of_thr.txt"'
    )
    vid = {"id": "doc_1c9b1302da", "modality": "video", "title": "clip"}
    assert wants_source_report(report_prompt, [img, pdf, vid]) is True


def test_wants_source_report_single_visual_keeps_extract_and_edit():
    img = {"id": "a", "modality": "image"}
    assert wants_source_report("extract the text", [img]) is False
    assert wants_source_report("transcribe this clip", [img]) is False
    assert wants_source_report("extract the layout", [img]) is False
    assert wants_source_report("make it darker", [img]) is False
    assert wants_source_report("write a report about this image", [img]) is True
    assert wants_source_report("summarize", [{"id": "v", "modality": "video"}]) is True


def test_wants_source_report_single_text_pdf_audio():
    assert wants_source_report("summarize", [{"id": "t", "modality": "text"}]) is True
    assert wants_source_report("summarize", [{"id": "p", "modality": "pdf"}]) is True
    assert wants_source_report("transcribe", [{"id": "a", "modality": "audio"}]) is True
    assert (
        wants_source_report(
            "compose a song about this", [{"id": "a", "modality": "audio"}]
        )
        is False
    )


def test_last_visual_source_prefers_later_item():
    text = {"id": "t", "modality": "text"}
    img = {"id": "i", "modality": "image"}
    vid = {"id": "v", "modality": "video"}
    assert last_visual_source([text, img, vid])["id"] == "v"
    assert last_visual_source([text]) is None


def test_wants_source_report_extract_named_image_among_many():
    toaster = {
        "id": "doc_toast",
        "modality": "image",
        "title": "a toaster on fire",
    }
    notes = {"id": "doc_notes", "modality": "text", "title": "Notes"}
    later = {"id": "doc_later", "modality": "image", "title": "harbor"}
    prompt = 'extract the text from the image "a toaster on fire"'
    assert wants_source_report(prompt, [toaster, notes, later]) is False
    assert wants_source_report("extract the text", [toaster, notes]) is False
    assert wants_source_report("write a report", [toaster, notes]) is True


def test_match_quoted_source_by_title_and_filename():
    toaster = {
        "id": "doc_toast",
        "modality": "image",
        "title": "a toaster on fire",
        "meta": {"originalFilename": "toaster-on-fire.png"},
    }
    later = {
        "id": "doc_later",
        "modality": "image",
        "title": "harbor",
        "meta": {"originalFilename": "harbor.png"},
    }
    notes = {"id": "doc_notes", "modality": "text", "title": "Notes"}
    sources = [toaster, notes, later]
    hit, err = match_quoted_source(
        'extract text from the image "a toaster on fire"',
        sources,
        modalities={"image", "video"},
    )
    assert err == ""
    assert hit["id"] == "doc_toast"
    hit, err = match_quoted_source(
        'extract the text from "toaster-on-fire.png"',
        sources,
        modalities={"image", "video"},
    )
    assert err == ""
    assert hit["id"] == "doc_toast"
    hit, err = match_quoted_source(
        'extract the text from "missing-shot.png"',
        sources,
        modalities={"image", "video"},
    )
    assert hit is None
    assert "missing-shot.png" in err
    hit, err = match_quoted_source(
        'extract the text from "Notes"',
        sources,
        modalities={"image", "video"},
    )
    assert hit is None
    assert "not an image or video" in err


def test_safe_original_filename_is_basename_only():
    from synthetic_text_extruder.studio_sources import (
        original_filename_for_creation,
        safe_original_filename,
    )

    assert safe_original_filename(r"C:\inbox\harbor-notes.pdf") == "harbor-notes.pdf"
    assert safe_original_filename("../etc/passwd") == "passwd"
    assert safe_original_filename("..") == ""
    assert original_filename_for_creation(
        {"meta": {"originalFilename": "clip.mp4"}, "title": "Other"}
    ) == "clip.mp4"
    assert original_filename_for_creation(
        {"prompt": "Imported from brief.pdf", "title": "brief"}
    ) == "brief.pdf"


def test_gather_text_source_does_not_call_gemini():
    creation = build_text_creation_from_plain(
        "Harbor notes body", prompt="notes", title="Notes"
    )
    briefs = gather_source_briefs([creation], config={})
    assert len(briefs) == 1
    assert briefs[0]["brief"] == "Harbor notes body"
    assert briefs[0]["title"] == "Notes"
    assert not briefs[0]["error"]


def test_list_source_files_in_folder_skips_hidden_and_unknown(tmp_path):
    folder = tmp_path / "bundle"
    folder.mkdir()
    (folder / "notes.txt").write_text("hi", encoding="utf-8")
    (folder / "shot.png").write_bytes(b"\x89PNG")
    (folder / "brief.pdf").write_bytes(b"%PDF-1.4")
    (folder / ".secret.txt").write_text("nope", encoding="utf-8")
    (folder / "skip.exe").write_bytes(b"MZ")
    nested = folder / "nested"
    nested.mkdir()
    (nested / "inner.txt").write_text("nope", encoding="utf-8")
    files = list_source_files_in_folder(folder)
    names = {p.name for p in files}
    assert names == {"notes.txt", "shot.png", "brief.pdf"}


def test_import_source_paths_pdf_and_text(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    (tmp_path / "media").mkdir(parents=True, exist_ok=True)
    text_path = tmp_path / "memo.txt"
    text_path.write_text("Memo body", encoding="utf-8")
    pdf_path = tmp_path / "spec.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    res = api._import_source_paths([text_path, pdf_path], already=0)
    assert res["ok"] is True
    mods = {c["modality"] for c in res["creations"]}
    assert mods == {"text", "pdf"}
    pdf = next(c for c in res["creations"] if c["modality"] == "pdf")
    assert pdf["mimeType"] == "application/pdf"
    assert pdf["meta"]["originalFilename"] == "spec.pdf"
    notes = next(c for c in res["creations"] if c["modality"] == "text")
    assert notes["meta"]["originalFilename"] == "memo.txt"
    stored = tmp_path / "media" / Path(pdf["mediaPath"]).name
    assert stored.is_file()


def test_import_source_paths_respects_cap(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    paths = []
    for i in range(3):
        p = tmp_path / f"n{i}.txt"
        p.write_text("x", encoding="utf-8")
        paths.append(p)
    res = api._import_source_paths(paths, already=MAX_SOURCES)
    assert res["ok"] is False
    assert "limited" in (res.get("error") or "").lower()


def test_generate_creation_routes_multi_source_to_report(monkeypatch):
    img = build_media_creation(
        modality="image",
        prompt="harbor",
        media_path="media/h.png",
        mime_type="image/png",
        title="Harbor",
        creation_id="doc_img",
    )
    notes = build_text_creation_from_plain("Notes", prompt="notes", title="Notes")
    called = {}

    def fake_gather(sources, **kwargs):
        called["sources"] = sources
        called["user_prompt"] = kwargs.get("user_prompt")
        return {
            "id": "doc_report",
            "modality": "text",
            "meta": {"studioJob": "report"},
            "sections": [{"title": "", "content": "combined", "keyValues": []}],
        }

    monkeypatch.setattr(
        "synthetic_text_extruder.studio_sources.gather_then_synthesize",
        fake_gather,
    )
    result = generate_creation(
        "Prompt",
        "General",
        "Custom",
        config={"gemini": {"text_model": "gemini-2.5-flash"}},
        exact_title=True,
        creation_description="Write a report",
        source_creations=[img, notes],
    )
    assert result["id"] == "doc_report"
    assert called["user_prompt"] == "Write a report"
    assert [c["id"] for c in called["sources"]] == ["doc_img", notes["id"]]


def test_create_creation_report_job(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    img = build_media_creation(
        modality="image",
        prompt="harbor",
        media_path="media/h.png",
        mime_type="image/png",
        title="Harbor",
        creation_id="doc_img",
    )
    notes = build_text_creation_from_plain("Notes", prompt="notes", title="Notes")
    notes["id"] = "doc_notes"
    api.store.upsert(img)
    api.store.upsert(notes)

    def fake_gather(*args, **kwargs):
        return build_text_creation_from_plain(
            "Combined report",
            prompt="Write a report",
            title="Harbor report",
            model_info={"provider": "gemini", "repo_id": "test"},
        ) | {"meta": {"studioJob": "report"}}

    monkeypatch.setattr(
        "synthetic_text_extruder.studio_sources.gather_then_synthesize",
        fake_gather,
    )
    res = api.create_creation(
        "Prompt",
        "General",
        "Custom",
        True,
        "Write a report",
        "doc_img",
        [],
        "",
        ["doc_img", "doc_notes"],
    )
    assert res["ok"] is True, res
    job = _wait_job(api, res["job_id"])
    assert job["status"] == "done", job
    assert (job["result"].get("meta") or {}).get("studioJob") == "report"
    assert "Combined report" in (job["result"]["sections"][0]["content"] or "")


_MIN_PNG = b"\x89PNG\r\n\x1a\n" + b"fake-harbor"


def test_normalize_report_layout_maps_source_ids_and_appends_unused():
    figures = [
        {"id": "fig_0", "sourceId": "doc_img", "title": "Harbor"},
        {"id": "fig_1", "sourceId": "doc_clip", "title": "Clip"},
    ]
    layout = normalize_report_layout(
        {
            "title": "**Harbor notes**",
            "sections": [
                {
                    "heading": "Photo",
                    "paragraphs": ["Calm **water**."],
                    "figureSourceId": "doc_img",
                    "figureCaption": "The harbor",
                }
            ],
        },
        figures,
        fallback_title="Fallback",
        fallback_body="unused",
    )
    assert layout["title"] == "Harbor notes"
    assert layout["sections"][0]["figureId"] == "fig_0"
    assert layout["sections"][0]["paragraphs"] == ["Calm water."]
    leftover = layout["sections"][-1]
    assert leftover["figureId"] == "fig_1"
    assert leftover["figureCaption"] == "Clip"


def test_normalize_report_layout_plain_fallback_strips_markdown():
    figures = [{"id": "fig_0", "sourceId": "a", "title": "Shot"}]
    layout = normalize_report_layout(
        None,
        figures,
        fallback_title="Report",
        fallback_body="Hello **world**\n\nSecond.",
    )
    assert layout["title"] == "Report"
    assert layout["sections"][0]["paragraphs"][0] == "Hello world"
    assert layout["sections"][-1]["figureId"] == "fig_0"


def test_snapshot_report_figures_copies_image_skips_text(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    png = media / "h.png"
    png.write_bytes(_MIN_PNG)
    monkeypatch.setattr("synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "synthetic_text_extruder.media_store.load_config",
        lambda: {"paths": {"media": "media"}},
    )
    img = build_media_creation(
        modality="image",
        prompt="harbor",
        media_path="media/h.png",
        mime_type="image/png",
        title="Harbor",
        creation_id="doc_img",
    )
    notes = build_text_creation_from_plain("Notes", prompt="notes", title="Notes")
    config = {"paths": {"media": "media"}}
    figs = snapshot_report_figures([img, notes], report_id="doc_rep", config=config)
    assert len(figs) == 1
    assert figs[0]["sourceId"] == "doc_img"
    assert figs[0]["id"] == "fig_0"
    stored = tmp_path / figs[0]["mediaPath"]
    assert stored.is_file()
    assert stored.read_bytes() == _MIN_PNG


def test_snapshot_report_figures_skips_failed_video(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    (media / "c.mp4").write_bytes(b"not-a-video")
    monkeypatch.setattr("synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "synthetic_text_extruder.media_store.load_config",
        lambda: {"paths": {"media": "media"}},
    )
    monkeypatch.setattr(
        "synthetic_text_extruder.video_edit.extract_video_frame_png",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no ffmpeg")),
    )
    vid = build_media_creation(
        modality="video",
        prompt="clip",
        media_path="media/c.mp4",
        mime_type="video/mp4",
        title="Clip",
        creation_id="doc_vid",
    )
    figs = snapshot_report_figures(
        [vid], report_id="doc_rep", config={"paths": {"media": "media"}}
    )
    assert figs == []


def test_gather_then_synthesize_illustrated_layout(tmp_path, monkeypatch):
    import json

    from synthetic_text_extruder.studio_sources import gather_then_synthesize

    media = tmp_path / "media"
    media.mkdir()
    (media / "h.png").write_bytes(_MIN_PNG)
    monkeypatch.setattr("synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "synthetic_text_extruder.media_store.load_config",
        lambda: {"paths": {"media": "media"}},
    )
    img = build_media_creation(
        modality="image",
        prompt="harbor",
        media_path="media/h.png",
        mime_type="image/png",
        title="Harbor",
        creation_id="doc_img",
    )
    notes = build_text_creation_from_plain("Notes", prompt="notes", title="Notes")
    notes["id"] = "doc_notes"

    def fake_briefs(sources, **kwargs):
        return [
            {
                "id": "doc_img",
                "title": "Harbor",
                "modality": "image",
                "brief": "A harbor photo.",
                "error": "",
            },
            {
                "id": "doc_notes",
                "title": "Notes",
                "modality": "text",
                "brief": "Harbor notes body",
                "error": "",
            },
        ]

    def fake_gemini(*args, **kwargs):
        body = json.dumps(
            {
                "title": "Harbor report",
                "sections": [
                    {
                        "heading": "The photo",
                        "paragraphs": ["The harbor is calm."],
                        "figureSourceId": "doc_img",
                        "figureCaption": "Harbor still",
                    },
                    {
                        "heading": "Sources",
                        "paragraphs": ["Harbor", "Notes"],
                        "figureSourceId": "",
                        "figureCaption": "",
                    },
                ],
            }
        )
        return build_text_creation_from_plain(body, prompt="synth-internal", title="x")

    monkeypatch.setattr(
        "synthetic_text_extruder.studio_sources.gather_source_briefs",
        fake_briefs,
    )
    monkeypatch.setattr(
        "synthetic_text_extruder.gemini_provider.generate_with_gemini",
        fake_gemini,
    )
    result = gather_then_synthesize(
        [img, notes],
        game="Prompt",
        platform="General",
        creation_type="Custom",
        config={"paths": {"media": "media"}, "gemini": {}},
        user_prompt="Compare the photo to the notes",
    )
    assert result["prompt"] == "Compare the photo to the notes"
    assert result["title"] == "Harbor report"
    assert result["creationType"] == "Report"
    assert result["modality"] == "text"
    assert not result.get("mediaPath")
    layout = result["meta"]["reportLayout"]
    figs = result["meta"]["reportFigures"]
    assert result["meta"]["studioJob"] == "report"
    assert len(figs) == 1
    assert layout["sections"][0]["figureId"] == figs[0]["id"]
    assert layout["sections"][0]["figureCaption"] == "Harbor still"
    headings = [sec["heading"] for sec in layout["sections"]]
    assert headings.count("Sources") == 1
    stored = tmp_path / figs[0]["mediaPath"]
    assert stored.is_file()


def test_gather_then_synthesize_is_text_even_if_model_returns_video(
    tmp_path, monkeypatch
):
    import json

    from synthetic_text_extruder.studio_sources import gather_then_synthesize

    media = tmp_path / "media"
    media.mkdir()
    (media / "h.png").write_bytes(_MIN_PNG)
    (media / "c.mp4").write_bytes(b"not-a-video")
    monkeypatch.setattr("synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path)
    img = build_media_creation(
        modality="image",
        prompt="harbor",
        media_path="media/h.png",
        mime_type="image/png",
        title="Harbor",
        creation_id="doc_img",
    )
    notes = build_text_creation_from_plain("Notes", prompt="notes", title="Notes")
    notes["id"] = "doc_notes"

    def fake_gemini(*args, **kwargs):
        body = json.dumps(
            {
                "title": "Harbor report",
                "sections": [
                    {
                        "heading": "The photo",
                        "paragraphs": ["The harbor is calm."],
                        "figureSourceId": "doc_img",
                        "figureCaption": "Harbor still",
                    }
                ],
            }
        )
        leaked = build_media_creation(
            modality="video",
            prompt="synth-internal",
            media_path="media/c.mp4",
            mime_type="video/mp4",
            title="x",
        )
        leaked["sections"] = [{"title": "", "content": body, "keyValues": []}]
        return leaked

    monkeypatch.setattr(
        "synthetic_text_extruder.studio_sources.gather_source_briefs",
        lambda sources, **kwargs: [
            {
                "id": "doc_img",
                "title": "Harbor",
                "modality": "image",
                "brief": "A harbor photo.",
                "error": "",
            },
            {
                "id": "doc_notes",
                "title": "Notes",
                "modality": "text",
                "brief": "Harbor notes body",
                "error": "",
            },
        ],
    )
    monkeypatch.setattr(
        "synthetic_text_extruder.gemini_provider.generate_with_gemini",
        fake_gemini,
    )
    result = gather_then_synthesize(
        [img, notes],
        game="Prompt",
        platform="General",
        creation_type="Custom",
        config={"paths": {"media": "media"}, "gemini": {}},
        user_prompt="summarize",
    )
    assert result["modality"] == "text"
    assert not result.get("mediaPath")
    assert (result.get("meta") or {}).get("studioJob") == "report"


def test_gather_then_synthesize_unreadable_json_still_embeds_figures(
    tmp_path, monkeypatch
):
    from synthetic_text_extruder.studio_sources import gather_then_synthesize

    media = tmp_path / "media"
    media.mkdir()
    (media / "h.png").write_bytes(_MIN_PNG)
    monkeypatch.setattr("synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path)
    img = build_media_creation(
        modality="image",
        prompt="harbor",
        media_path="media/h.png",
        mime_type="image/png",
        title="Harbor",
        creation_id="doc_img",
    )
    notes = build_text_creation_from_plain("Notes", prompt="notes", title="Notes")
    notes["id"] = "doc_notes"

    monkeypatch.setattr(
        "synthetic_text_extruder.studio_sources.gather_source_briefs",
        lambda sources, **kwargs: [
            {
                "id": "doc_img",
                "title": "Harbor",
                "modality": "image",
                "brief": "A harbor photo.",
                "error": "",
            },
            {
                "id": "doc_notes",
                "title": "Notes",
                "modality": "text",
                "brief": "Harbor notes body",
                "error": "",
            },
        ],
    )
    monkeypatch.setattr(
        "synthetic_text_extruder.gemini_provider.generate_with_gemini",
        lambda *args, **kwargs: build_text_creation_from_plain(
            "{not-json", prompt="synth-internal", title="Broken"
        ),
    )
    result = gather_then_synthesize(
        [img, notes],
        game="Prompt",
        platform="General",
        creation_type="Custom",
        config={"paths": {"media": "media"}, "gemini": {}},
        user_prompt="Write a report",
    )
    figs = result["meta"]["reportFigures"]
    assert len(figs) == 1
    figure_ids = [
        sec["figureId"] for sec in result["meta"]["reportLayout"]["sections"]
    ]
    assert figs[0]["id"] in figure_ids
