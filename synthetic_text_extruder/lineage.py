"""Generation-graph helpers: derivedFrom edges and connected components."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import Any

VALID_ROLES = frozenset({"basis", "source", "duplicate", "split", "splice", "prompt"})
PROMPT_ID_PREFIX = "prm_"
PROMPT_PREVIEW_MAX = 72
PROMPT_TEXT_MAX = 100_000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _creation_id(item: dict[str, Any] | None) -> str:
    return str((item or {}).get("id") or "").strip()


def prompt_node_id(child_id: str) -> str:
    stem = str(child_id or "").strip() or "item"
    return f"{PROMPT_ID_PREFIX}{stem}"[:80]


def is_prompt_node_id(cid: str | None) -> bool:
    return str(cid or "").startswith(PROMPT_ID_PREFIX)


def preview_prompt_text(text: str | None) -> str:
    collapsed = " ".join(str(text or "").split())
    if len(collapsed) <= PROMPT_PREVIEW_MAX:
        return collapsed
    return collapsed[: PROMPT_PREVIEW_MAX - 1].rstrip() + "…"


def clip_prompt_text(text: str | None) -> str:
    raw = str(text or "")
    if len(raw) <= PROMPT_TEXT_MAX:
        return raw
    return raw[: PROMPT_TEXT_MAX - 1] + "…"


def creation_result_text(creation: dict[str, Any] | None) -> str:
    """Generated document/lyrics body — not the CREATE prompt."""
    item = creation or {}
    parts: list[str] = []
    overview = str(item.get("overview") or "").strip()
    if overview:
        parts.append(overview)
    for sec in item.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        title = str(sec.get("title") or "").strip()
        content = str(sec.get("content") or "").strip()
        if title and content:
            parts.append(f"{title}\n{content}")
        elif content:
            parts.append(content)
        elif title:
            parts.append(title)
    return "\n\n".join(parts).strip()


def creation_for_prompt_node(
    creations: Sequence[dict[str, Any]] | None, node_id: str
) -> dict[str, Any] | None:
    nid = str(node_id or "").strip()
    if not nid:
        return None
    for item in creations or []:
        cid = _creation_id(item)
        if not cid:
            continue
        if prompt_node_id(cid) == nid:
            return dict(item)
        step = prompt_step_edge(item)
        if step and str(step.get("id") or "") == nid:
            return dict(item)
    return None


def display_root_title(root: dict[str, Any] | None, root_id: str) -> str:
    item = root or {}
    label = str(item.get("lineageLabel") or "").strip()
    if label:
        return label
    return str(item.get("title") or item.get("game") or root_id)


def compact_from_modality(creations: Sequence[dict[str, Any]] | None) -> str:
    """One parent modality, or ``mixed`` when several kinds were used."""
    seen: list[str] = []
    for item in creations or []:
        mod = str((item or {}).get("modality") or "").strip().lower()
        if not mod or mod in seen:
            continue
        seen.append(mod)
    if not seen:
        return ""
    if len(seen) == 1:
        return seen[0]
    return "mixed"


def normalize_derived_edge(raw: Any) -> dict[str, str] | None:
    """Return a compact ``{id, role, ...}`` edge or None."""
    if isinstance(raw, (tuple, list)) and len(raw) >= 2:
        raw = {"id": raw[0], "role": raw[1]}
    if not isinstance(raw, dict):
        return None
    cid = str(raw.get("id") or "").strip()
    role = str(raw.get("role") or "source").strip().lower()
    if role not in VALID_ROLES:
        role = "source"
    if not cid:
        return None
    edge: dict[str, str] = {"id": cid, "role": role}
    if role == "prompt":
        preview = preview_prompt_text(str(raw.get("promptPreview") or ""))
        if preview:
            edge["promptPreview"] = preview
        from_mod = str(raw.get("fromModality") or "").strip().lower()[:24]
        to_mod = str(raw.get("toModality") or "").strip().lower()[:24]
        if from_mod:
            edge["fromModality"] = from_mod
        if to_mod:
            edge["toModality"] = to_mod
    return edge


def derived_from_edges(creation: dict[str, Any] | None) -> list[dict[str, str]]:
    raw = (creation or {}).get("derivedFrom")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        edge = normalize_derived_edge(item)
        if not edge:
            continue
        key = (edge["id"], edge["role"])
        if key in seen:
            continue
        seen.add(key)
        out.append(edge)
    return out


def derived_from_ids(creation: dict[str, Any] | None) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for edge in derived_from_edges(creation):
        if edge.get("role") == "prompt" or is_prompt_node_id(edge.get("id")):
            continue
        cid = edge["id"]
        if cid in seen:
            continue
        seen.add(cid)
        ids.append(cid)
    return ids


def _is_visual_creation(item: dict[str, Any] | None) -> bool:
    raw = str((item or {}).get("modality") or "").strip().lower()
    if raw in {"image", "video"}:
        return True
    mime = str((item or {}).get("mimeType") or "").lower().split(";", 1)[0].strip()
    return mime.startswith(("image/", "video/"))


def media_ancestor_ids(
    creation: dict[str, Any] | None,
    by_id: dict[str, dict[str, Any]] | None = None,
    *,
    limit: int = 32,
) -> list[str]:
    """Oldest-first media parent ids (skips prompt nodes)."""
    index = by_id or {}
    nearest: list[str] = []
    seen: set[str] = set()
    stack = list(reversed(derived_from_ids(creation)))
    while stack:
        cid = stack.pop()
        if not cid or cid in seen or is_prompt_node_id(cid):
            continue
        seen.add(cid)
        nearest.append(cid)
        parent = index.get(cid)
        if isinstance(parent, dict):
            for pid in reversed(derived_from_ids(parent)):
                if pid not in seen:
                    stack.append(pid)
        if len(nearest) >= limit:
            break
    nearest.reverse()
    return nearest


def extra_sources_are_lineage_context(
    sources: list[dict[str, Any]] | None,
) -> bool:
    """True when every extra tray item is a media ancestor of the last visual."""
    items = [s for s in (sources or []) if isinstance(s, dict)]
    if len(items) < 2:
        return False
    visual = None
    for item in reversed(items):
        if _is_visual_creation(item):
            visual = item
            break
    if not visual:
        return False
    vid = _creation_id(visual)
    if not vid:
        return False
    by_id = {_creation_id(s): s for s in items if _creation_id(s)}
    ancestors = set(media_ancestor_ids(visual, by_id))
    extras: list[str] = []
    for item in items:
        sid = _creation_id(item)
        if not sid or sid == vid:
            continue
        extras.append(sid)
    return bool(extras) and all(sid in ancestors for sid in extras)


def prompt_step_edge(creation: dict[str, Any] | None) -> dict[str, str] | None:
    for edge in derived_from_edges(creation):
        if edge.get("role") == "prompt":
            return edge
    return None


def attach_derived_from(
    creation: dict[str, Any] | None,
    edges: Iterable[Any] | None,
) -> dict[str, Any]:
    """Copy creation and append unique parent edges (no self-loops)."""
    item = dict(creation or {})
    cid = _creation_id(item)
    existing = derived_from_edges(item)
    seen = {(e["id"], e["role"]) for e in existing}
    for raw in edges or []:
        edge = normalize_derived_edge(raw)
        if not edge or edge["id"] == cid:
            continue
        key = (edge["id"], edge["role"])
        if key in seen:
            continue
        seen.add(key)
        existing.append(edge)
    if existing:
        item["derivedFrom"] = existing
    return item


def attach_prompt_step(
    creation: dict[str, Any] | None,
    *,
    prompt: str | None,
    from_modality: str = "",
    to_modality: str = "",
) -> dict[str, Any]:
    """Record a compact CREATE (or split/splice/duplicate) prompt step on the child."""
    item = dict(creation or {})
    if prompt_step_edge(item):
        return item
    preview = preview_prompt_text(prompt)
    if not preview:
        return item
    cid = _creation_id(item)
    to_mod = (to_modality or str(item.get("modality") or "")).strip().lower()
    from_mod = str(from_modality or "").strip().lower()
    edge: dict[str, str] = {
        "id": prompt_node_id(cid),
        "role": "prompt",
        "promptPreview": preview,
    }
    if from_mod:
        edge["fromModality"] = from_mod[:24]
    if to_mod:
        edge["toModality"] = to_mod[:24]
    return attach_derived_from(item, [edge])


def stamp_revised_at(creation: dict[str, Any] | None) -> dict[str, Any]:
    """Mark an in-place edit (extract / Apply) without adding a graph node."""
    item = dict(creation or {})
    item["revisedAt"] = _now_iso()
    return item


def _created_sort_key(item: dict[str, Any]) -> tuple[str, str]:
    stamp = str(item.get("revisedAt") or item.get("createdAt") or "")
    return stamp, _creation_id(item)


def _oldest_id(nodes: Sequence[dict[str, Any]]) -> str:
    present = [
        n
        for n in nodes
        if not n.get("missing")
        and n.get("kind") != "prompt"
        and _creation_id(n)
        and not is_prompt_node_id(_creation_id(n))
    ]
    if present:
        present = sorted(present, key=lambda n: (str(n.get("createdAt") or ""), _creation_id(n)))
        return _creation_id(present[0])
    for n in nodes:
        cid = _creation_id(n)
        if cid and not is_prompt_node_id(cid):
            return cid
    return ""


def connected_components(creations: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Union-find over derivedFrom. Missing parent ids become stub nodes."""
    items = [dict(c) for c in (creations or []) if _creation_id(c)]
    by_id = {_creation_id(c): c for c in items}
    all_ids: set[str] = set(by_id)
    parent_links: list[tuple[str, str]] = []
    for c in items:
        cid = _creation_id(c)
        for edge in derived_from_edges(c):
            if edge.get("role") == "prompt" or is_prompt_node_id(edge.get("id")):
                continue
            pid = edge["id"]
            all_ids.add(pid)
            parent_links.append((cid, pid))

    uf: dict[str, str] = {i: i for i in all_ids}

    def find(x: str) -> str:
        while uf[x] != x:
            uf[x] = uf[uf[x]]
            x = uf[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            uf[rb] = ra

    for child, parent in parent_links:
        union(child, parent)

    groups: dict[str, list[str]] = {}
    for cid in all_ids:
        groups.setdefault(find(cid), []).append(cid)

    components: list[dict[str, Any]] = []
    for ids in groups.values():
        nodes: list[dict[str, Any]] = []
        for cid in ids:
            if cid in by_id:
                nodes.append(dict(by_id[cid]))
            elif is_prompt_node_id(cid):
                continue
            else:
                nodes.append(
                    {
                        "id": cid,
                        "title": "Missing parent",
                        "modality": "",
                        "missing": True,
                    }
                )
        nodes.sort(key=_created_sort_key)
        media_edges: list[dict[str, str]] = []
        has_prompt = False
        for node in nodes:
            if node.get("missing"):
                continue
            if prompt_step_edge(node):
                has_prompt = True
            for edge in derived_from_edges(node):
                if edge.get("role") == "prompt" or is_prompt_node_id(edge.get("id")):
                    continue
                media_edges.append(
                    {"from": edge["id"], "to": _creation_id(node), "role": edge["role"]}
                )
        root_id = _oldest_id(nodes)
        present = [n for n in nodes if not n.get("missing")]
        updated = ""
        if present:
            updated = max(str(n.get("revisedAt") or n.get("createdAt") or "") for n in present)
        orphan = len(present) <= 1 and not media_edges and not has_prompt
        root = next((n for n in nodes if _creation_id(n) == root_id), nodes[0] if nodes else {})
        components.append(
            {
                "rootId": root_id,
                "rootTitle": display_root_title(root, root_id),
                "nodes": nodes,
                "edges": media_edges,
                "orphan": orphan,
                "updatedAt": updated,
            }
        )

    components.sort(
        key=lambda c: (not c["orphan"], c.get("updatedAt") or "", c.get("rootId") or ""),
        reverse=True,
    )
    return components


def expand_prompt_steps(component: dict[str, Any]) -> dict[str, Any]:
    """Insert lightweight prompt nodes between parent media and each generated child."""
    nodes = [dict(n) for n in (component.get("nodes") or [])]
    edges: list[dict[str, str]] = []
    prompt_nodes: list[dict[str, Any]] = []
    seen_prompt: set[str] = set()
    for node in nodes:
        if node.get("missing") or node.get("kind") == "prompt":
            continue
        cid = _creation_id(node)
        step = prompt_step_edge(node)
        parents = [
            e
            for e in derived_from_edges(node)
            if e.get("role") != "prompt" and not is_prompt_node_id(e.get("id"))
        ]
        if not step:
            for edge in parents:
                edges.append({"from": edge["id"], "to": cid, "role": edge["role"]})
            continue
        pid = step["id"] if is_prompt_node_id(step["id"]) else prompt_node_id(cid)
        if pid not in seen_prompt:
            preview = step.get("promptPreview") or "Prompt"
            prompt_nodes.append(
                {
                    "id": pid,
                    "kind": "prompt",
                    "title": preview,
                    "promptPreview": preview,
                    "fromModality": step.get("fromModality") or "",
                    "toModality": step.get("toModality") or str(node.get("modality") or ""),
                    "createdAt": str(node.get("createdAt") or ""),
                    "modality": "",
                    "missing": False,
                }
            )
            seen_prompt.add(pid)
        for edge in parents:
            edges.append({"from": edge["id"], "to": pid, "role": edge["role"]})
        edges.append({"from": pid, "to": cid, "role": "prompt"})
    out = dict(component)
    out["nodes"] = nodes + prompt_nodes
    out["edges"] = edges
    return out


def lineage_root_id(creations: Sequence[dict[str, Any]] | None, creation_id: str) -> str:
    cid = str(creation_id or "").strip()
    if not cid:
        return ""
    for component in connected_components(creations):
        ids = {_creation_id(n) for n in component.get("nodes") or []}
        if cid in ids:
            return str(component.get("rootId") or cid)
    return cid


def lineage_root_for_new(
    creations: Sequence[dict[str, Any]] | None,
    parent_ids: Sequence[str] | None,
    new_id: str,
) -> str:
    """Folder name for a creation that is not in the archive yet."""
    new_id = str(new_id or "").strip()
    parents = [
        str(p or "").strip()
        for p in (parent_ids or [])
        if str(p or "").strip() and not is_prompt_node_id(str(p))
    ]
    if not parents:
        return new_id
    items = [dict(c) for c in (creations or []) if _creation_id(c)]
    by_id = {_creation_id(c): c for c in items}
    reachable: set[str] = set()
    stack = list(parents)
    while stack:
        cid = stack.pop()
        if not cid or cid in reachable or is_prompt_node_id(cid):
            continue
        reachable.add(cid)
        src = by_id.get(cid)
        if src:
            stack.extend(derived_from_ids(src))
    existing = [by_id[i] for i in reachable if i in by_id]
    if existing:
        return _oldest_id(existing)
    return parents[0]


def _compact_node(node: dict[str, Any]) -> dict[str, Any]:
    kind = str(node.get("kind") or "")
    if not kind and is_prompt_node_id(_creation_id(node)):
        kind = "prompt"
    entry: dict[str, Any] = {
        "id": _creation_id(node),
        "title": str(node.get("title") or node.get("game") or _creation_id(node)),
        "modality": str(node.get("modality") or ""),
        "createdAt": str(node.get("createdAt") or ""),
        "missing": bool(node.get("missing")),
        "kind": kind,
    }
    revised = str(node.get("revisedAt") or "")
    if revised:
        entry["revisedAt"] = revised
    if kind == "prompt":
        entry["title"] = str(node.get("promptPreview") or node.get("title") or "Prompt")
        entry["promptPreview"] = str(node.get("promptPreview") or entry["title"])
        entry["fromModality"] = str(node.get("fromModality") or "")
        entry["toModality"] = str(node.get("toModality") or "")
    return entry


def lineage_payload(
    creations: Sequence[dict[str, Any]] | None,
    *,
    focus_id: str = "",
) -> dict[str, Any]:
    """JSON-safe graph for the Lineage screen (prompt nodes expanded)."""
    components = [expand_prompt_steps(c) for c in connected_components(creations)]
    focus = str(focus_id or "").strip()
    focus_root = ""
    if focus:
        for component in components:
            ids = {_creation_id(n) for n in component.get("nodes") or []}
            if focus in ids:
                focus_root = str(component.get("rootId") or "")
                break
    compact = []
    for component in components:
        compact.append(
            {
                "rootId": component.get("rootId"),
                "rootTitle": component.get("rootTitle"),
                "orphan": bool(component.get("orphan")),
                "updatedAt": component.get("updatedAt") or "",
                "nodes": [_compact_node(n) for n in component.get("nodes") or []],
                "edges": list(component.get("edges") or []),
            }
        )
    return {
        "components": compact,
        "focusId": focus,
        "focusRootId": focus_root,
    }


def inspect_lineage_node(
    creations: Sequence[dict[str, Any]] | None,
    node_id: str,
    *,
    prompt_text: str = "",
) -> dict[str, Any]:
    """View payload for one graph node. Prompt text is never the media body."""
    nid = str(node_id or "").strip()
    items = [dict(c) for c in (creations or []) if _creation_id(c)]
    by_id = {_creation_id(c): c for c in items}
    if not nid:
        return {"ok": False, "error": "No node selected."}

    if is_prompt_node_id(nid):
        child = creation_for_prompt_node(items, nid)
        step = prompt_step_edge(child) if child else None
        text = clip_prompt_text(prompt_text)
        if not text and child:
            text = clip_prompt_text(str(child.get("prompt") or ""))
        if not text and step:
            text = str(step.get("promptPreview") or "")
        created = ""
        from_mod = ""
        to_mod = ""
        child_id = ""
        if child:
            child_id = _creation_id(child)
            created = str(child.get("createdAt") or "")
            to_mod = str((step or {}).get("toModality") or child.get("modality") or "")
            from_mod = str((step or {}).get("fromModality") or "")
        if step:
            from_mod = str(step.get("fromModality") or from_mod)
            to_mod = str(step.get("toModality") or to_mod)
        if not child and not text:
            return {"ok": False, "error": "Prompt step not found.", "id": nid, "kind": "prompt"}
        return {
            "ok": True,
            "kind": "prompt",
            "id": nid,
            "childId": child_id,
            "title": "Prompt",
            "promptText": text,
            "fromModality": from_mod,
            "toModality": to_mod,
            "createdAt": created,
            "missing": not bool(child),
        }

    item = by_id.get(nid)
    if not item:
        return {
            "ok": True,
            "kind": "media",
            "id": nid,
            "title": "Missing parent",
            "modality": "",
            "missing": True,
            "body": "",
        }
    modality = str(item.get("modality") or "").strip().lower()
    title = str(item.get("title") or item.get("game") or nid)
    payload: dict[str, Any] = {
        "ok": True,
        "kind": "media",
        "id": nid,
        "title": title,
        "modality": modality,
        "createdAt": str(item.get("createdAt") or ""),
        "missing": False,
        "mimeType": str(item.get("mimeType") or ""),
        "mediaPath": str(item.get("mediaPath") or ""),
        "body": creation_result_text(item),
        "creationType": str(item.get("creationType") or ""),
        "creation": dict(item),
    }
    revised = str(item.get("revisedAt") or "")
    if revised:
        payload["revisedAt"] = revised
    return payload
