"""
Agent日志模型 - 参考SQLBot的ChatLog设计

SQLBot日志系统参考 (backend/apps/chat/curd/chat.py):
1. 记录每个LLM调用的完整日志
2. Token使用统计
3. 执行时间追踪
4. 思考过程记录（支持o1/o3模型）

使用方式:
    from fastapi_app.models.agent_log import AgentLog
    from fastapi_app.services.log_service import AgentLogService
    
    # 开始日志
    log = AgentLogService.start_log(session, chat_id, "generate_sql", messages)
    
    # 结束日志
    AgentLogService.end_log(session, log, messages, thinking, token_usage)
"""
from datetime import datetime
from typing import Dict, Any, List, Optional
from enum import Enum
from sqlalchemy import Column, Integer, String, DateTime, JSON, Float, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class OperationTypeEnum(str, Enum):
    """操作类型枚举 - 参考SQLBot的OperationEnum"""
    
    GENERATE_SQL = "generate_sql"           # SQL生成
    EXECUTE_SQL = "execute_sql"             # SQL执行
    VALIDATE_SQL = "validate_sql"           # SQL验证
    RETRIEVE_SCHEMA = "retrieve_schema"     # 获取Schema
    RETRIEVE_KNOWLEDGE = "retrieve_knowledge"  # RAG检索
    EXPORT_DATA = "export_data"             # 数据导出
    GENERATE_CHART = "generate_chart"       # 图表生成（未来扩展）
    GENERATE_ANALYSIS = "generate_analysis" # 数据分析（未来扩展）


class AgentLog(Base):
    """
    Agent执行日志表
    
    记录Agent每个步骤的详细信息，用于：
    1. 调试和问题追踪
    2. Token成本统计
    3. 性能分析
    4. 用户行为分析
    """
    __tablename__ = "agent_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Integer, nullable=False, index=True)  # 会话ID
    
    # 操作信息
    operation = Column(String(50), nullable=False, index=True)  # 操作类型
    step_index = Column(Integer, default=0)  # 步骤序号（在同一会话中）
    
    # 消息和思考
    input_messages = Column(JSON, nullable=True)   # 输入消息列表
    output_message = Column(Text, nullable=True)   # 输出消息
    thinking_content = Column(Text, nullable=True) # LLM思考过程（o1/o3模型）
    
    # 工具调用
    tool_calls = Column(JSON, nullable=True)       # 工具调用列表
    tool_results = Column(JSON, nullable=True)     # 工具返回结果
    
    # Token统计
    token_usage = Column(JSON, nullable=True)      # {prompt_tokens, completion_tokens, total_tokens}
    estimated_cost = Column(Float, nullable=True)  # 预估成本（美元）
    
    # 执行信息
    execution_time_ms = Column(Float, nullable=True)  # 执行耗时（毫秒）
    success = Column(Boolean, default=True)           # 是否成功
    error_message = Column(Text, nullable=True)       # 错误信息
    
    # SQL相关（如果是SQL操作）
    sql_query = Column(Text, nullable=True)        # 执行的SQL
    sql_result_count = Column(Integer, nullable=True)  # SQL返回行数
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.now, index=True)
    finished_at = Column(DateTime, nullable=True)
    
    # 元数据（注意：不能使用 'metadata' 作为列名，这是SQLAlchemy保留字）
    extra_data = Column(JSON, nullable=True)  # 额外元数据

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "operation": self.operation,
            "step_index": self.step_index,
            "token_usage": self.token_usage,
            "estimated_cost": self.estimated_cost,
            "execution_time_ms": self.execution_time_ms,
            "success": self.success,
            "error_message": self.error_message,
            "sql_query": self.sql_query,
            "sql_result_count": self.sql_result_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
    
    def __repr__(self):
        return f"<AgentLog(id={self.id}, chat_id={self.chat_id}, operation={self.operation}, success={self.success})>"


class ChatSession(Base):
    """
    会话表 - 记录用户的对话会话
    """
    __tablename__ = "chat_session"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    datasource_id = Column(Integer, nullable=False, index=True)  # 数据源ID
    title = Column(String(255), nullable=True)  # 会话标题
    
    # 统计信息
    total_messages = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)
    
    # 状态
    is_active = Column(Boolean, default=True)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "datasource_id": self.datasource_id,
            "title": self.title,
            "total_messages": self.total_messages,
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# Token价格配置（美元/1K tokens）
TOKEN_PRICES = {
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    "deepseek-coder": {"input": 0.00014, "output": 0.00028},
    "qwen-max": {"input": 0.004, "output": 0.012},
    "qwen-plus": {"input": 0.0008, "output": 0.002},
    "glm-4": {"input": 0.014, "output": 0.014},
    # 本地模型免费
    "ollama": {"input": 0.0, "output": 0.0},
    "llama3": {"input": 0.0, "output": 0.0},
}


def estimate_cost(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    """
    估算Token成本
    
    Args:
        model_name: 模型名称
        prompt_tokens: 输入tokens数
        completion_tokens: 输出tokens数
        
    Returns:
        预估成本（美元）
    """
    # 尝试精确匹配
    prices = TOKEN_PRICES.get(model_name)
    
    # 尝试前缀匹配
    if not prices:
        for key in TOKEN_PRICES:
            if model_name.startswith(key) or key in model_name.lower():
                prices = TOKEN_PRICES[key]
                break
    
    # 默认使用gpt-4o-mini价格
    if not prices:
        prices = TOKEN_PRICES["gpt-4o-mini"]
    
    input_cost = (prompt_tokens / 1000) * prices["input"]
    output_cost = (completion_tokens / 1000) * prices["output"]
    
    return round(input_cost + output_cost, 6)

