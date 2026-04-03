"""
Excel (.xlsx) export utility.

Phase 4.2: Uses pandas DataFrame.to_excel for xlsx generation.
Falls back to CSV if pandas Excel backend is unavailable.
"""
import io
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ExcelExportConfig:
    """Excel export configuration."""
    sheet_name: str = "Sheet1"
    max_rows: int = 100000
    include_header: bool = True
    column_mapping: Optional[Dict[str, str]] = None
    freeze_panes: bool = True  # Freeze header row


@dataclass
class ExcelExportResult:
    success: bool
    row_count: int = 0
    column_count: int = 0
    file_size_bytes: int = 0
    error_message: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


def export_to_excel(
    data: List[Dict[str, Any]],
    columns: Optional[List[str]] = None,
    config: Optional[ExcelExportConfig] = None,
) -> tuple:
    """
    Export data to Excel bytes.

    Returns:
        (bytes_content, ExcelExportResult)
    """
    import pandas as pd

    config = config or ExcelExportConfig()
    warnings = []

    if not data:
        return b"", ExcelExportResult(
            success=False, error_message="No data to export"
        )

    # Truncate if too many rows
    if len(data) > config.max_rows:
        warnings.append(f"数据量超过限制，仅导出前{config.max_rows}行")
        data = data[:config.max_rows]

    # Build DataFrame
    df = pd.DataFrame(data)

    # Apply column order if specified
    if columns:
        available = [c for c in columns if c in df.columns]
        df = df[available]

    # Apply column name mapping
    if config.column_mapping:
        df = df.rename(columns=config.column_mapping)

    # Write to bytes buffer
    buffer = io.BytesIO()
    try:
        # Try openpyxl first, fall back to xlsxwriter, then fail gracefully
        engine = _detect_excel_engine()
        if engine is None:
            return b"", ExcelExportResult(
                success=False,
                error_message="No Excel engine available. Install openpyxl: pip install openpyxl",
                warnings=warnings,
            )

        with pd.ExcelWriter(buffer, engine=engine) as writer:
            df.to_excel(
                writer,
                sheet_name=config.sheet_name,
                index=False,
                header=config.include_header,
            )

            # Freeze header pane if using openpyxl
            if config.freeze_panes and engine == "openpyxl":
                ws = writer.sheets[config.sheet_name]
                ws.freeze_panes = "A2"

        content = buffer.getvalue()

        return content, ExcelExportResult(
            success=True,
            row_count=len(df),
            column_count=len(df.columns),
            file_size_bytes=len(content),
            warnings=warnings,
        )

    except Exception as e:
        logger.error(f"Excel export failed: {e}")
        return b"", ExcelExportResult(
            success=False,
            error_message=str(e),
            warnings=warnings,
        )


def _detect_excel_engine() -> Optional[str]:
    """Detect available pandas Excel writer engine."""
    try:
        import openpyxl  # noqa: F401
        return "openpyxl"
    except ImportError:
        pass
    try:
        import xlsxwriter  # noqa: F401
        return "xlsxwriter"
    except ImportError:
        pass
    return None


def is_excel_export_available() -> bool:
    """Check if Excel export is available."""
    return _detect_excel_engine() is not None
