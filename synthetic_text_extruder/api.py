"""JavaScript ↔ Python bridge exposed to the web UI via pywebview."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from . import __version__
from .config import load_config, save_config
from .gemini_provider import (
    SUGGESTED_GEMINI_MODELS,
    _gemini_model_id,
    extract_model_from_gemini_error,
    is_retired_gemini_error,
    learn_retired_gemini_model,
    list_available_gemini_models,
    merged_retired_aliases,
    resolve_api_key as resolve_gemini_key,
)
from .creation_utils import AmbiguousGameError
from .generator import generate_creation, provider_status
from .presets import CREATION_TYPES, PLATFORM_OPTIONS, PLATFORMS, POPULAR_GAME_PRESETS
from .storage import ArchiveStore, PromptStore

logger = logging.getLogger(__name__)


def _file_dialog(kind: str) -> Any:
    """pywebview file-dialog kind. Prefer FileDialog enum over deprecated constants."""
    import webview

    fd = getattr(webview, "FileDialog", None)
    if fd is not None:
        try:
            return getattr(fd, kind.upper())
        except AttributeError as exc:
            raise ValueError(f"Unknown FileDialog kind: {kind!r}") from exc
    # Older pywebview (<6) fallback
    legacy = {
        "open": "OPEN_DIALOG",
        "save": "SAVE_DIALOG",
        "folder": "FOLDER_DIALOG",
    }
    name = legacy.get(kind.lower())
    if not name or not hasattr(webview, name):
        raise ValueError(f"Unknown file dialog kind: {kind!r}")
    return getattr(webview, name)


def _save_file_types(suffix: str) -> tuple[str, ...]:
    """pywebview file_types entry for a save dialog, or empty if unknown."""
    labels = {
        ".png": "PNG Image (*.png)",
        ".pdf": "PDF Document (*.pdf)",
        ".mp4": "MP4 Video (*.mp4)",
        ".mp3": "MP3 Audio (*.mp3)",
        ".json": "JSON (*.json)",
        ".txt": "Text File (*.txt)",
    }
    key = suffix.lower()
    if key and not key.startswith("."):
        key = "." + key
    label = labels.get(key)
    return (label,) if label else ()


def _ensure_save_suffix(path: Path, suffix: str) -> Path:
    """Force a save path to end with suffix, replacing any other extension."""
    want = (suffix or "").lower()
    if not want:
        return path
    if not want.startswith("."):
        want = "." + want
    if path.suffix.lower() != want:
        return path.with_suffix(want)
    return path


def _safe_dialog_save_path(dialog_result: Any, suffix: str) -> Path:
    """Rebuild a save-dialog path from resolved parent + sanitized filename.

    Native dialogs return a user-chosen location. Writing that string directly
    is a path-injection sink (CodeQL py/path-injection). Only the basename is
    kept; the file must stay inside the resolved parent folder.
    """
    raw = dialog_result if isinstance(dialog_result, str) else dialog_result[0]
    picked = Path(str(raw or "").strip())
    if not picked.name or ".." in picked.parts:
        raise ValueError("Invalid save path")
    parent = picked.expanduser().resolve().parent
    if not parent.is_dir():
        raise ValueError("Save folder does not exist")
    name = _ensure_save_suffix(Path(picked.name), suffix).name
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("Invalid save filename")
    dest = (parent / name).resolve()
    dest.relative_to(parent)
    return dest

class Api:
    """Methods on this class are callable from window.pywebview.api in the UI."""

    def __init__(self) -> None:
        self.config = load_config()
        self.store = ArchiveStore()
        self.prompt_store = PromptStore()
        self._window = None
        self._ui_origin: str | None = None
        self._gen_lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._jobs_lock = threading.Lock()
        self._cancel_events: dict[str, threading.Event] = {}

    def set_window(self, window) -> None:  # noqa: ANN001 — pywebview Window
        self._window = window

    def set_ui_origin(self, origin: str | None) -> None:
        """Localhost origin that serves UI + /media/ (for WebView-safe video URLs)."""
        self._ui_origin = (origin or "").rstrip("/") or None

    # ── Jobs (JS polls these — reliable vs evaluate_js from worker threads) ──

    def _set_job(self, job_id: str, **fields: Any) -> None:
        with self._jobs_lock:
            job = self._jobs.setdefault(job_id, {"id": job_id, "status": "queued"})
            job.update(fields)

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            if not job:
                return {"id": job_id, "status": "missing", "error": "Unknown job id"}
            # Return a shallow copy so callers can mutate safely
            return dict(job)

    def _maybe_learn_retired_gemini(
        self, exc: BaseException, *, fallback_model: str = ""
    ) -> dict[str, Any] | None:
        """
        If Gemini returned a retired/missing-model error, persist an alias,
        switch the active slot when needed, and return UI details.
        """
        backend = (
            (self.config.get("backend") or {}).get("provider") or "gemini"
        ).lower().strip()
        if backend not in {"gemini", "google", "google-gemini"}:
            return None
        if not is_retired_gemini_error(exc):
            return None
        mid = extract_model_from_gemini_error(exc) or (fallback_model or "").strip()
        if not mid:
            return None
        try:
            info = learn_retired_gemini_model(self.config, mid)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to learn retired Gemini model %s", mid)
            return None
        self.config = info["config"]
        return {
            "retired": info["retired"],
            "replacement": info["replacement"],
            "modality": info["modality"],
            "switched": info["switched"],
            "message": info["message"],
            "gemini": (self.config.get("gemini") or {}),
        }

    def ping(self) -> dict[str, Any]:
        """Health check used by the UI to verify the Python bridge."""
        return {"ok": True, "version": __version__}

    def check_modality_match(self, prompt: str = "") -> dict[str, Any]:
        """Preflight: can this prompt run on the active backend?"""
        from .generator import _active_model_and_provider
        from .modality import check_prompt_model_compatibility

        model_id, provider = _active_model_and_provider(self.config)
        result = check_prompt_model_compatibility(
            prompt or "",
            model_id,
            provider=provider,
            gemini_cfg=self.config.get("gemini"),
        )
        return result

    # ── Catalog / config ──────────────────────────────────────────────

    def get_bootstrap(self) -> dict[str, Any]:
        creations = self.store.load()
        aliases = merged_retired_aliases(self.config.get("gemini") or {})
        return {
            "version": __version__,
            "config": self._public_config(),
            "suggestedGeminiModels": [
                m
                for m in SUGGESTED_GEMINI_MODELS
                if (m.get("repo_id") or "").lower() not in {k.lower() for k in aliases}
            ],
            "retiredGeminiModels": sorted(
                {_gemini_model_id(k).lower() for k in aliases if _gemini_model_id(k)}
            ),
            "platforms": PLATFORM_OPTIONS,
            "hardwarePlatforms": PLATFORMS,
            "creationTypes": CREATION_TYPES,
            "presets": POPULAR_GAME_PRESETS,
            "creations": creations,
            "prompts": self.prompt_store.load(),
            "modelStatus": provider_status(self.config),
            "geminiTools": self._gemini_tools_catalog(),
        }

    def _gemini_tools_catalog(self) -> list[dict[str, str]]:
        from .gemini_tools import list_tool_catalog

        return list_tool_catalog()

    def list_gemini_tools(self) -> dict[str, Any]:
        """Built-in Gemini file tools available when Use Tools is enabled."""
        return {"ok": True, "tools": self._gemini_tools_catalog()}

    def get_google_workspace_auth_status(self) -> dict[str, Any]:
        """Whether Google Workspace OAuth client + token are configured."""
        from .google_auth import google_auth_status

        return google_auth_status(self.config)

    def authorize_google_workspace(self) -> dict[str, Any]:
        """Run desktop OAuth for Gmail, Drive, Docs, and Calendar (opens browser)."""
        from .google_auth import authorize_google

        return authorize_google(self.config)

    def pick_google_workspace_credentials(self) -> dict[str, Any]:
        """Pick a Google OAuth client JSON file for Workspace tools."""
        import webview

        if self._window is None:
            return {"ok": False, "error": "No window"}
        result = self._window.create_file_dialog(
            _file_dialog("open"),
            allow_multiple=False,
            file_types=("JSON (*.json)", "All Files (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        path = Path(result if isinstance(result, str) else result[0])
        if not path.is_file():
            return {"ok": False, "error": f"File not found: {path}"}
        return {"ok": True, "path": str(path.resolve())}

    # Older Control Panel JS called these Gmail names.
    def get_gmail_auth_status(self) -> dict[str, Any]:
        return self.get_google_workspace_auth_status()

    def authorize_gmail(self) -> dict[str, Any]:
        return self.authorize_google_workspace()

    def pick_gmail_credentials(self) -> dict[str, Any]:
        return self.pick_google_workspace_credentials()

    def pick_media_folder(self) -> dict[str, Any]:
        """Pick a folder for generated/imported images, video, and audio."""
        from .config import normalize_media_folder
        from .media_store import media_dir

        if self._window is None:
            return {"ok": False, "error": "No window"}
        try:
            start = str(media_dir(self.config))
        except OSError:
            start = ""
        dialog_kwargs: dict[str, Any] = {}
        if start:
            dialog_kwargs["directory"] = start
        result = self._window.create_file_dialog(
            _file_dialog("folder"),
            **dialog_kwargs,
        )
        if not result:
            return {"ok": False, "cancelled": True}
        path = Path(result if isinstance(result, str) else result[0])
        if path.is_file():
            path = path.parent
        try:
            path = path.expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": f"Cannot use that folder: {exc}"}
        if not path.is_dir():
            return {"ok": False, "error": f"Not a folder: {path}"}
        stored = normalize_media_folder(str(path))
        return {"ok": True, "path": stored, "resolved": str(path)}

    def relocate_media_files(self, source: Any = None) -> dict[str, Any]:
        """Move media files from a previous folder into the current media folder."""
        from .media_store import media_dir, relocate_media_to_folder

        if isinstance(source, dict):
            source = source.get("source")
        raw = str(source or "").strip()
        if not raw or ".." in Path(raw).parts:
            return {"ok": False, "error": "Invalid source folder"}
        try:
            src = Path(raw).expanduser().resolve()
        except OSError as exc:
            return {"ok": False, "error": f"Cannot use that folder: {exc}"}
        if not src.is_dir():
            return {"ok": False, "error": f"Not a folder: {src}"}
        try:
            dest = media_dir(self.config)
        except OSError as exc:
            return {"ok": False, "error": f"Cannot use the new media folder: {exc}"}
        if src == dest:
            return {
                "ok": True,
                "moved": 0,
                "updated": 0,
                "skipped": 0,
                "creations": self.store.load(),
                "message": "Already using that folder.",
            }
        try:
            updated, stats = relocate_media_to_folder(src, dest, self.store.load())
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except OSError as exc:
            return {"ok": False, "error": f"Could not move media files: {exc}"}
        if stats.get("updated"):
            self.store.save(updated)
        else:
            updated = self.store.load()
        return {
            "ok": True,
            "creations": updated,
            "moved": stats.get("moved", 0),
            "updated": stats.get("updated", 0),
            "skipped": stats.get("skipped", 0),
            "source": str(src),
            "dest": str(dest),
        }

    def _apply_media_http_root(self) -> None:
        """Point localhost /media/ at the saved folder without restarting."""
        try:
            from .app import set_media_http_root
            from .media_store import media_dir

            set_media_http_root(media_dir(self.config))
        except Exception:  # noqa: BLE001
            logger.debug("Could not refresh media HTTP root", exc_info=True)

    def _public_config(self) -> dict[str, Any]:
        cfg = self.config
        gemini = dict(cfg.get("gemini") or {})
        if gemini.get("api_key"):
            gemini["api_key_set"] = True
            gemini["api_key"] = ""
        else:
            gemini["api_key_set"] = bool(resolve_gemini_key(cfg.get("gemini") or {}))

        from .media_store import media_dir

        paths = dict(cfg.get("paths") or {})
        try:
            paths["media_resolved"] = str(media_dir(cfg))
        except OSError:
            paths["media_resolved"] = str(paths.get("media") or "media")

        return {
            "backend": {"provider": "gemini"},
            "gemini": gemini,
            "prompt": dict(cfg.get("prompt") or {}),
            "google_workspace": dict(cfg.get("google_workspace") or {}),
            "ui": dict(cfg.get("ui") or {}),
            "paths": paths,
        }

    def get_model_status(self) -> dict[str, Any]:
        return provider_status(self.config)

    def list_gemini_models(self) -> dict[str, Any]:
        """Fetch generateContent models available to the saved Gemini API key."""
        gemini_cfg = self.config.get("gemini") or {}
        key = resolve_gemini_key(gemini_cfg)
        aliases = merged_retired_aliases(gemini_cfg)
        if not key:
            return {
                "ok": False,
                "error": "Paste a Gemini API key and Save before refreshing the model list.",
                "models": [
                    m
                    for m in SUGGESTED_GEMINI_MODELS
                    if (m.get("repo_id") or "").lower()
                    not in {k.lower() for k in aliases}
                ],
                "source": "fallback",
            }
        try:
            models = list_available_gemini_models(key, retired_aliases=aliases)
            return {
                "ok": True,
                "models": models,
                "source": "live",
                "count": len(models),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("list_gemini_models failed: %s", exc)
            return {
                "ok": False,
                "error": str(exc),
                "models": [
                    m
                    for m in SUGGESTED_GEMINI_MODELS
                    if (m.get("repo_id") or "").lower()
                    not in {k.lower() for k in aliases}
                ],
                "source": "fallback",
            }

    def recommend_models(self, criteria: str = "balanced", provider: str = "") -> dict[str, Any]:
        """Pick Text / Image / Video Gemini models from Google's catalog."""
        from .recommend_models import recommend_models_for_config

        try:
            return recommend_models_for_config(
                self.config,
                criteria,
                provider=(provider or "").strip() or None,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("recommend_models failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def save_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Persist Control Panel changes."""
        if not isinstance(updates, dict):
            return {"ok": False, "error": "Invalid settings payload"}

        updates.pop("reload_model", False)

        from .media_store import collect_relocatable_media, media_dir

        try:
            old_media_root = media_dir(self.config)
        except OSError:
            old_media_root = None

        self.config = save_config(updates, existing=self.config)
        self._apply_media_http_root()

        result: dict[str, Any] = {
            "ok": True,
            "config": self._public_config(),
            "modelStatus": provider_status(self.config),
            "message": "Settings saved.",
        }
        try:
            if old_media_root is not None:
                new_media_root = media_dir(self.config)
                if new_media_root != old_media_root:
                    pending = collect_relocatable_media(
                        old_media_root, new_media_root, self.store.load()
                    )
                    if pending:
                        result["mediaMove"] = {
                            "offered": True,
                            "count": len(pending),
                            "source": str(old_media_root),
                            "dest": str(new_media_root),
                        }
        except Exception:  # noqa: BLE001
            logger.debug("Could not preview media folder move", exc_info=True)
        return result

    def preload_model(self) -> dict[str, Any]:
        """Gemini uses the cloud API — nothing to download locally."""
        status = provider_status(self.config)
        return {
            "ok": True,
            "message": status.get("detail") or "Gemini uses the cloud API — no local download.",
            "modelStatus": status,
        }

    # ── Archives ──────────────────────────────────────────────────────

    def list_creations(self) -> list[dict[str, Any]]:
        return self.store.load()

    def save_creation(self, creation: dict[str, Any]) -> dict[str, Any]:
        return self.store.upsert(creation)

    def delete_creation(self, creation_id: str) -> list[dict[str, Any]]:
        return self.store.delete(creation_id)

    def import_creations(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.store.import_items(items)

    def export_creations_json(self) -> str:
        return self.store.export_json()

    def list_prompts(self) -> dict[str, Any]:
        return {"ok": True, "prompts": self.prompt_store.load()}

    def save_prompt(self, prompt: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            saved = self.prompt_store.upsert(prompt or {})
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("save_prompt failed")
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "prompt": saved, "prompts": self.prompt_store.load()}

    def delete_prompt(self, prompt_id: str) -> dict[str, Any]:
        prompt_id = (prompt_id or "").strip()
        if not prompt_id:
            return {"ok": False, "error": "No prompt selected"}
        prompts = self.prompt_store.delete(prompt_id)
        return {"ok": True, "prompts": prompts}

    # ── Generation ────────────────────────────────────────────────────

    def create_creation(
        self,
        game: str,
        platform: str,
        creation_type: str,
        exact_title: bool = False,
        creation_description: str = "",
        basis_creation_id: str = "",
        tool_aliases: list[str] | None = None,
        search_query: str = "",
        source_creation_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Start generation in a background thread; UI must poll get_job(job_id)."""
        logger.info(
            "create_creation requested: %s / %s / %s (exact=%s, basis=%s, sources=%s, tools=%s, search=%s)",
            game,
            platform,
            creation_type,
            exact_title,
            (basis_creation_id or "")[:24] or "-",
            len(source_creation_ids or []),
            ",".join(tool_aliases or []) or "-",
            "yes" if (search_query or "").strip() else "no",
        )

        if not game or not platform or not creation_type:
            return {
                "ok": False,
                "error": "game, platform, and creationType are required.",
            }

        from .generator import _active_model_and_provider
        from .modality import (
            check_prompt_model_compatibility,
            infer_layout_extract_intent,
            infer_text_extract_intent,
        )

        desc_preview = (creation_description or "").strip() or game
        basis_id = (basis_creation_id or "").strip()
        basis_media: dict[str, Any] | None = None
        source_creations: list[dict[str, Any]] = []
        try:
            source_creations = self._resolve_source_creations(source_creation_ids)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        from .studio_sources import (
            DEFAULT_REPORT_PROMPT,
            last_visual_source,
            match_quoted_source,
            wants_source_report,
        )
        from .collection_jobs import wants_collection_job

        if source_creations and not (creation_description or "").strip():
            desc_preview = DEFAULT_REPORT_PROMPT
        extract_job = infer_layout_extract_intent(
            desc_preview
        ) or infer_text_extract_intent(desc_preview)
        named_visual = None
        if extract_job and source_creations:
            named_visual, match_err = match_quoted_source(
                desc_preview,
                source_creations,
                modalities={"image", "video"},
            )
            if match_err:
                return {"ok": False, "error": match_err}
            if named_visual:
                basis_id = str(named_visual.get("id") or "").strip()
        visual = named_visual or last_visual_source(source_creations)
        if visual and not basis_id:
            basis_id = str(visual.get("id") or "").strip()
        will_report = wants_source_report(desc_preview, source_creations)
        will_collection = wants_collection_job(desc_preview, source_creations)
        if basis_id:
            try:
                basis_media = self._resolve_basis_media(basis_id)
            except Exception as exc:  # noqa: BLE001
                if will_report or will_collection:
                    basis_media = None
                else:
                    return {"ok": False, "error": str(exc)}
            bmod = (basis_media or {}).get("modality")
            if will_report or will_collection:
                pass
            elif infer_layout_extract_intent(desc_preview) or infer_text_extract_intent(
                desc_preview
            ):
                pass
            elif bmod == "image":
                desc_preview = f"Create an image: {desc_preview}"
            elif bmod == "video":
                desc_preview = f"Generate a video: {desc_preview}"

        model_id, provider = _active_model_and_provider(self.config)
        compat = check_prompt_model_compatibility(
            desc_preview,
            model_id,
            provider=provider,
            gemini_cfg=self.config.get("gemini"),
        )
        if not compat.get("ok"):
            return {
                "ok": False,
                "error": compat.get("error") or "Model modality mismatch.",
                "modalityMismatch": True,
                "promptModality": compat.get("promptModality"),
                "modelModality": compat.get("modelModality"),
                "suggestions": compat.get("suggestions") or [],
            }

        if not self._gen_lock.acquire(blocking=False):
            return {"ok": False, "error": "A generation is already in progress."}

        job_id = f"gen_{uuid.uuid4().hex[:10]}"
        desc_override = (creation_description or "").strip()
        if source_creations and not desc_override:
            desc_override = DEFAULT_REPORT_PROMPT
        search_override = (search_query or "").strip()
        from .gemini_tools import normalize_tool_aliases

        tools_for_job = normalize_tool_aliases(tool_aliases)
        cancel_evt = threading.Event()
        with self._jobs_lock:
            self._cancel_events[job_id] = cancel_evt
        self._set_job(
            job_id,
            status="running",
            kind="generate",
            progress={
                "message": f"Starting generation for {game}…",
                "percent": 0,
                "phase": "generate",
                "title": "Creating…",
            },
        )

        def _progress(payload: Any) -> None:
            from .cancellation import GenerationCancelled

            if cancel_evt.is_set():
                raise GenerationCancelled("Cancelled by user")
            self._on_job_progress(job_id, payload)

        def _run() -> None:
            from .cancellation import GenerationCancelled

            try:
                result = generate_creation(
                    game=game.strip(),
                    platform=platform.strip(),
                    creation_type=creation_type.strip(),
                    config=self.config,
                    progress=_progress,
                    exact_title=bool(exact_title),
                    creation_description=desc_override or None,
                    cancel_event=cancel_evt,
                    basis_media=basis_media,
                    tool_aliases=tools_for_job,
                    search_query=search_override or None,
                    source_creations=source_creations or None,
                )
                if cancel_evt.is_set():
                    raise GenerationCancelled("Cancelled by user")
                extras = []
                if isinstance(result, dict):
                    extras = list(result.pop("_also_upsert", None) or [])
                saved = self.store.upsert(result)
                for extra in extras:
                    if isinstance(extra, dict) and extra.get("id"):
                        try:
                            self.store.upsert(extra)
                        except Exception:  # noqa: BLE001
                            logger.debug(
                                "Could not save collection output %s",
                                extra.get("id"),
                                exc_info=True,
                            )
                logger.info(
                    "Generation complete: %s modality=%s model=%s",
                    saved.get("id"),
                    saved.get("modality"),
                    (saved.get("_model") or {}).get("repo_id") or "-",
                )
                self._set_job(
                    job_id,
                    status="done",
                    result=saved,
                    progress={"message": "Ready", "percent": 100, "phase": "ready"},
                )
                try:
                    payload = json.dumps(saved, ensure_ascii=False)
                    self._push_best_effort(
                        f"window.__onGenerationComplete && window.__onGenerationComplete({payload})"
                    )
                except (TypeError, ValueError):
                    self._push_best_effort(
                        f"window.__onGenerationComplete && window.__onGenerationComplete("
                        f"JSON.parse({json.dumps(json.dumps(saved))}))"
                    )
            except GenerationCancelled:
                logger.info("Generation cancelled: %s", job_id)
                self._set_job(
                    job_id,
                    status="cancelled",
                    error="Cancelled",
                    progress={
                        "message": "Cancelled",
                        "percent": 100,
                        "phase": "cancelled",
                    },
                )
                self._push_best_effort(
                    "window.__onGenerateCancelled && window.__onGenerateCancelled()"
                )
            except AmbiguousGameError as exc:
                logger.info("Ambiguous game title: %s (%d candidates)", exc.user_game, len(exc.candidates))
                choice = {
                    "kind": "ambiguous",
                    "query": exc.user_game,
                    "candidates": exc.candidates,
                    "platform": platform.strip(),
                    "creationType": creation_type.strip(),
                }
                self._set_job(
                    job_id,
                    status="needs_choice",
                    result=choice,
                    progress={
                        "message": "Multiple matches — choose a title",
                        "percent": 100,
                        "phase": "choice",
                    },
                )
                try:
                    payload = json.dumps(choice, ensure_ascii=False)
                    self._push_best_effort(
                        f"window.__onNeedsChoice && window.__onNeedsChoice({payload})"
                    )
                except (TypeError, ValueError):
                    self._push_best_effort(
                        f"window.__onNeedsChoice && window.__onNeedsChoice("
                        f"JSON.parse({json.dumps(json.dumps(choice))}))"
                    )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Generation failed")
                err = str(exc)
                retired = self._maybe_learn_retired_gemini(exc)
                if retired:
                    err = retired["message"]
                    self._set_job(
                        job_id,
                        status="error",
                        error=err,
                        retired_model=retired,
                    )
                    try:
                        payload = json.dumps(retired, ensure_ascii=False)
                        self._push_best_effort(
                            "window.__onRetiredGeminiModel && "
                            f"window.__onRetiredGeminiModel({payload})"
                        )
                    except (TypeError, ValueError):
                        self._push_best_effort(
                            "window.__onRetiredGeminiModel && "
                            "window.__onRetiredGeminiModel("
                            f"JSON.parse({json.dumps(json.dumps(retired))}))"
                        )
                else:
                    self._set_job(job_id, status="error", error=err)
                    self._push_best_effort(
                        f"window.__onGenerateError && window.__onGenerateError({json.dumps(err)})"
                    )
            finally:
                with self._jobs_lock:
                    self._cancel_events.pop(job_id, None)
                self._gen_lock.release()

        threading.Thread(target=_run, daemon=True, name="rgc-generate").start()
        return {"ok": True, "job_id": job_id, "message": "Generation started."}

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """Request cancellation of a running generation (or model-load) job."""
        job_id = (job_id or "").strip()
        if not job_id:
            return {"ok": False, "error": "Missing job id"}
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            if not job:
                return {"ok": False, "error": "Unknown job id"}
            status = str(job.get("status") or "")
            if status in ("done", "error", "cancelled", "needs_choice", "missing"):
                return {"ok": False, "error": f"Job already finished ({status})"}
            evt = self._cancel_events.get(job_id)
            if evt is None:
                return {"ok": False, "error": "Job is not cancellable"}
            evt.set()
            job["status"] = "cancelling"
            job["progress"] = {
                "message": "Cancelling…",
                "phase": "cancel",
                "title": "Cancelling",
            }
        logger.info("Cancel requested for job %s", job_id)
        return {"ok": True, "job_id": job_id, "message": "Cancel requested"}

    def _on_job_progress(self, job_id: str, payload: Any) -> None:
        if isinstance(payload, str):
            data: dict[str, Any] = {"message": payload}
        elif isinstance(payload, dict):
            data = payload
        else:
            data = {"message": str(payload)}
        self._set_job(job_id, progress=data)
        self._push_best_effort(
            f"window.__onProgress && window.__onProgress({json.dumps(data)})"
        )

    def _push_best_effort(self, script: str) -> None:
        """Try evaluate_js; never raise — JS polling is the source of truth."""
        if self._window is None:
            return
        try:
            self._window.evaluate_js(script)
        except Exception:  # noqa: BLE001
            logger.debug("evaluate_js failed (UI should poll get_job)", exc_info=True)

    def export_creation_txt(self, creation: dict[str, Any]) -> str:
        """Export only the generated text body (no prompt or metadata)."""
        from .extract_text import get_extracted_text

        modality = str((creation or {}).get("modality") or "text").lower()
        if modality in {"image", "video"}:
            extracted = get_extracted_text(creation)
            if extracted:
                return extracted + ("\n" if not extracted.endswith("\n") else "")
            raise RuntimeError(
                f"TXT export is not available for {modality} creations until you extract the text in Creation Studio."
            )
        # Audio: lyrics/structure from Lyria live in sections.

        lines: list[str] = []
        overview = str(creation.get("overview") or "").strip()
        sections = creation.get("sections") or []
        skip_overview = False
        if overview and sections:
            body = str((sections[0] or {}).get("content") or "").strip()
            clipped = overview.rstrip("…").rstrip(".").strip()
            if body.startswith(clipped) or (
                str(creation.get("creationType") or "") == "Text" and body
            ):
                skip_overview = True
        if overview and not skip_overview:
            lines.append(overview)
            lines.append("")
        for section in sections:
            title = str((section or {}).get("title") or "").strip()
            hide_title = (not title) or (title.casefold() == "response")
            if not hide_title:
                lines.append(title)
                lines.append("")
            content = str((section or {}).get("content") or "")
            if content:
                lines.append(content)
            for kv in (section or {}).get("keyValues") or []:
                lines.append(f"  • {kv.get('label', '')}: {kv.get('value', '')}")
            lines.append("")
        return "\n".join(lines).strip() + ("\n" if lines else "")

    def extract_creation_text(self, creation_id: str) -> dict[str, Any]:
        """Start OCR (image) or transcription (video) in a background job."""
        from .cancellation import GenerationCancelled
        from .extract_text import extract_text_from_creation
        from .media_store import resolve_media_path

        creation_id = (creation_id or "").strip()
        if not creation_id:
            return {"ok": False, "error": "Missing creation id"}

        target = next((c for c in self.store.load() if c.get("id") == creation_id), None)
        if not target:
            return {"ok": False, "error": "Creation not found"}
        modality = str(target.get("modality") or "").lower()
        if modality not in {"image", "video"}:
            return {"ok": False, "error": "Extract Text is only for image or video creations."}

        path = resolve_media_path(target.get("mediaPath"), config=self.config)
        if path is None:
            return {"ok": False, "error": "Media file is missing on disk."}

        if not self._gen_lock.acquire(blocking=False):
            return {"ok": False, "error": "Another AI job is already in progress."}

        job_id = f"extract_{uuid.uuid4().hex[:10]}"
        cancel_evt = threading.Event()
        with self._jobs_lock:
            self._cancel_events[job_id] = cancel_evt
        title = "Extracting text" if modality == "image" else "Transcribing"
        self._set_job(
            job_id,
            status="running",
            kind="extract",
            progress={
                "message": f"Starting {title.lower()}…",
                "percent": 0,
                "phase": "extract",
                "title": title,
            },
        )

        def _progress(payload: Any) -> None:
            from .cancellation import GenerationCancelled as _GC

            if cancel_evt.is_set():
                raise _GC("Cancelled by user")
            self._on_job_progress(job_id, payload)

        def _run() -> None:
            try:
                updated = extract_text_from_creation(
                    target,
                    config=self.config,
                    media_path=path,
                    progress=_progress,
                    cancel_event=cancel_evt,
                )
                if cancel_evt.is_set():
                    raise GenerationCancelled("Cancelled by user")
                saved = self.store.upsert(updated)
                self._set_job(
                    job_id,
                    status="done",
                    result=saved,
                    progress={
                        "message": "Ready",
                        "percent": 100,
                        "phase": "ready",
                        "title": title,
                    },
                )
            except GenerationCancelled:
                logger.info("Extract text cancelled: %s", job_id)
                self._set_job(
                    job_id,
                    status="cancelled",
                    error="Cancelled",
                    progress={
                        "message": "Cancelled",
                        "percent": 100,
                        "phase": "cancelled",
                        "title": "Cancelled",
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Extract text failed")
                err = str(exc)
                retired = self._maybe_learn_retired_gemini(exc)
                if retired:
                    err = retired["message"]
                    self._set_job(
                        job_id,
                        status="error",
                        error=err,
                        retired_model=retired,
                    )
                else:
                    self._set_job(job_id, status="error", error=err)
            finally:
                with self._jobs_lock:
                    self._cancel_events.pop(job_id, None)
                self._gen_lock.release()

        threading.Thread(target=_run, daemon=True, name=job_id).start()
        return {"ok": True, "job_id": job_id}

    def extract_creation_layout(self, creation_id: str) -> dict[str, Any]:
        """Start UI layout extraction (image, or a still frame from video)."""
        from .cancellation import GenerationCancelled
        from .extract_layout import extract_layout_from_creation
        from .media_store import resolve_media_path

        creation_id = (creation_id or "").strip()
        if not creation_id:
            return {"ok": False, "error": "Missing creation id"}

        target = next((c for c in self.store.load() if c.get("id") == creation_id), None)
        if not target:
            return {"ok": False, "error": "Creation not found"}
        modality = str(target.get("modality") or "").lower()
        if modality not in {"image", "video"}:
            return {
                "ok": False,
                "error": "Extract Layout is only for image or video creations.",
            }

        path = resolve_media_path(target.get("mediaPath"), config=self.config)
        if path is None:
            return {"ok": False, "error": "Media file is missing on disk."}

        if not self._gen_lock.acquire(blocking=False):
            return {"ok": False, "error": "Another AI job is already in progress."}

        job_id = f"layout_{uuid.uuid4().hex[:10]}"
        cancel_evt = threading.Event()
        with self._jobs_lock:
            self._cancel_events[job_id] = cancel_evt
        title = "Extracting layout"
        self._set_job(
            job_id,
            status="running",
            kind="layout",
            progress={
                "message": "Starting layout extraction…",
                "percent": 0,
                "phase": "layout",
                "title": title,
            },
        )

        def _progress(payload: Any) -> None:
            from .cancellation import GenerationCancelled as _GC

            if cancel_evt.is_set():
                raise _GC("Cancelled by user")
            self._on_job_progress(job_id, payload)

        def _run() -> None:
            try:
                updated = extract_layout_from_creation(
                    target,
                    config=self.config,
                    media_path=path,
                    progress=_progress,
                    cancel_event=cancel_evt,
                )
                if cancel_evt.is_set():
                    raise GenerationCancelled("Cancelled by user")
                saved = self.store.upsert(updated)
                self._set_job(
                    job_id,
                    status="done",
                    result=saved,
                    progress={
                        "message": "Ready",
                        "percent": 100,
                        "phase": "ready",
                        "title": title,
                    },
                )
            except GenerationCancelled:
                logger.info("Extract layout cancelled: %s", job_id)
                self._set_job(
                    job_id,
                    status="cancelled",
                    error="Cancelled",
                    progress={
                        "message": "Cancelled",
                        "percent": 100,
                        "phase": "cancelled",
                        "title": "Cancelled",
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Extract layout failed")
                err = str(exc)
                retired = self._maybe_learn_retired_gemini(exc)
                if retired:
                    err = retired["message"]
                    self._set_job(
                        job_id,
                        status="error",
                        error=err,
                        retired_model=retired,
                    )
                else:
                    self._set_job(job_id, status="error", error=err)
            finally:
                with self._jobs_lock:
                    self._cancel_events.pop(job_id, None)
                self._gen_lock.release()

        threading.Thread(target=_run, daemon=True, name=job_id).start()
        return {"ok": True, "job_id": job_id}

    def _creation_by_id(self, creation_id: str) -> dict[str, Any] | None:
        cid = (creation_id or "").strip()
        if not cid:
            return None
        for item in self.store.load():
            if str(item.get("id") or "") == cid:
                return item
        return None

    def _resolve_source_creations(
        self, source_creation_ids: list[str] | None
    ) -> list[dict[str, Any]]:
        from .studio_sources import MAX_SOURCES

        raw_ids = source_creation_ids or []
        if not isinstance(raw_ids, list):
            raw_ids = [raw_ids]
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for raw in raw_ids:
            cid = str(raw or "").strip()
            if not cid or cid in seen:
                continue
            seen.add(cid)
            item = self._creation_by_id(cid)
            if not item:
                raise RuntimeError(f"Studio source {cid} was not found in Archives.")
            out.append(item)
            if len(out) >= MAX_SOURCES:
                break
        return out

    def _resolve_basis_media(self, creation_id: str) -> dict[str, Any]:
        """Load Archive media for Studio image/video → new media generation."""
        from .media_store import mime_for_path, read_media_bytes, resolve_media_path
        from .modality import normalize_modality

        cid = (creation_id or "").strip()
        if not cid:
            raise RuntimeError("Media basis id missing.")
        source = None
        for item in self.store.load():
            if str(item.get("id") or "") == cid:
                source = item
                break
        if not source:
            raise RuntimeError("Media basis creation was not found in Archives.")
        mod = normalize_modality(source.get("modality"), default="")
        mime = str(source.get("mimeType") or "").lower()
        if not mod:
            if mime.startswith("video/"):
                mod = "video"
            elif mime.startswith("image/"):
                mod = "image"
        if mod not in {"image", "video"}:
            raise RuntimeError("Studio media basis must be an image or video creation.")
        path = resolve_media_path(source.get("mediaPath"), config=self.config)
        if path is None:
            raise RuntimeError("Media basis file is missing on disk.")
        mime = mime or mime_for_path(path)

        if mod == "image":
            raw = read_media_bytes(source.get("mediaPath"), config=self.config)
            if not raw:
                raise RuntimeError("Could not read basis image bytes.")
            payload = {
                "modality": "image",
                "bytes": raw,
                "mime_type": mime or "image/png",
                "creation_id": cid,
                "source_creation": dict(source),
            }
        else:
            # Video basis: use a still frame as image reference for I2V / edit flows
            from .video_edit import extract_video_frame_png

            try:
                frame = extract_video_frame_png(path, at_seconds=0.0)
            except Exception as exc:
                raise RuntimeError(
                    f"Could not prepare video basis (need ffmpeg for a reference frame): {exc}"
                ) from exc
            payload = {
                "modality": "video",
                "bytes": frame,
                "mime_type": "image/png",
                "creation_id": cid,
                "source_modality": "video",
                "source_creation": dict(source),
            }
        from .extract_layout import get_extracted_layout

        layout = get_extracted_layout(source)
        if layout:
            payload["extracted_layout"] = layout
        return payload

    def get_media_payload(self, creation: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return media for Viewer/Studio: data URL and/or same-origin HTTP URL."""
        from .media_store import media_data_url, media_file_uri, mime_for_path, resolve_media_path

        creation = creation or {}
        media_path = creation.get("mediaPath")
        mime = creation.get("mimeType")
        path = resolve_media_path(media_path)
        if path is None:
            return {"ok": False, "error": "Media file not found"}
        mime = mime or mime_for_path(path)
        modality = str(creation.get("modality") or "").lower()
        is_video = modality == "video" or (mime or "").startswith("video/")
        is_audio = modality == "audio" or (mime or "").startswith("audio/")
        is_pdf = modality == "pdf" or (mime or "") == "application/pdf"

        # Prefer same-origin HTTP — WebView blocks file:// from localhost pages,
        # and large image data URLs can choke the pywebview bridge.
        http_url = None
        if self._ui_origin:
            http_url = f"{self._ui_origin}/media/{path.name}"
        file_uri = http_url or media_file_uri(media_path)

        if is_video or is_audio or is_pdf:
            return {
                "ok": True,
                "modality": "pdf" if is_pdf else ("audio" if is_audio else "video"),
                "mimeType": mime,
                "fileUrl": file_uri,
                "mediaPath": media_path,
            }

        data_url = media_data_url(media_path, mime)
        if not data_url and not file_uri:
            return {"ok": False, "error": "Could not read media"}
        out: dict[str, Any] = {
            "ok": True,
            "modality": "image",
            "mimeType": mime,
            "mediaPath": media_path,
        }
        if file_uri:
            out["fileUrl"] = file_uri
        if data_url:
            out["dataUrl"] = data_url
        return out

    def replace_creation_media(
        self, creation_id: str, base64_data: str, mime_type: str = "image/png"
    ) -> dict[str, Any]:
        """Overwrite a creation's media file from a base64 payload (Viewer Edit Apply)."""
        import base64

        from .media_store import write_media_bytes

        creation_id = (creation_id or "").strip()
        if not creation_id:
            return {"ok": False, "error": "Missing creation id"}
        items = self.store.load()
        target = next((c for c in items if c.get("id") == creation_id), None)
        if not target:
            return {"ok": False, "error": "Creation not found"}
        if str(target.get("modality") or "").lower() != "image":
            return {"ok": False, "error": "Only image creations can be edited this way"}

        payload = base64_data or ""
        if "," in payload and payload.strip().lower().startswith("data:"):
            header, payload = payload.split(",", 1)
            if "image/jpeg" in header or "image/jpg" in header:
                mime_type = "image/jpeg"
            elif "image/png" in header:
                mime_type = "image/png"
            elif "image/webp" in header:
                mime_type = "image/webp"
        try:
            raw = base64.b64decode(payload, validate=False)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Invalid base64: {exc}"}
        if not raw:
            return {"ok": False, "error": "Empty image payload"}

        stored = write_media_bytes(
            creation_id, raw, mime_type=mime_type or "image/png", config=self.config
        )
        target = dict(target)
        target["mediaPath"] = stored["mediaPath"]
        target["mimeType"] = stored["mimeType"]
        target["modality"] = "image"
        from .extract_layout import clear_layout_fields
        from .extract_text import clear_extraction_fields

        target = clear_layout_fields(clear_extraction_fields(target))
        saved = self.store.upsert(target)
        return {"ok": True, "creation": saved}

    def ffmpeg_status(self) -> dict[str, Any]:
        """Whether system ffmpeg/ffprobe are available for Video Editor."""
        from .video_edit import ffmpeg_available

        return ffmpeg_available()

    def get_video_info(self, creation_id: str) -> dict[str, Any]:
        """Return duration/size for a video creation."""
        from .media_store import resolve_media_path
        from .video_edit import FfmpegNotFoundError, probe_video_info

        creation_id = (creation_id or "").strip()
        target = next((c for c in self.store.load() if c.get("id") == creation_id), None)
        if not target:
            return {"ok": False, "error": "Creation not found"}
        if str(target.get("modality") or "").lower() != "video":
            return {"ok": False, "error": "Not a video creation"}
        path = resolve_media_path(target.get("mediaPath"))
        if path is None:
            return {"ok": False, "error": "Media file not found"}
        try:
            info = probe_video_info(path)
        except FfmpegNotFoundError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "creationId": creation_id, **info}

    def _render_edited_video(
        self, creation_id: str, ops: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, Path | None, Any]:
        """
        Resolve a video creation and render edits to a temp MP4.

        Returns (error_dict, dest_path, target_creation). On success error_dict is None
        and dest_path points at the rendered file (caller must delete it).
        """
        from .media_store import resolve_media_path
        from .video_edit import FfmpegNotFoundError, apply_edits, temp_mp4_path

        creation_id = (creation_id or "").strip()
        ops = ops or {}
        target = next((c for c in self.store.load() if c.get("id") == creation_id), None)
        if not target:
            return {"ok": False, "error": "Creation not found"}, None, None
        if str(target.get("modality") or "").lower() != "video":
            return {"ok": False, "error": "Only video creations can be edited this way"}, None, None
        path = resolve_media_path(target.get("mediaPath"))
        if path is None:
            return {"ok": False, "error": "Media file not found"}, None, None

        dest = temp_mp4_path("r98edit_")
        try:
            segments = ops.get("segments")
            if segments:
                from .video_edit import assemble_segments

                assemble_segments(
                    path,
                    dest,
                    list(segments),
                    filters=ops.get("filters"),
                    crop=ops.get("crop"),
                    rotation=float(ops.get("rotation") or 0),
                )
            else:
                apply_edits(
                    path,
                    dest,
                    filters=ops.get("filters"),
                    crop=ops.get("crop"),
                    rotation=float(ops.get("rotation") or 0),
                    trim=ops.get("trim"),
                )
            return None, dest, target
        except FfmpegNotFoundError as exc:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
            return {"ok": False, "error": str(exc)}, None, None
        except Exception as exc:  # noqa: BLE001
            logger.exception("render edited video failed")
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
            return {"ok": False, "error": str(exc)}, None, None

    def edit_video(self, creation_id: str, ops: dict[str, Any] | None = None) -> dict[str, Any]:
        """Apply filters/crop/rotate/trim to a video creation and overwrite its media."""
        from .media_store import write_media_bytes

        err, dest, target = self._render_edited_video(creation_id, ops)
        if err is not None:
            return err
        assert dest is not None and target is not None
        try:
            raw = dest.read_bytes()
            stored = write_media_bytes(
                creation_id, raw, mime_type="video/mp4", config=self.config
            )
            target = dict(target)
            target["mediaPath"] = stored["mediaPath"]
            target["mimeType"] = stored["mimeType"]
            target["modality"] = "video"
            from .extract_layout import clear_layout_fields
            from .extract_text import clear_extraction_fields

            target = clear_layout_fields(clear_extraction_fields(target))
            saved = self.store.upsert(target)
            return {"ok": True, "creation": saved}
        except Exception as exc:  # noqa: BLE001
            logger.exception("edit_video failed")
            return {"ok": False, "error": str(exc)}
        finally:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass

    def export_edited_video(
        self, creation_id: str, ops: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Render video edits and save via a file dialog (does not overwrite Archives)."""
        import webview

        if self._window is None:
            return {"ok": False, "error": "No window"}

        err, dest, target = self._render_edited_video(creation_id, ops)
        if err is not None:
            return err
        assert dest is not None and target is not None
        try:
            safe = self._media_save_basename(target, fallback="video")
            result = self._window.create_file_dialog(
                _file_dialog("save"),
                save_filename=f"{safe}.mp4",
                file_types=_save_file_types(".mp4"),
            )
            if not result:
                return {"ok": False, "cancelled": True}
            out = _safe_dialog_save_path(result, ".mp4")
            out.write_bytes(dest.read_bytes())
            return {"ok": True, "path": str(out)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("export_edited_video failed")
            return {"ok": False, "error": str(exc)}
        finally:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass

    def split_video(self, creation_id: str, time_s: float) -> dict[str, Any]:
        """Split a video at time_s into two new library creations (A before, B after)."""
        import uuid

        from .creation_utils import build_media_creation, title_from_prompt
        from .media_store import resolve_media_path, write_media_bytes
        from .video_edit import FfmpegNotFoundError, split_at, temp_mp4_path

        creation_id = (creation_id or "").strip()
        target = next((c for c in self.store.load() if c.get("id") == creation_id), None)
        if not target:
            return {"ok": False, "error": "Creation not found"}
        if str(target.get("modality") or "").lower() != "video":
            return {"ok": False, "error": "Only video creations can be split"}
        path = resolve_media_path(target.get("mediaPath"))
        if path is None:
            return {"ok": False, "error": "Media file not found"}

        dest_a = temp_mp4_path("r98split_a_")
        dest_b = temp_mp4_path("r98split_b_")
        try:
            split_at(path, dest_a, dest_b, float(time_s))
            base_title = (
                target.get("title") or target.get("game") or title_from_prompt(target.get("prompt") or "")
            )
            prompt = target.get("prompt") or base_title
            model_info = target.get("_model")
            creations_out: list[dict[str, Any]] = []
            for label, dest in (("A", dest_a), ("B", dest_b)):
                cid = f"doc_{uuid.uuid4().hex[:10]}"
                stored = write_media_bytes(
                    cid, dest.read_bytes(), mime_type="video/mp4", config=self.config
                )
                creation = build_media_creation(
                    modality="video",
                    prompt=prompt,
                    media_path=stored["mediaPath"],
                    mime_type=stored["mimeType"],
                    title=f"{base_title} ({label})",
                    model_info=model_info if isinstance(model_info, dict) else None,
                    creation_id=cid,
                )
                creations_out.append(self.store.upsert(creation))
            return {"ok": True, "creations": creations_out}
        except FfmpegNotFoundError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("split_video failed")
            return {"ok": False, "error": str(exc)}
        finally:
            for p in (dest_a, dest_b):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

    def splice_videos(self, creation_ids: list[str] | None = None) -> dict[str, Any]:
        """Concatenate ordered video creations into a new library video."""
        import uuid

        from .creation_utils import build_media_creation
        from .media_store import resolve_media_path, write_media_bytes
        from .video_edit import FfmpegNotFoundError, concat_videos, temp_mp4_path

        ids = [str(i).strip() for i in (creation_ids or []) if str(i).strip()]
        if len(ids) < 2:
            return {"ok": False, "error": "Select at least two videos to splice"}

        items = self.store.load()
        by_id = {c.get("id"): c for c in items}
        paths: list[Path] = []
        titles: list[str] = []
        for cid in ids:
            target = by_id.get(cid)
            if not target:
                return {"ok": False, "error": f"Creation not found: {cid}"}
            if str(target.get("modality") or "").lower() != "video":
                return {"ok": False, "error": f"Not a video: {cid}"}
            path = resolve_media_path(target.get("mediaPath"))
            if path is None:
                return {"ok": False, "error": f"Media missing for {cid}"}
            paths.append(path)
            titles.append(str(target.get("title") or target.get("game") or cid))

        dest = temp_mp4_path("r98splice_")
        try:
            concat_videos(paths, dest)
            new_id = f"doc_{uuid.uuid4().hex[:10]}"
            stored = write_media_bytes(
                new_id, dest.read_bytes(), mime_type="video/mp4", config=self.config
            )
            title = " + ".join(titles)[:80]
            creation = build_media_creation(
                modality="video",
                prompt=f"Spliced: {title}",
                media_path=stored["mediaPath"],
                mime_type=stored["mimeType"],
                title=title or "Spliced Video",
                creation_id=new_id,
            )
            saved = self.store.upsert(creation)
            return {"ok": True, "creation": saved}
        except FfmpegNotFoundError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("splice_videos failed")
            return {"ok": False, "error": str(exc)}
        finally:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass

    def _remember_embedding_filename(
        self, creation: dict[str, Any], name: str
    ) -> None:
        """Cache a suggested basename on the Archive record so later saves skip the API."""
        cid = str((creation or {}).get("id") or "").strip()
        safe = str(name or "").strip()
        if not cid or not safe:
            return
        try:
            for item in self.store.load():
                if item.get("id") != cid:
                    continue
                meta = dict(item.get("meta") or {})
                if meta.get("embeddingFilename") == safe:
                    return
                meta["embeddingFilename"] = safe
                item["meta"] = meta
                self.store.upsert(item)
                creation_meta = dict(creation.get("meta") or {})
                creation_meta["embeddingFilename"] = safe
                creation["meta"] = creation_meta
                return
        except Exception:  # noqa: BLE001
            logger.debug("Could not cache embedding filename", exc_info=True)

    def _media_save_basename(
        self, creation: dict[str, Any] | None, *, fallback: str = "creation"
    ) -> str:
        """Embedding-based basename for a media save dialog, with prompt-slug fallback."""
        from .creation_utils import title_from_prompt
        from .embedding_filename import slugify_filename, suggest_filename_for_creation

        creation = creation or {}
        gemini_cfg = (self.config or {}).get("gemini") or {}
        name = suggest_filename_for_creation(
            creation,
            api_key=resolve_gemini_key(gemini_cfg),
            config=self.config,
            fallback=fallback,
        )
        prompt_slug = slugify_filename(
            title_from_prompt(str(creation.get("prompt") or ""), fallback),
            fallback=fallback,
        )
        if name and name != prompt_slug:
            self._remember_embedding_filename(creation, name)
        return name

    def suggest_media_filename(
        self, creation: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Return a filesystem-safe basename (no extension) for Viewer / editor Save As."""
        try:
            name = self._media_save_basename(creation or {}, fallback="creation")
        except Exception as exc:  # noqa: BLE001
            logger.exception("suggest_media_filename failed")
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "filename": name}

    def export_creation_media(self, creation: dict[str, Any] | None = None) -> dict[str, Any]:
        """Save the native media file via a file dialog (Viewer Save MP4 / similar)."""
        from .media_store import mime_for_path, resolve_media_path

        if self._window is None:
            return {"ok": False, "error": "No window"}
        creation = creation or {}
        path = resolve_media_path(creation.get("mediaPath"))
        if path is None:
            return {"ok": False, "error": "Media file not found"}
        mime = creation.get("mimeType") or mime_for_path(path)
        modality = (creation.get("modality") or "").strip().lower()
        if modality == "video" or (mime or "").startswith("video/"):
            ext = ".mp4"
        elif modality == "audio" or (mime or "").startswith("audio/"):
            ext = ".mp3"
        else:
            from .media_store import extension_for_mime

            ext = extension_for_mime(mime, fallback=path.suffix or ".bin")
        safe = self._media_save_basename(creation, fallback="creation")
        default_name = f"{safe}{ext}"
        result = self._window.create_file_dialog(
            _file_dialog("save"),
            save_filename=default_name,
            file_types=_save_file_types(ext),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        try:
            dest = _safe_dialog_save_path(result, ext)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        dest.write_bytes(path.read_bytes())
        return {"ok": True, "path": str(dest)}

    def save_file_dialog(self, default_name: str, content: str) -> dict[str, Any]:
        """Open a native save dialog and write text content."""
        if self._window is None:
            return {"ok": False, "error": "No window"}
        result = self._window.create_file_dialog(
            _file_dialog("save"),
            save_filename=default_name,
            file_types=_save_file_types(Path(default_name).suffix),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        try:
            path = _safe_dialog_save_path(result, Path(default_name).suffix)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        path.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(path)}

    def save_binary_file_dialog(self, default_name: str, base64_data: str) -> dict[str, Any]:
        """Open a native save dialog and write base64-decoded bytes (PNG/PDF)."""
        import base64

        if self._window is None:
            return {"ok": False, "error": "No window"}
        if not isinstance(base64_data, str) or not base64_data:
            return {"ok": False, "error": "Empty payload"}

        # Allow data URLs: data:image/png;base64,AAAA…
        payload = base64_data
        if "," in payload and payload.strip().lower().startswith("data:"):
            payload = payload.split(",", 1)[1]

        try:
            raw = base64.b64decode(payload, validate=False)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Invalid base64: {exc}"}

        result = self._window.create_file_dialog(
            _file_dialog("save"),
            save_filename=default_name,
            file_types=_save_file_types(Path(default_name).suffix),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        try:
            path = _safe_dialog_save_path(result, Path(default_name).suffix)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        path.write_bytes(raw)
        return {"ok": True, "path": str(path)}

    def _dialog_open_paths(
        self, file_types: tuple[str, ...], *, allow_multiple: bool = False
    ) -> dict[str, Any]:
        if self._window is None:
            return {"ok": False, "error": "No window"}
        result = self._window.create_file_dialog(
            _file_dialog("open"),
            allow_multiple=bool(allow_multiple),
            file_types=file_types,
        )
        if not result:
            return {"ok": False, "cancelled": True}
        if isinstance(result, (list, tuple)):
            paths = [Path(p) for p in result if str(p).strip()]
        else:
            paths = [Path(result)]
        files = [p for p in paths if p.is_file()]
        if not files:
            return {"ok": False, "error": "File not found"}
        return {"ok": True, "paths": files}

    def _dialog_open_path(self, file_types: tuple[str, ...]) -> dict[str, Any]:
        picked = self._dialog_open_paths(file_types, allow_multiple=False)
        if not picked.get("ok"):
            return picked
        return {"ok": True, "path": picked["paths"][0]}

    def _import_text_from_path(
        self, path: Path, save_to_archives: bool = False
    ) -> dict[str, Any]:
        from .creation_utils import build_text_creation_from_plain

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        title = path.stem.strip() or "Imported text"
        out: dict[str, Any] = {
            "ok": True,
            "modality": "text",
            "text": text,
            "title": title,
            "path": str(path),
        }
        if save_to_archives:
            from .studio_sources import apply_original_filename

            creation = build_text_creation_from_plain(
                text,
                prompt=f"Imported from {path.name}",
                title=title,
                model_info={"provider": "import", "repo_id": path.name},
            )
            creation = apply_original_filename(creation, path.name)
            out["creation"] = self.store.upsert(creation)
        return out

    def _import_media_from_path(self, path: Path, modality: str) -> dict[str, Any]:
        import uuid

        from .creation_utils import build_media_creation
        from .media_store import mime_for_path, write_media_bytes
        from .modality import normalize_modality

        mod = normalize_modality(modality, default="image")
        if mod not in {"image", "video", "audio", "pdf"}:
            return {"ok": False, "error": "modality must be image, video, audio, or pdf"}
        if not path.is_file():
            return {"ok": False, "error": "File not found"}

        try:
            raw = path.read_bytes()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        if not raw:
            return {"ok": False, "error": "Empty file"}

        mime = mime_for_path(path)
        if mod == "image" and not str(mime).startswith("image/"):
            mime = "image/png"
        if mod == "video" and not str(mime).startswith("video/"):
            mime = "video/mp4"
        if mod == "audio" and not str(mime).startswith("audio/"):
            mime = "audio/mpeg"
        if mod == "pdf":
            mime = "application/pdf"

        new_id = f"doc_{uuid.uuid4().hex[:10]}"
        try:
            stored = write_media_bytes(
                new_id, raw, mime_type=mime, config=self.config
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

        title = path.stem.strip() or {
            "image": "Imported Image",
            "video": "Imported Video",
            "audio": "Imported Audio",
            "pdf": "Imported PDF",
        }.get(mod, "Imported Media")
        from .studio_sources import apply_original_filename

        creation = build_media_creation(
            modality=mod,
            prompt=f"Imported from {path.name}",
            media_path=stored["mediaPath"],
            mime_type=stored["mimeType"],
            title=title,
            creation_id=new_id,
            model_info={"provider": "import", "repo_id": path.name, "modality": mod},
        )
        creation = apply_original_filename(creation, path.name)
        saved = self.store.upsert(creation)
        return {"ok": True, "creation": saved, "modality": mod}

    def import_text_file(self, save_to_archives: bool = False) -> dict[str, Any]:
        """Open a text file for use as a Studio prompt / text basis."""
        picked = self._dialog_open_path(
            ("Text Files (*.txt;*.md;*.markdown;*.csv)", "All Files (*.*)")
        )
        if not picked.get("ok"):
            return picked
        return self._import_text_from_path(picked["path"], save_to_archives)

    def import_media_file(self, modality: str = "image") -> dict[str, Any]:
        """Import an image, video, or audio file into Archives as a new creation."""
        from .modality import normalize_modality

        mod = normalize_modality(modality, default="image")
        if mod not in {"image", "video", "audio"}:
            return {"ok": False, "error": "modality must be image, video, or audio"}

        if mod == "image":
            file_types = (
                "Image Files (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp)",
                "All Files (*.*)",
            )
        elif mod == "audio":
            file_types = (
                "Audio Files (*.mp3;*.wav;*.ogg;*.m4a;*.aac)",
                "All Files (*.*)",
            )
        else:
            file_types = (
                "Video Files (*.mp4;*.webm;*.mov;*.mkv;*.avi)",
                "All Files (*.*)",
            )

        picked = self._dialog_open_path(file_types)
        if not picked.get("ok"):
            return picked
        return self._import_media_from_path(picked["path"], mod)

    def import_pdf_file(self) -> dict[str, Any]:
        """Import a PDF into Archives as a Studio source."""
        picked = self._dialog_open_path(
            ("PDF Files (*.pdf)", "All Files (*.*)")
        )
        if not picked.get("ok"):
            return picked
        return self._import_media_from_path(picked["path"], "pdf")

    def _import_source_from_path(self, path: Path) -> dict[str, Any]:
        from .media_store import modality_for_path

        mod = modality_for_path(path)
        if not mod:
            return {"ok": False, "error": "Unsupported file type"}
        if mod == "text":
            return self._import_text_from_path(path, save_to_archives=True)
        return self._import_media_from_path(path, mod)

    def _import_source_paths(
        self, paths: list[Path], *, already: int = 0, as_collection: bool = False,
        folder_name: str = "", recursive: bool = False,
    ) -> dict[str, Any]:
        from .collection_jobs import MAX_COLLECTION_ITEMS, build_collection_creation
        from .studio_sources import MAX_SOURCES

        remaining_slots = max(0, MAX_SOURCES - max(0, int(already or 0)))
        unique_paths: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            unique_paths.append(path)
        use_collection = bool(as_collection)
        if not use_collection:
            if remaining_slots <= 0:
                return {
                    "ok": False,
                    "error": f"Studio sources are limited to {MAX_SOURCES}.",
                }
            if len(unique_paths) > MAX_SOURCES or len(unique_paths) > remaining_slots:
                use_collection = remaining_slots >= 1 and len(unique_paths) >= 2
        if use_collection and remaining_slots <= 0:
            return {
                "ok": False,
                "error": f"Studio sources are limited to {MAX_SOURCES}.",
            }

        cap = MAX_COLLECTION_ITEMS if use_collection else remaining_slots
        creations: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for path in unique_paths:
            if len(creations) >= cap:
                skipped.append({"name": path.name, "error": "Source limit reached"})
                continue
            res = self._import_source_from_path(path)
            if res.get("ok") and res.get("creation"):
                creations.append(res["creation"])
            else:
                skipped.append(
                    {
                        "name": path.name,
                        "error": str(res.get("error") or "Import failed"),
                    }
                )
        if not creations:
            err = skipped[0]["error"] if skipped else "No supported files"
            return {"ok": False, "error": err, "skipped": skipped}
        if use_collection:
            wrapper = build_collection_creation(
                creations,
                folder_name=folder_name or (unique_paths[0].parent.name if unique_paths else "Collection"),
                recursive=recursive,
                prompt=f"Collection from {folder_name or 'files'}",
            )
            wrapper = self.store.upsert(wrapper)
            return {
                "ok": True,
                "collection": True,
                "creations": [wrapper],
                "members": creations,
                "skipped": skipped,
            }
        return {
            "ok": True,
            "creations": creations,
            "skipped": skipped,
        }

    def import_studio_sources(self, already: int = 0) -> dict[str, Any]:
        """Multi-select mixed files (text, image, video, audio, PDF) as Studio sources."""
        picked = self._dialog_open_paths(
            (
                "All supported (*.txt;*.md;*.markdown;*.csv;*.png;*.jpg;*.jpeg;"
                "*.webp;*.gif;*.bmp;*.mp4;*.webm;*.mov;*.mkv;*.avi;*.mp3;*.wav;"
                "*.ogg;*.m4a;*.aac;*.pdf)",
                "Text Files (*.txt;*.md;*.markdown;*.csv)",
                "Image Files (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp)",
                "Video Files (*.mp4;*.webm;*.mov;*.mkv;*.avi)",
                "Audio Files (*.mp3;*.wav;*.ogg;*.m4a;*.aac)",
                "PDF Files (*.pdf)",
                "All Files (*.*)",
            ),
            allow_multiple=True,
        )
        if not picked.get("ok"):
            return picked
        return self._import_source_paths(picked["paths"], already=already)

    def import_studio_sources_folder(
        self, already: int = 0, recursive: bool = False
    ) -> dict[str, Any]:
        """Import files from a chosen folder as Studio sources."""
        from .studio_sources import list_source_files_in_folder

        if self._window is None:
            return {"ok": False, "error": "No window"}
        result = self._window.create_file_dialog(_file_dialog("folder"))
        if not result:
            return {"ok": False, "cancelled": True}
        folder = Path(result if isinstance(result, str) else result[0])
        if folder.is_file():
            folder = folder.parent
        try:
            folder = folder.expanduser().resolve()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        if not folder.is_dir():
            return {"ok": False, "error": "Folder not found"}
        files = list_source_files_in_folder(folder, recursive=bool(recursive))
        if not files:
            return {"ok": False, "error": "No supported files in that folder."}
        return self._import_source_paths(
            files,
            already=already,
            folder_name=folder.name,
            recursive=bool(recursive),
        )

    def open_viewer_file(self) -> dict[str, Any]:
        """Open any supported file in the Viewer and save it to Archives."""
        from .media_store import modality_for_path

        picked = self._dialog_open_path(
            (
                "All supported (*.txt;*.md;*.markdown;*.csv;*.png;*.jpg;*.jpeg;"
                "*.webp;*.gif;*.bmp;*.mp4;*.webm;*.mov;*.mkv;*.avi;*.mp3;*.wav;"
                "*.ogg;*.m4a;*.aac;*.pdf)",
                "Text Files (*.txt;*.md;*.markdown;*.csv)",
                "Image Files (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp)",
                "Video Files (*.mp4;*.webm;*.mov;*.mkv;*.avi)",
                "Audio Files (*.mp3;*.wav;*.ogg;*.m4a;*.aac)",
                "PDF Files (*.pdf)",
                "All Files (*.*)",
            )
        )
        if not picked.get("ok"):
            return picked
        path = picked["path"]
        mod = modality_for_path(path)
        if not mod:
            return {
                "ok": False,
                "error": "Viewer can open text, images, video, audio, or PDF.",
            }
        if mod == "text":
            return self._import_text_from_path(path, save_to_archives=True)
        return self._import_media_from_path(path, mod)

    def duplicate_creation(self, creation_id: str) -> dict[str, Any]:
        """Clone a creation (and media file) so edits become a new Archive item."""
        import copy
        import uuid

        from .creation_utils import build_media_creation, build_text_creation_from_plain
        from .media_store import read_media_bytes, write_media_bytes

        creation_id = (creation_id or "").strip()
        source = next((c for c in self.store.load() if c.get("id") == creation_id), None)
        if not source:
            return {"ok": False, "error": "Creation not found"}

        mod = str(source.get("modality") or "text").lower()
        new_id = f"doc_{uuid.uuid4().hex[:10]}"
        title = str(source.get("title") or source.get("game") or "Untitled").strip()
        if not title.lower().endswith("(copy)"):
            title = f"{title} (copy)"

        if mod in {"image", "video", "audio", "pdf"}:
            raw = read_media_bytes(source.get("mediaPath"), config=self.config)
            if not raw:
                return {"ok": False, "error": "Media file not found"}
            mime = source.get("mimeType") or (
                "application/pdf"
                if mod == "pdf"
                else "audio/mpeg"
                if mod == "audio"
                else "video/mp4"
                if mod == "video"
                else "image/png"
            )
            stored = write_media_bytes(
                new_id, raw, mime_type=mime, config=self.config
            )
            lyrics = None
            if mod == "audio":
                lyric_parts: list[str] = []
                for sec in source.get("sections") or []:
                    if not isinstance(sec, dict):
                        continue
                    content = str(sec.get("content") or "").strip()
                    if content:
                        lyric_parts.append(content)
                lyrics = "\n\n".join(lyric_parts) or None
            creation = build_media_creation(
                modality=mod,
                prompt=str(source.get("prompt") or title),
                media_path=stored["mediaPath"],
                mime_type=stored["mimeType"],
                title=title,
                creation_id=new_id,
                model_info={"provider": "duplicate", "from": creation_id, "modality": mod},
                lyrics=lyrics,
            )
        else:
            body_parts: list[str] = []
            overview = (source.get("overview") or "").strip()
            if overview:
                body_parts.append(overview)
            for sec in source.get("sections") or []:
                if not isinstance(sec, dict):
                    continue
                st = (sec.get("title") or "").strip()
                sc = (sec.get("content") or "").strip()
                if st and sc:
                    body_parts.append(f"{st}\n{sc}")
                elif sc:
                    body_parts.append(sc)
                elif st:
                    body_parts.append(st)
            body = "\n\n".join(body_parts).strip() or "(empty)"
            creation = build_text_creation_from_plain(
                body,
                prompt=str(source.get("prompt") or title),
                title=title,
                model_info={"provider": "duplicate", "from": creation_id},
            )
            creation["id"] = new_id

        # Preserve useful metadata without sharing the same id
        for key in ("platform", "creationType", "theme", "meta", "accuracyNote"):
            if source.get(key) is not None and key not in creation:
                creation[key] = copy.deepcopy(source.get(key))

        saved = self.store.upsert(creation)
        return {"ok": True, "creation": saved}

    def open_json_import(self) -> dict[str, Any]:
        import webview

        if self._window is None:
            return {"ok": False, "error": "No window"}
        result = self._window.create_file_dialog(
            _file_dialog("open"),
            allow_multiple=True,
            file_types=("JSON Files (*.json)",),
        )
        if not result:
            return {"ok": False, "cancelled": True}

        imported: list[dict[str, Any]] = []
        paths = result if isinstance(result, (list, tuple)) else [result]
        for p in paths:
            try:
                data = json.loads(Path(p).read_text(encoding="utf-8"))
                if isinstance(data, list):
                    imported.extend(data)
                elif isinstance(data, dict):
                    imported.append(data)
            except (OSError, json.JSONDecodeError) as exc:
                return {"ok": False, "error": f"Failed to read {p}: {exc}"}

        creations = self.store.import_items(imported)
        return {"ok": True, "creations": creations, "imported": len(imported)}
