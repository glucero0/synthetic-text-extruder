"""Tests for YouTube caption enrichment from search."""

from __future__ import annotations

from unittest.mock import patch

from synthetic_text_extruder.config import DEFAULTS
from synthetic_text_extruder.research_youtube import (
    discover_youtube_urls,
    enrich_research_with_youtube_captions,
    extract_youtube_video_id,
    is_youtube_url,
)


def test_youtube_search_captions_default_is_true():
    assert DEFAULTS["gemini"]["youtube_search_captions"] is True


def test_extract_youtube_video_id_watch():
    assert (
        extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )


def test_extract_youtube_video_id_short_link():
    assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_discover_youtube_urls_from_grounding():
    sources = [{"title": "Guide", "url": "https://www.youtube.com/watch?v=abc123XYZ12"}]
    urls = discover_youtube_urls("See also https://youtu.be/def456UVW78", grounding_sources=sources)
    assert len(urls) == 2
    assert all(is_youtube_url(u) for u in urls)


def test_enrich_research_with_youtube_captions_appends_block():
    sources = [{"title": "Controls", "url": "https://www.youtube.com/watch?v=abc123XYZ12"}]

    with patch(
        "synthetic_text_extruder.research_youtube._fetch_captions",
        return_value="Press R1 to sprint.",
    ):
        block, meta = enrich_research_with_youtube_captions(
            "Video walkthrough",
            grounding_sources=sources,
        )

    assert "YOUTUBE CAPTION FINDINGS" in block
    assert "Press R1 to sprint." in block
    assert meta["youtubeCaptionCount"] == 1


def test_fetch_captions_supports_v1_fetch_api(monkeypatch):
    import sys
    import types

    from synthetic_text_extruder.research_youtube import _fetch_captions

    class _Snippet:
        def __init__(self, text: str):
            self.text = text

    class _ApiV1:
        def fetch(self, video_id: str, languages=None):
            assert video_id == "abc123XYZ12"
            return [_Snippet("Line one"), _Snippet("Line two")]

    fake_mod = types.ModuleType("youtube_transcript_api")
    fake_mod.YouTubeTranscriptApi = _ApiV1
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", fake_mod)
    assert _fetch_captions("abc123XYZ12") == "Line one\nLine two"


def test_fetch_captions_supports_legacy_get_transcript_api(monkeypatch):
    import sys
    import types

    from synthetic_text_extruder.research_youtube import _fetch_captions

    class _ApiV0:
        @staticmethod
        def get_transcript(video_id: str, languages=None):
            assert video_id == "abc123XYZ12"
            return [{"text": "Legacy line"}]

    fake_mod = types.ModuleType("youtube_transcript_api")
    fake_mod.YouTubeTranscriptApi = _ApiV0
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", fake_mod)
    assert _fetch_captions("abc123XYZ12") == "Legacy line"
