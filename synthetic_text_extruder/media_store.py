"""File-backed storage for generated images and videos."""

from __future__ import annotations

import base64
import mimetypes
import re
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, load_config

_SAFE_ID = re.compile(r"[^a-zA-Z0-9_-]+")

EXT_FOR_MIME: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/ogg": ".ogg",
    "application/pdf": ".pdf",
}

MIME_FOR_EXT: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".pdf": "application/pdf",
}

_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv"}


def _folder_from_paths(config: dict[str, Any] | None, key: str, default: str) -> Path:
    cfg = config if config is not None else load_config()
    rel = ((cfg.get("paths") or {}).get(key) or default).strip() or default
    path = Path(rel).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def media_dir(config: dict[str, Any] | None = None) -> Path:
    return _folder_from_paths(config, "media", "media")


def exports_dir(config: dict[str, Any] | None = None) -> Path:
    """Default Save As folder (user-owned copies)."""
    return _folder_from_paths(config, "exports", "exports")


def default_exports_dir() -> Path:
    return (PROJECT_ROOT / "exports").resolve()


def default_media_dir() -> Path:
    """Built-in project `media/` folder (used as a read fallback)."""
    return (PROJECT_ROOT / "media").resolve()


def media_read_roots(config: dict[str, Any] | None = None) -> list[Path]:
    """Folders allowed when opening an Archive media file."""
    current = media_dir(config)
    roots = [current]
    legacy = default_media_dir()
    if legacy != current:
        roots.append(legacy)
    return roots


def _safe_basename(name: str) -> str | None:
    base = Path(str(name or "")).name
    if not base or base in {".", ".."} or ".." in Path(base).parts:
        return None
    if "/" in base or "\\" in base:
        return None
    return base


def _join_under_dir(root: Path, name: str) -> Path | None:
    """Rebuild root / basename so the result cannot escape root."""
    return _join_rel_under_dir(root, [name])


def _join_rel_under_dir(root: Path, parts: Sequence[str]) -> Path | None:
    """Rebuild root / part / part so the result cannot escape root (max two parts)."""
    cleaned: list[str] = []
    for part in parts:
        base = _safe_basename(str(part))
        if base is None:
            return None
        cleaned.append(base)
    if not cleaned or len(cleaned) > 2:
        return None
    try:
        parent = root.expanduser().resolve()
        dest = parent
        for base in cleaned:
            dest = dest / base
        dest = dest.resolve()
        dest.relative_to(parent)
    except (OSError, ValueError):
        return None
    return dest


def _resolve_within_roots(
    candidate: Path, roots: list[Path], *, must_exist: bool
) -> Path | None:
    # Rebuild from each root + basename; do not resolve the raw candidate.
    base = _safe_basename(Path(str(candidate)).name)
    if base is None:
        return None
    for root in roots:
        dest = _join_under_dir(root, base)
        if dest is None:
            continue
        if must_exist and not dest.is_file():
            continue
        return dest
    return None


def _safe_stem(creation_id: str) -> str:
    stem = _SAFE_ID.sub("_", (creation_id or "media").strip()) or "media"
    return stem[:80]


def extension_for_mime(mime_type: str | None, fallback: str = ".bin") -> str:
    mime = (mime_type or "").strip().lower()
    if mime in EXT_FOR_MIME:
        return EXT_FOR_MIME[mime]
    guessed = mimetypes.guess_extension(mime.split(";")[0].strip()) if mime else None
    return guessed or fallback


def mime_for_path(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in MIME_FOR_EXT:
        return MIME_FOR_EXT[ext]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def modality_for_path(path: Path) -> str | None:
    """Viewer/import type for a user-chosen file, or None if unsupported."""
    suffix = Path(path).suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        return "text"
    mime = str(mime_for_path(path) or "").split(";", 1)[0].strip().lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if mime == "application/pdf" or suffix == ".pdf":
        return "pdf"
    return None


_SKIP_RELOCATE_NAMES = {
    "archives.json",
    "prompts.json",
    "config.yaml",
    "config.local.yaml",
}


def stored_media_path(dest: Path) -> str:
    """Portable relative path under the project, otherwise absolute."""
    try:
        safe = dest.expanduser().resolve()
    except OSError as exc:
        raise ValueError("Invalid media path") from exc
    if safe.name in {".", ".."} or ".." in safe.parts:
        raise ValueError("Invalid media path")
    try:
        rel = safe.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return safe.as_posix()
    if ".." in rel.parts:
        raise ValueError("Invalid media path")
    return rel.as_posix()


def lineage_subdir_from_media_path(media_path: str | None) -> str | None:
    """Return the lineage folder name if mediaPath is ``media/root/file.ext``."""
    if not media_path:
        return None
    raw = Path(str(media_path).strip().replace("\\", "/"))
    if ".." in raw.parts:
        return None
    parts = [p for p in raw.parts if p not in {"/", "\\"}]
    if raw.anchor:
        parts = list(raw.parts[1:]) if len(raw.parts) > 1 else []
    if parts and parts[0].lower() == "media":
        parts = parts[1:]
    if len(parts) < 2:
        return None
    folder = _safe_basename(parts[0])
    name = _safe_basename(parts[1])
    if not folder or not name:
        return None
    return folder


def unique_media_filename(dest_dir: Path, filename: str) -> str:
    """Pick a name in dest_dir that does not already exist."""
    name = Path(filename).name
    if not name or name in {".", ".."} or ".." in Path(name).parts:
        name = "media.bin"
    dest_dir = dest_dir.resolve()
    if not (dest_dir / name).exists():
        return name
    stem = Path(name).stem or "media"
    suffix = Path(name).suffix
    n = 1
    while n <= 10_000:
        candidate = f"{stem}_{n}{suffix}"
        if not (dest_dir / candidate).exists():
            return candidate
        n += 1
    raise ValueError("Could not pick a unique media filename")


def resolve_path_under_folder(media_path: str | None, folder: Path) -> Path | None:
    """Resolve an Archive mediaPath if it sits inside folder."""
    if not media_path:
        return None
    raw = Path(str(media_path).strip())
    if ".." in raw.parts:
        return None
    try:
        root = folder.expanduser().resolve()
    except OSError:
        return None
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(PROJECT_ROOT / raw)
        if raw.parts and raw.parts[0].lower() == "media":
            candidates.append(root / Path(*raw.parts[1:]))
        elif len(raw.parts) <= 2 and not raw.is_absolute():
            candidates.append(root / raw)
        if raw.name:
            candidates.append(root / raw.name)
            try:
                if root.is_dir():
                    for child in root.iterdir():
                        if child.is_dir() and _safe_basename(child.name):
                            candidates.append(child / raw.name)
            except OSError:
                pass
    seen: set[str] = set()
    for cand in candidates:
        key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        try:
            resolved = cand.expanduser().resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if resolved.is_file():
            return resolved
    return None


def collect_relocatable_media(
    source: Path,
    dest: Path,
    creations: list[dict[str, Any]] | None = None,
) -> list[Path]:
    """Media files in source (by extension or Archive record) to move into dest."""
    try:
        source = source.expanduser().resolve()
        dest = dest.expanduser().resolve()
    except OSError:
        return []
    if source == dest or not source.is_dir():
        return []

    found: dict[str, Path] = {}

    def _consider(child: Path) -> None:
        if not child.is_file():
            return
        if child.name.lower() in _SKIP_RELOCATE_NAMES:
            return
        if child.suffix.lower() not in MIME_FOR_EXT:
            return
        try:
            resolved = child.resolve()
            resolved.relative_to(source)
        except (OSError, ValueError):
            return
        found[str(resolved)] = resolved

    try:
        children = list(source.iterdir())
    except OSError:
        children = []
    for child in children:
        if child.is_dir():
            if _safe_basename(child.name) is None:
                continue
            try:
                nested = list(child.iterdir())
            except OSError:
                continue
            for inner in nested:
                _consider(inner)
            continue
        _consider(child)

    for creation in creations or []:
        resolved = resolve_path_under_folder(creation.get("mediaPath"), source)
        if resolved is None:
            continue
        found[str(resolved)] = resolved
    return list(found.values())


def relocate_media_to_folder(
    source: Path,
    dest: Path,
    creations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Move media files from source into dest and rewrite Archive mediaPath values."""
    try:
        source = source.expanduser().resolve()
        dest = dest.expanduser().resolve()
    except OSError as exc:
        raise ValueError(f"Cannot use that folder: {exc}") from exc
    dest.mkdir(parents=True, exist_ok=True)
    files = collect_relocatable_media(source, dest, creations)
    old_by_creation: dict[str, Path] = {}
    for creation in creations:
        cid = str(creation.get("id") or "")
        resolved = resolve_path_under_folder(creation.get("mediaPath"), source)
        if cid and resolved is not None:
            old_by_creation[cid] = resolved

    moved_map: dict[str, str] = {}
    moved = 0
    skipped = 0
    for src_file in files:
        try:
            src_resolved = src_file.resolve()
            src_resolved.relative_to(source)
        except (OSError, ValueError):
            skipped += 1
            continue
        try:
            src_resolved.relative_to(dest)
            skipped += 1
            continue
        except ValueError:
            pass
        try:
            rel = src_resolved.relative_to(source)
        except ValueError:
            rel = Path(src_resolved.name)
        if ".." in rel.parts or len(rel.parts) > 2:
            skipped += 1
            continue
        dest_subdir = dest
        if len(rel.parts) == 2:
            folder = _safe_basename(rel.parts[0])
            if folder is None:
                skipped += 1
                continue
            dest_subdir = dest / folder
            dest_subdir.mkdir(parents=True, exist_ok=True)
        new_name = unique_media_filename(dest_subdir, src_resolved.name)
        dest_file = dest_subdir / new_name
        try:
            dest_resolved = dest_file.resolve()
            dest_resolved.relative_to(dest)
        except (OSError, ValueError):
            skipped += 1
            continue
        if ".." in Path(new_name).parts:
            skipped += 1
            continue
        try:
            shutil.move(str(src_resolved), str(dest_resolved))
        except OSError:
            skipped += 1
            continue
        moved_map[str(src_resolved)] = stored_media_path(dest_resolved)
        moved += 1

    updated = 0
    new_creations: list[dict[str, Any]] = []
    for creation in creations:
        item = dict(creation)
        cid = str(item.get("id") or "")
        old = old_by_creation.get(cid)
        if old is not None and str(old) in moved_map:
            item["mediaPath"] = moved_map[str(old)]
            updated += 1
        new_creations.append(item)
    return new_creations, {"moved": moved, "updated": updated, "skipped": skipped}


def write_media_bytes(
    creation_id: str,
    data: bytes,
    *,
    mime_type: str,
    config: dict[str, Any] | None = None,
    suffix: str | None = None,
    lineage_root: str | None = None,
    nested: bool = True,
) -> dict[str, str]:
    """Write bytes under media/ and return relative mediaPath + mimeType.

    New library files go in ``{media}/{lineageRoot}/{creationId}.ext``.
    Pass ``nested=False`` to overwrite a legacy flat ``media/{id}.ext`` file.
    """
    if not data:
        raise ValueError("Empty media payload")
    ext = suffix or extension_for_mime(mime_type)
    if not ext.startswith("."):
        ext = "." + ext
    filename = f"{_safe_stem(creation_id)}{ext}"
    root = media_dir(config)
    dest: Path | None
    if nested:
        folder = _safe_stem(lineage_root or creation_id)
        dest_dir = _join_rel_under_dir(root, [folder])
        if dest_dir is None:
            raise ValueError("Invalid media destination path")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = _join_rel_under_dir(root, [folder, filename])
    else:
        dest = _join_under_dir(root, filename)
    if dest is None:
        raise ValueError("Invalid media destination path")
    dest.write_bytes(data)
    return {
        "mediaPath": stored_media_path(dest),
        "mimeType": mime_type or mime_for_path(dest),
    }


def overwrite_media_bytes(
    creation: dict[str, Any],
    data: bytes,
    *,
    mime_type: str,
    config: dict[str, Any] | None = None,
    suffix: str | None = None,
) -> dict[str, str]:
    """Overwrite an existing library file in place, or write a new nested file."""
    if not data:
        raise ValueError("Empty media payload")
    cid = str(creation.get("id") or "").strip() or "media"
    existing = resolve_media_path(creation.get("mediaPath"), config=config)
    if existing is not None and existing.is_file():
        existing.write_bytes(data)
        return {
            "mediaPath": str(creation.get("mediaPath") or stored_media_path(existing)),
            "mimeType": mime_type or mime_for_path(existing),
        }
    nested = lineage_subdir_from_media_path(str(creation.get("mediaPath") or ""))
    return write_media_bytes(
        cid,
        data,
        mime_type=mime_type,
        config=config,
        suffix=suffix,
        lineage_root=nested or cid,
        nested=True,
    )


def place_library_media(
    creation: dict[str, Any],
    lineage_root: str,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Move a library file into ``{media}/{lineageRoot}/{filename}`` if needed."""
    item = dict(creation or {})
    path = resolve_media_path(item.get("mediaPath"), config=config)
    if path is None or not path.is_file():
        return item
    folder = _safe_stem(lineage_root or str(item.get("id") or "media"))
    filename = path.name
    dest = _join_rel_under_dir(media_dir(config), [folder, filename])
    if dest is None:
        return item
    try:
        if path.resolve() == dest.resolve():
            item["mediaPath"] = stored_media_path(dest)
            return item
    except OSError:
        return item
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        item["mediaPath"] = stored_media_path(dest)
        return item
    try:
        shutil.move(str(path), str(dest))
    except OSError:
        return item
    old_parent = path.parent
    try:
        if old_parent.is_dir() and not any(old_parent.iterdir()):
            old_parent.rmdir()
    except OSError:
        pass
    item["mediaPath"] = stored_media_path(dest)
    return item


def media_http_relpath(path: Path, config: dict[str, Any] | None = None) -> str:
    """Path under /media/ for the local HTTP server (posix, no leading slash)."""
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return path.name
    for root in media_read_roots(config):
        try:
            rel = resolved.relative_to(Path(root).expanduser().resolve())
        except (OSError, ValueError):
            continue
        if ".." in rel.parts or not rel.parts or len(rel.parts) > 2:
            continue
        cleaned = [_safe_basename(p) for p in rel.parts]
        if any(p is None for p in cleaned):
            continue
        return "/".join(cleaned)  # type: ignore[arg-type]
    return path.name


def _find_basename_in_roots(name: str, roots: list[Path]) -> Path | None:
    base = _safe_basename(name)
    if base is None:
        return None
    for root in roots:
        dest = _join_under_dir(root, base)
        if dest is not None and dest.is_file():
            return dest
        try:
            if not root.is_dir():
                continue
            for child in root.iterdir():
                if not child.is_dir() or _safe_basename(child.name) is None:
                    continue
                dest = _join_rel_under_dir(root, [child.name, base])
                if dest is not None and dest.is_file():
                    return dest
        except OSError:
            continue
    return None


def resolve_media_path(media_path: str | None, config: dict[str, Any] | None = None) -> Path | None:
    if not media_path:
        return None
    raw = Path(str(media_path).strip())
    if ".." in raw.parts:
        return None
    roots = media_read_roots(config)
    rel_parts: list[str] = []
    parts = list(raw.parts)
    if parts and parts[0].lower() == "media":
        rel_parts = parts[1:]
    elif not raw.is_absolute():
        rel_parts = parts
    if len(rel_parts) in {1, 2} and all(_safe_basename(p) for p in rel_parts):
        for root in roots:
            dest = _join_rel_under_dir(root, rel_parts)
            if dest is not None and dest.is_file():
                return dest
        dest = _join_rel_under_dir(PROJECT_ROOT / "media", rel_parts) if rel_parts else None
        if dest is not None and dest.is_file():
            try:
                dest.relative_to((PROJECT_ROOT / "media").resolve())
                return dest
            except (OSError, ValueError):
                pass

    found = _find_basename_in_roots(raw.name, roots)
    if found:
        return found

    # Trusted Archive absolute path (previous custom folder) still on disk.
    if raw.is_absolute():
        try:
            resolved = raw.resolve()
        except OSError:
            return None
        if resolved.is_file():
            return resolved
    return None


def read_media_bytes(media_path: str | None, config: dict[str, Any] | None = None) -> bytes | None:
    path = resolve_media_path(media_path, config)
    if path is None:
        return None
    return path.read_bytes()


def media_data_url(media_path: str | None, mime_type: str | None = None) -> str | None:
    raw = read_media_bytes(media_path)
    if raw is None:
        return None
    path = resolve_media_path(media_path)
    mime = (mime_type or (mime_for_path(path) if path else None) or "application/octet-stream")
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def media_file_uri(media_path: str | None) -> str | None:
    path = resolve_media_path(media_path)
    if path is None:
        return None
    return path.as_uri()
