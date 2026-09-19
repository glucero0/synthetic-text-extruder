"""Modality helpers and media creation records."""

from pathlib import Path

from synthetic_text_extruder.creation_utils import (
    build_media_creation,
    build_text_creation_from_plain,
    is_generic_studio_request,
    title_from_prompt,
)
from synthetic_text_extruder.media_store import (
    _join_under_dir,
    resolve_media_path,
    stored_media_path,
    write_media_bytes,
)
from synthetic_text_extruder.modality import (
    check_prompt_model_compatibility,
    classify_model_modality,
    infer_layout_extract_intent,
    infer_prompt_modality,
    infer_text_extract_intent,
    normalize_modality,
    resolve_generation_modality,
)


def test_normalize_and_classify():
    assert normalize_modality("IMAGE") == "image"
    assert classify_model_modality("gemini-2.5-flash") == "text"
    assert classify_model_modality("gemini-flash-latest") == "text"
    assert classify_model_modality("gemini-2.5-flash-image") == "image"
    assert classify_model_modality("google/gemini-2.5-flash-image") == "image"
    assert classify_model_modality("black-forest-labs/flux.2-pro") == "image"
    assert classify_model_modality("veo-3.1-generate-preview") == "video"
    assert classify_model_modality("google/veo-2.0") == "video"
    assert classify_model_modality("gemini-2.5-flash-preview-tts") is None
    assert classify_model_modality("lyria-3-clip-preview") == "audio"
    assert classify_model_modality("lyria-3.5") == "audio"
    assert classify_model_modality("lyria-3-pro-preview") == "audio"
    assert normalize_modality("MUSIC") == "audio"
    assert normalize_modality("pdf") == "pdf"
    assert normalize_modality("pdf") == "pdf"


def test_infer_prompt_modality_image_dragon():
    prompt = (
        "create an image of a dragon sitting in a lounge chair, smoking a pipe, "
        "reading the nyt -- it's wearing a suite, tie, and there's a stylish hat "
        "on the table next to him. the room has nice paintings, plants, and other "
        "adornments. very posh"
    )
    assert infer_prompt_modality(prompt) == "image"


def test_infer_prompt_modality_video_and_text():
    assert infer_prompt_modality("Generate a video of waves crashing") == "video"
    assert infer_prompt_modality("Write a short poem about autumn") == "text"
    assert infer_prompt_modality("a red bicycle leaning on a fence") is None
    assert infer_prompt_modality("Compose a chiptune song for a Sega Genesis title screen") == "audio"
    assert infer_prompt_modality("Generate a music clip with dusty vinyl crackle") == "audio"
    assert infer_prompt_modality("create background music, instrumental only") == "audio"


def test_infer_prompt_modality_create_report_is_not_video():
    from synthetic_text_extruder.modality import infer_report_intent

    prompt = (
        'create a report, include a summary of the video, "doc_1c9b1302da.mp4", '
        'the image, "doc_7b759c704e.jpg", and the story from '
        '"a_very_short_story_of_a_dog_being_rescued_by_a_family_of_thr.txt"'
    )
    assert infer_report_intent(prompt) is True
    assert infer_prompt_modality(prompt) == "text"
    assert infer_prompt_modality("create a video of a toaster") == "video"
    assert infer_report_intent("generate a video of the harbor") is False
    assert infer_report_intent("summarize") is True
    assert infer_prompt_modality("summarize") == "text"
    assert infer_report_intent("summarize this into a video") is False
    assert infer_report_intent("create a video summarizing the clips") is False
    assert infer_prompt_modality("create a video summarizing the clips") == "video"


def test_resolve_generation_modality_prompt_wins_over_image_basis():
    # Image basis + video prompt → I2V (video), not forced img2img
    assert (
        resolve_generation_modality(
            "Generate a video of the dragon standing up",
            basis_modality="image",
        )
        == "video"
    )
    assert (
        resolve_generation_modality(
            "turn this into a video",
            basis_modality="image",
        )
        == "video"
    )
    assert (
        resolve_generation_modality(
            "convert the image to a video clip",
            basis_modality="image",
        )
        == "video"
    )
    assert (
        resolve_generation_modality("make it blue", basis_modality="image") == "image"
    )
    assert (
        resolve_generation_modality("Create an image of a cat", basis_modality="video")
        == "image"
    )
    assert resolve_generation_modality("hello world") is None
    assert (
        resolve_generation_modality(
            "Compose a song inspired by this painting",
            basis_modality="image",
        )
        == "audio"
    )
    assert infer_prompt_modality("recreate this dialog as HTML") == "text"
    assert infer_prompt_modality("generate a web app from this screenshot") == "text"
    assert (
        resolve_generation_modality(
            "rebuild this window",
            basis_modality="image",
            layout_basis=True,
        )
        == "text"
    )
    assert (
        resolve_generation_modality(
            "create an image of a cleaner mockup",
            basis_modality="image",
            layout_basis=True,
        )
        == "image"
    )


def test_infer_layout_extract_intent_from_studio_prompt():
    assert infer_layout_extract_intent("extract the layout")
    assert infer_layout_extract_intent("Extract layout from this screenshot")
    assert infer_layout_extract_intent("find UI chrome")
    assert infer_layout_extract_intent("get the layout JSON")
    assert not infer_layout_extract_intent("recreate the layout as HTML")
    assert not infer_layout_extract_intent("make it blue")
    assert infer_prompt_modality("extract the layout") == "text"
    assert (
        resolve_generation_modality("extract the layout", basis_modality="image")
        == "text"
    )
    assert (
        resolve_generation_modality("extract the layout", basis_modality="video")
        == "text"
    )


def test_infer_text_extract_intent_from_studio_prompt():
    assert infer_text_extract_intent("extract the text")
    assert infer_text_extract_intent("OCR this screenshot")
    assert infer_text_extract_intent("transcribe this video")
    assert infer_text_extract_intent("speech to text")
    assert not infer_text_extract_intent("extract the layout")
    assert not infer_text_extract_intent("write a short story")
    assert infer_prompt_modality("transcribe this clip") == "text"
    assert (
        resolve_generation_modality("extract the text", basis_modality="image")
        == "text"
    )
    assert resolve_generation_modality("transcribe", basis_modality="video") == "text"


def test_gemini_routes_music_prompt_ok():
    prompt = "Compose a song about neon rain"
    ok = check_prompt_model_compatibility(prompt, "gemini-flash-latest", provider="gemini")
    assert ok["ok"] is True
    assert ok.get("routed") is True
    assert ok["modelModality"] == "audio"
    assert "lyria" in ok["model"]


def test_gemini_routes_image_prompt_ok():
    prompt = "create an image of a dragon in a suit"
    ok = check_prompt_model_compatibility(prompt, "gemini-flash-latest", provider="gemini")
    assert ok["ok"] is True
    assert ok.get("routed") is True
    assert ok["modelModality"] == "image"
    assert "flash-image" in ok["model"] or "image" in ok["model"]


def test_classify_local_diffusion_and_t2v():
    assert (
        classify_model_modality("stable-diffusion-v1-5/stable-diffusion-v1-5")
        == "image"
    )
    assert classify_model_modality("stabilityai/sd-turbo") == "image"
    assert classify_model_modality("ali-vilab/text-to-video-ms-1.7b") == "video"
    assert classify_model_modality("cerspense/zeroscope_v2_576w") == "video"


def test_generic_studio_request():
    assert is_generic_studio_request("Prompt", "General", "Custom")
    assert not is_generic_studio_request("Sonic", "Sega Genesis", "Quick Reference Card")


def test_title_from_prompt():
    assert title_from_prompt("Hello world\nmore") == "Hello world"
    assert title_from_prompt("") == "Untitled"


def test_build_text_and_media_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path
    )
    monkeypatch.setattr(
        "synthetic_text_extruder.media_store.load_config",
        lambda: {"paths": {"media": "media"}},
    )
    text = build_text_creation_from_plain(
        "Body text here", prompt="Write a poem", model_info={"provider": "test"}
    )
    assert text["modality"] == "text"
    assert text["prompt"] == "Write a poem"
    assert text["overview"] == ""
    assert "Body text" in text["sections"][0]["content"]
    assert text["sections"][0]["title"] == ""

    stored = write_media_bytes(
        "doc_abc123", b"\x89PNG\r\n", mime_type="image/png", config={"paths": {"media": "media"}}
    )
    assert stored["mediaPath"].endswith(".png")
    assert (tmp_path / stored["mediaPath"]).exists()

    media = build_media_creation(
        modality="image",
        prompt="A red robot",
        media_path=stored["mediaPath"],
        mime_type=stored["mimeType"],
        creation_id="doc_abc123",
    )
    assert media["modality"] == "image"
    assert media["mediaPath"] == stored["mediaPath"]
    assert media["id"] == "doc_abc123"


def test_resolve_media_path_finds_legacy_after_folder_switch(tmp_path, monkeypatch):
    monkeypatch.setattr("synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path)
    leftover = tmp_path / "media" / "doc_x.png"
    leftover.parent.mkdir(parents=True, exist_ok=True)
    leftover.write_bytes(b"png-bytes")
    custom = tmp_path / "other-media"
    cfg = {"paths": {"media": str(custom.resolve())}}
    found = resolve_media_path("media/doc_x.png", config=cfg)
    assert found == leftover.resolve()
    assert found.read_bytes() == b"png-bytes"


def test_join_under_dir_stays_in_root(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    dest = _join_under_dir(root, "ok.png")
    assert dest == (root / "ok.png").resolve()
    # Parent segments are dropped; the file stays in root.
    assert _join_under_dir(root, "../secret.txt") == (root / "secret.txt").resolve()
    assert _join_under_dir(root, "..") is None


def test_stored_media_path_uses_basename_only(tmp_path, monkeypatch):
    monkeypatch.setattr("synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path)
    dest = tmp_path / "media" / "clip.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"x")
    assert stored_media_path(dest) == "media/clip.png"


def test_write_media_bytes_to_custom_absolute_folder(tmp_path):
    custom = (tmp_path / "abs-media").resolve()
    cfg = {"paths": {"media": str(custom)}}
    stored = write_media_bytes(
        "doc_y", b"\x89PNG", mime_type="image/png", config=cfg
    )
    dest = custom / Path(stored["mediaPath"]).name
    assert dest.is_file()
    assert dest.read_bytes() == b"\x89PNG"
