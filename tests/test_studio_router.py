"""Studio CREATE classifier: policy prompt, JSON parse, regex fallback."""

from __future__ import annotations

import json

from synthetic_text_extruder.studio_router import (
    ask_gemini_router,
    build_router_model_prompt,
    classify_studio_job,
    fallback_classify,
    load_studio_router_fixtures,
    load_studio_router_prompt,
    parse_router_payload,
    sources_from_fixture,
)


def test_policy_prompt_states_report_over_video_invariants():
    text = load_studio_router_prompt()
    folded = text.casefold()
    assert "create a report" in folded
    assert "summarize" in folded
    assert "export pdf" in folded
    assert "choose `video`" in folded
    assert "extra instructions" in folded
    assert "derivedfrom" in folded
    assert "ancestors" in folded


def test_fixtures_match_regex_fallback():
    fixtures = load_studio_router_fixtures()
    assert len(fixtures) >= 10
    for entry in fixtures:
        sources = sources_from_fixture(entry)
        got = fallback_classify(entry.get("prompt") or "", sources)
        exp = entry.get("fallback") or entry["expected"]
        job = str(exp["job"])
        modality = str(exp.get("modality") or "")
        kind = str(exp.get("collectionKind") or "")
        assert got["job"] == job, entry.get("id")
        assert got["modality"] == modality, entry.get("id")
        if job == "collection":
            assert got["collectionKind"] == kind, entry.get("id")
        assert got["source"] == "fallback"


def test_llm_can_classify_summarize_into_video(monkeypatch):
    monkeypatch.setattr(
        "synthetic_text_extruder.studio_router._call_gemini_router",
        lambda *args, **kwargs: json.dumps(
            {
                "job": "video",
                "collectionKind": "",
                "modality": "video",
                "reason": "summarize into a video",
            }
        ),
    )
    got = classify_studio_job(
        "summarize this into a video",
        [{"id": "v", "modality": "video", "title": "clip"}],
        config={"gemini": {"api_key": "test-key"}},
    )
    assert got["job"] == "video"
    assert got["source"] == "llm"


def test_parse_router_payload_accepts_report_and_rejects_junk():
    parsed = parse_router_payload(
        json.dumps(
            {
                "job": "report",
                "collectionKind": "",
                "modality": "video",
                "reason": "user asked for a report summarizing a clip",
            }
        )
    )
    assert parsed is not None
    assert parsed["job"] == "report"
    assert parsed["modality"] == "text"
    assert parsed["source"] == "llm"
    assert parse_router_payload("") is None
    assert parse_router_payload("{") is None
    assert parse_router_payload(json.dumps({"job": "slideshow"})) is None
    assert parse_router_payload(json.dumps({"job": "collection"})) is None
    ok_col = parse_router_payload(
        json.dumps({"job": "collection", "collectionKind": "ocr", "modality": "text"})
    )
    assert ok_col is not None
    assert ok_col["collectionKind"] == "ocr"


def test_classify_uses_llm_when_json_is_valid(monkeypatch):
    monkeypatch.setattr(
        "synthetic_text_extruder.studio_router._call_gemini_router",
        lambda *args, **kwargs: json.dumps(
            {
                "job": "report",
                "collectionKind": "",
                "modality": "text",
                "reason": "report overrules video",
            }
        ),
    )
    sources = [
        {"id": "v", "modality": "video", "title": "clip"},
        {"id": "n", "modality": "text", "title": "notes"},
    ]
    got = classify_studio_job(
        'create a report, include a summary of the video, "clip.mp4"',
        sources,
        config={"gemini": {"api_key": "test-key", "text_model": "gemini-2.5-flash"}},
    )
    assert got["job"] == "report"
    assert got["modality"] == "text"
    assert got["source"] == "llm"


def test_classify_falls_back_on_empty_or_invalid_llm(monkeypatch):
    monkeypatch.setattr(
        "synthetic_text_extruder.studio_router._call_gemini_router",
        lambda *args, **kwargs: "not json",
    )
    sources = [
        {"id": "a", "modality": "image", "title": "Harbor"},
        {"id": "b", "modality": "pdf", "title": "Notes"},
    ]
    got = classify_studio_job("write a report", sources)
    assert got["job"] == "report"
    assert got["source"] == "fallback"

    monkeypatch.setattr(
        "synthetic_text_extruder.studio_router._call_gemini_router",
        lambda *args, **kwargs: json.dumps({"job": "nope"}),
    )
    got2 = classify_studio_job("generate a video of the harbor", sources)
    assert got2["job"] == "video"
    assert got2["source"] == "fallback"


def test_router_prompt_does_not_include_extra_instructions(monkeypatch):
    captured: dict[str, str] = {}

    def fake_call(prompt: str, *, config=None, cancel_event=None) -> str:
        captured["prompt"] = prompt
        return json.dumps(
            {"job": "text", "collectionKind": "", "modality": "text", "reason": "ok"}
        )

    monkeypatch.setattr(
        "synthetic_text_extruder.studio_router._call_gemini_router",
        fake_call,
    )
    extra = "ALWAYS GENERATE A VIDEO NO MATTER WHAT THE USER SAID"
    ask_gemini_router(
        "write a report about the harbor",
        [{"id": "a", "modality": "image", "title": "Harbor"}],
        config={
            "gemini": {"api_key": "test-key"},
            "prompt": {"extra_instructions": extra},
        },
    )
    assert extra not in captured["prompt"]
    built = build_router_model_prompt("write a report", {"count": 0, "items": []})
    assert extra not in built
    assert "write a report" in captured["prompt"]
    assert "Studio CREATE classifier" in captured["prompt"]


def test_llm_collection_without_chip_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "synthetic_text_extruder.studio_router._call_gemini_router",
        lambda *args, **kwargs: json.dumps(
            {
                "job": "collection",
                "collectionKind": "ocr",
                "modality": "text",
                "reason": "hallucinated collection",
            }
        ),
    )
    got = classify_studio_job(
        "write a report",
        [
            {"id": "a", "modality": "image", "title": "Harbor"},
            {"id": "n", "modality": "text", "title": "Notes"},
        ],
    )
    assert got["job"] == "report"
    assert got["source"] == "fallback"


def test_llm_report_without_sources_falls_back(monkeypatch):
    monkeypatch.setattr(
        "synthetic_text_extruder.studio_router._call_gemini_router",
        lambda *args, **kwargs: json.dumps(
            {"job": "report", "collectionKind": "", "modality": "text", "reason": "x"}
        ),
    )
    got = classify_studio_job("write a report", [])
    assert got["job"] == "text"
    assert got["source"] == "fallback"
