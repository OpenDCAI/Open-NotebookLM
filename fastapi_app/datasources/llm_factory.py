"""
LLM工厂模式 - 支持多种LLM模型

参考SQLBot设计 (backend/apps/ai_model/model_factory.py):
1. 支持多种LLM类型的工厂模式
2. 配置文件化，便于切换模型
3. 支持本地模型（Ollama）、云服务（OpenAI、通义千问、Azure）

使用方式:
    from fastapi_app.core.llm_factory import LLMFactory, LLMConfig
    
    config = LLMConfig(
        model_type="openai",
        model_name="gpt-4o-mini",
        api_key="sk-xxx",
        base_url="https://api.openai.com/v1"
    )
    llm = LLMFactory.create_llm(config)
"""
from typing import Literal, Optional, Dict, Any
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)

# 支持的LLM类型
LLMType = Literal["openai", "ollama", "tongyi", "azure", "zhipu", "deepseek"]


class LLMConfig(BaseModel):
    """LLM配置模型"""
    
    model_type: LLMType = Field(default="openai", description="LLM类型")
    model_name: str = Field(default="gpt-4o-mini", description="模型名称")
    api_key: Optional[str] = Field(default=None, description="API密钥")
    base_url: Optional[str] = Field(default=None, description="API基础URL")
    temperature: float = Field(default=0.0, description="温度参数")
    max_tokens: Optional[int] = Field(default=None, description="最大输出tokens")
    timeout: int = Field(default=60, description="请求超时时间（秒）")
    extra_params: Dict[str, Any] = Field(default_factory=dict, description="额外参数")
    
    class Config:
        extra = "allow"


class LLMFactory:
    """
    LLM工厂类 - 创建不同类型的LLM实例
    
    支持的模型类型:
    - openai: OpenAI API兼容模型（包括Azure OpenAI、DeepSeek等兼容API）
    - ollama: 本地Ollama模型
    - tongyi: 通义千问
    - azure: Azure OpenAI
    - zhipu: 智谱AI
    - deepseek: DeepSeek
    """
    
    @staticmethod
    def create_llm(config: LLMConfig):
        """
        根据配置创建LLM实例
        
        Args:
            config: LLM配置
            
        Returns:
            LangChain ChatModel实例
        """
        model_type = config.model_type.lower()
        
        if model_type == "openai":
            return LLMFactory._create_openai(config)
        elif model_type == "ollama":
            return LLMFactory._create_ollama(config)
        elif model_type == "tongyi":
            return LLMFactory._create_tongyi(config)
        elif model_type == "azure":
            return LLMFactory._create_azure(config)
        elif model_type == "zhipu":
            return LLMFactory._create_zhipu(config)
        elif model_type == "deepseek":
            return LLMFactory._create_deepseek(config)
        else:
            raise ValueError(f"不支持的LLM类型: {model_type}")
    
    @staticmethod
    def _create_openai(config: LLMConfig):
        """创建OpenAI ChatModel"""
        from fastapi_app.core.openai_compat_chat_model import OpenAICompatChatModel

        logger.info(f"Creating OpenAI LLM (compat): model={config.model_name}, base_url={config.base_url}")
        return OpenAICompatChatModel(
            model=config.model_name,
            api_key=config.api_key or "",
            base_url=config.base_url,
            temperature=config.temperature,
            timeout=config.timeout,
            max_tokens=config.max_tokens,
            extra_params=config.extra_params or {},
        )
    
    @staticmethod
    def _create_ollama(config: LLMConfig):
        """创建Ollama ChatModel（本地模型）"""
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            from langchain_community.chat_models import ChatOllama
        
        base_url = config.base_url or "http://localhost:11434"
        
        kwargs = {
            "model": config.model_name,
            "base_url": base_url,
            "temperature": config.temperature,
            **config.extra_params
        }
        
        logger.info(f"Creating Ollama LLM: model={config.model_name}, base_url={base_url}")
        return ChatOllama(**kwargs)
    
    @staticmethod
    def _create_tongyi(config: LLMConfig):
        """创建通义千问ChatModel"""
        try:
            from langchain_community.chat_models import ChatTongyi
            
            kwargs = {
                "model": config.model_name or "qwen-max",
                "temperature": config.temperature,
                **config.extra_params
            }
            
            if config.api_key:
                kwargs["dashscope_api_key"] = config.api_key
                
            logger.info(f"Creating Tongyi LLM: model={config.model_name}")
            return ChatTongyi(**kwargs)
        except ImportError:
            # 回退到OpenAI兼容模式
            logger.warning("ChatTongyi not available, falling back to OpenAI-compatible mode")
            from fastapi_app.core.openai_compat_chat_model import OpenAICompatChatModel

            return OpenAICompatChatModel(
                model=config.model_name or "qwen-max",
                api_key=config.api_key or "",
                base_url=config.base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
                temperature=config.temperature,
                timeout=config.timeout,
                max_tokens=config.max_tokens,
                extra_params=config.extra_params or {},
            )
    
    @staticmethod
    def _create_azure(config: LLMConfig):
        """创建Azure OpenAI ChatModel"""
        from fastapi_app.core.openai_compat_chat_model import AzureOpenAICompatChatModel

        logger.info(f"Creating Azure OpenAI LLM (compat): deployment={config.model_name}")
        return AzureOpenAICompatChatModel(
            model=config.model_name,
            api_key=config.api_key or "",
            azure_endpoint=config.base_url,
            temperature=config.temperature,
            timeout=config.timeout,
            max_tokens=config.max_tokens,
            extra_params=config.extra_params or {},
        )
    
    @staticmethod
    def _create_zhipu(config: LLMConfig):
        """创建智谱AI ChatModel"""
        try:
            from langchain_community.chat_models import ChatZhipuAI
            
            kwargs = {
                "model": config.model_name or "glm-4",
                "temperature": config.temperature,
                **config.extra_params
            }
            
            if config.api_key:
                kwargs["api_key"] = config.api_key
                
            logger.info(f"Creating ZhipuAI LLM: model={config.model_name}")
            return ChatZhipuAI(**kwargs)
        except ImportError:
            # 回退到OpenAI兼容模式
            logger.warning("ChatZhipuAI not available, falling back to OpenAI-compatible mode")
            from fastapi_app.core.openai_compat_chat_model import OpenAICompatChatModel

            return OpenAICompatChatModel(
                model=config.model_name or "glm-4",
                api_key=config.api_key or "",
                base_url=config.base_url or "https://open.bigmodel.cn/api/paas/v4/",
                temperature=config.temperature,
                timeout=config.timeout,
                max_tokens=config.max_tokens,
                extra_params=config.extra_params or {},
            )
    
    @staticmethod
    def _create_deepseek(config: LLMConfig):
        """创建DeepSeek ChatModel（OpenAI兼容模式）"""
        from fastapi_app.core.openai_compat_chat_model import OpenAICompatChatModel

        base_url = config.base_url or "https://api.deepseek.com/v1"
        model_name = config.model_name or "deepseek-chat"

        logger.info(f"Creating DeepSeek LLM: model={model_name}, base_url={base_url}")
        return OpenAICompatChatModel(
            model=model_name,
            api_key=config.api_key or "",
            base_url=base_url,
            temperature=config.temperature,
            timeout=config.timeout,
            max_tokens=config.max_tokens,
            extra_params=config.extra_params or {},
        )
    
    @staticmethod
    def from_settings():
        """
        从配置文件创建默认LLM
        
        Returns:
            LLM实例
        """
        from fastapi_app.core.config import settings
        
        llm_type = getattr(settings, "LLM_TYPE", "openai")
        
        # 根据LLM类型选择配置
        if llm_type == "ollama":
            config = LLMConfig(
                model_type="ollama",
                model_name=getattr(settings, "OLLAMA_MODEL", "llama3"),
                base_url=getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434"),
                temperature=getattr(settings, "LLM_TEMPERATURE", 0.0),
            )
        else:
            # OpenAI及其兼容API
            config = LLMConfig(
                model_type=llm_type,
                model_name=settings.OPENAI_MODEL,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_API_BASE,
                temperature=getattr(settings, "LLM_TEMPERATURE", 0.0),
            )
        
        return LLMFactory.create_llm(config)


# 便捷函数
def get_default_llm():
    """获取默认LLM实例"""
    return LLMFactory.from_settings()
