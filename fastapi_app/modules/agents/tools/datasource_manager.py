"""
Datasource cache and lazy restoration helpers.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from sqlmodel import Session

from fastapi_app.adapters.csv_datasource import CSVDataSource
from fastapi_app.core.database import engine
from fastapi_app.core.datasource_interface import DataSourceInterface, DataSourceMetadata, DataSourceType
from fastapi_app.models.chat_models import Datasource

logger = logging.getLogger(__name__)

# Cache: datasource_id -> (handler, timestamp)
_datasource_cache: Dict[int, Tuple[DataSourceInterface, float]] = {}
_CACHE_TTL = 1800  # 30 minutes


def _restore_datasource_handler(datasource_id: int) -> Optional[DataSourceInterface]:
    with Session(engine) as session:
        record = session.get(Datasource, datasource_id)

    if not record:
        return None

    ds_type = (record.type or "").lower().strip()
    if ds_type != "csv" or not record.file_path:
        logger.warning("Datasource %s cannot be lazily restored yet (type=%s)", datasource_id, ds_type)
        return None

    file_path = Path(record.file_path)
    if not file_path.exists():
        logger.warning("Datasource %s file is missing: %s", datasource_id, file_path)
        return None

    metadata = DataSourceMetadata(
        id=str(record.id),
        name=record.name,
        type=DataSourceType.CSV,
        connection_config={
            "file_path": str(file_path),
            "has_header": True,
            "auto_detect": True,
        },
    )
    handler = CSVDataSource(metadata)
    handler.connect()
    _datasource_cache[datasource_id] = (handler, time.time())
    logger.info("Restored datasource handler from database: id=%s", datasource_id)
    return handler


def set_datasource_handler(datasource_id: int, handler: DataSourceInterface, *, bootstrap: bool = True):
    _datasource_cache[datasource_id] = (handler, time.time())
    logger.info("Registered datasource handler: id=%s", datasource_id)

    auto_bootstrap = os.getenv("SQLBOT_AUTO_BOOTSTRAP", "1").strip().lower() not in {"0", "false", "no", "off"}
    if bootstrap and auto_bootstrap:
        try:
            from fastapi_app.modules.data_pipeline.bootstrap import bootstrap_datasource

            bootstrap_datasource(datasource_id, handler)
        except Exception as exc:
            logger.warning("Datasource bootstrap skipped/failed for id=%s: %s", datasource_id, exc)


def get_datasource_handler(datasource_id: int) -> Optional[DataSourceInterface]:
    cached = _datasource_cache.get(datasource_id)
    if cached is not None:
        handler, timestamp = cached
        # Check TTL
        if time.time() - timestamp < _CACHE_TTL:
            return handler
        else:
            # Expired, remove and reconnect
            logger.info("Datasource cache expired for id=%s, reconnecting", datasource_id)
            try:
                handler.disconnect()
            except Exception:
                pass
            del _datasource_cache[datasource_id]

    return _restore_datasource_handler(datasource_id)


def clear_datasource_cache():
    for ds_id, ds in list(_datasource_cache.items()):
        try:
            ds.disconnect()
            logger.info("Disconnected datasource: id=%s", ds_id)
        except Exception as exc:
            logger.warning("Error disconnecting datasource %s: %s", ds_id, exc)
    _datasource_cache.clear()


def get_all_datasource_ids() -> list:
    return list(_datasource_cache.keys())


def has_datasource(datasource_id: int) -> bool:
    return datasource_id in _datasource_cache


class DataSourceManager:
    def set_datasource_handler(self, datasource_id: int, handler: DataSourceInterface):
        return set_datasource_handler(datasource_id, handler)

    def get_datasource_handler(self, datasource_id: int) -> Optional[DataSourceInterface]:
        return get_datasource_handler(datasource_id)

    def clear_datasource_cache(self):
        return clear_datasource_cache()

    def get_all_datasource_ids(self) -> list:
        return get_all_datasource_ids()

    def has_datasource(self, datasource_id: int) -> bool:
        return has_datasource(datasource_id)


datasource_manager = DataSourceManager()
