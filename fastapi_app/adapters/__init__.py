"""Compatibility package mapping legacy ``fastapi_app.adapters`` imports to ``fastapi_app.datasources.adapters``."""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parents[1] / "datasources" / "adapters")]
