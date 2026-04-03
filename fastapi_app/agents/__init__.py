"""Compatibility package mapping legacy ``fastapi_app.agents`` imports to ``fastapi_app.modules.agents``."""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parents[1] / "modules" / "agents")]
