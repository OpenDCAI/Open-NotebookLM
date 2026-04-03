"""Catalog service (Discovery/Catalog layer).

This module provides a lightweight, local catalog over *registered* datasources.
It is designed to support:
- Discovery: "what datasources/tables exist in this workspace?"
- Auditing: keep minimal structured metadata (no secrets)

It intentionally avoids being a full DB catalog or a heavy profiler.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi_app.core.datasource_interface import DataSourceInterface, TableSchema

logger = logging.getLogger(__name__)


def _safe_table_summary(table: TableSchema) -> Dict[str, Any]:
    t = table.to_dict()
    # Keep it compact: remove potentially huge sample_values arrays.
    for col in t.get("columns", []) or []:
        if "sample_values" in col and isinstance(col["sample_values"], list):
            col["sample_values"] = col["sample_values"][:3]
    return t


@dataclass
class CatalogEntry:
    datasource_id: int
    name: str
    type: str
    origin: str = "manual"
    # Optional filesystem path (CSV/Excel/SQLite) for debugging / audit.
    file_path: Optional[str] = None
    tables: List[Dict[str, Any]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "datasource_id": self.datasource_id,
            "name": self.name,
            "type": self.type,
            "origin": self.origin,
            "file_path": self.file_path,
            "tables": self.tables,
            "tags": self.tags,
        }


class CatalogService:
    def __init__(self):
        self._entries: Dict[int, CatalogEntry] = {}

    def upsert_from_datasource(
        self,
        datasource_id: int,
        datasource: DataSourceInterface,
        *,
        origin: str = "manual",
        tags: Optional[List[str]] = None,
    ) -> CatalogEntry:
        meta = getattr(datasource, "metadata", None)
        name = getattr(meta, "name", None) or f"datasource_{datasource_id}"
        ds_type = getattr(getattr(meta, "type", None), "code", None) or "unknown"

        file_path = None
        try:
            cfg = getattr(meta, "connection_config", None) or {}
            file_path = cfg.get("file_path") or cfg.get("database_path")
        except Exception:
            file_path = None

        tables: List[Dict[str, Any]] = []
        if hasattr(datasource, "get_tables"):
            try:
                for t in (datasource.get_tables() or [])[:50]:
                    tables.append(_safe_table_summary(t))
            except Exception as e:
                logger.debug(f"CatalogService.get_tables failed for ds={datasource_id}: {e}")

        entry = CatalogEntry(
            datasource_id=int(datasource_id),
            name=str(name),
            type=str(ds_type),
            origin=str(origin or "manual"),
            file_path=str(file_path) if file_path else None,
            tables=tables,
            tags=list(tags or []),
        )
        self._entries[int(datasource_id)] = entry
        return entry

    def list_entries(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._entries.values()]

    def get_entry(self, datasource_id: int) -> Optional[Dict[str, Any]]:
        e = self._entries.get(int(datasource_id))
        return e.to_dict() if e else None

    def clear(self) -> None:
        self._entries.clear()

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"entries": self.list_entries()}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def load_json(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            self._entries.clear()
            for e in obj.get("entries", []) or []:
                try:
                    cid = int(e.get("datasource_id"))
                except Exception:
                    continue
                self._entries[cid] = CatalogEntry(
                    datasource_id=cid,
                    name=e.get("name") or f"datasource_{cid}",
                    type=e.get("type") or "unknown",
                    origin=e.get("origin") or "manual",
                    file_path=e.get("file_path"),
                    tables=e.get("tables") or [],
                    tags=e.get("tags") or [],
                )
        except Exception as ex:
            logger.warning(f"CatalogService.load_json failed: {ex}")


catalog_service = CatalogService()

