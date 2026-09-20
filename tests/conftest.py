"""Keep Studio's Gemini classifier offline in unit tests (regex fallback)."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _offline_studio_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid a live Gemini call on every CREATE path during pytest."""
    monkeypatch.setattr(
        "synthetic_text_extruder.studio_router._call_gemini_router",
        lambda *args, **kwargs: None,
    )
