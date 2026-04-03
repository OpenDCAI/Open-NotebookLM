"""
数据库模型定义
"""
from typing import Optional, Union, List
from datetime import datetime
from sqlmodel import SQLModel, Field, Column, Text
import json


class Datasource(SQLModel, table=True):
    """数据源表"""
    __tablename__ = "datasources"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    type: str  # csv, postgresql, mysql, etc
    config: str = Field(default="{}")  # JSON字符串存储配置
    description: Optional[str] = None
    file_path: Optional[str] = None  # CSV文件路径
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def get_config(self) -> dict:
        """获取配置字典"""
        return json.loads(self.config) if self.config else {}

    def set_config(self, config: dict):
        """设置配置"""
        self.config = json.dumps(config)


class Chat(SQLModel, table=True):
    """对话表"""
    __tablename__ = "chats"

    id: Optional[int] = Field(default=None, primary_key=True)
    datasource_id: int = Field(foreign_key="datasources.id")
    title: str = Field(default="新对话")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChatRecord(SQLModel, table=True):
    """对话记录表"""
    __tablename__ = "chat_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int = Field(foreign_key="chats.id")

    # 用户问题
    question: str = Field(sa_column=Column(Text))

    # LLM思考过程
    thinking: Optional[str] = Field(default=None, sa_column=Column(Text))

    # SQL (如果有)
    sql: Optional[str] = Field(default=None, sa_column=Column(Text))

    # 执行结果
    result_data: Optional[str] = Field(default=None, sa_column=Column(Text))  # JSON
    result_summary: Optional[str] = Field(default=None, sa_column=Column(Text))

    # 图表配置 (用于可视化)
    chart_config: Optional[str] = Field(default=None, sa_column=Column(Text))  # JSON

    # 状态
    status: str = Field(default="pending")  # pending, processing, completed, error
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text))

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None  # 执行耗时(毫秒)

    def get_result_data(self) -> Optional[Union[dict, list]]:
        """获取结果数据 (dict or list, parsed from JSON string)"""
        import json
        return json.loads(self.result_data) if self.result_data else None

    def set_result_data(self, data: Union[dict, list]):
        """设置结果数据"""
        import json
        self.result_data = json.dumps(data, ensure_ascii=False, default=str)

    def get_chart_config(self) -> Optional[dict]:
        """获取图表配置"""
        import json
        return json.loads(self.chart_config) if self.chart_config else None

    def set_chart_config(self, config: dict):
        """设置图表配置"""
        import json
        self.chart_config = json.dumps(config)
