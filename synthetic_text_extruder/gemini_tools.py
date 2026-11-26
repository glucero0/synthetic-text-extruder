"""Built-in Gemini function-calling tools (local file read/write and PowerShell)."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MiB
MAX_POWERSHELL_OUTPUT_BYTES = 2 * 1024 * 1024
POWERSHELL_TIMEOUT_SEC = 120
MAX_TOOL_ITERATIONS = 16

# Catalog: fixed aliases declared to Gemini when the user attaches them in Creator.
TOOL_CATALOG: list[dict[str, str]] = [
    {
        "alias": "read_json",
        "display_name": "Read JSON",
        "summary": "Read and parse a JSON file at an absolute path",
    },
    {
        "alias": "write_json",
        "display_name": "Write JSON",
        "summary": "Write JSON data to a file at an absolute path (overwrites)",
    },
    {
        "alias": "read_text",
        "display_name": "Read text",
        "summary": "Read a text file at an absolute path",
    },
    {
        "alias": "write_text",
        "display_name": "Write text",
        "summary": "Write text to a file at an absolute path (overwrites)",
    },
    {
        "alias": "execute_powershell",
        "display_name": "Execute PowerShell",
        "summary": "Run a .ps1 script at an absolute path; returns stdout, stderr, and exit code",
    },
    {
        "alias": "search_gmail",
        "display_name": "Search Gmail",
        "summary": "Search Gmail with query syntax (unread, shipments, specific senders, etc.)",
    },
    {
        "alias": "search_drive",
        "display_name": "Search Drive",
        "summary": "Search Google Drive files by name, type, or Drive query syntax",
    },
    {
        "alias": "create_drive_file",
        "display_name": "Create Drive file",
        "summary": "Create a Google Drive file (text/plain by default)",
    },
    {
        "alias": "read_google_doc",
        "display_name": "Read Google Doc",
        "summary": "Read the text of a Google Doc by document ID",
    },
    {
        "alias": "create_google_doc",
        "display_name": "Create Google Doc",
        "summary": "Create a Google Doc with an optional initial body",
    },
    {
        "alias": "edit_google_doc",
        "display_name": "Edit Google Doc",
        "summary": "Replace or append text in a Google Doc",
    },
    {
        "alias": "list_calendar_events",
        "display_name": "List Calendar events",
        "summary": "List Google Calendar events in a time range",
    },
    {
        "alias": "create_calendar_event",
        "display_name": "Create Calendar event",
        "summary": "Create a Google Calendar event",
    },
    {
        "alias": "edit_calendar_event",
        "display_name": "Edit Calendar event",
        "summary": "Update an existing Google Calendar event",
    },
    {
        "alias": "list_tasks",
        "display_name": "List Tasks",
        "summary": "List Google Tasks on the default or a named list",
    },
    {
        "alias": "create_task",
        "display_name": "Create Task",
        "summary": "Create a Google Task (title, optional notes and due date/time)",
    },
    {
        "alias": "edit_task",
        "display_name": "Edit Task",
        "summary": "Update or complete a Google Task",
    },
    {
        "alias": "browse_web",
        "display_name": "Browse Web",
        "summary": "Open an http(s) URL, read the page, and follow its links",
    },
]

_ALIAS_SET = {t["alias"] for t in TOOL_CATALOG}


def list_tool_catalog() -> list[dict[str, str]]:
    """Return a copy of the built-in tool catalog for UI / bootstrap."""
    from .platform_env import is_android

    if is_android():
        return [dict(t) for t in TOOL_CATALOG if t["alias"] != "execute_powershell"]
    return [dict(t) for t in TOOL_CATALOG]


def normalize_tool_aliases(aliases: list[str] | None) -> list[str]:
    """Dedupe and keep only known catalog aliases (stable catalog order)."""
    if not aliases:
        return []
    from .platform_env import is_android

    wanted = {str(a).strip() for a in aliases if str(a).strip()}
    if is_android():
        wanted.discard("execute_powershell")
    return [t["alias"] for t in TOOL_CATALOG if t["alias"] in wanted]


def _require_absolute_path(path_str: str) -> Path:
    from .config import PROJECT_ROOT
    from .platform_env import configured_workspace_dir, is_android

    raw = (path_str or "").strip()
    if not raw:
        raise ValueError("path is required")
    p = Path(raw)
    if not p.is_absolute():
        if is_android():
            base = configured_workspace_dir() or (PROJECT_ROOT / "workspace")
            base.mkdir(parents=True, exist_ok=True)
            resolved_base = base.resolve()
            resolved = (resolved_base / p).resolve(strict=False)
            try:
                resolved.relative_to(resolved_base)
            except ValueError as exc:
                raise ValueError(f"path must stay inside workspace folder (got {raw!r})") from exc
            return resolved
        raise ValueError(f"path must be absolute (got {raw!r})")
    # Reject empty / odd drive-relative forms after resolve where possible
    try:
        resolved = p.resolve(strict=False)
    except OSError as exc:
        raise ValueError(f"invalid path: {exc}") from exc
    if not resolved.is_absolute():
        raise ValueError(f"path must be absolute (got {raw!r})")
    return resolved


def _read_bytes_limited(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {path}")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(
            f"file too large ({size} bytes); max is {MAX_FILE_BYTES} bytes"
        )
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(
            f"file too large ({len(data)} bytes); max is {MAX_FILE_BYTES} bytes"
        )
    return data


def _write_bytes(path: Path, data: bytes) -> None:
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(
            f"content too large ({len(data)} bytes); max is {MAX_FILE_BYTES} bytes"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _decode_output(raw: bytes) -> str:
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def _truncate_output(text: str, *, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    trimmed = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return trimmed + "\n…[output truncated]"


def _execute_powershell_script(
    script_path: Path,
    arguments: list[str] | None = None,
) -> dict[str, Any]:
    if sys.platform != "win32":
        return {
            "ok": False,
            "error": "execute_powershell is only available on Windows",
        }
    if script_path.suffix.lower() != ".ps1":
        return {
            "ok": False,
            "error": f"script must be a .ps1 file (got {script_path.name!r})",
        }
    if not script_path.is_file():
        return {"ok": False, "error": f"script not found: {script_path}"}

    args = [str(a) for a in (arguments or []) if str(a).strip()]
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        *args,
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            timeout=POWERSHELL_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "path": str(script_path),
            "error": f"script timed out after {POWERSHELL_TIMEOUT_SEC} seconds",
        }
    except OSError as exc:
        return {"ok": False, "error": f"failed to start PowerShell: {exc}"}

    stdout = _truncate_output(
        _decode_output(completed.stdout or b""),
        max_bytes=MAX_POWERSHELL_OUTPUT_BYTES,
    )
    stderr = _truncate_output(
        _decode_output(completed.stderr or b""),
        max_bytes=MAX_POWERSHELL_OUTPUT_BYTES,
    )
    exit_code = int(completed.returncode)
    result: dict[str, Any] = {
        "ok": exit_code == 0,
        "path": str(script_path),
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
    }
    if exit_code != 0:
        result["error"] = f"script exited with code {exit_code}"
    return result


def execute_tool(name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """Run a built-in tool; always returns a JSON-serializable result dict."""
    alias = (name or "").strip()
    params = dict(args or {})
    try:
        if alias not in _ALIAS_SET:
            return {"ok": False, "error": f"unknown tool: {alias!r}"}
        if alias == "read_json":
            path = _require_absolute_path(str(params.get("path") or ""))
            raw = _read_bytes_limited(path)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                return {"ok": False, "error": f"file is not valid UTF-8: {exc}"}
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                return {"ok": False, "error": f"invalid JSON: {exc}"}
            return {"ok": True, "path": str(path), "data": data}
        if alias == "write_json":
            path = _require_absolute_path(str(params.get("path") or ""))
            if "data" not in params:
                return {"ok": False, "error": "data is required"}
            try:
                encoded = json.dumps(
                    params["data"], ensure_ascii=False, indent=2
                ).encode("utf-8")
            except (TypeError, ValueError) as exc:
                return {"ok": False, "error": f"data is not JSON-serializable: {exc}"}
            _write_bytes(path, encoded)
            return {"ok": True, "path": str(path), "bytes_written": len(encoded)}
        if alias == "read_text":
            path = _require_absolute_path(str(params.get("path") or ""))
            raw = _read_bytes_limited(path)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                return {"ok": False, "error": f"file is not valid UTF-8: {exc}"}
            return {"ok": True, "path": str(path), "text": text}
        if alias == "write_text":
            path = _require_absolute_path(str(params.get("path") or ""))
            if "text" not in params:
                return {"ok": False, "error": "text is required"}
            text = params.get("text")
            if not isinstance(text, str):
                text = str(text)
            encoded = text.encode("utf-8")
            _write_bytes(path, encoded)
            return {"ok": True, "path": str(path), "bytes_written": len(encoded)}
        if alias == "execute_powershell":
            path = _require_absolute_path(str(params.get("path") or ""))
            raw_args = params.get("arguments")
            arguments: list[str] = []
            if raw_args is not None:
                if not isinstance(raw_args, list):
                    return {"ok": False, "error": "arguments must be an array of strings"}
                arguments = [str(a) for a in raw_args]
            return _execute_powershell_script(path, arguments)
        if alias == "search_gmail":
            from .gmail_client import search_gmail as gmail_search

            query = str(params.get("query") or "").strip()
            raw_max = params.get("max_results")
            max_results: int | None = None
            if raw_max is not None:
                try:
                    max_results = int(raw_max)
                except (TypeError, ValueError):
                    return {"ok": False, "error": "max_results must be an integer"}
            include_body = bool(params.get("include_body"))
            return gmail_search(
                query,
                max_results=max_results,
                include_body=include_body,
            )
        if alias == "search_drive":
            from .drive_client import search_drive as drive_search

            query = str(params.get("query") or "").strip()
            raw_max = params.get("max_results")
            max_results: int | None = None
            if raw_max is not None:
                try:
                    max_results = int(raw_max)
                except (TypeError, ValueError):
                    return {"ok": False, "error": "max_results must be an integer"}
            mime_type = str(params.get("mime_type") or "").strip() or None
            return drive_search(
                query,
                max_results=max_results,
                mime_type=mime_type,
            )
        if alias == "create_drive_file":
            from .drive_client import create_drive_file as drive_create

            name = str(params.get("name") or "").strip()
            content = params.get("content")
            if content is not None and not isinstance(content, str):
                content = str(content)
            mime_type = str(params.get("mime_type") or "").strip() or None
            return drive_create(name, content=content, mime_type=mime_type)
        if alias == "read_google_doc":
            from .docs_client import read_google_doc as docs_read

            return docs_read(str(params.get("document_id") or ""))
        if alias == "create_google_doc":
            from .docs_client import create_google_doc as docs_create

            title = str(params.get("title") or "").strip()
            text = params.get("text")
            if text is not None and not isinstance(text, str):
                text = str(text)
            return docs_create(title, text=text)
        if alias == "edit_google_doc":
            from .docs_client import edit_google_doc as docs_edit

            if "text" not in params:
                return {"ok": False, "error": "text is required"}
            text = params.get("text")
            if not isinstance(text, str):
                text = str(text)
            mode = str(params.get("mode") or "replace")
            return docs_edit(
                str(params.get("document_id") or ""),
                text=text,
                mode=mode,
            )
        if alias == "list_calendar_events":
            from .calendar_client import list_calendar_events as cal_list

            raw_max = params.get("max_results")
            max_results = None
            if raw_max is not None:
                try:
                    max_results = int(raw_max)
                except (TypeError, ValueError):
                    return {"ok": False, "error": "max_results must be an integer"}
            return cal_list(
                time_min=str(params.get("time_min") or "").strip() or None,
                time_max=str(params.get("time_max") or "").strip() or None,
                max_results=max_results,
                calendar_id=str(params.get("calendar_id") or "").strip() or None,
                query=str(params.get("query") or "").strip() or None,
            )
        if alias == "create_calendar_event":
            from .calendar_client import create_calendar_event as cal_create

            return cal_create(
                str(params.get("summary") or ""),
                str(params.get("start") or ""),
                str(params.get("end") or ""),
                description=(
                    str(params.get("description"))
                    if params.get("description") is not None
                    else None
                ),
                location=(
                    str(params.get("location"))
                    if params.get("location") is not None
                    else None
                ),
                calendar_id=str(params.get("calendar_id") or "").strip() or None,
                all_day=bool(params.get("all_day")),
            )
        if alias == "edit_calendar_event":
            from .calendar_client import edit_calendar_event as cal_edit

            def _opt_str(key: str) -> str | None:
                if key not in params:
                    return None
                return str(params.get(key))

            return cal_edit(
                str(params.get("event_id") or ""),
                summary=_opt_str("summary"),
                start=_opt_str("start"),
                end=_opt_str("end"),
                description=_opt_str("description"),
                location=_opt_str("location"),
                calendar_id=str(params.get("calendar_id") or "").strip() or None,
                all_day=bool(params.get("all_day")),
            )
        if alias == "list_tasks":
            from .tasks_client import list_tasks as tasks_list

            raw_max = params.get("max_results")
            max_results = None
            if raw_max is not None:
                try:
                    max_results = int(raw_max)
                except (TypeError, ValueError):
                    return {"ok": False, "error": "max_results must be an integer"}
            return tasks_list(
                max_results=max_results,
                tasklist_id=str(params.get("tasklist_id") or "").strip() or None,
                show_completed=bool(params.get("show_completed")),
                query=str(params.get("query") or "").strip() or None,
            )
        if alias == "create_task":
            from .tasks_client import create_task as tasks_create

            return tasks_create(
                str(params.get("title") or ""),
                notes=(
                    str(params.get("notes"))
                    if params.get("notes") is not None
                    else None
                ),
                due=str(params.get("due") or "").strip() or None,
                tasklist_id=str(params.get("tasklist_id") or "").strip() or None,
            )
        if alias == "edit_task":
            from .tasks_client import edit_task as tasks_edit

            def _opt_task_str(key: str) -> str | None:
                if key not in params:
                    return None
                return str(params.get(key))

            return tasks_edit(
                str(params.get("task_id") or ""),
                title=_opt_task_str("title"),
                notes=_opt_task_str("notes"),
                due=_opt_task_str("due"),
                status=_opt_task_str("status"),
                tasklist_id=str(params.get("tasklist_id") or "").strip() or None,
            )
        if alias == "browse_web":
            from .web_browse import browse_web as web_browse

            page_url = str(params.get("url") or "").strip()
            raw_max = params.get("max_chars")
            max_chars: int | None = None
            if raw_max is not None:
                try:
                    max_chars = int(raw_max)
                except (TypeError, ValueError):
                    return {"ok": False, "error": "max_chars must be an integer"}
            include_links = True
            if "include_links" in params:
                include_links = bool(params.get("include_links"))
            return web_browse(
                page_url,
                include_links=include_links,
                max_chars=max_chars,
            )
        return {"ok": False, "error": f"unhandled tool: {alias!r}"}
    except Exception as exc:  # noqa: BLE001
        logger.info("Tool %s failed: %s", alias, exc)
        return {"ok": False, "error": str(exc)}


def function_declarations_for(
    aliases: list[str] | None,
    *,
    now: Any = None,
) -> list[Any]:
    """Build google.genai FunctionDeclaration objects for the given aliases."""
    from google.genai import types

    from .prompts import CLOCK_TOOL_ALIASES, local_clock_line

    selected = normalize_tool_aliases(aliases)
    clock_line = ""
    if any(alias in CLOCK_TOOL_ALIASES for alias in selected):
        clock_line = " " + local_clock_line(now)
    decls: list[Any] = []
    for alias in selected:
        if alias == "read_json":
            decls.append(
                types.FunctionDeclaration(
                    name="read_json",
                    description=(
                        "Read a JSON file from an absolute filesystem path and "
                        "return the parsed data."
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Absolute path to a JSON file",
                            }
                        },
                        "required": ["path"],
                    },
                )
            )
        elif alias == "write_json":
            decls.append(
                types.FunctionDeclaration(
                    name="write_json",
                    description=(
                        "Write JSON-serializable data to an absolute filesystem "
                        "path (creates parent directories; overwrites existing files)."
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Absolute path for the output JSON file",
                            },
                            "data": {
                                "description": "JSON-serializable value to write",
                            },
                        },
                        "required": ["path", "data"],
                    },
                )
            )
        elif alias == "read_text":
            decls.append(
                types.FunctionDeclaration(
                    name="read_text",
                    description=(
                        "Read a UTF-8 text file from an absolute filesystem path."
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Absolute path to a text file",
                            }
                        },
                        "required": ["path"],
                    },
                )
            )
        elif alias == "write_text":
            decls.append(
                types.FunctionDeclaration(
                    name="write_text",
                    description=(
                        "Write UTF-8 text to an absolute filesystem path "
                        "(creates parent directories; overwrites existing files)."
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Absolute path for the output text file",
                            },
                            "text": {
                                "type": "string",
                                "description": "Text content to write",
                            },
                        },
                        "required": ["path", "text"],
                    },
                )
            )
        elif alias == "execute_powershell":
            decls.append(
                types.FunctionDeclaration(
                    name="execute_powershell",
                    description=(
                        "Run a PowerShell script (.ps1) at an absolute filesystem path. "
                        "Returns stdout, stderr, and exit_code in the tool response — "
                        "use stdout with write_text when saving script output to a file."
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Absolute path to a .ps1 script file",
                            },
                            "arguments": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional arguments passed to the script",
                            },
                        },
                        "required": ["path"],
                    },
                )
            )
        elif alias == "search_gmail":
            decls.append(
                types.FunctionDeclaration(
                    name="search_gmail",
                    description=(
                        "Search the user's Gmail inbox using Gmail search syntax. "
                        "Resolve today/yesterday/last week against the injected "
                        "local clock. Use after:YYYY/MM/DD, before:YYYY/MM/DD, "
                        "newer_than:7d. Examples: is:unread in:inbox; "
                        "category:purchases; subject:tracking; from:amazon.com "
                        "newer_than:7d; is:unread to:me -from:noreply. "
                        "Returns message metadata (from, subject, date, snippet, labels) "
                        "and optional full plain-text bodies. Read-only."
                        f"{clock_line}"
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": (
                                    "Gmail search query (same syntax as Gmail search "
                                    "box). Resolve relative dates against the injected "
                                    "local clock (after:YYYY/MM/DD, before:YYYY/MM/DD, "
                                    "newer_than:7d)."
                                ),
                            },
                            "max_results": {
                                "type": "integer",
                                "description": (
                                    "Maximum messages to return (default 20, max 50)"
                                ),
                            },
                            "include_body": {
                                "type": "boolean",
                                "description": (
                                    "When true, fetch plain-text body for each message "
                                    "(larger response; use for detailed analysis)"
                                ),
                            },
                        },
                        "required": ["query"],
                    },
                )
            )
        elif alias == "search_drive":
            decls.append(
                types.FunctionDeclaration(
                    name="search_drive",
                    description=(
                        "Search the user's Google Drive using Drive query syntax. "
                        "Resolve relative date windows against the injected local "
                        "clock; use modifiedTime / createdTime with RFC3339 from "
                        "this clock. Examples: name contains 'budget'; mimeType = "
                        "'application/vnd.google-apps.document'; "
                        "fullText contains 'invoice' and trashed = false. "
                        "Returns file id, name, mime type, modified time, and URL."
                        f"{clock_line}"
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": (
                                    "Drive search query (name contains, mimeType, "
                                    "fullText, modifiedTime, createdTime, …). "
                                    "Resolve relative windows against the injected "
                                    "local clock using RFC3339."
                                ),
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum files to return (default 20, max 50)",
                            },
                            "mime_type": {
                                "type": "string",
                                "description": "Optional MIME type filter appended to the query",
                            },
                        },
                        "required": ["query"],
                    },
                )
            )
        elif alias == "create_drive_file":
            decls.append(
                types.FunctionDeclaration(
                    name="create_drive_file",
                    description=(
                        "Create a file in the user's Google Drive. Default MIME type "
                        "is text/plain. Use create_google_doc for a Google Doc. "
                        "Resolve relative dates against the injected local clock; "
                        "put today's date in the title only if the user asked for "
                        "today/this week."
                        f"{clock_line}"
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": (
                                    "File name, including extension when useful. "
                                    "Use today's date from the local clock only if "
                                    "the user asked for today/this week."
                                ),
                            },
                            "content": {
                                "type": "string",
                                "description": "Optional file body (UTF-8 text)",
                            },
                            "mime_type": {
                                "type": "string",
                                "description": "MIME type (default text/plain)",
                            },
                        },
                        "required": ["name"],
                    },
                )
            )
        elif alias == "read_google_doc":
            decls.append(
                types.FunctionDeclaration(
                    name="read_google_doc",
                    description=(
                        "Read the plain text of a Google Doc. Use search_drive first "
                        "when you only have a title, then pass the returned file id. "
                        "Resolve today/this week against the injected local clock "
                        "when matching titles; do not invent dates the user did "
                        "not imply."
                        f"{clock_line}"
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "document_id": {
                                "type": "string",
                                "description": "Google Doc document/file ID",
                            },
                        },
                        "required": ["document_id"],
                    },
                )
            )
        elif alias == "create_google_doc":
            decls.append(
                types.FunctionDeclaration(
                    name="create_google_doc",
                    description=(
                        "Create a Google Doc with a title and optional body text. "
                        "Resolve today/this week against the injected local clock "
                        "for titles or body; do not invent dates the user did "
                        "not imply."
                        f"{clock_line}"
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": (
                                    "Document title. Use today's date from the "
                                    "local clock only if the user asked for "
                                    "today/this week."
                                ),
                            },
                            "text": {
                                "type": "string",
                                "description": "Optional initial document body",
                            },
                        },
                        "required": ["title"],
                    },
                )
            )
        elif alias == "edit_google_doc":
            decls.append(
                types.FunctionDeclaration(
                    name="edit_google_doc",
                    description=(
                        "Edit a Google Doc. mode=replace overwrites the body; "
                        "mode=append adds text at the end. Resolve today/this "
                        "week against the injected local clock for body text; "
                        "do not invent dates the user did not imply."
                        f"{clock_line}"
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "document_id": {
                                "type": "string",
                                "description": "Google Doc document/file ID",
                            },
                            "text": {
                                "type": "string",
                                "description": "Text to write or append",
                            },
                            "mode": {
                                "type": "string",
                                "description": "replace (default) or append",
                            },
                        },
                        "required": ["document_id", "text"],
                    },
                )
            )
        elif alias == "list_calendar_events":
            decls.append(
                types.FunctionDeclaration(
                    name="list_calendar_events",
                    description=(
                        "List events on the user's Google Calendar. Resolve relative "
                        "dates against the injected local clock. Times are RFC3339 with "
                        "the local UTC offset, not Z unless the user asked for UTC. "
                        "Defaults to the primary calendar."
                        f"{clock_line}"
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "time_min": {
                                "type": "string",
                                "description": (
                                    "Lower bound (RFC3339 with local UTC offset, "
                                    "not Z unless UTC was requested), inclusive"
                                ),
                            },
                            "time_max": {
                                "type": "string",
                                "description": (
                                    "Upper bound (RFC3339 with local UTC offset, "
                                    "not Z unless UTC was requested), exclusive"
                                ),
                            },
                            "query": {
                                "type": "string",
                                "description": "Optional free-text search across events",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum events to return (default 20, max 50)",
                            },
                            "calendar_id": {
                                "type": "string",
                                "description": "Calendar ID (default primary)",
                            },
                        },
                    },
                )
            )
        elif alias == "create_calendar_event":
            decls.append(
                types.FunctionDeclaration(
                    name="create_calendar_event",
                    description=(
                        "Create an event on the user's Google Calendar. Resolve "
                        "relative dates/times against the injected local clock. Pass "
                        "start/end as RFC3339 with the local UTC offset, not Z unless "
                        "the user asked for UTC; or YYYY-MM-DD with all_day=true."
                        f"{clock_line}"
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "summary": {
                                "type": "string",
                                "description": "Event title",
                            },
                            "start": {
                                "type": "string",
                                "description": (
                                    "Start time (RFC3339 with local UTC offset, "
                                    "not Z unless UTC was requested) or date (YYYY-MM-DD)"
                                ),
                            },
                            "end": {
                                "type": "string",
                                "description": (
                                    "End time (RFC3339 with local UTC offset, "
                                    "not Z unless UTC was requested) or date (YYYY-MM-DD)"
                                ),
                            },
                            "description": {
                                "type": "string",
                                "description": "Optional event description",
                            },
                            "location": {
                                "type": "string",
                                "description": "Optional location",
                            },
                            "calendar_id": {
                                "type": "string",
                                "description": "Calendar ID (default primary)",
                            },
                            "all_day": {
                                "type": "boolean",
                                "description": "When true, start/end are calendar dates",
                            },
                        },
                        "required": ["summary", "start", "end"],
                    },
                )
            )
        elif alias == "edit_calendar_event":
            decls.append(
                types.FunctionDeclaration(
                    name="edit_calendar_event",
                    description=(
                        "Update fields on an existing Google Calendar event. Resolve "
                        "relative dates/times against the injected local clock. Pass "
                        "start/end as RFC3339 with the local UTC offset, not Z unless "
                        "the user asked for UTC."
                        f"{clock_line}"
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "event_id": {
                                "type": "string",
                                "description": "Event ID from list_calendar_events",
                            },
                            "summary": {
                                "type": "string",
                                "description": "New title",
                            },
                            "start": {
                                "type": "string",
                                "description": (
                                    "New start (RFC3339 with local UTC offset, "
                                    "not Z unless UTC was requested, or YYYY-MM-DD)"
                                ),
                            },
                            "end": {
                                "type": "string",
                                "description": (
                                    "New end (RFC3339 with local UTC offset, "
                                    "not Z unless UTC was requested, or YYYY-MM-DD)"
                                ),
                            },
                            "description": {
                                "type": "string",
                                "description": "New description",
                            },
                            "location": {
                                "type": "string",
                                "description": "New location",
                            },
                            "calendar_id": {
                                "type": "string",
                                "description": "Calendar ID (default primary)",
                            },
                            "all_day": {
                                "type": "boolean",
                                "description": "When true, start/end are calendar dates",
                            },
                        },
                        "required": ["event_id"],
                    },
                )
            )
        elif alias == "list_tasks":
            decls.append(
                types.FunctionDeclaration(
                    name="list_tasks",
                    description=(
                        "List Google Tasks on the user's default task list "
                        "(@default) or a specific tasklist_id. This is Tasks, "
                        "not Calendar events. Resolve relative due dates/times against "
                        "the injected local clock."
                        f"{clock_line}"
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Optional filter matching title or notes",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum tasks to return (default 20, max 50)",
                            },
                            "tasklist_id": {
                                "type": "string",
                                "description": "Task list ID (default @default)",
                            },
                            "show_completed": {
                                "type": "boolean",
                                "description": "When true, include completed tasks",
                            },
                        },
                    },
                )
            )
        elif alias == "create_task":
            decls.append(
                types.FunctionDeclaration(
                    name="create_task",
                    description=(
                        "Create a Google Task (a to-do item, not a Calendar event). "
                        "Resolve relative due dates/times against the injected local "
                        "clock. due is an optional due date and time — pass RFC3339 "
                        "with the local UTC offset from the injected clock, not Z "
                        "unless the user asked for UTC."
                        f"{clock_line}"
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Task title",
                            },
                            "notes": {
                                "type": "string",
                                "description": "Optional details",
                            },
                            "due": {
                                "type": "string",
                                "description": (
                                    "Optional due date/time (RFC3339 with local UTC "
                                    "offset from the injected clock, not Z unless UTC "
                                    "was requested). Resolve relative dates and times "
                                    "against the local clock."
                                ),
                            },
                            "tasklist_id": {
                                "type": "string",
                                "description": "Task list ID (default @default)",
                            },
                        },
                        "required": ["title"],
                    },
                )
            )
        elif alias == "edit_task":
            decls.append(
                types.FunctionDeclaration(
                    name="edit_task",
                    description=(
                        "Update a Google Task. status is needsAction or completed. "
                        "Resolve relative due dates/times against the injected local "
                        "clock. due is an optional due date and time — pass RFC3339 "
                        "with the local UTC offset from the injected clock, not Z "
                        "unless the user asked for UTC."
                        f"{clock_line}"
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "Task ID from list_tasks",
                            },
                            "title": {
                                "type": "string",
                                "description": "New title",
                            },
                            "notes": {
                                "type": "string",
                                "description": "New notes",
                            },
                            "due": {
                                "type": "string",
                                "description": (
                                    "New due date/time (RFC3339 with local UTC offset "
                                    "from the injected clock, not Z unless UTC was "
                                    "requested). Resolve relative dates and times "
                                    "against the local clock."
                                ),
                            },
                            "status": {
                                "type": "string",
                                "description": "needsAction or completed",
                            },
                            "tasklist_id": {
                                "type": "string",
                                "description": "Task list ID (default @default)",
                            },
                        },
                        "required": ["task_id"],
                    },
                )
            )
        elif alias == "browse_web":
            decls.append(
                types.FunctionDeclaration(
                    name="browse_web",
                    description=(
                        "Fetch an http(s) URL and return readable page text plus outbound "
                        "links so you can traverse the web. You may construct the URL "
                        "(including query strings and paths) before calling. After a page "
                        "loads, pick a returned link and call browse_web again to follow it. "
                        "Use this for a specific page; use Google Search when you need to "
                        "discover URLs first. Do not use file:// or local filesystem paths."
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": (
                                    "http(s) URL to open. May be constructed "
                                    "(for example https://example.com/search?q=term)."
                                ),
                            },
                            "include_links": {
                                "type": "boolean",
                                "description": (
                                    "When true (default), include outbound links for traversal"
                                ),
                            },
                            "max_chars": {
                                "type": "integer",
                                "description": (
                                    "Maximum extracted text characters to return "
                                    "(default 24000, max 48000)"
                                ),
                            },
                        },
                        "required": ["url"],
                    },
                )
            )
    return decls


def tools_config_for(
    aliases: list[str] | None,
    *,
    with_search: bool = False,
) -> list[Any] | None:
    """Return GenerateContentConfig.tools list, or None if nothing to enable."""
    from google.genai import types

    tools: list[Any] = []
    if with_search:
        tools.append(types.Tool(google_search=types.GoogleSearch()))
    decls = function_declarations_for(aliases)
    if decls:
        tools.append(types.Tool(function_declarations=decls))
    return tools or None


def extract_function_calls(response: Any) -> list[tuple[str, dict[str, Any]]]:
    """Return [(name, args), ...] from a generate_content response."""
    calls: list[tuple[str, dict[str, Any]]] = []
    try:
        cands = getattr(response, "candidates", None) or []
        if not cands:
            return calls
        content = getattr(cands[0], "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            fc = getattr(part, "function_call", None)
            if not fc:
                continue
            name = getattr(fc, "name", None) or ""
            raw_args = getattr(fc, "args", None)
            if raw_args is None:
                args: dict[str, Any] = {}
            elif isinstance(raw_args, dict):
                args = dict(raw_args)
            else:
                # protobuf MapComposite / similar
                try:
                    args = dict(raw_args)
                except Exception:  # noqa: BLE001
                    args = {}
            if name:
                calls.append((str(name), args))
    except Exception:  # noqa: BLE001
        logger.debug("Could not parse function_call parts", exc_info=True)
    return calls


def response_text(response: Any) -> str:
    """Best-effort plain text from a generate_content response."""
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    try:
        cands = getattr(response, "candidates", None) or []
        if not cands:
            return ""
        parts = getattr(getattr(cands[0], "content", None), "parts", None) or []
        chunks: list[str] = []
        for part in parts:
            t = getattr(part, "text", None)
            if isinstance(t, str) and t:
                chunks.append(t)
        return "".join(chunks).strip()
    except Exception:  # noqa: BLE001
        return ""
