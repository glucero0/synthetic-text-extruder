"""derivedFrom edges, prompt steps, nested library paths, and lineage payload."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

from synthetic_text_extruder.api import Api
from synthetic_text_extruder.creation_utils import (
    build_media_creation,
    build_text_creation_from_plain,
)
from synthetic_text_extruder.lineage import (
    PROMPT_PREVIEW_MAX,
    attach_prompt_step,
    compact_from_modality,
    connected_components,
    expand_prompt_steps,
    extra_sources_are_lineage_context,
    inspect_lineage_node,
    lineage_payload,
    lineage_root_for_new,
    media_ancestor_ids,
    normalize_derived_edge,
    preview_prompt_text,
    prompt_node_id,
)
from synthetic_text_extruder.lineage_store import LineageStore, lineage_db_path
from synthetic_text_extruder.media_store import (
    media_http_relpath,
    resolve_media_path,
    write_media_bytes,
)
from synthetic_text_extruder.storage import ArchiveStore


def _api_with_tmp_store(tmp_path, monkeypatch) -> Api:
    api = Api()
    api.config = {
        "backend": {"provider": "gemini"},
        "gemini": {"text_model": "gemini-2.5-flash", "api_key": "test-key"},
        "paths": {
            "archives": str(tmp_path / "archives.json"),
            "media": "media",
            "exports": "exports",
        },
    }
    api.store = ArchiveStore(path=tmp_path / "archives.json")
    monkeypatch.setattr("synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "synthetic_text_extruder.media_store.load_config",
        lambda: api.config,
    )
    return api


def test_preview_prompt_text_truncates():
    long = "word " * 40
    preview = preview_prompt_text(long)
    assert len(preview) <= PROMPT_PREVIEW_MAX
    assert preview.endswith("…")
    assert "\n" not in preview


def test_normalize_prompt_edge_keeps_compact_fields_only():
    edge = normalize_derived_edge(
        {
            "id": "prm_doc_child",
            "role": "prompt",
            "promptPreview": "  a  harbor   at dawn  ",
            "fromModality": "image",
            "toModality": "video",
            "model": "veo-2.0-generate-001",
            "temperature": 0.7,
            "mediaPath": "media/secret.png",
        }
    )
    assert edge == {
        "id": "prm_doc_child",
        "role": "prompt",
        "promptPreview": "a harbor at dawn",
        "fromModality": "image",
        "toModality": "video",
    }


def test_attach_prompt_step_is_idempotent():
    child = {"id": "doc_child", "modality": "image", "prompt": "full prompt"}
    once = attach_prompt_step(
        child, prompt="paint a fox", from_modality="image", to_modality="image"
    )
    twice = attach_prompt_step(once, prompt="ignored second", from_modality="video")
    prompts = [e for e in twice["derivedFrom"] if e["role"] == "prompt"]
    assert len(prompts) == 1
    assert prompts[0]["id"] == prompt_node_id("doc_child")
    assert prompts[0]["promptPreview"] == "paint a fox"
    assert prompts[0]["fromModality"] == "image"
    assert prompts[0]["toModality"] == "image"


def test_first_create_is_not_orphan_and_expands_prompt_node():
    child = attach_prompt_step(
        {
            "id": "doc_new",
            "title": "Fox",
            "modality": "image",
            "createdAt": "2026-09-20T12:00:00Z",
        },
        prompt="a red fox in snow",
        to_modality="image",
    )
    comps = connected_components([child])
    assert len(comps) == 1
    assert comps[0]["orphan"] is False
    expanded = expand_prompt_steps(comps[0])
    kinds = {n["id"]: n.get("kind") for n in expanded["nodes"]}
    assert kinds[prompt_node_id("doc_new")] == "prompt"
    assert any(
        e["from"] == prompt_node_id("doc_new") and e["to"] == "doc_new"
        for e in expanded["edges"]
    )


def test_import_without_prompt_step_is_orphan():
    imported = {
        "id": "doc_imp",
        "title": "photo",
        "modality": "image",
        "prompt": "Imported from photo.png",
        "createdAt": "2026-09-20T12:00:00Z",
    }
    comps = connected_components([imported])
    assert comps[0]["orphan"] is True
    expanded = expand_prompt_steps(comps[0])
    assert all(n.get("kind") != "prompt" for n in expanded["nodes"])


def test_parent_prompt_child_chain_and_compact_payload():
    parent = {
        "id": "doc_parent",
        "title": "Harbor",
        "modality": "image",
        "createdAt": "2026-09-19T10:00:00Z",
        "mediaPath": "media/doc_parent/doc_parent.png",
        "mimeType": "image/png",
        "_model": {"repo_id": "imagen-4"},
        "sections": [{"content": "do not dump"}],
    }
    child = attach_prompt_step(
        {
            "id": "doc_child",
            "title": "Clip",
            "modality": "video",
            "createdAt": "2026-09-20T12:00:00Z",
            "derivedFrom": [{"id": "doc_parent", "role": "basis"}],
            "lyrics": "secret verses",
        },
        prompt="turn the harbor still into a slow pan",
        from_modality="image",
        to_modality="video",
    )
    payload = lineage_payload([parent, child], focus_id="doc_child")
    assert payload["focusRootId"] == "doc_parent"
    assert len(payload["components"]) == 1
    component = payload["components"][0]
    nodes = {n["id"]: n for n in component["nodes"]}
    pid = prompt_node_id("doc_child")
    assert nodes[pid]["kind"] == "prompt"
    assert nodes[pid]["promptPreview"].startswith("turn the harbor")
    assert nodes[pid]["fromModality"] == "image"
    assert nodes[pid]["toModality"] == "video"
    assert "mediaPath" not in nodes["doc_parent"]
    assert "mimeType" not in nodes["doc_parent"]
    assert "_model" not in nodes["doc_parent"]
    assert "sections" not in nodes["doc_parent"]
    assert "lyrics" not in nodes["doc_child"]
    assert {"from": "doc_parent", "to": pid, "role": "basis"} in component["edges"]
    assert {"from": pid, "to": "doc_child", "role": "prompt"} in component["edges"]

    prompt_view = inspect_lineage_node(
        [parent, child], pid, prompt_text="turn the harbor still into a slow pan"
    )
    assert prompt_view["ok"] is True
    assert prompt_view["kind"] == "prompt"
    assert prompt_view["promptText"] == "turn the harbor still into a slow pan"
    assert "Harbor" not in prompt_view["promptText"]
    media_view = inspect_lineage_node([parent, child], "doc_child")
    assert media_view["kind"] == "media"
    assert media_view["modality"] == "video"
    assert media_view["body"] == ""
    assert "promptText" not in media_view
    parent_view = inspect_lineage_node([parent, child], "doc_parent")
    assert parent_view["kind"] == "media"
    assert parent_view["title"] == "Harbor"


def test_prompt_ids_are_not_missing_parent_stubs():
    child = attach_prompt_step(
        {
            "id": "doc_x",
            "title": "X",
            "modality": "text",
            "createdAt": "2026-09-20T12:00:00Z",
        },
        prompt="write a haiku",
        to_modality="text",
    )
    comps = connected_components([child])
    assert all(not n.get("missing") for n in comps[0]["nodes"])
    assert all(not str(n.get("id") or "").startswith("prm_") for n in comps[0]["nodes"])


def test_lineage_root_for_new_uses_oldest_parent():
    older = {
        "id": "doc_old",
        "createdAt": "2026-01-01T00:00:00Z",
        "modality": "image",
    }
    newer = {
        "id": "doc_newp",
        "createdAt": "2026-06-01T00:00:00Z",
        "modality": "image",
        "derivedFrom": [{"id": "doc_old", "role": "source"}],
    }
    root = lineage_root_for_new([older, newer], ["doc_newp"], "doc_child")
    assert root == "doc_old"
    assert lineage_root_for_new([], [], "doc_solo") == "doc_solo"


def test_compact_from_modality_mixed():
    assert compact_from_modality([{"modality": "image"}]) == "image"
    assert (
        compact_from_modality([{"modality": "image"}, {"modality": "video"}]) == "mixed"
    )


def test_write_media_bytes_nests_under_lineage_root(tmp_path, monkeypatch):
    monkeypatch.setattr("synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path)
    stored = write_media_bytes(
        "doc_child",
        b"\x89PNG",
        mime_type="image/png",
        config={"paths": {"media": "media"}},
        lineage_root="doc_root",
    )
    assert stored["mediaPath"] == "media/doc_root/doc_child.png"
    dest = tmp_path / "media" / "doc_root" / "doc_child.png"
    assert dest.is_file()
    assert dest.read_bytes() == b"\x89PNG"


def test_resolve_media_path_legacy_flat_and_nested(tmp_path, monkeypatch):
    monkeypatch.setattr("synthetic_text_extruder.media_store.PROJECT_ROOT", tmp_path)
    cfg = {"paths": {"media": "media"}}
    flat = tmp_path / "media" / "doc_legacy.png"
    flat.parent.mkdir(parents=True, exist_ok=True)
    flat.write_bytes(b"flat")
    nested = tmp_path / "media" / "doc_root" / "doc_child.png"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_bytes(b"nested")
    assert resolve_media_path("media/doc_legacy.png", config=cfg) == flat.resolve()
    assert (
        resolve_media_path("media/doc_root/doc_child.png", config=cfg) == nested.resolve()
    )
    assert media_http_relpath(nested, config=cfg) == "doc_root/doc_child.png"
    assert media_http_relpath(flat, config=cfg) == "doc_legacy.png"


def test_import_is_orphan_duplicate_gets_prompt_edge(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    src = tmp_path / "photo.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n")
    win = MagicMock()
    win.create_file_dialog.return_value = str(src)
    api._window = win
    imported = api.import_media_file("image")["creation"]
    assert imported.get("derivedFrom") in (None, [])
    nested = Path(imported["mediaPath"])
    assert nested.parts[-2] == imported["id"]
    assert (tmp_path / imported["mediaPath"]).is_file()
    graph = api.lineage_graph(imported["id"])
    component = graph["components"][0]
    assert component["orphan"] is True
    assert all(n.get("kind") != "prompt" for n in component["nodes"])

    copy = api.duplicate_creation(imported["id"])["creation"]
    roles = {e["role"] for e in copy["derivedFrom"]}
    assert "duplicate" in roles
    assert "prompt" in roles
    prompt_edge = next(e for e in copy["derivedFrom"] if e["role"] == "prompt")
    assert prompt_edge["promptPreview"] == "Duplicate"
    assert set(prompt_edge) <= {
        "id",
        "role",
        "promptPreview",
        "fromModality",
        "toModality",
    }
    dup_graph = api.lineage_graph(copy["id"])
    chain = next(c for c in dup_graph["components"] if not c["orphan"])
    assert any(n.get("kind") == "prompt" for n in chain["nodes"])


def test_create_creation_stamps_prompt_and_source_edges(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    parent = build_media_creation(
        modality="image",
        prompt="harbor",
        media_path="media/h.png",
        mime_type="image/png",
        title="Harbor",
        creation_id="doc_img",
    )
    parent["createdAt"] = "2026-01-01T00:00:00Z"
    api.store.upsert(parent)
    monkeypatch.setattr(
        "synthetic_text_extruder.studio_router.classify_studio_job",
        lambda *args, **kwargs: {
            "job": "report",
            "collectionKind": "",
            "modality": "text",
            "reason": "test",
            "source": "test",
        },
    )

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
        ["doc_img"],
    )
    assert res["ok"] is True
    job = api.get_job(res["job_id"])
    for _ in range(100):
        if job.get("status") in {"done", "error", "cancelled", "missing"}:
            break
        threading.Event().wait(0.05)
        job = api.get_job(res["job_id"])
    assert job["status"] == "done", job
    result = job["result"]
    roles = {e["role"]: e for e in result["derivedFrom"]}
    assert "basis" in roles or "source" in roles
    assert roles["prompt"]["promptPreview"] == "Write a report"
    assert roles["prompt"]["toModality"] == "text"
    graph = api.lineage_graph(result["id"])
    nodes = graph["components"][0]["nodes"]
    assert any(n.get("kind") == "prompt" for n in nodes)
    for node in nodes:
        assert "mediaPath" not in node
        assert "temperature" not in node
        assert "_model" not in node
    pid = prompt_node_id(result["id"])
    prompt_view = api.lineage_inspect(pid)
    assert prompt_view["ok"] is True
    assert prompt_view["kind"] == "prompt"
    assert prompt_view["promptText"] == "Write a report"
    media_view = api.lineage_inspect(result["id"])
    assert media_view["kind"] == "media"
    assert "Combined report" in media_view["body"]
    assert media_view["body"] != prompt_view["promptText"]
    db = LineageStore(lineage_db_path(api.config))
    stored = db.get_prompt_step(pid)
    assert stored is not None
    assert stored["prompt_text"] == "Write a report"


def test_save_dialog_opens_in_exports_folder(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    captured: list[dict[str, object]] = []

    class _Win:
        def create_file_dialog(self, *_args, **kwargs):
            captured.append(dict(kwargs))
            return str(tmp_path / f"out-{len(captured)}.txt")

    api._window = _Win()
    res = api.save_file_dialog("notes.txt", "hello")
    assert res["ok"] is True
    assert Path(str(captured[0]["directory"])).resolve() == (tmp_path / "exports").resolve()
    again = api.save_file_dialog("more.txt", "world")
    assert again["ok"] is True
    assert Path(str(captured[1]["directory"])).resolve() == (tmp_path / "exports").resolve()


def test_get_media_payload_nested_file_url(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    api._ui_origin = "http://127.0.0.1:8765"
    stored = write_media_bytes(
        "doc_child",
        b"\x89PNG\r\n\x1a\n",
        mime_type="image/png",
        config=api.config,
        lineage_root="doc_root",
    )
    creation = build_media_creation(
        modality="image",
        prompt="nested",
        media_path=stored["mediaPath"],
        mime_type="image/png",
        title="Nested",
        creation_id="doc_child",
    )
    payload = api.get_media_payload(creation)
    assert payload["ok"] is True
    assert payload["fileUrl"] == "http://127.0.0.1:8765/media/doc_root/doc_child.png"


def test_lineage_store_keeps_full_prompt(tmp_path):
    store = LineageStore(tmp_path / "lineage.sqlite")
    long_prompt = "paint a fox\n" + ("more detail. " * 40)
    store.upsert_prompt_step(
        node_id="prm_doc_child",
        child_id="doc_child",
        prompt_text=long_prompt,
        from_modality="image",
        to_modality="image",
        created_at="2026-09-20T12:00:00Z",
    )
    store.upsert_prompt_step(
        node_id="prm_doc_child",
        child_id="doc_child",
        prompt_text="ignored second write",
        overwrite=False,
    )
    row = store.get_prompt_step("prm_doc_child")
    assert row is not None
    assert row["prompt_text"] == long_prompt
    assert "fox" in row["prompt_text"]


def test_inspect_text_node_keeps_prompt_and_body_separate():
    child = attach_prompt_step(
        {
            "id": "doc_txt",
            "title": "Haiku",
            "modality": "text",
            "prompt": "write a haiku about snow",
            "createdAt": "2026-09-20T12:00:00Z",
            "overview": "",
            "sections": [{"title": "", "content": "white field\nquiet fox\ndawn"}],
        },
        prompt="write a haiku about snow",
        to_modality="text",
    )
    pid = prompt_node_id("doc_txt")
    prompt_view = inspect_lineage_node([child], pid)
    media_view = inspect_lineage_node([child], "doc_txt")
    assert prompt_view["promptText"] == "write a haiku about snow"
    assert "quiet fox" in media_view["body"]
    assert media_view["body"] != prompt_view["promptText"]
    assert "promptText" not in media_view


def test_lineage_payload_prefers_lineage_label():
    root = {
        "id": "doc_root",
        "title": "image (1)",
        "lineageLabel": "Harbor dusk",
        "modality": "image",
        "createdAt": "2026-01-01T00:00:00Z",
    }
    payload = lineage_payload([root], focus_id="doc_root")
    assert payload["components"][0]["rootTitle"] == "Harbor dusk"


def test_relabel_lineage_roots_persists_unique_names(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    weak = build_media_creation(
        modality="image",
        prompt="Imported from preview.png",
        media_path="media/x.png",
        mime_type="image/png",
        title="ai_generated_preview_42b7f3fe-9a1f-4454-90bd-167bd139ab0d",
        creation_id="doc_weak",
    )
    good = build_text_creation_from_plain(
        "hello",
        prompt="write a sentence about love",
        title="write a sentence about love",
    )
    good["id"] = "doc_love"
    api.store.upsert(weak)
    api.store.upsert(good)
    monkeypatch.setattr(
        "synthetic_text_extruder.embedding_filename.suggest_lineage_label",
        lambda creation, **kwargs: "Harbor dusk",
    )
    res = api.relabel_lineage_roots(["doc_weak", "doc_love"])
    assert res["ok"] is True
    assert res["labels"]["doc_love"] == "write a sentence about love"
    assert res["labels"]["doc_weak"] == "Harbor dusk"
    stored = api.store.load()
    by_id = {c["id"]: c for c in stored}
    assert by_id["doc_weak"]["lineageLabel"] == "Harbor dusk"
    assert "lineageLabel" not in by_id["doc_love"] or by_id["doc_love"].get("lineageLabel") in (
        None,
        "",
    )
    graph = api.lineage_graph("doc_weak")
    titles = {c["rootId"]: c["rootTitle"] for c in graph["components"]}
    assert titles["doc_weak"] == "Harbor dusk"


def test_media_ancestor_ids_oldest_first_and_lineage_context():
    orig = {"id": "doc_orig", "modality": "image"}
    mid = {
        "id": "doc_mid",
        "modality": "image",
        "derivedFrom": [{"id": "doc_orig", "role": "basis"}],
    }
    child = {
        "id": "doc_child",
        "modality": "image",
        "derivedFrom": [{"id": "doc_mid", "role": "basis"}],
    }
    by_id = {"doc_orig": orig, "doc_mid": mid, "doc_child": child}
    assert media_ancestor_ids(child, by_id) == ["doc_orig", "doc_mid"]
    assert extra_sources_are_lineage_context([orig, child]) is False
    assert extra_sources_are_lineage_context([orig, mid, child]) is True
    sibling = {
        "id": "doc_edit",
        "modality": "image",
        "derivedFrom": [{"id": "doc_orig", "role": "basis"}],
    }
    assert extra_sources_are_lineage_context([orig, sibling]) is True
    notes = {"id": "notes", "modality": "pdf"}
    assert extra_sources_are_lineage_context([orig, notes, sibling]) is False
    other = {"id": "other", "modality": "image"}
    assert extra_sources_are_lineage_context([orig, other]) is False


def test_lineage_reference_images_loads_ancestor_bytes(tmp_path, monkeypatch):
    api = _api_with_tmp_store(tmp_path, monkeypatch)
    orig_store = write_media_bytes(
        "doc_orig",
        b"\x89PNG original",
        mime_type="image/png",
        config=api.config,
        lineage_root="doc_orig",
    )
    edit_store = write_media_bytes(
        "doc_edit",
        b"\x89PNG edited",
        mime_type="image/png",
        config=api.config,
        lineage_root="doc_orig",
    )
    orig = {
        "id": "doc_orig",
        "modality": "image",
        "mimeType": "image/png",
        "mediaPath": orig_store["mediaPath"],
    }
    edit = {
        "id": "doc_edit",
        "modality": "image",
        "mimeType": "image/png",
        "mediaPath": edit_store["mediaPath"],
        "derivedFrom": [{"id": "doc_orig", "role": "basis"}],
    }
    refs = api._lineage_reference_images([orig, edit], "doc_edit")
    assert len(refs) == 1
    assert refs[0]["bytes"] == b"\x89PNG original"
    assert "image/" in refs[0]["mime_type"]
    assert api._lineage_reference_images([edit], "doc_edit") == []


