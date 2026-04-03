"""Catalog/Discovery tools.

These tools expose *registered* datasources to the agent so it can:
- Discover which datasources exist (and their types)
- See table names quickly before deciding single-source vs cross-source

The returned payload intentionally excludes sensitive connection_config fields.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from langchain_core.tools import tool

from .datasource_manager import get_all_datasource_ids, get_datasource_handler

logger = logging.getLogger(__name__)


@tool
def list_datasources(include_tables: bool = True, max_tables: int = 30) -> str:
    """List currently registered datasources and optional table names.

    Guidance for the agent:
      - Only call this when datasource selection is ambiguous or when the user asks.
      - Prefer using the routing-provided `available_datasources` / `selected_datasource_ids` when present.

    Args:
        include_tables: When True, also include (up to max_tables) table names per datasource.
        max_tables: Max table names returned per datasource (to keep prompts compact).

    Returns:
        JSON string: {"datasources":[...], "count": N}
    """
    try:
        max_tables_i = max(0, min(int(max_tables or 0), 200))
    except Exception:
        max_tables_i = 30

    datasources = []
    for ds_id in get_all_datasource_ids():
        ds = get_datasource_handler(ds_id)
        if ds is None:
            continue

        meta = None
        try:
            meta = ds.metadata.to_dict() if getattr(ds, "metadata", None) else None
        except Exception:
            meta = None

        table_names: Optional[list[str]] = None
        if include_tables and hasattr(ds, "get_tables"):
            try:
                tables = ds.get_tables() or []
                table_names = [getattr(t, "name", str(t)) for t in tables][:max_tables_i]
            except Exception as e:
                logger.debug(f"list_datasources get_tables failed for ds={ds_id}: {e}")
                table_names = None

        datasources.append(
            {
                "id": ds_id,
                "name": getattr(ds.metadata, "name", None) if getattr(ds, "metadata", None) else None,
                "type": getattr(getattr(ds.metadata, "type", None), "code", None) if getattr(ds, "metadata", None) else None,
                "metadata": meta,
                "tables": table_names,
            }
        )

    return json.dumps({"count": len(datasources), "datasources": datasources}, ensure_ascii=False, indent=2, default=str)
