from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: List[str], api_url: str, api_key: str, model: str) -> List[List[float]]:
        pass


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, api_url: str, api_key: str, model: str, voice: Optional[str] = None) -> bytes:
        pass

    def get_voices(self) -> List[Dict[str, str]]:
        """返回支持的音色列表 [{"id": "voice_id", "name": "音色名称"}]"""
        return []


class SearchProvider(ABC):
    @abstractmethod
    async def search(self, query: str, api_key: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        搜索并返回结果列表

        Returns:
            [
                {
                    "title": "标题",
                    "url": "链接",
                    "snippet": "摘要",
                    "content": "完整内容（可选）"
                },
                ...
            ]
        """
        pass
