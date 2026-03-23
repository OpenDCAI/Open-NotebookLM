# src/insight/singlesource_insight_agent/utils/data_source_reader.py
import json
import pandas as pd
import sqlite3
import logging
import os
import base64
from typing import Dict, Any, Optional, List, Union, Literal

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
from io import StringIO

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Type alias for background text data
BackgroundTextData = Dict[str, Any]  # {"type": "background_text", "content": str, "source": str, ...}

class DataSourceReader:
    """多数据源读取器"""
    
    @staticmethod
    def read_data(file_path: str, **kwargs) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
        """
        根据文件扩展名自动选择读取方法
        
        Args:
            file_path: 文件路径
            **kwargs: 各读取方法的额外参数
            
        Returns:
            Union[pd.DataFrame, Dict[str, pd.DataFrame]]: 
                - 通常返回 DataFrame
                - 当读取含有多个表的 SQLite 或多个 Sheet 的 Excel(预留)时，可能返回字典 {表名: DataFrame}
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        file_ext = os.path.splitext(file_path)[1].lower()
        
        try:
            if file_ext == '.csv':
                return DataSourceReader.read_csv(file_path, **kwargs)
            elif file_ext in ['.sqlite', '.db']:
                return DataSourceReader.read_sqlite(file_path, **kwargs)
            elif file_ext == '.txt':
                return DataSourceReader.read_txt(file_path, **kwargs)
            elif file_ext in ['.xlsx', '.xls']:
                return DataSourceReader.read_excel(file_path, **kwargs)
            elif file_ext == '.json':
                return DataSourceReader.read_json(file_path, **kwargs)
            elif file_ext in ['.jsonl', '.ndjson']:
                return DataSourceReader.read_jsonl(file_path, **kwargs)
            elif file_ext == '.parquet':
                return DataSourceReader.read_parquet(file_path, **kwargs)
            elif file_ext in ['.png', '.jpg', '.jpeg', '.bmp']:
                return DataSourceReader.read_image(file_path, **kwargs)
            else:
                raise ValueError(f"不支持的文件格式: {file_ext}")
        except Exception as e:
            logger.error(f"读取文件 {file_path} 时出错: {str(e)}")
            raise


    @staticmethod
    def read_csv(file_path: str, **kwargs) -> pd.DataFrame:
        """读取CSV文件"""
        # Filter out non-pandas parameters
        pandas_kwargs = {k: v for k, v in kwargs.items() 
                        if k not in ['as_background', 'max_chars_for_direct_use', 'model']}
        
        default_kwargs = {
            'encoding': 'utf-8',
            'sep': ',',
            'header': 0
        }
        default_kwargs.update(pandas_kwargs)
        return pd.read_csv(file_path, **default_kwargs)

    @staticmethod
    def read_sqlite(file_path: str, **kwargs) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
        """
        读取SQLite数据库
        
        Args:
            file_path: SQLite文件路径
            table_name: 指定表名（如果指定，返回单个 DataFrame）
            query: 自定义SQL查询（如果指定，返回单个 DataFrame）
            
        Returns:
            如果指定了 table_name 或 query，返回 pd.DataFrame
            否则，返回 Dict[str, pd.DataFrame]，包含数据库中所有表的数据
        """
        table_name = kwargs.get('table_name')
        query = kwargs.get('query')
        
        with sqlite3.connect(file_path) as conn:
            if query:
                # 情况1：执行自定义查询
                return pd.read_sql_query(query, conn)
            elif table_name:
                # 情况2：读取指定表
                return pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
            else:
                # 情况3：读取所有表
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = cursor.fetchall()
                
                if not tables:
                    raise ValueError("数据库中未找到任何表")
                
                all_tables_data = {}
                logger.info(f"未指定表名，开始读取数据库中所有表: {[t[0] for t in tables]}")
                
                for table in tables:
                    t_name = table[0]
                    try:
                        df = pd.read_sql_query(f"SELECT * FROM {t_name}", conn)
                        all_tables_data[t_name] = df
                        logger.info(f"已读取表: {t_name}, 行数: {len(df)}")
                    except Exception as e:
                        logger.warning(f"读取表 {t_name} 失败: {str(e)}")
                
                if not all_tables_data:
                    raise ValueError("未能成功读取任何表数据")
                    
                return all_tables_data


    @staticmethod
    def _summarize_text(content: str, model: str = "gpt-4o", max_summary_length: int = 1000) -> str:
        """
        使用 LLM 对长文本生成摘要
        
        Args:
            content: 原始文本内容
            model: 模型名称
            max_summary_length: 摘要最大长度
            
        Returns:
            文本摘要
        """
        client = DataSourceReader._get_openai_client()
        
        summarize_prompt = f"""
        请对以下文本内容进行信息提取和摘要，生成一个结构化的摘要。
        
        要求：
        1. 保留关键的数据信息、时间节点、数量指标等
        2. 识别并保留重要的业务背景、行业知识
        3. 摘要长度控制在 {max_summary_length} 字符以内
        4. 使用清晰的分点结构
        
        原始文本：
        {content[:8000]}  # 限制输入长度避免超过上下文限制
        
        请生成摘要：
        """
        
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": summarize_prompt}],
                max_tokens=max_summary_length,
                temperature=0.1
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"文本摘要生成失败: {str(e)}")
            # 降级处理：截取前后部分
            return content[:max_summary_length // 2] + "\n...[中间内容已省略]...\n" + content[-max_summary_length // 2:]

    @staticmethod
    def read_txt(file_path: str, **kwargs) -> Union[pd.DataFrame, BackgroundTextData]:
        """
        读取文本文件 - 支持结构化表格解析和背景信息提取
        
        Args:
            file_path: 文件路径
            as_background: 是否作为背景信息处理（默认 False，先尝试解析为表格）
            max_chars_for_direct_use: 直接使用的最大字符数阈值（默认 2000）
            model: 摘要生成使用的模型名称
            **kwargs: 传递给 pd.read_csv 的参数
            
        Returns:
            - 如果成功解析为表格: 返回 pd.DataFrame
            - 如果作为背景信息: 返回 {"type": "background_text", ...}
        """
        as_background = kwargs.pop('as_background', False)
        max_chars_for_direct_use = kwargs.pop('max_chars_for_direct_use', 2000)
        model = kwargs.pop('model', 'gpt-4o')
        
        # 首先读取文件内容
        encoding = kwargs.get('encoding', 'utf-8')
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                raw_content = f.read()
        except UnicodeDecodeError:
            # 尝试其他编码
            for enc in ['gbk', 'latin1', 'utf-16']:
                try:
                    with open(file_path, 'r', encoding=enc) as f:
                        raw_content = f.read()
                    encoding = enc
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise ValueError(f"无法使用常见编码读取文件: {file_path}")
        
        # 如果强制作为背景信息处理
        if as_background:
            return DataSourceReader._process_as_background_text(
                raw_content, file_path, max_chars_for_direct_use, model
            )
        
        # 尝试解析为结构化表格
        default_kwargs = {'encoding': encoding, 'sep': '\t'}
        default_kwargs.update(kwargs)
        separators = [default_kwargs.pop('sep', '\t'), ',', ';', '|']
        
        for sep in separators:
            try:
                df = pd.read_csv(file_path, sep=sep, encoding=encoding, **{k: v for k, v in default_kwargs.items() if k != 'encoding'})
                if len(df.columns) > 1:
                    logger.info(f"成功读取文本文件为表格，使用分隔符: {repr(sep)}")
                    return df
            except Exception:
                continue
        
        # 尝试固定宽度格式
        try:
            df = pd.read_fwf(file_path, encoding=encoding)
            if len(df.columns) > 1:
                logger.info(f"成功读取文本文件为固定宽度格式")
                return df
        except Exception:
            pass
        
        # 无法解析为表格，作为背景信息处理
        logger.info(f"无法将文本文件解析为表格，转为背景信息处理: {file_path}")
        return DataSourceReader._process_as_background_text(
            raw_content, file_path, max_chars_for_direct_use, model
        )

    @staticmethod
    def _process_as_background_text(
        content: str, 
        source_path: str, 
        max_chars_for_direct_use: int = 2000,
        model: str = "gpt-4o"
    ) -> BackgroundTextData:
        """
        将文本内容处理为背景信息格式
        
        Args:
            content: 文本内容
            source_path: 来源文件路径
            max_chars_for_direct_use: 直接使用的最大字符数阈值
            model: 摘要生成使用的模型
            
        Returns:
            背景信息字典
        """
        content = content.strip()
        
        if len(content) <= max_chars_for_direct_use:
            # 短文本直接使用
            logger.info(f"文本较短({len(content)}字符)，直接使用")
            return {
                "type": "background_text",
                "content": content,
                "source": source_path,
                "source_type": "text_file",
                "is_summarized": False,
                "original_length": len(content)
            }
        else:
            # 长文本需要摘要
            logger.info(f"文本较长({len(content)}字符)，进行摘要提取")
            summary = DataSourceReader._summarize_text(content, model)
            return {
                "type": "background_text",
                "content": summary,
                "source": source_path,
                "source_type": "text_file",
                "is_summarized": True,
                "original_length": len(content),
                "summary_length": len(summary)
            }


    @staticmethod
    def read_excel(file_path: str, **kwargs) -> pd.DataFrame:
        """读取Excel文件"""
        default_kwargs = {
            'sheet_name': 0,  # 第一个sheet
            'header': 0
        }
        default_kwargs.update(kwargs)
        return pd.read_excel(file_path, **default_kwargs)

    @staticmethod
    def _try_parse_json_string(val: Any) -> Any:
        """尝试解析字符串形式的 JSON，如果不是 JSON 则返回原值"""
        if isinstance(val, str) and val.strip().startswith(('{', '[')):
            try:
                return json.loads(val)
            except:
                return val
        return val

    @staticmethod
    def _try_parse_json_string(val: Any) -> Any:
        """尝试解析字符串形式的 JSON，如果不是 JSON 或解析失败则返回原值"""
        if isinstance(val, str):
            trimmed = val.strip()
            if trimmed.startswith(('{', '[')):
                try:
                    return json.loads(trimmed)
                except (json.JSONDecodeError, TypeError):
                    return val
        return val

    @staticmethod
    def _deep_flatten_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        """
        深度递归拉平逻辑：
        1. 探测字符串形式的 JSON 并解析。
        2. 使用 pd.json_normalize 展开嵌套字典。
        3. 循环直到没有可展开的内容。
        """
        if df.empty:
            return df

        while True:
            changed = False
            cols_to_process = df.columns.tolist()

            for col in cols_to_process:
                # 采样检查该列是否包含字典或 JSON 字符串
                non_na_values = df[col].dropna()
                if non_na_values.empty:
                    continue
                
                sample_val = non_na_values.iloc[0]
                
                # 场景 A: 该列是字符串，但内容是 JSON 结构
                if isinstance(sample_val, str) and sample_val.strip().startswith(('{', '[')):
                    parsed_series = df[col].apply(DataSourceReader._try_parse_json_string)
                    # 如果解析后确实变成了字典或列表，则更新并标记需要进一步处理
                    if not parsed_series.equals(df[col]):
                        df[col] = parsed_series
                        changed = True

                # 场景 B: 该列是字典对象（由场景A解析而来，或原本就是嵌套结构）
                if isinstance(sample_val, dict):
                    # 使用 json_normalize 展开
                    # errors='ignore' 确保即使某些行不是字典也能跳过
                    expanded = pd.json_normalize(df[col].tolist())
                    expanded.index = df.index
                    # 增加前缀以保留层级关系
                    expanded = expanded.add_prefix(f"{col}_")
                    
                    # 合并回原表并删除旧列
                    df = pd.concat([df.drop(columns=[col]), expanded], axis=1)
                    changed = True
                    break # 结构改变，跳出当前循环重新扫描所有列

            if not changed:
                break
        
        return df

    @staticmethod
    def read_json(file_path: str, **kwargs) -> Union[pd.DataFrame, Dict[str, pd.DataFrame]]:
        """读取标准 JSON，支持多表识别和深度递归拉平"""
        with open(file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)

        # 1. 多表识别 (类似 DB 逻辑)
        if isinstance(data, dict):
            list_keys = [k for k, v in data.items() if isinstance(v, list)]
            if len(list_keys) > 1:
                all_tables = {}
                for k in list_keys:
                    temp_df = pd.DataFrame(data[k])
                    all_tables[k] = DataSourceReader._deep_flatten_dataframe(temp_df)
                return all_tables
            
            # 单表情况
            if not isinstance(data, list):
                data = [data]

        # 2. 转换为初始 DataFrame 并执行深度拉平
        df = pd.DataFrame(data)
        return DataSourceReader._deep_flatten_dataframe(df)

    @staticmethod
    def read_jsonl(file_path: str, **kwargs) -> pd.DataFrame:
        """读取 JSONL 并执行深度递归拉平"""
        data = []
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    data.append(json.loads(line))
        
        if not data:
            raise ValueError("JSONL 文件为空")
            
        df = pd.DataFrame(data)
        return DataSourceReader._deep_flatten_dataframe(df)

        
    @staticmethod
    def _get_openai_client():
        """获取 OpenAI 客户端实例"""
        if OpenAI is None:
            raise ImportError("需要安装 'openai' 库才能使用图片读取功能: pip install openai")
            
        OPENAI_API_KEY = os.getenv("QDF_API_KEY")
        OPENAI_API_URL = os.getenv("QDF_API_URL")
        if not OPENAI_API_KEY:
            raise ValueError("未提供 OpenAI API Key，无法调用 LLM")
            
        return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_URL)

    @staticmethod
    def _encode_image(image_path: str) -> str:
        """将图片编码为 base64 字符串"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    @staticmethod
    def _classify_image(file_path: str, model: str = "gpt-4o") -> Literal["table", "chart", "other"]:
        """
        使用 LLM 判断图片类型
        
        Args:
            file_path: 图片路径
            model: 模型名称
            
        Returns:
            图片类型: "table" (表格), "chart" (可视化图表), "other" (其他)
        """
        client = DataSourceReader._get_openai_client()
        base64_image = DataSourceReader._encode_image(file_path)
        
        classify_prompt = """
        请仔细观察这张图片，判断它属于以下哪种类型：
        
        1. "table" - 图片包含结构化的数据表格（有行、列、表头的表格数据）
        2. "chart" - 图片是数据可视化图表（如折线图、柱状图、饼图、散点图、箱线图、热力图等）
        3. "other" - 图片既不是表格也不是数据图表（如普通照片、文档截图、示意图等）
        
        请只返回一个单词：table、chart 或 other，不要包含其他任何内容。
        """
        
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": classify_prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                            }
                        ]
                    }
                ],
                max_tokens=50,
                temperature=0
            )
            
            result = response.choices[0].message.content.strip().lower()
            
            # 确保返回值是有效的类型
            if "table" in result:
                return "table"
            elif "chart" in result:
                return "chart"
            else:
                return "other"
                
        except Exception as e:
            logger.warning(f"图片分类失败，默认返回 'other': {str(e)}")
            return "other"

    @staticmethod
    def _generate_chart_description(file_path: str, model: str = "gpt-4o") -> str:
        """
        为可视化图表生成自然语言描述
        
        Args:
            file_path: 图片路径
            model: 模型名称
            
        Returns:
            图表的自然语言描述
        """
        client = DataSourceReader._get_openai_client()
        base64_image = DataSourceReader._encode_image(file_path)
        
        description_prompt = """
        请详细描述这张数据可视化图表，包括：
        
        1. 图表类型（折线图、柱状图、饼图、散点图等）
        2. X轴和Y轴分别代表什么（如果适用）
        3. 图表展示的主要数据趋势或模式
        4. 关键的数据点或峰值（如果可见）
        5. 图表标题和图例信息（如果有）
        6. 任何值得注意的异常值或特殊模式
        
        请用清晰、结构化的方式描述，便于后续数据分析使用。
        """
        
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": description_prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                            }
                        ]
                    }
                ],
                max_tokens=1000,
                temperature=0.1
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"图表描述生成失败: {str(e)}")
            return f"[图表描述生成失败] 文件: {os.path.basename(file_path)}"

    @staticmethod
    def _extract_table_from_image(file_path: str, model: str = "gpt-4o") -> pd.DataFrame:
        """
        从图片中提取表格数据
        
        Args:
            file_path: 图片路径
            model: 模型名称
            
        Returns:
            pd.DataFrame: 提取的表格数据
        """
        client = DataSourceReader._get_openai_client()
        base64_image = DataSourceReader._encode_image(file_path)
        
        prompt = """
        你是一个数据提取助手。请查看这张图片，它包含一个或多个表格。
        请提取表格数据并将其转换为标准的 JSON 格式。
        
        要求：
        1. 返回结果必须是一个纯 JSON 数组（List of Objects），每个对象代表表格的一行。
        2. 对象的键（Key）应该是表头，值（Value）是单元格内容。
        3. 不要包含 Markdown 代码块标记（如 ```json），只返回纯文本 JSON 字符串。
        4. 如果图片中没有识别出表格，返回空数组 []。
        5. 能够智能处理合并单元格，将其拆分为对应的数据。
        """
        
        logger.info(f"正在调用 {model} 解析图片表格: {file_path}")
        
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user", 
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                            }
                        ]
                    }
                ],
                max_tokens=4096,
                temperature=0
            )
            
            content = response.choices[0].message.content.strip()
            
            # 清理可能存在的 Markdown 标记
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            
            content = content.strip()
            
            data = json.loads(content)
            
            if not data:
                logger.warning("模型未在图片中识别到数据")
                return pd.DataFrame()
                
            df = pd.DataFrame(data)
            logger.info(f"成功从图片提取数据，形状: {df.shape}")
            return df
            
        except Exception as e:
            logger.error(f"图片表格解析失败: {str(e)}")
            raise

    @staticmethod
    def read_image(file_path: str, **kwargs) -> Union[pd.DataFrame, BackgroundTextData]:
        """
        智能读取图片数据 - 支持表格提取和图表描述生成
        
        Args:
            file_path: 图片路径
            model: 模型名称 (默认 gpt-4o)
            force_type: 强制指定图片类型 ("table", "chart", "other")，跳过自动分类
            
        Returns:
            - 如果是表格图片: 返回 pd.DataFrame
            - 如果是图表/其他: 返回 {"type": "background_text", "content": str, "source": str, ...}
        """
        model = kwargs.get('model', 'gpt-4o')
        force_type = kwargs.get('force_type', None)
        
        # Phase 1: 分类图片类型
        if force_type:
            image_type = force_type
            logger.info(f"强制指定图片类型为: {image_type}")
        else:
            logger.info(f"正在分类图片类型: {file_path}")
            image_type = DataSourceReader._classify_image(file_path, model)
            logger.info(f"图片分类结果: {image_type}")
        
        # Phase 2: 根据类型处理
        if image_type == "table":
            return DataSourceReader._extract_table_from_image(file_path, model)
        elif image_type == "chart":
            description = DataSourceReader._generate_chart_description(file_path, model)
            return {
                "type": "background_text",
                "content": description,
                "source": file_path,
                "source_type": "chart_image",
                "is_summarized": False
            }
        else:
            # 对于其他类型的图片，生成简单描述
            return {
                "type": "background_text",
                "content": f"[非结构化图片] 文件: {os.path.basename(file_path)}",
                "source": file_path,
                "source_type": "other_image",
                "is_summarized": False
            }

    @staticmethod
    def get_file_info(file_path: str) -> Dict[str, Any]:
        """获取文件信息"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        file_ext = os.path.splitext(file_path)[1].lower()
        file_size = os.path.getsize(file_path)
        
        info = {
            'file_path': file_path,
            'file_extension': file_ext,
            'file_size': file_size,
            'file_size_mb': round(file_size / (1024 * 1024), 2),
            'exists': True
        }
        
        if file_ext in ['.sqlite', '.db']:
            info.update(DataSourceReader._get_sqlite_info(file_path))
        elif file_ext == '.csv':
            info.update(DataSourceReader._get_csv_info(file_path))
        elif file_ext in ['.xlsx', '.xls']:
            info.update(DataSourceReader._get_excel_info(file_path))
        # 这里可以继续扩展 JSONL 和 Image 的 info 获取逻辑
            
        return info

    @staticmethod
    def _get_sqlite_info(file_path: str) -> Dict[str, Any]:
        """获取SQLite数据库信息"""
        try:
            with sqlite3.connect(file_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = [table[0] for table in cursor.fetchall()]
                
                table_info = {}
                for table in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    row_count = cursor.fetchone()[0]
                    
                    cursor.execute(f"PRAGMA table_info({table})")
                    columns_info = cursor.fetchall()
                    columns = [col[1] for col in columns_info]
                    
                    table_info[table] = {
                        'row_count': row_count,
                        'columns': columns,
                        # 'columns_detail': columns_info # 详细信息可能过大，视需求保留
                    }
                
                return {
                    'database_tables': tables,
                    'table_info': table_info,
                    'total_tables': len(tables)
                }
        except Exception as e:
            logger.warning(f"获取SQLite数据库信息失败: {str(e)}")
            return {'error': str(e)}

    @staticmethod
    def _get_csv_info(file_path: str) -> Dict[str, Any]:
        """获取CSV文件信息"""
        try:
            # 只读取前几行来获取信息，避免读取整个大文件
            df_sample = pd.read_csv(file_path, nrows=5)
            full_df = pd.read_csv(file_path, nrows=0)  # 只读取列名
            return {
                'columns': full_df.columns.tolist(),
                'dtypes': full_df.dtypes.astype(str).to_dict(),
                'sample_data': df_sample.to_dict('records'),
                'sample_shape': df_sample.shape
            }
        except Exception as e:
            logger.warning(f"获取CSV文件信息失败: {str(e)}")
            return {'error': str(e)}

    @staticmethod
    def _get_excel_info(file_path: str) -> Dict[str, Any]:
        """获取Excel文件信息"""
        try:
            excel_file = pd.ExcelFile(file_path)
            sheets = excel_file.sheet_names
            
            sheet_info = {}
            for sheet in sheets[:5]:  # 只检查前5个sheet，避免大文件
                df_sample = pd.read_excel(file_path, sheet_name=sheet, nrows=5)
                sheet_info[sheet] = {
                    'columns': df_sample.columns.tolist(),
                    'sample_shape': df_sample.shape
                }
            
            return {
                'sheets': sheets,
                'sheet_info': sheet_info,
                'total_sheets': len(sheets)
            }
        except Exception as e:
            logger.warning(f"获取Excel文件信息失败: {str(e)}")
            return {'error': str(e)}

    @staticmethod
    def validate_data_source(file_path: str, **kwargs) -> Dict[str, Any]:
        """
        验证数据源是否可读
        
        Returns:
            Dict[str, Any]: 验证结果
        """
        try:
            # 尝试读取少量数据
            df = DataSourceReader.read_data(file_path, **kwargs)
            info = DataSourceReader.get_file_info(file_path)
            
            return {
                'valid': True,
                'message': '数据源验证成功',
                'shape': df.shape,
                'columns': df.columns.tolist(),
                'file_info': info
            }
        except Exception as e:
            return {
                'valid': False,
                'message': f'数据源验证失败: {str(e)}',
                'error': str(e)
            }

    @staticmethod
    def get_supported_formats() -> List[Dict[str, str]]:
        """获取支持的文件格式列表"""
        return [
            {'format': 'CSV', 'extensions': ['.csv'], 'description': '逗号分隔值文件'},
            {'format': 'SQLite', 'extensions': ['.sqlite', '.db'], 'description': 'SQLite数据库文件(支持多表)'},
            {'format': 'Excel', 'extensions': ['.xlsx', '.xls'], 'description': 'Excel电子表格'},
            {'format': 'JSON', 'extensions': ['.json'], 'description': 'JSON数据文件'},
            {'format': 'JSONL', 'extensions': ['.jsonl', '.ndjson'], 'description': '换行符分隔的JSON文件'},
            {'format': 'Text', 'extensions': ['.txt'], 'description': '文本文件'},
            {'format': 'Parquet', 'extensions': ['.parquet'], 'description': 'Parquet列式存储文件'},
            {'format': 'Image', 'extensions': ['.png', '.jpg', '.jpeg'], 'description': '图片表格(AI提取)'}
        ]