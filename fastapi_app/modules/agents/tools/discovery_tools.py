"""Discovery tools - scan a directory of files and register datasources.

This is a pragmatic step toward HDR-Bench "Discovery" tasks:
- Given a messy folder, find candidate CSV/Excel/SQLite files
- Register them as DataSourceInterface instances so the agent can query them
- Build/return a lightweight Catalog snapshot for auditing

Note: registration may be expensive for large CSVs because the current CSV adapter
materializes tables in DuckDB memory. This tool caps the number of files and is
meant for controlled evaluation/workspace usage.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from langchain_core.tools import tool

from fastapi_app.core.config import settings
from fastapi_app.core.datasource_interface import DataSourceMetadata, DataSourceType
from fastapi_app.adapters.csv_datasource import CSVDataSource
from fastapi_app.adapters.excel_datasource import ExcelDataSource
from fastapi_app.adapters.sql_datasource import SQLDataSource
from fastapi_app.agents.tools.datasource_manager import (
    get_all_datasource_ids,
    get_datasource_handler,
    set_datasource_handler,
)
from fastapi_app.modules.catalog.catalog_service import catalog_service

logger = logging.getLogger(__name__)


_SUPPORTED_EXTS = {
    ".csv": DataSourceType.CSV,
    ".xlsx": DataSourceType.EXCEL,
    ".xls": DataSourceType.EXCEL,
    ".sqlite": DataSourceType.SQLITE,
    ".db": DataSourceType.SQLITE,
}


def _allocate_ids(count: int) -> List[int]:
    existing = [int(x) for x in (get_all_datasource_ids() or []) if str(x).isdigit()]
    next_id = (max(existing) + 1) if existing else 1
    return list(range(next_id, next_id + max(0, int(count))))


def _is_under(base: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(base)
        return True
    except Exception:
        return False


def _existing_file_paths() -> set[str]:
    paths = set()
    for ds_id in get_all_datasource_ids():
        ds = get_datasource_handler(ds_id)
        if ds is None:
            continue
        meta = getattr(ds, "metadata", None)
        cfg = getattr(meta, "connection_config", None) or {}
        fp = cfg.get("file_path") or cfg.get("database_path")
        if fp:
            paths.add(str(fp))
    return paths


def _discover_files(root: Path, recursive: bool, max_files: int) -> List[Path]:
    pattern = "**/*" if recursive else "*"
    paths = []
    for p in root.glob(pattern):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in _SUPPORTED_EXTS:
            paths.append(p)
    paths.sort(key=lambda x: (x.suffix.lower(), x.name.lower()))
    return paths[: max(0, int(max_files or 0))]


def _create_datasource(ds_id: int, path: Path, ds_type: DataSourceType):
    name = path.stem
    if ds_type == DataSourceType.CSV:
        md = DataSourceMetadata(
            id=str(ds_id),
            name=name,
            type=DataSourceType.CSV,
            connection_config={"file_path": str(path), "has_header": True, "auto_detect": True, "table_name": name},
        )
        ds = CSVDataSource(md)
    elif ds_type == DataSourceType.EXCEL:
        md = DataSourceMetadata(
            id=str(ds_id),
            name=name,
            type=DataSourceType.EXCEL,
            connection_config={"file_path": str(path), "sheet_name": None, "header_row": 0, "skip_rows": 0},
        )
        ds = ExcelDataSource(md)
    elif ds_type == DataSourceType.SQLITE:
        md = DataSourceMetadata(
            id=str(ds_id),
            name=name,
            type=DataSourceType.SQLITE,
            # Open read-only by default for safety and to work on restricted filesystems.
            connection_config={"database_path": str(path), "readonly": True},
        )
        ds = SQLDataSource(md)
    else:
        raise ValueError(f"Unsupported datasource type: {ds_type}")
    ds.connect()
    return ds


@tool
def discover_and_register_datasources(
    directory: Optional[str] = None,
    recursive: bool = True,
    max_files: int = 25,
    bootstrap: bool = False,
) -> str:
    """Scan a directory for CSV/Excel/SQLite files and register them as datasources.

    Safety:
      - Only allows scanning under the backend working directory by default.
      - Caps max_files.

    Args:
        directory: Directory to scan. Default: `uploads/` under backend.
        recursive: Recursively scan subdirectories.
        max_files: Max files to register (cap to 100).
        bootstrap: Whether to run bootstrap indexing after registration.

    Returns:
        JSON with registered datasource ids and a catalog snapshot.
    """
    base_dir = Path(".").resolve()
    root = Path(directory).expanduser() if directory else Path("uploads")
    if not root.is_absolute():
        root = (base_dir / root).resolve()

    if not root.exists() or not root.is_dir():
        return json.dumps({"success": False, "error": f"Directory not found: {str(root)}"}, ensure_ascii=False)

    if not _is_under(base_dir, root):
        return json.dumps(
            {"success": False, "error": f"Refuse to scan outside workspace: {str(root)}"},
            ensure_ascii=False,
        )

    max_files_i = max(1, min(int(max_files or 1), 100))
    files = _discover_files(root, bool(recursive), max_files_i)
    if not files:
        return json.dumps(
            {"success": True, "registered": [], "skipped_existing": 0, "catalog": catalog_service.list_entries()},
            ensure_ascii=False,
        )

    existing_paths = _existing_file_paths()
    to_register: List[Tuple[Path, DataSourceType]] = []
    skipped_existing = 0
    for p in files:
        if str(p) in existing_paths:
            skipped_existing += 1
            continue
        ds_type = _SUPPORTED_EXTS.get(p.suffix.lower())
        if ds_type:
            to_register.append((p, ds_type))

    new_ids = _allocate_ids(len(to_register))
    registered: List[Dict] = []
    errors: List[Dict] = []

    for (p, ds_type), ds_id in zip(to_register, new_ids):
        try:
            ds = _create_datasource(ds_id, p, ds_type)
            set_datasource_handler(ds_id, ds, bootstrap=bool(bootstrap))
            catalog_service.upsert_from_datasource(ds_id, ds, origin="discovery", tags=["discovered"])
            registered.append(
                {"datasource_id": ds_id, "name": p.stem, "type": ds_type.code, "path": str(p)}
            )
        except Exception as e:
            logger.warning(f"Discovery registration failed for {p}: {e}")
            errors.append({"path": str(p), "error": str(e)})

    return json.dumps(
        {
            "success": True,
            "root": str(root),
            "registered": registered,
            "skipped_existing": skipped_existing,
            "errors": errors,
            "catalog": catalog_service.list_entries(),
        },
        ensure_ascii=False,
        indent=2,
        default=str,
    )


@tool
def get_catalog_snapshot() -> str:
    """Return the current in-memory catalog snapshot (safe, no secrets)."""
    return json.dumps({"entries": catalog_service.list_entries()}, ensure_ascii=False, indent=2, default=str)
