"""Compatibility package mapping legacy ``fastapi_app.core`` imports to ``fastapi_app.datasources``."""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parents[1] / "datasources")]
