"""Embedding-based media save-dialog filenames (no live Gemini calls)."""

from __future__ import annotations

from synthetic_text_extruder.embedding_filename import (
    candidate_phrases,
    humanize_lineage_label,
    name_from_phrases,
    slugify_filename,
    suggest_filename_for_creation,
    suggest_lineage_label,
    suggest_media_filename,
    title_is_prompt_dump,
    title_is_weak_lineage_name,
    uniquify_lineage_label,
)


def test_slugify_filename_strips_paths_and_reserved_names():
    assert slugify_filename("Red Fox in Snow") == "red-fox-in-snow"
    assert "/" not in slugify_filename("a/b\\c")
    assert "\\" not in slugify_filename("a/b\\c")
    assert slugify_filename("CON") == "con-file"
    assert slugify_filename("") == "creation"
    assert slugify_filename("..") == "creation"
    long_name = slugify_filename("a " * 80)
    assert len(long_name) <= 48
    assert "/" not in long_name


def test_title_is_prompt_dump():
    prompt = "cinematic wide shot of a red fox in snow at dawn, photorealistic"
    assert title_is_prompt_dump(prompt, prompt)
    assert title_is_prompt_dump("Untitled", prompt)
    assert title_is_prompt_dump("", prompt)
    assert not title_is_prompt_dump("Harbor dusk", prompt)


def test_candidate_phrases_skips_boilerplate():
    phrases = candidate_phrases(
        "generate a photorealistic image of a red fox in snow at dawn"
    )
    joined = " ".join(phrases)
    assert "red fox" in joined or "fox" in joined
    assert "generate" not in phrases
    assert "photorealistic" not in phrases
    assert "image" not in phrases


def test_name_from_phrases_dedupes_words():
    assert name_from_phrases(["red fox", "fox snow", "dawn"]) == "red-fox-snow-dawn"


def test_suggest_filename_ranks_titles_against_media_embedding():
    """The image vector, not the prompt, decides which proposed title wins."""
    prompt = "cinematic wide shot of a red fox in snow at dawn, photorealistic"
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    def propose(**_kwargs):
        return ["red fox in snow", "studio lighting setup", "wide cinematic plate"]

    def embed_media(**_kwargs):
        return [1.0, 0.0, 0.0]

    def embed_texts(texts):
        table = {
            "red fox in snow": [0.98, 0.05, 0.0],
            "studio lighting setup": [0.05, 0.98, 0.0],
            "wide cinematic plate": [0.1, 0.1, 0.98],
        }
        return [table[str(t)] for t in texts]

    name = suggest_filename_for_creation(
        {
            "prompt": prompt,
            "title": prompt,
            "modality": "image",
            "mimeType": "image/png",
        },
        api_key="unused",
        content={"modality": "image", "bytes": png, "mime": "image/png", "text": ""},
        propose_fn=propose,
        embed_media_fn=embed_media,
        embed_texts_fn=embed_texts,
    )
    assert name == "red-fox-in-snow"
    assert "cinematic" not in name
    assert "photorealistic" not in name


def test_suggest_filename_ignores_prompt_when_looking_at_image():
    captured = {}

    def propose(**kwargs):
        captured.update(kwargs)
        return ["harbor at dusk"]

    suggest_filename_for_creation(
        {
            "prompt": "ignore this prompt about a spaceship",
            "title": "ignore this prompt about a spaceship",
            "modality": "image",
        },
        api_key="unused",
        content={
            "modality": "image",
            "bytes": b"\x89PNG fake",
            "mime": "image/png",
            "text": "",
        },
        propose_fn=propose,
        embed_media_fn=lambda **_k: [1.0],
        embed_texts_fn=lambda texts: [[1.0] for _ in texts],
    )
    assert captured.get("modality") == "image"
    assert captured.get("data").startswith(b"\x89PNG")
    assert "spaceship" not in str(captured.get("text") or "")


def test_suggest_filename_uses_document_body_not_prompt():
    body = "A field guide to alpine lilies that bloom above the treeline in July."
    name = suggest_filename_for_creation(
        {
            "prompt": "write a long essay about anything interesting please",
            "title": "write a long essay about anything interesting please",
            "modality": "text",
            "overview": "",
            "sections": [{"title": "", "content": body, "keyValues": []}],
        },
        content={"modality": "text", "bytes": None, "mime": "", "text": body},
        embed_fn=lambda texts: [[1.0, 0.0] if i == 0 else [0.9, 0.1] for i, _ in enumerate(texts)],
        api_key="unused",
    )
    assert "alpine" in name or "lilies" in name or "treeline" in name
    assert not name.startswith("write-a-long-essay")


def test_suggest_media_filename_keeps_custom_title_without_embedding():
    def boom(_texts):
        raise AssertionError("should not embed a user-chosen title")

    name = suggest_media_filename(
        "a lofi beat",
        title="Song",
        embed_fn=boom,
    )
    assert name == "song"


def test_suggest_filename_falls_back_without_key_or_file():
    prompt = "a red fox in snow at dawn"
    name = suggest_filename_for_creation(
        {"prompt": prompt, "title": prompt, "modality": "image"},
        content={"modality": "image", "bytes": None, "mime": "", "text": ""},
    )
    assert name == slugify_filename(prompt)


def test_suggest_filename_uses_first_title_if_embed_rank_fails():
    name = suggest_filename_for_creation(
        {"prompt": "make an image", "title": "make an image", "modality": "image"},
        api_key="unused",
        content={
            "modality": "image",
            "bytes": b"\x89PNG",
            "mime": "image/png",
            "text": "",
        },
        propose_fn=lambda **_k: ["harbor at dusk", "other title"],
        embed_media_fn=lambda **_k: (_ for _ in ()).throw(RuntimeError("embed down")),
    )
    assert name == "harbor-at-dusk"


def test_suggest_filename_for_creation_uses_cache():
    creation = {
        "prompt": "cinematic wide shot of a red fox in snow at dawn",
        "title": "cinematic wide shot of a red fox in snow at dawn",
        "meta": {"embeddingFilename": "red-fox-snow-dawn"},
    }

    def boom(**_kwargs):
        raise AssertionError("cached name should skip embedding")

    assert (
        suggest_filename_for_creation(creation, propose_fn=boom)
        == "red-fox-snow-dawn"
    )


def test_title_is_weak_lineage_name():
    assert title_is_weak_lineage_name(
        "ai_generated_preview_42b7f3fe-9a1f-4454-90bd-167bd139ab0d_6751cfdbda7054"
    )
    assert title_is_weak_lineage_name("image (1)")
    assert title_is_weak_lineage_name("IMG_1234.png")
    assert title_is_weak_lineage_name("Imported from photo.png")
    assert not title_is_weak_lineage_name("write a sentence about love")
    assert not title_is_weak_lineage_name("Harbor dusk")


def test_humanize_and_uniquify_lineage_label():
    assert humanize_lineage_label("red-fox-in-snow") == "Red fox in snow"
    assert uniquify_lineage_label("Harbor dusk", ["Harbor dusk"]) == "Harbor dusk (2)"


def test_suggest_lineage_label_keeps_meaningful_title():
    def boom(**_kwargs):
        raise AssertionError("should not embed a readable chain title")

    label = suggest_lineage_label(
        {"title": "write a sentence about love", "prompt": "write a sentence about love"},
        propose_fn=boom,
    )
    assert label == "Write a sentence about love"


def test_suggest_lineage_label_uses_media_embedding_for_uuid_title():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    def propose(**_kwargs):
        return ["harbor at dusk", "studio lighting setup"]

    label = suggest_lineage_label(
        {
            "title": "ai_generated_preview_42b7f3fe-9a1f-4454-90bd-167bd139ab0d",
            "prompt": "Imported from preview.png",
            "modality": "image",
            "mimeType": "image/png",
        },
        taken=["Harbor at dusk"],
        api_key="unused",
        content={"modality": "image", "bytes": png, "mime": "image/png", "text": ""},
        propose_fn=propose,
        embed_media_fn=lambda **_k: [1.0, 0.0],
        embed_texts_fn=lambda texts: (
            [[0.99, 0.0] if "harbor" in str(t).lower() else [0.1, 0.9] for t in texts]
        ),
    )
    assert "Harbor" in label
    assert label != "Harbor at dusk"

