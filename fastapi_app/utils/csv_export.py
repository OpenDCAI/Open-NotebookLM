"""
CSV导出工具模块

核心功能（参考SQLBot的设计理念，并做改进）：
1. 流式生成 - 分块写入，避免内存溢出
2. 编码处理 - UTF-8 with BOM，提升Excel兼容性
3. 数据格式化 - 大数值、日期时间、空值的统一处理
4. 配置化 - 分隔符、引号、编码等可配置
5. 类型安全 - 严格的类型转换和错误处理
6. 性能优化 - 针对大数据量场景优化

参考SQLBot实现：
- apps/chat/task/llm.py: DataFormat.convert_object_array_for_pandas
- apps/chat/api/chat.py: get_chat_chart_data
- common/utils/data_format.py: DataFormat类
"""

import io
import csv
import logging
import urllib.parse
from typing import List, Dict, Any, Optional, Iterator, Union, Callable
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from dataclasses import dataclass, field
import math

logger = logging.getLogger(__name__)


# ==================== 配置定义 ====================

class CSVEncoding(str, Enum):
    """CSV编码枚举"""
    UTF8 = "utf-8"
    UTF8_BOM = "utf-8-sig"  # UTF-8 with BOM，Excel友好
    GBK = "gbk"             # 中文Windows常用
    GB2312 = "gb2312"
    LATIN1 = "latin-1"


class CSVDelimiter(str, Enum):
    """CSV分隔符枚举"""
    COMMA = ","
    TAB = "\t"
    SEMICOLON = ";"
    PIPE = "|"


class NullHandling(str, Enum):
    """空值处理方式"""
    EMPTY = "empty"     # 空字符串
    NULL_TEXT = "null"  # 字符串 "NULL"
    NA = "na"           # 字符串 "N/A"
    NONE = "none"       # 字符串 "None"


class DateTimeFormat(str, Enum):
    """日期时间格式"""
    ISO8601 = "%Y-%m-%dT%H:%M:%S"
    ISO8601_DATE = "%Y-%m-%d"
    COMPACT = "%Y%m%d%H%M%S"
    COMPACT_DATE = "%Y%m%d"
    FRIENDLY = "%Y-%m-%d %H:%M:%S"
    FRIENDLY_DATE = "%Y-%m-%d"
    EXCEL = "%Y/%m/%d %H:%M:%S"


@dataclass
class CSVExportConfig:
    """
    CSV导出配置

    提供完整的配置选项，支持各种导出场景
    """
    # 基础配置
    encoding: CSVEncoding = CSVEncoding.UTF8_BOM
    delimiter: CSVDelimiter = CSVDelimiter.COMMA
    quotechar: str = '"'
    quoting: int = csv.QUOTE_MINIMAL  # QUOTE_ALL, QUOTE_MINIMAL, QUOTE_NONNUMERIC, QUOTE_NONE

    # 数据处理
    null_handling: NullHandling = NullHandling.EMPTY
    datetime_format: DateTimeFormat = DateTimeFormat.FRIENDLY
    date_format: DateTimeFormat = DateTimeFormat.FRIENDLY_DATE

    # 大数值处理（避免Excel科学计数法和精度丢失）
    stringify_large_integers: bool = True  # 大整数转字符串
    large_integer_threshold: int = 10**15  # 超过此值转字符串
    decimal_places: Optional[int] = None   # 小数位数限制（None表示不限制）

    # 流式配置
    chunk_size: int = 10000  # 每块行数
    buffer_size: int = 65536  # 缓冲区大小（字节）

    # 列配置
    include_header: bool = True
    column_mapping: Optional[Dict[str, str]] = None  # 列名映射 {原名: 显示名}
    column_order: Optional[List[str]] = None  # 列顺序
    exclude_columns: Optional[List[str]] = None  # 排除的列

    # 限制
    max_rows: int = 100000  # 最大导出行数

    # 回调
    row_transformer: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None  # 行转换函数

    def __post_init__(self):
        """初始化后处理"""
        if self.column_mapping is None:
            self.column_mapping = {}
        if self.exclude_columns is None:
            self.exclude_columns = []


@dataclass
class CSVExportResult:
    """
    CSV导出结果
    """
    success: bool
    row_count: int = 0
    column_count: int = 0
    file_size_bytes: int = 0
    execution_time_ms: float = 0.0
    error_message: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    # 元数据
    encoding: str = ""
    delimiter: str = ""
    columns: List[str] = field(default_factory=list)


# ==================== 数据格式化器 ====================

class DataFormatter:
    """
    数据格式化器

    参考SQLBot的DataFormat类，但功能更完善
    """

    def __init__(self, config: CSVExportConfig):
        self.config = config

    def format_value(self, value: Any, column_name: str = "") -> str:
        """
        格式化单个值

        Args:
            value: 原始值
            column_name: 列名（用于特殊处理）

        Returns:
            格式化后的字符串
        """
        # None / NaN 处理
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return self._format_null()

        # 布尔值
        if isinstance(value, bool):
            return "true" if value else "false"

        # 日期时间
        if isinstance(value, datetime):
            return self._format_datetime(value)
        if isinstance(value, date):
            return self._format_date(value)

        # 大整数处理（避免Excel科学计数法）
        if isinstance(value, int):
            return self._format_integer(value)

        # 浮点数处理
        if isinstance(value, float):
            return self._format_float(value)

        # Decimal处理
        if isinstance(value, Decimal):
            return self._format_decimal(value)

        # 列表/字典转JSON字符串
        if isinstance(value, (list, dict)):
            import json
            return json.dumps(value, ensure_ascii=False)

        # 字节转字符串
        if isinstance(value, bytes):
            try:
                return value.decode('utf-8')
            except UnicodeDecodeError:
                return value.hex()

        # 字符串去除嵌入的BOM
        if isinstance(value, str):
            if value.startswith('\ufeff'):
                value = value.lstrip('\ufeff')
            return value

        # 默认转字符串
        return str(value)

    def _format_null(self) -> str:
        """格式化空值"""
        mapping = {
            NullHandling.EMPTY: "",
            NullHandling.NULL_TEXT: "NULL",
            NullHandling.NA: "N/A",
            NullHandling.NONE: "None",
        }
        return mapping.get(self.config.null_handling, "")

    def _format_datetime(self, value: datetime) -> str:
        """格式化日期时间"""
        try:
            return value.strftime(self.config.datetime_format.value)
        except Exception:
            return str(value)

    def _format_date(self, value: date) -> str:
        """格式化日期"""
        try:
            return value.strftime(self.config.date_format.value)
        except Exception:
            return str(value)

    def _format_integer(self, value: int) -> str:
        """
        格式化整数

        大整数转字符串，避免Excel显示为科学计数法
        """
        if self.config.stringify_large_integers:
            if abs(value) >= self.config.large_integer_threshold:
                return str(value)
        return str(value)

    def _format_float(self, value: float) -> str:
        """格式化浮点数"""
        # 检查是否为整数形式的浮点数（如 1.0）
        if value.is_integer():
            return self._format_integer(int(value))

        # 限制小数位数
        if self.config.decimal_places is not None:
            return f"{value:.{self.config.decimal_places}f}"

        # 避免科学计数法
        if abs(value) >= self.config.large_integer_threshold:
            return f"{value:.0f}"

        return str(value)

    def _format_decimal(self, value: Decimal) -> str:
        """格式化Decimal"""
        if self.config.decimal_places is not None:
            return f"{float(value):.{self.config.decimal_places}f}"
        return str(value)


# ==================== CSV生成器 ====================

class CSVGenerator:
    """
    CSV生成器

    支持流式生成，适合大数据量导出
    """

    def __init__(self, config: Optional[CSVExportConfig] = None):
        self.config = config or CSVExportConfig()
        self.formatter = DataFormatter(self.config)
        self._warnings: List[str] = []

    def generate(
        self,
        data: List[Dict[str, Any]],
        columns: Optional[List[str]] = None,
    ) -> Iterator[str]:
        """
        流式生成CSV内容

        Args:
            data: 数据列表（字典列表）
            columns: 列名列表（如果为None则从数据推断）

        Yields:
            CSV文本块
        """
        if not data:
            yield ""
            return

        # 确定列名
        columns = self._determine_columns(data, columns)
        if not columns:
            yield ""
            return

        # 应用行数限制
        if len(data) > self.config.max_rows:
            self._warnings.append(f"数据量超过限制，仅导出前{self.config.max_rows}行")
            data = data[:self.config.max_rows]

        # 创建缓冲区
        buffer = io.StringIO()
        writer = csv.writer(
            buffer,
            delimiter=self.config.delimiter.value,
            quotechar=self.config.quotechar,
            quoting=self.config.quoting,
        )

        # 写入BOM（如果是UTF-8-BOM编码）
        if self.config.encoding == CSVEncoding.UTF8_BOM:
            yield '\ufeff'

        # 写入表头
        if self.config.include_header:
            header_row = self._build_header_row(columns)
            writer.writerow(header_row)
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

        # 分块写入数据
        for i in range(0, len(data), self.config.chunk_size):
            chunk = data[i:i + self.config.chunk_size]

            for row_dict in chunk:
                # 应用行转换器
                if self.config.row_transformer:
                    try:
                        row_dict = self.config.row_transformer(row_dict)
                    except Exception as e:
                        logger.warning(f"Row transformer error: {e}")

                # 构建行
                row = self._build_data_row(row_dict, columns)
                writer.writerow(row)

            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    def generate_bytes(
        self,
        data: List[Dict[str, Any]],
        columns: Optional[List[str]] = None,
    ) -> Iterator[bytes]:
        """
        流式生成CSV字节流

        Args:
            data: 数据列表
            columns: 列名列表

        Yields:
            CSV字节块
        """
        encoding = self.config.encoding.value

        for chunk in self.generate(data, columns):
            yield chunk.encode(encoding)

    def generate_full(
        self,
        data: List[Dict[str, Any]],
        columns: Optional[List[str]] = None,
    ) -> str:
        """
        一次性生成完整CSV内容

        注意：大数据量时可能消耗大量内存

        Args:
            data: 数据列表
            columns: 列名列表

        Returns:
            完整的CSV字符串
        """
        return "".join(self.generate(data, columns))

    def get_warnings(self) -> List[str]:
        """获取警告信息"""
        return self._warnings.copy()

    def _determine_columns(
        self,
        data: List[Dict[str, Any]],
        columns: Optional[List[str]]
    ) -> List[str]:
        """
        确定最终的列列表
        """
        # 清洗工具
        def _clean(col: str) -> str:
            return col.lstrip('\ufeff') if isinstance(col, str) else col

        # 如果指定了列顺序，使用指定的
        if self.config.column_order:
            return [ _clean(c) for c in self.config.column_order if _clean(c) not in self.config.exclude_columns ]

        # 如果传入了columns参数
        if columns:
            return [ _clean(c) for c in columns if _clean(c) not in self.config.exclude_columns ]

        # 从数据推断（保持第一行的键顺序）
        if data:
            inferred = [ _clean(k) for k in list(data[0].keys()) ]
            return [c for c in inferred if c not in self.config.exclude_columns]

        return []

    def _build_header_row(self, columns: List[str]) -> List[str]:
        """构建表头行"""
        # 清洗列名映射中的BOM
        cleaned_mapping = { (k.lstrip('\ufeff') if isinstance(k, str) else k): v for k, v in (self.config.column_mapping or {}).items() }
        header = []
        for col in columns:
            base_col = col.lstrip('\ufeff') if isinstance(col, str) else col
            display_name = cleaned_mapping.get(base_col, base_col)
            header.append(display_name)
        return header

    def _build_data_row(self, row_dict: Dict[str, Any], columns: List[str]) -> List[str]:
        """构建数据行"""
        row = []
        for col in columns:
            value = row_dict.get(col)
            if value is None:
                # 支持带BOM的键名
                if isinstance(col, str):
                    value = row_dict.get('\ufeff' + col)
            formatted = self.formatter.format_value(value, col)
            row.append(formatted)
        return row


# ==================== 便捷函数 ====================

def export_to_csv(
    data: List[Dict[str, Any]],
    columns: Optional[List[str]] = None,
    config: Optional[CSVExportConfig] = None,
) -> CSVExportResult:
    """
    导出数据为CSV字符串（便捷函数）

    Args:
        data: 数据列表
        columns: 列名列表
        config: 导出配置

    Returns:
        CSVExportResult: 包含CSV内容和元数据
    """
    import time
    start_time = time.time()

    try:
        config = config or CSVExportConfig()
        generator = CSVGenerator(config)

        csv_content = generator.generate_full(data, columns)

        execution_time = (time.time() - start_time) * 1000

        # 确定最终使用的列
        final_columns = generator._determine_columns(data, columns)

        return CSVExportResult(
            success=True,
            row_count=min(len(data), config.max_rows),
            column_count=len(final_columns),
            file_size_bytes=len(csv_content.encode(config.encoding.value)),
            execution_time_ms=execution_time,
            encoding=config.encoding.value,
            delimiter=config.delimiter.value,
            columns=final_columns,
            warnings=generator.get_warnings(),
        )

    except Exception as e:
        execution_time = (time.time() - start_time) * 1000
        logger.error(f"CSV export failed: {e}")

        return CSVExportResult(
            success=False,
            error_message=str(e),
            execution_time_ms=execution_time,
        )


def create_csv_streaming_response(
    data: List[Dict[str, Any]],
    columns: Optional[List[str]] = None,
    filename: str = "export.csv",
    config: Optional[CSVExportConfig] = None,
) -> tuple:
    """
    创建流式CSV响应的生成器和headers

    用于FastAPI StreamingResponse

    Args:
        data: 数据列表
        columns: 列名列表
        filename: 文件名
        config: 导出配置

    Returns:
        (generator, headers, media_type): 生成器、响应头、媒体类型
    """
    config = config or CSVExportConfig()
    generator = CSVGenerator(config)

    # 生成器
    content_generator = generator.generate_bytes(data, columns)

    # 响应头
    delimiter_name_map = {
        CSVDelimiter.COMMA: "comma",
        CSVDelimiter.TAB: "tab",
        CSVDelimiter.SEMICOLON: "semicolon",
        CSVDelimiter.PIPE: "pipe",
    }
    headers = {
        # Starlette 会用 latin-1 编码响应头，需保证 ASCII 安全
        # 构造 ASCII fallback + RFC 5987 的 UTF-8 扩展参数
        # 参考：https://datatracker.ietf.org/doc/html/rfc5987
        # 示例：attachment; filename="export.csv"; filename*=UTF-8''%E4%B8%AD%E6%96%87.csv
        "Content-Disposition": (
            lambda fn: (
                (lambda ascii_fn, utf8_fn: f'attachment; filename="{ascii_fn}"; filename*=UTF-8\'\'{utf8_fn}')(
                    "".join(c for c in fn if c.isascii() and (c.isalnum() or c in (' ', '-', '_', '.'))) or "export.csv",
                    urllib.parse.quote(fn)
                )
            )
        )(filename),
        "X-Total-Rows": str(min(len(data), config.max_rows)),
        "X-Encoding": config.encoding.value,
        "X-Delimiter": delimiter_name_map.get(config.delimiter, "comma"),
    }

    # 媒体类型
    media_type = f"text/csv; charset={config.encoding.value}"

    return content_generator, headers, media_type


# ==================== 数据转换辅助 ====================

def convert_query_result_to_export_data(
    query_result: Dict[str, Any],
    column_mapping: Optional[Dict[str, str]] = None,
) -> tuple:
    """
    将查询结果转换为导出数据格式

    Args:
        query_result: 查询结果（包含data和columns字段）
        column_mapping: 列名映射

    Returns:
        (data, columns, config): 数据、列名、建议的配置
    """
    data = query_result.get("data", [])
    columns = query_result.get("columns", [])

    if not data and not columns:
        raise ValueError("查询结果为空")

    # 如果columns为空，从数据推断
    if not columns and data:
        columns = list(data[0].keys())

    # 创建配置
    config = CSVExportConfig()
    if column_mapping:
        config.column_mapping = column_mapping

    return data, columns, config


def merge_chart_columns_mapping(
    chart_config: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """
    从图表配置中提取列名映射

    参考SQLBot的chart columns格式

    Args:
        chart_config: 图表配置

    Returns:
        列名映射字典
    """
    mapping = {}

    if not chart_config:
        return mapping

    # 处理columns数组
    columns = chart_config.get("columns", [])
    for col in columns:
        if isinstance(col, dict):
            value = col.get("value")
            name = col.get("name")
            if value and name and value != name:
                mapping[value] = name

    # 处理axis配置
    axis = chart_config.get("axis", {})
    for axis_type in ["x", "y", "series"]:
        axis_config = axis.get(axis_type, {})
        if isinstance(axis_config, dict):
            value = axis_config.get("value")
            name = axis_config.get("name")
            if value and name and value != name:
                mapping[value] = name

    return mapping
