"""SQLite sidecar for first-class prompt steps (full text, not graph previews)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .config import archives_path, load_config

PROMPT_TEXT_MAX = 100_000


def lineage_db_path(cfg: dict[str, Any] | None = None) -> Path:
    """``lineage.sqlite`` next to ``archives.json``."""
    archives = archives_path(cfg if cfg is not None else load_config())
    return archives.with_name("lineage.sqlite")


def clip_prompt_text(text: str | None) -> str:
    raw = str(text or "")
    if len(raw) <= PROMPT_TEXT_MAX:
        return raw
    return raw[: PROMPT_TEXT_MAX - 1] + "…"


class LineageStore:
    """Prompt-node bodies for the Lineage viewer. Graph topology stays in archives."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prompt_steps (
                    id TEXT PRIMARY KEY,
                    child_id TEXT NOT NULL,
                    prompt_text TEXT NOT NULL DEFAULT '',
                    from_modality TEXT NOT NULL DEFAULT '',
                    to_modality TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_prompt_steps_child ON prompt_steps(child_id)"
            )
            conn.commit()

    def upsert_prompt_step(
        self,
        *,
        node_id: str,
        child_id: str,
        prompt_text: str = "",
        from_modality: str = "",
        to_modality: str = "",
        created_at: str = "",
        overwrite: bool = False,
    ) -> dict[str, str]:
        nid = str(node_id or "").strip()
        cid = str(child_id or "").strip()
        if not nid or not cid:
            return {}
        row = {
            "id": nid,
            "child_id": cid,
            "prompt_text": clip_prompt_text(prompt_text),
            "from_modality": str(from_modality or "").strip().lower()[:24],
            "to_modality": str(to_modality or "").strip().lower()[:24],
            "created_at": str(created_at or "").strip(),
        }
        with self._connect() as conn:
            if overwrite:
                conn.execute(
                    """
                    INSERT INTO prompt_steps (
                        id, child_id, prompt_text, from_modality, to_modality, created_at
                    ) VALUES (:id, :child_id, :prompt_text, :from_modality, :to_modality, :created_at)
                    ON CONFLICT(id) DO UPDATE SET
                        child_id = excluded.child_id,
                        prompt_text = excluded.prompt_text,
                        from_modality = excluded.from_modality,
                        to_modality = excluded.to_modality,
                        created_at = excluded.created_at
                    """,
                    row,
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO prompt_steps (
                        id, child_id, prompt_text, from_modality, to_modality, created_at
                    ) VALUES (:id, :child_id, :prompt_text, :from_modality, :to_modality, :created_at)
                    """,
                    row,
                )
            conn.commit()
        return row

    def get_prompt_step(self, node_id: str) -> dict[str, str] | None:
        nid = str(node_id or "").strip()
        if not nid:
            return None
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT id, child_id, prompt_text, from_modality, to_modality, created_at "
                "FROM prompt_steps WHERE id = ?",
                (nid,),
            )
            found = cur.fetchone()
        if found is None:
            return None
        return {name: str(found[name] or "") for name in found.keys()}
